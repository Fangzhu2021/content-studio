import { create } from 'zustand'
import { api, getToken, setAuth, clearAuth } from './api'
import type { CanvasEdge, CanvasNode, ProjectItem, User } from './types'
import { FORMATS, TYPE_META } from './types'

/* ---------- React Flow 形状 ---------- */
export interface FlowNode {
  id: string
  type: 'cs'
  position: { x: number; y: number }
  data: { kind: string; subtype: string; label: string; status: string; error?: string }
  selected?: boolean
}
export interface FlowEdge { id: string; source: string; target: string; animated?: boolean }

export function toFlowNode(n: CanvasNode): FlowNode {
  const fmt = FORMATS[n.subtype] || ''
  const label = n.label || (fmt ? `${TYPE_META[n.type as keyof typeof TYPE_META].label} · ${fmt}` : TYPE_META[n.type as keyof typeof TYPE_META].label)
  return { id: n.id, type: 'cs', position: n.position, data: { kind: n.type, subtype: n.subtype, label, status: n.status || 'idle', error: n.error || '' } }
}
export function toFlowEdge(e: CanvasEdge): FlowEdge { return { id: e.id, source: e.source, target: e.target } }

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

  toastMsg(msg: string): void
  select(id: string | null): void
  init(): Promise<void>
  login(username: string, password: string): Promise<void>
  register(username: string, password: string): Promise<void>
  logout(): void
  loadProjects(): Promise<void>
  createProject(name: string, template: boolean): Promise<string | null>
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
}

export const useStore = create<StoreState>((set, get) => {
  function patchStatus(nodeId: string, status: string, error?: string) {
    const nodes = get().nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, status, error: error || '' } } : n))
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
          patchStatus(msg.node_id, msg.status || 'done', msg.error || '')
          set({ running: get().running.filter((x) => x !== msg.node_id) })
        }
      } catch { /* ignore */ }
    }
    return ws
  }

  return {
    token: null, user: null, projects: [], currentId: null, nodes: [], edges: [], selected: null,
    toast: null, ws: null, running: [],

    toastMsg: (msg) => { set({ toast: msg }); setTimeout(() => { if (get().toast === msg) set({ toast: null }) }, 4200) },
    select: (id) => set({ selected: id }),

    async init() {
      const token = getToken()
      if (!token) return
      let user: User | null = null
      try { user = JSON.parse(localStorage.getItem('cs_user') || 'null') } catch { /* ignore */ }
      set({ token, user })
      try { await get().loadProjects() } catch { /* 401 交给拦截器 */ }
    },
    async login(username, password) { const r = await api.login(username, password); setAuth(r.token, r.user); set({ token: r.token, user: r.user }); await get().loadProjects() },
    async register(username, password) { const r = await api.register(username, password); setAuth(r.token, r.user); set({ token: r.token, user: r.user }); await get().loadProjects() },
    logout() {
      clearAuth(); get().ws?.close()
      set({ token: null, user: null, projects: [], currentId: null, nodes: [], edges: [], selected: null, ws: null })
    },
    async loadProjects() { set({ projects: await api.listProjects() }) },
    async createProject(name, template) {
      const p = await api.createProject(name, template)
      await get().loadProjects()
      await get().openProject(p.id)
      return p.id
    },
    async openProject(id) {
      get().ws?.close()
      const d = await api.getProject(id)
      set({ currentId: id, nodes: d.nodes.map(toFlowNode), edges: d.edges.map(toFlowEdge), selected: null, running: [] })
      set({ ws: await openWs(id) })
    },
    closeProject() { get().ws?.close(); set({ currentId: null, nodes: [], edges: [], selected: null, ws: null }) },
    async refreshCanvas() {
      const cid = get().currentId
      if (!cid) return
      const c = await api.getCanvas(cid)
      set({ nodes: c.nodes.map(toFlowNode), edges: c.edges.map(toFlowEdge) })
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
    async runProject() {
      const cid = get().currentId
      if (!cid) return
      set({ running: get().nodes.map((n) => n.id) })
      try {
        const res = await api.executeProject(cid)
        const failed = res.results.filter((r) => r.status === 'failed')
        get().toastMsg(failed.length ? `执行完成：${failed.length} 个节点失败，请查看` : '画布自动执行完成')
      } catch (e) { get().toastMsg(api.detail(e)) }
      set({ running: [] })
      await get().refreshCanvas()
    },
  }
})

export function errText(e: unknown): string { return api.detail(e) }
