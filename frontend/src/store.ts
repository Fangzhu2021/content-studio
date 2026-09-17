import { create } from 'zustand'
import { api, getToken, setAuth, clearAuth } from './api'
import type { CanvasEdge, CanvasNode, ProjectItem, User } from './types'
import { FORMATS, TYPE_META } from './types'

/* ---------- React Flow 形状 ---------- */
export interface FlowNode {
  id: string
  type: 'cs'
  position: { x: number; y: number }
  data: {
    kind: string
    subtype: string
    label: string
    status: string
    error?: string
    config?: Record<string, unknown>
    icon?: string
    durationMs?: number
    chars?: number
    progress?: number
  }
  selected?: boolean
}
export interface FlowEdge { id: string; source: string; target: string; animated?: boolean }

/* 节点模板图标（后台可改）：kind:subtype → Lucide 图标名 */
let TEMPLATE_ICONS: Record<string, string> = {}
export function setTemplateIcons(nodes: { kind: string; subtype: string; icon: string }[]) {
  const next: Record<string, string> = {}
  for (const n of nodes) next[`${n.kind}:${n.subtype || ''}`] = n.icon || ''
  TEMPLATE_ICONS = next
}

export function toFlowNode(n: CanvasNode): FlowNode {
  const meta = TYPE_META[n.type as keyof typeof TYPE_META]
  const fmt = FORMATS[n.subtype] || ''
  const fallback = fmt ? `${meta?.label || n.type} · ${fmt}` : (meta?.label || n.type)
  // 后端在未传 label 时会用类型名兜底，这里把这种占位名换回可读名称
  const label = (n.label && n.label !== n.type) ? n.label : fallback
  return {
    id: n.id, type: 'cs', position: n.position,
    data: {
      kind: n.type, subtype: n.subtype, label, status: n.status || 'idle', error: n.error || '',
      config: n.config || {}, icon: TEMPLATE_ICONS[`${n.type}:${n.subtype || ''}`] || '',
    },
  }
}
export function toFlowEdge(e: CanvasEdge): FlowEdge { return { id: e.id, source: e.source, target: e.target } }

/** 刷新画布时保留本地指标（耗时/字数/进度）：接口不返回这些字段，否则会被清空 */
function keepMetrics(prev: FlowNode[], next: FlowNode[]): FlowNode[] {
  const byId = new Map(prev.map((n) => [n.id, n.data]))
  return next.map((n) => {
    const old = byId.get(n.id)
    if (!old) return n
    const data = { ...n.data }
    if (old.durationMs != null) data.durationMs = old.durationMs
    if (old.chars != null) data.chars = old.chars
    if (old.icon) data.icon = old.icon
    return { ...n, data }
  })
}

/** 拓扑排序（与后端一致）：用于「运行工作流」按序逐个发起 */
function topoOrder(ids: string[], edges: FlowEdge[]): string[] {
  const indeg: Record<string, number> = {}
  const out: Record<string, string[]> = {}
  ids.forEach((id) => { indeg[id] = 0; out[id] = [] })
  edges.forEach((e) => {
    if (indeg[e.target] === undefined || indeg[e.source] === undefined) return
    indeg[e.target] += 1
    out[e.source].push(e.target)
  })
  const queue = ids.filter((id) => indeg[id] === 0)
  const order: string[] = []
  while (queue.length) {
    const id = queue.shift() as string
    order.push(id)
    for (const t of out[id]) { indeg[t] -= 1; if (indeg[t] === 0) queue.push(t) }
  }
  return order.length === ids.length ? order : ids
}

/* ---------- Store ---------- */
interface StoreState {
  token: string | null
  user: User | null
  projects: ProjectItem[]
  currentId: string | null
  nodes: FlowNode[]
  edges: FlowEdge[]
  selected: string | null
  toast: string | null
  ws: WebSocket | null
  running: string[]
  stopRequested: boolean
  runPlan: { total: number; done: number } | null
  runActive: boolean
  zoom: number
  lastRun: { at: number; ms: number; failed: number; total: number } | null

