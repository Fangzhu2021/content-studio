import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { errText, setTemplateIcons, useStore } from './store'
import { BUILTIN_GROUPS, groupsFromApi, type PaletteGroupView } from './nodes'
import { Icon, groupIcon } from './icons'
import { catOf } from './types'
import Canvas from './Canvas'
import ConfigPanel from './Panels'
import AdminApp from './Admin'

/* ---------------- 登录 / 注册 ---------------- */
function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [invite, setInvite] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [regMode, setRegMode] = useState<{ invite_required: boolean } | null>(null)
  const toastMsg = useStore((s) => s.toastMsg)

  useEffect(() => {
    void (async () => {
      try { setRegMode(await api.registerMode()) } catch { /* 忽略 */ }
    })()
    const code = new URLSearchParams(location.search).get('invite')
    if (code) { setInvite(code); setMode('register') }
  }, [])

  const fromLink = !!new URLSearchParams(location.search).get('invite')

  async function submit() {
    setErr(''); setBusy(true)
    try {
      if (mode === 'login') await useStore.getState().login(u.trim(), p)
      else await useStore.getState().register(u.trim(), p, invite.trim())
    } catch (e) { setErr(errText(e)); toastMsg(errText(e)) }
    setBusy(false)
  }
  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-logo">智能编辑系统</div>
        <div className="login-sub">在线无限画布 · 稿件改写与发布工作台</div>
        <div className="tabs">
          <button className={mode === 'login' ? 'on' : ''} onClick={() => setMode('login')}>登录</button>
          <button className={mode === 'register' ? 'on' : ''} onClick={() => setMode('register')}>注册</button>
        </div>
        <input value={u} onChange={(e) => setU(e.target.value)} placeholder="用户名（≥2 字符）" autoFocus />
        <input type="password" value={p} onChange={(e) => setP(e.target.value)}
          placeholder={mode === 'register' ? '密码（≥8 位，含字母和数字）' : '密码'}
          onKeyDown={(e) => { if (e.key === 'Enter') void submit() }} />
        {mode === 'register' && (regMode ? regMode.invite_required : true) ? (
          <input value={invite} onChange={(e) => setInvite(e.target.value)} placeholder="邀请码（向管理员索取）"
            onKeyDown={(e) => { if (e.key === 'Enter') void submit() }} />
        ) : null}
        {fromLink ? <div className="login-hint" style={{ margin: '4px 0 8px' }}>已从链接带入邀请码，填写用户名与密码即可注册</div> : null}
        {err ? <div className="login-err">{err}</div> : null}
        <button className="primary" disabled={busy || !u || !p} onClick={submit}>
          {busy ? '…' : mode === 'login' ? '登 录' : '注册并登录'}
        </button>
        <div className="login-hint">
          {mode === 'register' && regMode && regMode.invite_required
            ? '内部系统：注册需管理员发放的邀请码'
            : '云阳县融媒体中心 · AI 模型驱动'}
        </div>
      </div>
    </div>
  )
}

/* ---------------- 新建项目 ---------------- */
function CreateModal({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [tmpl, setTmpl] = useState(true)
  const [aiReview, setAiReview] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function create() {
    setBusy(true); setErr('')
    try {
      await useStore.getState().createProject(name.trim(), tmpl, aiReview)
      useStore.getState().toastMsg('项目已创建，可开始拖入节点')
      onDone()
    } catch (e) { setErr(errText(e)) }
    setBusy(false)
  }
  return (
    <div className="modal-mask" onClick={onDone}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>新建项目</h3>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="项目名称，如：防汛演练报道" autoFocus />
        <label className="check-row" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={tmpl} onChange={(e) => setTmpl(e.target.checked)} />
          <span>使用标准工作流模板（草稿 → TV/报刊 → 审稿 → 公众号/微博/抖音 → 成稿）</span>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={tmpl && aiReview} disabled={!tmpl}
            onChange={(e) => setAiReview(e.target.checked)} />
          <span><b>使用 AI 审稿</b>（自动判定通过/打回并给出审稿意见，无需人工确认）</span>
        </label>
        {err ? <div className="login-err">{err}</div> : null}
        <div className="btn-row right">
          <button onClick={onDone}>取消</button>
          <button className="primary" disabled={busy || !name.trim()} onClick={create}>{busy ? '创建中…' : '创建'}</button>
        </div>
      </div>
    </div>
  )
}

/* ---------------- 修改密码 ---------------- */
function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [newPw2, setNewPw2] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit() {
    setErr('')
    if (newPw !== newPw2) { setErr('两次输入的新密码不一致'); return }
    if (newPw.length < 8 || !/[A-Za-z]/.test(newPw) || !/[0-9]/.test(newPw)) {
      setErr('新密码至少 8 位，且需同时包含字母和数字'); return
    }
    setBusy(true)
    try {
      await useStore.getState().changePassword(oldPw, newPw)
      useStore.getState().toastMsg('密码已修改，其他设备上的登录已失效')
      onClose()
    } catch (e) { setErr(errText(e)) }
    setBusy(false)
  }
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>修改密码</h3>
        <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} placeholder="当前密码" autoFocus />
        <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="新密码（≥8 位，含字母和数字）" />
        <input type="password" value={newPw2} onChange={(e) => setNewPw2(e.target.value)} placeholder="再次输入新密码" />
        {err ? <div className="login-err">{err}</div> : null}
        <div className="btn-row right">
          <button onClick={onClose}>取消</button>
          <button className="primary" disabled={busy || !oldPw || !newPw} onClick={submit}>{busy ? '提交中…' : '确认修改'}</button>
        </div>
      </div>
    </div>
  )
}

