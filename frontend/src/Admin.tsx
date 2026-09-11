import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { errText, useStore } from './store'

type Tab = 'overview' | 'users' | 'projects' | 'usage' | 'audit' | 'templates' | 'settings'

type TabMeta = { key: Tab; label: string; desc: string; badge?: (ov: any, users: any[], projects: any[]) => string | number }
const TABS: TabMeta[] = [
  { key: 'overview', label: '📊 概览', desc: '系统总体情况与本月消耗' },
  { key: 'users', label: '👥 用户管理', desc: '角色、配额、密码与邀请码', badge: (_o, u) => (u?.length ?? 0) },
  { key: 'projects', label: '📁 项目管理', desc: '全部项目、归属与清理', badge: (_o, _u, p) => (p?.length ?? 0) },
  { key: 'usage', label: '💰 用量看板', desc: 'AI 调用趋势与成本排行' },
  { key: 'audit', label: '📜 审计日志', desc: '关键操作留痕查询' },
  { key: 'templates', label: '🧩 节点与提示词', desc: '维护节点库与全站提示词（改完全站生效）' },
  { key: 'settings', label: '⚙️ 系统设置', desc: '注册、配额与并发策略' },
]

function fmtTime(s?: string | null) {
  if (!s) return '-'
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }) } catch { return s }
}