  toastMsg(msg: string): void
  select(id: string | null): void
  setZoom(z: number): void
  init(): Promise<void>
  login(username: string, password: string): Promise<void>
  register(username: string, password: string, inviteCode?: string): Promise<void>
  changePassword(oldPassword: string, newPassword: string): Promise<void>
  logout(): void
  loadProjects(): Promise<void>
  createProject(name: string, template: boolean, aiReview?: boolean): Promise<string | null>
  openProject(id: string): Promise<void>
  closeProject(): void
  refreshCanvas(): Promise<void>
  setNodes(nodes: FlowNode[]): void
  setEdges(edges: FlowEdge[]): void
  upsertNodeLocal(node: FlowNode): void
  removeNodeLocal(id: string): void
  removeEdgeLocal(id: string): void
  syncNode(nodeId: string, data: Partial<FlowNode['data']>): void
  runProject(): Promise<void>
  stopRun(): void
}

export const useStore = create<StoreState>((set, get) => {
  function patchStatus(nodeId: string, status: string, error?: string, extra: Partial<FlowNode['data']> = {}) {
    // 过滤掉 undefined：HTTP 响应里没有耗时时，不能覆盖掉 WebSocket 刚送来的耗时/字数
    const clean: Record<string, unknown> = {}
    Object.entries(extra).forEach(([k, v]) => { if (v !== undefined && v !== null) clean[k] = v })
    const nodes = get().nodes.map((n) => (
      n.id === nodeId ? { ...n, data: { ...n.data, status, error: error || '', ...clean } } : n
    ))
    set({ nodes })
  }
  async function openWs(pid: string): Promise<WebSocket | null> {
    const token = get().token || getToken()
    if (!token) return null
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/${pid}?token=${token}`)
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string)
        if (msg.type === 'node_status' && msg.node_id) {
          patchStatus(msg.node_id, msg.status || 'done', msg.error || '', {
            durationMs: msg.duration_ms,
            chars: msg.chars,
            progress: msg.progress,
          })
          // 只有终态才算「这个节点跑完了」；后端开始执行时会广播 running，不能当结束
          if (['done', 'failed', 'approved', 'canceled'].includes(msg.status)) {
            set({ running: get().running.filter((x) => x !== msg.node_id) })
          }
        }
      } catch { /* ignore */ }
    }
    return ws
  }

  return {
    token: null, user: null, projects: [], currentId: null, nodes: [], edges: [], selected: null,
    toast: null, ws: null, running: [], stopRequested: false, runPlan: null, runActive: false, zoom: 1, lastRun: null,

    toastMsg: (msg) => { set({ toast: msg }); setTimeout(() => { if (get().toast === msg) set({ toast: null }) }, 4200) },
    select: (id) => set({ selected: id }),
    setZoom: (z) => set({ zoom: z }),

    async init() {
      const token = getToken()
      if (!token) return
      let user: User | null = null
      try { user = JSON.parse(localStorage.getItem('cs_user') || 'null') } catch { /* ignore */ }
      set({ token, user })
      try {
        await get().loadProjects()
        // 自动恢复上次打开的项目（刷新页面后不丢上下文）
        const last = localStorage.getItem('cs_last_project')
        if (last && get().projects.some((p) => p.id === last)) {
          await get().openProject(last)
        }
      } catch { /* 401 交给拦截器 */ }
    },
    async login(username, password) { const r = await api.login(username, password); setAuth(r.token, r.user); set({ token: r.token, user: r.user }); await get().loadProjects() },
    async register(username, password, inviteCode = '') { const r = await api.register(username, password, inviteCode); setAuth(r.token, r.user); set({ token: r.token, user: r.user }); await get().loadProjects() },
    async changePassword(oldPassword, newPassword) {
      const r = await api.changePassword(oldPassword, newPassword)
      setAuth(r.token, r.user)
      set({ token: r.token, user: r.user })
    },
    logout() {
      clearAuth()
      localStorage.removeItem('cs_last_project')
      get().ws?.close()
      set({ token: null, user: null, projects: [], currentId: null, nodes: [], edges: [], selected: null, ws: null, lastRun: null })
    },
    async loadProjects() { set({ projects: await api.listProjects() }) },
    async createProject(name, template, aiReview = false) {
      const p = await api.createProject(name, template, aiReview)
      await get().loadProjects()
      await get().openProject(p.id)
      return p.id
    },
    async openProject(id) {
      get().ws?.close()
      const d = await api.getProject(id)
      localStorage.setItem('cs_last_project', id)
      set({ currentId: id, nodes: d.nodes.map(toFlowNode), edges: d.edges.map(toFlowEdge), selected: null, running: [], stopRequested: false })
      set({ ws: await openWs(id) })
    },
    closeProject() {
      get().ws?.close()
      localStorage.removeItem('cs_last_project')
      set({ currentId: null, nodes: [], edges: [], selected: null, ws: null, running: [], lastRun: null })
    },
    async refreshCanvas() {
      const cid = get().currentId
      if (!cid) return
      const c = await api.getCanvas(cid)
      set({ nodes: keepMetrics(get().nodes, c.nodes.map(toFlowNode)), edges: c.edges.map(toFlowEdge) })
    },
    setNodes: (nodes) => set({ nodes }),
    setEdges: (edges) => set({ edges }),
    upsertNodeLocal: (node) => {
      const exists = get().nodes.some((n) => n.id === node.id)
      set({ nodes: exists ? get().nodes.map((n) => (n.id === node.id ? node : n)) : [...get().nodes, node] })
    },
    removeNodeLocal: (id) => set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selected: get().selected === id ? null : get().selected,
    }),
    removeEdgeLocal: (id) => set({ edges: get().edges.filter((e) => e.id !== id) }),
    syncNode: (nodeId, data) => {
      const nodes = get().nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n))
      set({ nodes })
    },

    /** 运行工作流：前端按拓扑序逐个发起（trigger=auto），「停止」可真正中止后续节点 */
    async runProject() {
      const { currentId, nodes, edges } = get()
      if (!currentId) return
      const order = topoOrder(nodes.map((n) => n.id), edges)
      const t0 = Date.now()
      const total = order.filter((id) => nodes.find((n) => n.id === id)?.data.kind !== 'reviewer').length
      set({ stopRequested: false, running: [], lastRun: null, runActive: true, runPlan: { total, done: 0 } })
      let failed = 0
      let done = 0
      for (const id of order) {
        if (get().stopRequested) break
        const node = get().nodes.find((n) => n.id === id)
        if (!node) continue
        if (node.data.kind === 'reviewer') continue          // 人工审定节点需手动操作
        set({ running: [...get().running, id] })
        patchStatus(id, 'running')
        try {
          const r: any = await api.executeNode(id, { trigger: 'auto' })
          done += 1
          // 录音转写等异步节点返回 running，其余交给 WebSocket 收尾（耗时/字数以台账广播为准）
          if (r?.status && r.status !== 'running') {
            const extra: Record<string, unknown> = {}
            if (r.chars != null) extra.chars = r.chars
            if (r.duration_ms != null) extra.durationMs = r.duration_ms
            patchStatus(id, r.status === 'approved' ? 'approved' : 'done', '', extra as any)
          }
        } catch (e) {
          failed += 1
          patchStatus(id, 'failed', errText(e))
        } finally {
          set({
            running: get().running.filter((x) => x !== id),
            runPlan: { total, done },
          })
        }
      }
      const ms = Date.now() - t0
      set({ lastRun: { at: Date.now(), ms, failed, total: done } })
      get().toastMsg(get().stopRequested
        ? `已停止：本次完成 ${done} 个节点${failed ? `，${failed} 个失败` : ''}`
        : failed ? `执行结束：${failed} 个节点失败，请查看节点提示` : `工作流执行完成（${done} 个节点）`)
      set({ stopRequested: false, runPlan: null, runActive: false })
      await get().refreshCanvas()
    },
    stopRun() {
      if (!get().running.length && !get().stopRequested) return
      set({ stopRequested: true })
      get().toastMsg('已请求停止：正在执行的节点会跑完，后续节点不再发起')
    },
  }
})

export function errText(e: unknown): string { return api.detail(e) }

/* 调试与端到端测试用：把 store 挂到 window（只读使用，不影响业务） */
if (typeof window !== 'undefined') (window as any).__csStore = useStore