/* ---------------- 左栏 · 节点库 ---------------- */
const COLLAPSE_KEY = 'cs_palette_collapsed'

function Palette() {
  const select = useStore((s) => s.select)
  const currentId = useStore((s) => s.currentId)
  const [groups, setGroups] = useState<PaletteGroupView[]>(BUILTIN_GROUPS)
  const [keyword, setKeyword] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '{}') } catch { return {} }
  })

  useEffect(() => {
    void (async () => {
      try {
        const d = await api.getTemplates()
        if (d.nodes?.length) {
          setGroups(groupsFromApi(d.nodes))
          setTemplateIcons(d.nodes)
        }
      } catch { /* 接口不可用时保留内置节点库 */ }
    })()
  }, [])

  function persist(next: Record<string, boolean>) {
    try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next)) } catch { /* 隐私模式下忽略 */ }
  }
  function toggle(group: string) {
    setCollapsed((c) => { const next = { ...c, [group]: !c[group] }; persist(next); return next })
  }
  const allCollapsed = groups.length > 0 && groups.every((g) => collapsed[g.group])
  function toggleAll() {
    const next: Record<string, boolean> = {}
    groups.forEach((g) => { next[g.group] = !allCollapsed })
    persist(next); setCollapsed(next)
  }

  const kw = keyword.trim().toLowerCase()
  const shown = useMemo(() => groups.map((g) => ({
    ...g,
    items: kw ? g.items.filter((it) => `${it.label || ''}${it.subtype}${g.group}`.toLowerCase().includes(kw)) : g.items,
  })).filter((g) => g.items.length > 0), [groups, kw])

  return (
    <aside className="palette">
      <div className="palette-title">
        <span>节点库</span>
        <button className="pal-toggle" onClick={toggleAll} title={allCollapsed ? '展开所有分组' : '折叠所有分组'}>
          {allCollapsed ? '展开' : '折叠'}
        </button>
      </div>

      <div className="pal-search">
        <span className="pal-search-ico"><Icon name="search" size={14} /></span>
        <input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索节点…" />
      </div>

      {shown.length === 0 ? <div className="pal-empty">没有匹配的节点</div> : null}

      {shown.map((g) => {
        const shut = !!collapsed[g.group] && !kw
        const cat = catOf(g.items[0].kind)
        return (
          <div key={g.group}>
            <div
              className={`palette-group${shut ? ' collapsed' : ''}`}
              role="button" tabIndex={0} aria-expanded={!shut}
              title={shut ? `展开「${g.group}」` : `折叠「${g.group}」`}
              onClick={() => toggle(g.group)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(g.group) } }}
            >
              <span className={`tri${shut ? '' : ' open'}`} aria-hidden="true"><Icon name="chevron-right" size={12} /></span>
              <i className="gdot" style={{ background: cat.cssVar }} />
              <Icon name={groupIcon(g.group)} size={13} style={{ color: cat.cssVar }} />
              <span>{g.group}</span>
              {shut ? <span className="gcount">{g.items.length}</span> : g.hint ? <span className="ghint">{g.hint}</span> : null}
            </div>
            {shut ? null : g.items.map((it) => {
              const c = catOf(it.kind)
              return (
                <div
                  key={it.kind + it.subtype}
                  className="palette-item"
                  style={{ ['--cat' as any]: c.cssVar }}
                  draggable
                  onDragStart={(e) => { e.dataTransfer.setData('application/cs-node', JSON.stringify(it)); e.dataTransfer.effectAllowed = 'move' }}
                  onClick={() => select(null)}
                  title={currentId ? '拖到画布中放置' : '请先打开一个项目'}
                >
                  <span className="pi-ico"><Icon name={it.icon} size={16} /></span>
                  <span className="pi-name">{it.label || it.subtype || c.label}</span>
                  {it.kind === 'exporter' ? <span className="pi-badge">终稿</span> : null}
                </div>
              )
            })}
          </div>
        )
      })}

      <div className="legend">
        <div><i className="dot idle" />待执行</div>
        <div><i className="dot running" />运行中</div>
        <div><i className="dot done" />完成</div>
        <div><i className="dot approved" />已通过</div>
        <div><i className="dot failed" />失败</div>
      </div>
    </aside>
  )
}

