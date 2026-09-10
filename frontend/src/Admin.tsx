import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { errText, useStore } from './store'

type Tab = 'overview' | 'users' | 'projects' | 'usage' | 'audit' | 'settings'

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: '📊 概览' },
  { key: 'users', label: '👥 用户管理' },
  { key: 'projects', label: '📁 项目管理' },
  { key: 'usage', label: '💰 用量看板' },
  { key: 'audit', label: '📜 审计日志' },
  { key: 'settings', label: '⚙️ 系统设置' },
]

function fmtTime(s?: string | null) {
  if (!s) return '-'
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }) } catch { return s }
}

export default function AdminApp() {
  const toastMsg = useStore((s) => s.toastMsg)
  const toast = useStore((s) => s.toast)
  const logout = useStore((s) => s.logout)
  const [tab, setTab] = useState<Tab>('overview')
  const [denied, setDenied] = useState(false)

  const [ov, setOv] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [daily, setDaily] = useState<any[]>([])
  const [usageUsers, setUsageUsers] = useState<any[]>([])
  const [audit, setAudit] = useState<any>({ total: 0, items: [] })
  const [settings, setSettings] = useState<any>({})
  const [q, setQ] = useState('')
  const [auditQ, setAuditQ] = useState({ action: '', username: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      if (tab === 'overview') setOv(await api.adminOverview())
      if (tab === 'users') setUsers(await api.adminUsers(q))
      if (tab === 'projects') setProjects(await api.adminProjects(q))
      if (tab === 'usage') {
        const d: any = await api.adminUsageDaily(14)
        const u: any = await api.adminUsageUsers(30)
        setDaily(d.daily || []); setUsageUsers(u.users || [])
      }
      if (tab === 'audit') setAudit(await api.adminAudit({ ...auditQ, limit: 150 }))
      if (tab === 'settings') setSettings(await api.adminSettings())
    } catch (e: any) {
      if (e?.response?.status === 403) setDenied(true)
      else toastMsg(errText(e))
    }
    setBusy(false)
  }, [tab, q, auditQ.action, auditQ.username, toastMsg])

  useEffect(() => { void load() }, [load])

  async function updateUser(u: any, body: Record<string, unknown>, tip: string) {
    try {
      await api.adminUpdateUser(u.id, body)
      toastMsg(tip)
      await load()
    } catch (e) { toastMsg(errText(e)) }
  }

  async function resetPassword(u: any) {
    const pw = prompt(`为用户「${u.username}」设置新密码（≥8 位，含字母和数字）`)
    if (!pw) return
    try {
      await api.adminResetPassword(u.id, pw)
      toastMsg(`${u.username} 的密码已重置，旧登录已失效`)
    } catch (e) { toastMsg(errText(e)) }
  }

  async function deleteProject(p: any) {
    if (!confirm(`确定删除项目「${p.name}」（归属 ${p.owner}）？\n将连同画布与稿件一并删除，不可恢复。`)) return
    try { await api.adminDeleteProject(p.id); toastMsg('项目已删除'); await load() } catch (e) { toastMsg(errText(e)) }
  }

  async function transferProject(p: any) {
    const owner = prompt(`把项目「${p.name}」转移给哪个用户？（输入用户名）`)
    if (!owner) return
    try { await api.adminTransferProject(p.id, owner); toastMsg(`已转移给 ${owner}`); await load() } catch (e) { toastMsg(errText(e)) }
  }

  if (denied) {
    return (
      <div className="admin-denied">
        <h2>需要管理员权限</h2>
        <p>当前账号不是管理员，无法访问管理后台。</p>
        <a href="/">← 返回工作台</a>
      </div>
    )
  }

  return (
    <div className="admin">
      <header className="admin-top">
        <div className="brand">🛠 智能编辑系统 · 管理后台</div>
        <div className="spacer" />
        <span className="dim">{busy ? '加载中…' : ''}</span>
        <button onClick={() => void load()}>↻ 刷新</button>
        <a className="admin-link" href="/">← 返回工作台</a>
        <button onClick={logout}>退出登录</button>
      </header>

      <nav className="admin-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? 'on' : ''} onClick={() => { setTab(t.key); setQ('') }}>{t.label}</button>
        ))}
      </nav>

      <main className="admin-body">
        {tab === 'overview' && ov ? (
          <>
            <div className="cards">
              <div className="card"><div className="card-num">{ov.users.total}</div><div className="card-label">用户（启用 {ov.users.active}）</div></div>
              <div className="card"><div className="card-num">{ov.projects}</div><div className="card-label">项目</div></div>
              <div className="card"><div className="card-num">{ov.nodes}</div><div className="card-label">画布节点</div></div>
              <div className="card"><div className="card-num">{ov.revisions}</div><div className="card-label">稿件版本</div></div>
              <div className="card"><div className="card-num">{ov.today.calls}</div><div className="card-label">今日 AI 调用（≈{ov.today.cost_yuan} 元）</div></div>
              <div className="card"><div className="card-num">{ov.month.calls}</div><div className="card-label">本月调用（≈{ov.month.cost_yuan} 元 / 预算 {ov.month.budget_yuan} 元，{ov.month.budget_used_pct}%）</div></div>
              <div className="card"><div className="card-num">{ov.window.failed}</div><div className="card-label">近 {ov.window.days} 天失败调用</div></div>
              <div className="card"><div className="card-num">{ov.registration_open ? '开启' : '关闭'}</div><div className="card-label">公开注册（默认配额 {ov.default_monthly_call_limit} 次/月）</div></div>
            </div>
            <p className="tip">提示：注册已关闭时，新同事需凭邀请码注册。邀请码可用「用户管理」页生成。</p>
          </>
        ) : null}

        {tab === 'users' ? (
          <>
            <div className="admin-toolbar">
              <input placeholder="搜索用户名…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 240 }} />
              <button onClick={() => void load()}>搜索</button>
              <div className="spacer" />
              <button className="primary" onClick={async () => {
                const role = (prompt('邀请码角色（admin/editor/reviewer/viewer）', 'editor') || 'editor').trim()
                const validRoles = ['admin', 'editor', 'reviewer', 'viewer']
                const daysRaw = Number((prompt('有效期天数', '7') || '7').trim())
                const days = Number.isFinite(daysRaw) && daysRaw > 0 ? Math.min(Math.floor(daysRaw), 365) : 7
                try {
                  const r = await fetch('/api/invites', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('cs_token')}` },
                    body: JSON.stringify({ role: validRoles.includes(role) ? role : 'editor', expires_days: days }),
                  })
                  const d = await r.json()
                  if (!r.ok) throw new Error(d.detail || '生成失败')
                  toastMsg(`邀请码：${d.code}（${days} 天内有效，角色 ${d.role}）`)
                  alert(`邀请码：${d.code}\n有效期：${days} 天\n角色：${d.role}\n\n请发给需要注册的同事。`)
                } catch (e) { toastMsg(errText(e)) }
              }}>＋ 生成邀请码</button>
            </div>
            <table className="tbl">
              <thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>项目</th><th>近30天调用</th><th>成本(元)</th><th>配额/月</th><th>最近登录</th><th>操作</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><b>{u.username}</b></td>
                    <td>
                      <select value={u.role} onChange={(e) => void updateUser(u, { role: e.target.value }, `${u.username} 角色已改为 ${e.target.value}`)}>
                        <option value="admin">管理员</option>
                        <option value="editor">编辑</option>
                        <option value="reviewer">审核</option>
                        <option value="viewer">只读</option>
                      </select>
                    </td>
                    <td>{u.is_active ? <span className="ok">启用</span> : <span className="danger">已禁用</span>}</td>
                    <td>{u.projects}</td>
                    <td>{u.usage_30d.calls}</td>
                    <td>{u.usage_30d.cost_yuan}</td>
                    <td>
                      <input style={{ width: 74 }} defaultValue={u.monthly_call_limit ?? ''} placeholder="继承"
                        onBlur={(e) => {
                          const v = e.target.value.trim()
                          const val = v === '' ? null : Number(v)
                          if (val !== (u.monthly_call_limit ?? null)) void updateUser(u, { monthly_call_limit: val }, `${u.username} 配额已更新`)
                        }} />
                    </td>
                    <td>{fmtTime(u.last_login_at)}</td>
                    <td>
                      <button onClick={() => void resetPassword(u)}>重置密码</button>
                      <button onClick={() => void updateUser(u, { is_active: !u.is_active }, u.is_active ? '已禁用该账号' : '已启用该账号')}>
                        {u.is_active ? '禁用' : '启用'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tip">配额留空 = 继承全局默认；填 0 = 禁止该账号调用 AI；修改角色或禁用会使其登录立即失效。</p>
          </>
        ) : null}

        {tab === 'projects' ? (
          <>
            <div className="admin-toolbar">
              <input placeholder="搜索项目名 / 归属…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} />
              <button onClick={() => void load()}>搜索</button>
            </div>
            <table className="tbl">
              <thead><tr><th>项目</th><th>归属</th><th>节点</th><th>稿件</th><th>更新时间</th><th>操作</th></tr></thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.owner}</td>
                    <td>{p.nodes}</td>
                    <td>{p.revisions}</td>
                    <td>{fmtTime(p.updated_at)}</td>
                    <td>
                      <button onClick={() => void transferProject(p)}>转移</button>
                      <button className="danger" onClick={() => void deleteProject(p)}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}

        {tab === 'usage' ? (
          <>
            <div className="admin-toolbar">
              <b>近 14 天趋势</b>
              <div className="spacer" />
              <button onClick={() => void api.adminDownloadUsageCsv(30)}>⬇ 导出近30天 CSV</button>
            </div>
            <table className="tbl">
              <thead><tr><th>日期</th><th>调用次数</th><th>Token</th><th>成本(元)</th></tr></thead>
              <tbody>{daily.map((d) => <tr key={d.date}><td>{d.date}</td><td>{d.calls}</td><td>{d.tokens}</td><td>{d.cost_yuan}</td></tr>)}</tbody>
            </table>
            <h4>近 30 天按用户排行</h4>
            <table className="tbl">
              <thead><tr><th>用户</th><th>角色</th><th>调用次数</th><th>Token</th><th>成本(元)</th></tr></thead>
              <tbody>{usageUsers.map((u) => (
                <tr key={u.username}><td><b>{u.username}</b></td><td>{u.role}</td><td>{u.calls}</td><td>{u.tokens}</td><td>{u.cost_yuan}</td></tr>
              ))}</tbody>
            </table>
          </>
        ) : null}

        {tab === 'audit' ? (
          <>
            <div className="admin-toolbar">
              <input placeholder="动作类型，如 login / node_execute…" value={auditQ.action}
                onChange={(e) => setAuditQ({ ...auditQ, action: e.target.value })} style={{ maxWidth: 240 }} />
              <input placeholder="用户名" value={auditQ.username}
                onChange={(e) => setAuditQ({ ...auditQ, username: e.target.value })} style={{ maxWidth: 160 }} />
              <button onClick={() => void load()}>查询</button>
              <div className="spacer" />
              <span className="dim">共 {audit.total} 条，显示最新 {audit.items.length} 条</span>
            </div>
            <table className="tbl">
              <thead><tr><th>时间</th><th>动作</th><th>用户</th><th>对象</th><th>详情</th><th>IP</th></tr></thead>
              <tbody>{audit.items.map((a: any) => (
                <tr key={a.id}>
                  <td>{fmtTime(a.created_at)}</td>
                  <td><code>{a.action}</code></td>
                  <td>{a.username || '-'}</td>
                  <td>{a.target_type ? `${a.target_type}:${(a.target_id || '').slice(0, 8)}` : '-'}</td>
                  <td className="detail-cell">{JSON.stringify(a.detail).slice(0, 90)}</td>
                  <td>{a.ip || '-'}</td>
                </tr>
              ))}</tbody>
            </table>
          </>
        ) : null}

        {tab === 'settings' && settings ? (
          <div className="settings-form">
            <label className="check-row">
              <input type="checkbox" checked={!!settings.registration_open}
                onChange={(e) => setSettings({ ...settings, registration_open: e.target.checked })} />
              <span>开放公开注册（关闭时需邀请码）</span>
            </label>
            <label>默认每人每月 AI 调用上限（留空/0 语义见说明）</label>
            <input type="number" value={settings.default_monthly_call_limit ?? 600}
              onChange={(e) => setSettings({ ...settings, default_monthly_call_limit: Number(e.target.value) })} />
            <label>全局月度预算（元，用于用量看板进度）</label>
            <input type="number" value={settings.global_monthly_budget_yuan ?? 300}
              onChange={(e) => setSettings({ ...settings, global_monthly_budget_yuan: Number(e.target.value) })} />
            <label>并发上限（全局 / 单用户）</label>
            <div className="btn-row">
              <input type="number" value={settings.max_concurrency_global ?? 8} style={{ maxWidth: 100 }}
                onChange={(e) => setSettings({ ...settings, max_concurrency_global: Number(e.target.value) })} />
              <input type="number" value={settings.max_concurrency_user ?? 2} style={{ maxWidth: 100 }}
                onChange={(e) => setSettings({ ...settings, max_concurrency_user: Number(e.target.value) })} />
            </div>
            <button className="primary wide" onClick={async () => {
              try { await api.adminSaveSettings(settings); toastMsg('设置已保存') } catch (e) { toastMsg(errText(e)) }
            }}>💾 保存设置</button>
            <p className="tip">修改配额后对下一次调用立即生效；预算仅用于统计提醒，不自动阻断。</p>
          </div>
        ) : null}
      </main>
      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  )
}
