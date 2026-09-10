import { useEffect, useState } from 'react'
import Canvas from './Canvas'
import ConfigPanel from './Panels'
import { api } from './api'
import { errText, useStore } from './store'
import { PALETTE } from './nodes'
import { FORMATS } from './types'

const DND = 'application/cs-node'

function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit() {
    setBusy(true); setErr('')
    try {
      if (mode === 'login') await useStore.getState().login(u, p)
      else await useStore.getState().register(u, p)
    } catch (e) { setErr(errText(e)) }
    setBusy(false)
  }
  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-logo">✒️ 内容工坊</div>
        <div className="login-sub">Content Studio · 在线无限画布稿件改写系统</div>
        <div className="tabs">
          <button className={mode === 'login' ? 'on' : ''} onClick={() => setMode('login')}>登录</button>
          <button className={mode === 'register' ? 'on' : ''} onClick={() => setMode('register')}>注册</button>
        </div>
        <input value={u} onChange={(e) => setU(e.target.value)} placeholder="用户名（≥2 字符）" autoFocus />
        <input type="password" value={p} onChange={(e) => setP(e.target.value)} placeholder="密码（≥6 位）"
          onKeyDown={(e) => { if (e.key === 'Enter') void submit() }} />
        {err ? <div className="login-err">{err}</div> : null}
        <button className="primary wide" disabled={busy || !u || !p} onClick={submit}>
          {busy ? '…' : mode === 'login' ? '登 录' : '注册并登录'}
        </button>
        <div className="login-hint">部署于 YOUR_SERVER_IP · DeepSeek AI 可配置</div>
      </div>
    </div>
  )
}

function CreateModal({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [tmpl, setTmpl] = useState(true)
  const [aiReview, setAiReview] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function create() {
    setBusy(true)
    try {
      await useStore.getState().createProject(name.trim(), tmpl, aiReview)
      onDone()
    } catch (e) { setErr(errText(e)) }
    setBusy(false)
  }
  return (
    <div className="modal-mask" onClick={onDone}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>新建项目</h3>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="项目名称，如：防汛演练报道" autoFocus />
        <label className="check-row"><input type="checkbox" checked={tmpl} onChange={(e) => setTmpl(e.target.checked)} />
          <span>使用标准工作流模板（草稿 → TV/报刊 → 审稿 → 公众号/微博/抖音 → 成稿）</span></label>
        <label className="check-row"><input type="checkbox" checked={tmpl && aiReview} disabled={!tmpl}
          onChange={(e) => setAiReview(e.target.checked)} />
          <span><b>使用 AI 审稿</b>（自动判定通过/打回并给出审稿意见，无需人工确认）</span></label>
        {err ? <div className="login-err">{err}</div> : null}
        <div className="btn-row right">
          <button onClick={onDone}>取消</button>
          <button className="primary" disabled={busy || !name.trim()} onClick={create}>{busy ? '创建中…' : '创建'}</button>
        </div>
      </div>
    </div>
  )
}

function Palette() {
  const select = useStore((s) => s.select)
  const currentId = useStore((s) => s.currentId)
  return (
    <aside className="palette">
      <div className="palette-title">节点库 <span className="dim">（拖到画布）</span></div>
      {PALETTE.map((g) => (
        <div key={g.group}>
          <div className="palette-group">{g.group}</div>
          {g.items.map((it) => (
            <div
              key={it.kind + it.subtype}
              className="palette-item"
              draggable
              onDragStart={(e) => { e.dataTransfer.setData(DND, JSON.stringify(it)); e.dataTransfer.effectAllowed = 'move' }}
              onClick={() => select(null)}
              title={currentId ? '拖到画布中放置' : '请先打开一个项目'}
            >
              <span>{it.icon}</span>
              <span>{it.subtype ? FORMATS[it.subtype] : { draft_input: '草稿输入', reviewer: '人工审定', ai_reviewer: 'AI 审稿' }[it.kind]}</span>
            </div>
          ))}
        </div>
      ))}
      <div className="legend">
        <div><i className="dot idle" />待命</div><div><i className="dot running" />执行中</div>
        <div><i className="dot done" />完成</div><div><i className="dot approved" />已通过</div>
        <div><i className="dot failed" />失败</div>
      </div>
    </aside>
  )
}

function Workspace() {
  const user = useStore((s) => s.user)
  const projects = useStore((s) => s.projects)
  const currentId = useStore((s) => s.currentId)
  const toast = useStore((s) => s.toast)
  const [showCreate, setShowCreate] = useState(false)

  async function removeCurrent() {
    if (!currentId) return
    if (!confirm('确定删除当前项目及其全部内容？')) return
    try { await api.deleteProject(currentId) } catch (e) { useStore.getState().toastMsg(errText(e)); return }
    useStore.getState().closeProject()
    await useStore.getState().loadProjects()
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">✒️ 内容工坊 <span className="brand-en">Content Studio</span></div>
        <div className="project-ctl">
          <select value={currentId || ''} onChange={(e) => { const v = e.target.value; if (v) void useStore.getState().openProject(v) }}>
            <option value="" disabled>— 选择项目 —</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button onClick={() => setShowCreate(true)}>＋ 新建</button>
          {currentId ? <button className="danger" onClick={removeCurrent}>删除</button> : null}
        </div>
        <div className="spacer" />
        {user ? <div className="user-chip">👤 {user.username} <button onClick={() => useStore.getState().logout()}>退出</button></div> : null}
      </header>
      <div className="workspace">
        <Palette />
        <main className="stage">
          {currentId ? <Canvas /> : (
            <div className="empty-stage">
              <div>🌐 从上方选择已有项目，或</div>
              <button className="primary" onClick={() => setShowCreate(true)}>＋ 新建项目（推荐模板）</button>
            </div>
          )}
        </main>
        <ConfigPanel />
      </div>
      {showCreate ? <CreateModal onDone={() => setShowCreate(false)} /> : null}
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
  return token ? <Workspace /> : <Login />
}