/* ---------------- 工作台 ---------------- */
const PANEL_MIN = 300
const PANEL_MAX = 1100      // 输出窗口要看得清长稿，允许拖到很宽
const PANEL_DEFAULT = 380

function fmtClock(ts: number) {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function Workspace() {
  const user = useStore((s) => s.user)
  const projects = useStore((s) => s.projects)
  const currentId = useStore((s) => s.currentId)
  const toast = useStore((s) => s.toast)
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const running = useStore((s) => s.running)
  const zoom = useStore((s) => s.zoom)
  const lastRun = useStore((s) => s.lastRun)
  const runPlan = useStore((s) => s.runPlan)
  const runActive = useStore((s) => s.runActive)
  const [showCreate, setShowCreate] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [panelWidth, setPanelWidth] = useState(() => {
    const saved = Number(localStorage.getItem('cs_panel_width') || 0)
    return saved >= PANEL_MIN && saved <= PANEL_MAX ? saved : PANEL_DEFAULT
  })
  const widthRef = useRef(panelWidth)
  useEffect(() => { widthRef.current = panelWidth }, [panelWidth])

  const currentProject = projects.find((p) => p.id === currentId)
  const roleText = user?.role === 'admin' ? '管理员' : user?.role === 'reviewer' ? '审核' : user?.role === 'viewer' ? '只读' : '编辑'

  function startResize(e: React.MouseEvent) {
    e.preventDefault()
    const startX = e.clientX
    const startW = widthRef.current
    document.body.classList.add('resizing')
    function onMove(ev: MouseEvent) {
      const next = Math.min(PANEL_MAX, Math.max(PANEL_MIN, startW - (ev.clientX - startX)))
      setPanelWidth(next)
    }
    function onUp() {
      document.body.classList.remove('resizing')
      localStorage.setItem('cs_panel_width', String(Math.round(widthRef.current)))
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function resetWidth() {
    setPanelWidth(PANEL_DEFAULT)
    localStorage.setItem('cs_panel_width', String(PANEL_DEFAULT))
  }

  async function removeCurrent() {
    if (!currentId) return
    if (!confirm('确定删除当前项目及其全部内容？')) return
    try { await api.deleteProject(currentId) } catch (e) { useStore.getState().toastMsg(errText(e)); return }
    useStore.getState().closeProject()
    await useStore.getState().loadProjects()
  }

  const busyRun = runActive || running.length > 0

  return (
    <div className="app">
      <header className="topbar">
        {/* 左区 · 品牌 */}
        <div className="brand">
          <span className="brand-mark"><Icon name="sparkles" size={16} /></span>
          <span>智能编辑系统</span>
        </div>

        {/* 左区 · 上下文：角色 + 当前工作流 */}
        <div className="ctx-group">
          <span className="ctx-sep" />
          <span className="ctx-role"><Icon name="badge-check" size={13} />{roleText}</span>
          <div className="project-ctl">
            <select value={currentId || ''} onChange={(e) => { const v = e.target.value; if (v) void useStore.getState().openProject(v) }}>
              <option value="" disabled>— 选择项目 —</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="icon-btn" title="新建项目" onClick={() => setShowCreate(true)}>
              <Icon name="plus" size={16} />
            </button>
          </div>
        </div>

        <div className="spacer" />

        {/* 右区 · 主操作：运行工作流 / 停止 + 状态 */}
        <div className="run-group">
          <span className={`run-dot${busyRun ? ' on' : ''}`} />
          <span className="run-state">
            {busyRun
              ? `运行中 ${runPlan ? `${runPlan.done}/${runPlan.total}` : `${running.length} 个节点`}`
              : lastRun
                ? `上次 ${fmtClock(lastRun.at)} · ${(lastRun.ms / 1000).toFixed(1)}s${lastRun.failed ? ` · ${lastRun.failed} 失败` : ''}`
                : '尚未运行'}
          </span>
          <button className="primary" disabled={!currentId || busyRun}
            onClick={() => void useStore.getState().runProject()}
            title="按连线顺序自动执行画布中的节点">
            <Icon name="play" size={14} />运行工作流
          </button>
          <button disabled={!busyRun} onClick={() => useStore.getState().stopRun()} title="停止后续节点（正在执行的节点会跑完）">
            <Icon name="square" size={13} />停止
          </button>
        </div>

        {/* 右区 · 账号：低频操作收进下拉 */}
        {user ? (
          <div className="user-chip">
            <button className="user-btn" onClick={() => setMenuOpen((v) => !v)}>
              <span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>
              <span>{user.username}</span>
              {user.role === 'admin' ? <span className="role-badge">管理员</span> : null}
              <Icon name="chevron-down" size={13} />
            </button>
            {menuOpen ? (
              <div className="menu" onMouseLeave={() => setMenuOpen(false)}>
                {user.role === 'admin' ? (
                  <a href="/admin"><Icon name="settings" size={14} />管理后台</a>
                ) : null}
                <button onClick={() => { setMenuOpen(false); setShowPw(true) }}><Icon name="key-round" size={14} />修改密码</button>
                {currentId ? (
                  <>
                    <div className="menu-sep" />
                    <button onClick={() => { setMenuOpen(false); void removeCurrent() }}><Icon name="trash-2" size={14} />删除当前项目</button>
                  </>
                ) : null}
                <div className="menu-sep" />
                <button onClick={() => useStore.getState().logout()}><Icon name="log-out" size={14} />退出登录</button>
              </div>
            ) : null}
          </div>
        ) : null}
      </header>

      <div className="workspace">
        <Palette />
        <main className="stage">
          {currentId ? <Canvas /> : (
            <div className="empty-stage">
              <Icon name="folder-open" size={48} className="empty-ico" />
              <div className="empty-title">还没有打开工作流</div>
              <div className="dim">从上方选择一个已有项目，或新建一个带标准流程的项目</div>
              <button className="primary" onClick={() => setShowCreate(true)}>
                <Icon name="plus" size={14} />新建项目（推荐模板）
              </button>
            </div>
          )}
        </main>
        <div className="splitter" onMouseDown={startResize} onDoubleClick={resetWidth}
          title="拖动调整宽度（双击恢复默认）" />
        <div className="panel-wrap" style={{ width: panelWidth }}>
          <ConfigPanel />
        </div>
      </div>

      {/* 底部状态栏：把画布状态从隐式变为显式（规范 5.3） */}
      <footer className="statusbar">
        <span className="sb-item">缩放 <b className="sb-num">{Math.round(zoom * 100)}%</b></span>
        <span className="sb-item">节点 <b className="sb-num">{nodes.length}</b></span>
        <span className="sb-item">连线 <b className="sb-num">{edges.length}</b></span>
        <span className="sb-item">
          最近执行 <b className="sb-num">{lastRun ? `${fmtClock(lastRun.at)} · ${(lastRun.ms / 1000).toFixed(1)}s` : '—'}</b>
        </span>
        <span className="sb-item">{busyRun ? <span className="warn">运行中…</span> : null}</span>
        <div className="spacer" />
        <span className="sb-item">{currentProject ? `当前工作流：${currentProject.name}` : '未打开项目'}</span>
        <span className="sb-item">音频不出内网 · 本地语音识别</span>
      </footer>

      {showCreate ? <CreateModal onDone={() => setShowCreate(false)} /> : null}
      {showPw ? <ChangePasswordModal onClose={() => setShowPw(false)} /> : null}
      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  )
}

export default function App() {
  const token = useStore((s) => s.token)
  const init = useStore((s) => s.init)
  const logout = useStore((s) => s.logout)
  useEffect(() => { void init() }, [init])
  useEffect(() => {
    const h = () => logout()
    window.addEventListener('cs:logout', h)
    return () => window.removeEventListener('cs:logout', h)
  }, [logout])
  if (location.pathname.startsWith('/admin')) {
    return token ? <AdminApp /> : <Login />
  }
  return token ? <Workspace /> : <Login />
}