export default function AdminApp() {
  const me = useStore((s) => s.user)
  const userName = () => me?.username || '-'
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
  const [nodeTpls, setNodeTpls] = useState<any[]>([])
  const [promptTpls, setPromptTpls] = useState<any[]>([])
  const [editNode, setEditNode] = useState<any>(null)
  const [editPrompt, setEditPrompt] = useState<any>(null)
  const [invites, setInvites] = useState<any[]>([])
  const [newInvite, setNewInvite] = useState<any>(null)
  const [q, setQ] = useState('')
  const [auditQ, setAuditQ] = useState({ action: '', username: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      if (tab === 'overview') setOv(await api.adminOverview())
      if (tab === 'users') {
        setUsers(await api.adminUsers(q))
        setInvites(await api.listInvites())
      }
      if (tab === 'projects') setProjects(await api.adminProjects(q))
      if (tab === 'usage') {
        const d: any = await api.adminUsageDaily(14)
        const u: any = await api.adminUsageUsers(30)
        setDaily(d.daily || []); setUsageUsers(u.users || [])
      }
      if (tab === 'audit') setAudit(await api.adminAudit({ ...auditQ, limit: 150 }))
      if (tab === 'templates') {
        setNodeTpls(await api.adminNodeTemplates())
        setPromptTpls(await api.adminPromptTemplates())
      }
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

  async function copyInviteLink(iv: any) {
    const text = iv.link || iv.code
    try {
      await navigator.clipboard.writeText(text)
      toastMsg('注册链接已复制，发给同事即可')
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      toastMsg('注册链接已复制')
    }
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

      <div className="admin-main">
        <aside className="admin-nav">
          <div className="admin-nav-title">功能区</div>
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? 'on' : ''} onClick={() => { setTab(t.key); setQ('') }}>
              <span className="nav-label">{t.label}</span>
              {t.badge ? <span className="nav-badge">{t.badge(ov, users, projects)}</span> : null}
            </button>
          ))}
          <div className="admin-nav-foot">
            <div className="dim">当前登录</div>
            <div>{userName()}</div>
          </div>
        </aside>

        <main className="admin-body">
          <div className="admin-body-head">
            <div>
              <h2>{TABS.find((t) => t.key === tab)?.label}</h2>
              <div className="dim">{TABS.find((t) => t.key === tab)?.desc}</div>
            </div>
            <div className="spacer" />
            <span className="dim">{busy ? '加载中…' : '已同步'}</span>
          </div>
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
                  const d = await api.createInvite(validRoles.includes(role) ? role : 'editor', days)
                  setNewInvite(d)
                  await load()
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

            <div className="admin-toolbar" style={{ marginTop: 20 }}>
              <b>邀请码（{invites.length}）</b>
              <div className="spacer" />
              <span className="dim">把「链接」直接发给同事，对方打开即自动填入邀请码</span>
            </div>
            <table className="tbl">
              <thead><tr><th>邀请码</th><th>角色</th><th>状态</th><th>有效期至</th><th>注册链接</th><th>操作</th></tr></thead>
              <tbody>
                {invites.map((iv) => {
                  const expired = iv.expires_at ? new Date(iv.expires_at) < new Date() : false
                  const state = iv.revoked ? '已作废' : iv.used_by ? '已使用' : expired ? '已过期' : '可用'
                  return (
                    <tr key={iv.id}>
                      <td><code>{iv.code}</code></td>
                      <td>{iv.role}</td>
                      <td>{state === '可用' ? <span className="ok">{state}</span> : <span className="dim">{state}</span>}</td>
                      <td>{fmtTime(iv.expires_at)}</td>
                      <td className="detail-cell">{iv.link}</td>
                      <td>
                        <button onClick={() => copyInviteLink(iv)}>复制链接</button>
                        {state === '可用' ? <button className="danger" onClick={async () => {
                          if (!confirm(`作废邀请码 ${iv.code}？`)) return
                          try { await api.revokeInvite(iv.id); toastMsg('已作废'); await load() } catch (e) { toastMsg(errText(e)) }
                        }}>作废</button> : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {invites.length === 0 ? <div className="empty">还没有邀请码，点右上角「＋ 生成邀请码」。</div> : null}
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

        {tab === 'templates' ? (
          <>
            <div className="admin-toolbar">
              <b>节点库（{nodeTpls.length}）</b>
              <div className="spacer" />
              <button onClick={async () => {
                const group = prompt('分组名称，如：新媒体转换', '自定义') || '自定义'
                const kind = prompt('节点类型（draft_input/rewriter/reviewer/ai_reviewer/transformer/tool/exporter）', 'transformer') || ''
                if (!kind) return
                const subtype = prompt('格式代码（如 wechat / newspaper，可留空）', '') || ''
                const label = prompt('节点显示名称', '新节点') || '新节点'
                try {
                  await api.adminCreateNodeTemplate({ group, kind, subtype, label, icon: '🧩', color: '#64748b' })
                  toastMsg('节点模板已创建')
                  await load()
                } catch (e) { toastMsg(errText(e)) }
              }}>＋ 新增节点</button>
            </div>
            <table className="tbl">
              <thead><tr><th>分组</th><th>节点</th><th>图标</th><th>颜色</th><th>排序</th><th>提示词</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {nodeTpls.map((t) => (
                  <tr key={t.id}>
                    <td>{t.group}</td>
                    <td><b>{t.label}</b><div className="dim">{t.kind}{t.subtype ? ':' + t.subtype : ''}</div></td>
                    <td style={{ fontSize: 18 }}>{t.icon}</td>
                    <td><span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 99, background: t.color }} /> {t.color}</td>
                    <td>{t.sort}</td>
                    <td>{t.prompt ? <span className="ok">{t.prompt.length} 字</span> : <span className="dim">未设置</span>}</td>
                    <td>{t.enabled ? <span className="ok">启用</span> : <span className="danger">已停用</span>}</td>
                    <td>
                      <button onClick={() => setEditNode({ ...t })}>编辑</button>
                      <button onClick={async () => {
                        try { await api.adminUpdateNodeTemplate(t.id, { enabled: !t.enabled }); toastMsg('已更新'); await load() } catch (e) { toastMsg(errText(e)) }
                      }}>{t.enabled ? '停用' : '启用'}</button>
                      <button className="danger" onClick={async () => {
                        if (!confirm(`删除节点模板「${t.label}」？`)) return
                        try { await api.adminDeleteNodeTemplate(t.id); toastMsg('已删除'); await load() } catch (e) { toastMsg(errText(e)) }
                      }}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {editNode ? (
              <div className="settings-form" style={{ marginTop: 14 }}>
                <h4>编辑节点：{editNode.kind}{editNode.subtype ? ':' + editNode.subtype : ''}</h4>
                <label>显示名称</label>
                <input value={editNode.label} onChange={(e) => setEditNode({ ...editNode, label: e.target.value })} />
                <div className="btn-row">
                  <div style={{ flex: 1 }}>
                    <label>图标</label>
                    <input value={editNode.icon} onChange={(e) => setEditNode({ ...editNode, icon: e.target.value })} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label>颜色</label>
                    <input value={editNode.color} onChange={(e) => setEditNode({ ...editNode, color: e.target.value })} />
                  </div>
                  <div style={{ width: 100 }}>
                    <label>排序</label>
                    <input type="number" value={editNode.sort} onChange={(e) => setEditNode({ ...editNode, sort: Number(e.target.value) })} />
                  </div>
                </div>
                <label>该节点默认提示词（留空则用内置；改完全站生效）</label>
                <textarea className="rev-content" rows={8} value={editNode.prompt || ''}
                  onChange={(e) => setEditNode({ ...editNode, prompt: e.target.value })} />
                <div className="btn-row right">
                  <button onClick={() => setEditNode(null)}>取消</button>
                  <button className="primary" onClick={async () => {
                    try {
                      await api.adminUpdateNodeTemplate(editNode.id, {
                        label: editNode.label, icon: editNode.icon, color: editNode.color,
                        sort: editNode.sort, prompt: editNode.prompt,
                      })
                      toastMsg('节点模板已保存')
                      setEditNode(null)
                      await load()
                    } catch (e) { toastMsg(errText(e)) }
                  }}>💾 保存</button>
                </div>
              </div>
            ) : null}

            <div className="admin-toolbar" style={{ marginTop: 22 }}>
              <b>全站提示词模板（{promptTpls.length}）</b>
              <div className="spacer" />
              <span className="dim">修改后对所有用户的对应节点生效（节点自身保存过的提示词优先）</span>
            </div>
            <table className="tbl">
              <thead><tr><th>标识</th><th>名称</th><th>字数</th><th>范围</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {promptTpls.map((t) => (
                  <tr key={t.id}>
                    <td><code>{t.key}</code></td>
                    <td>{t.name}</td>
                    <td>{t.content.length}</td>
                    <td>{t.scope === 'global' ? '全站' : '个人'}</td>
                    <td>{t.enabled ? <span className="ok">启用</span> : <span className="danger">已停用</span>}</td>
                    <td>
                      <button onClick={() => setEditPrompt({ ...t })}>编辑</button>
                      <button onClick={async () => {
                        if (t.scope !== 'global') return
                        try { await api.adminUpdatePromptTemplate(t.id, { enabled: !t.enabled }); toastMsg('已更新'); await load() } catch (e) { toastMsg(errText(e)) }
                      }} disabled={t.scope !== 'global'}>{t.enabled ? '停用' : '启用'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {editPrompt ? (
              <div className="settings-form" style={{ marginTop: 14 }}>
                <h4>编辑提示词：{editPrompt.key}（{editPrompt.name}）</h4>
                <textarea className="rev-content" rows={10} value={editPrompt.content}
                  onChange={(e) => setEditPrompt({ ...editPrompt, content: e.target.value })} />
                <div className="btn-row right">
                  <button onClick={() => setEditPrompt(null)}>取消</button>
                  <button className="primary" onClick={async () => {
                    try {
                      await api.adminUpdatePromptTemplate(editPrompt.id, { content: editPrompt.content })
                      toastMsg('提示词已保存，全站生效')
                      setEditPrompt(null)
                      await load()
                    } catch (e) { toastMsg(errText(e)) }
                  }}>💾 保存并全站生效</button>
                </div>
              </div>
            ) : null}
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
      </div>
      {newInvite ? (
        <div className="modal-mask" onClick={() => setNewInvite(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>邀请码已生成</h3>
            <p className="tip">把下面这条链接发给同事，对方打开后会自动切到「注册」并填入邀请码。</p>
            <label>注册链接</label>
            <input readOnly value={newInvite.link} onFocus={(e) => e.currentTarget.select()} />
            <div className="dim">
              邀请码 <b>{newInvite.code}</b> · 角色 {newInvite.role} · 有效期至 {fmtTime(newInvite.expires_at)}
            </div>
            <div className="btn-row right">
              <button onClick={() => setNewInvite(null)}>关闭</button>
              <button className="primary" onClick={() => copyInviteLink(newInvite)}>📋 复制链接</button>
            </div>
          </div>
        </div>
      ) : null}
      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  )
}
