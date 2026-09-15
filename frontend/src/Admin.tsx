import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { errText, useStore } from './store'
import { modelLabel } from './labels'

type Tab = 'overview' | 'runlogs' | 'users' | 'projects' | 'usage' | 'audit' | 'templates' | 'settings'

type TabMeta = { key: Tab; label: string; desc: string; badge?: (ov: any, users: any[], projects: any[]) => string | number }
const TABS: TabMeta[] = [
  { key: 'overview', label: '📊 概览', desc: '系统总体情况与本月消耗' },
  { key: 'runlogs', label: '🧾 运行台账', desc: '谁用了哪个模板、输入了什么、生成了什么（含失败与被拦截）', badge: () => '' },
  { key: 'users', label: '👥 用户管理', desc: '角色、配额、密码与邀请码', badge: (_o, u) => (u?.length ?? 0) },
  { key: 'projects', label: '📁 项目管理', desc: '全部项目、归属与清理', badge: (_o, _u, p) => (p?.length ?? 0) },
  { key: 'usage', label: '💰 用量看板', desc: 'AI 调用趋势与成本排行' },
  { key: 'audit', label: '📜 审计日志', desc: '关键操作留痕查询' },
  { key: 'templates', label: '🧩 节点与提示词', desc: '维护节点库与全站提示词（改完全站生效）' },
  { key: 'settings', label: '⚙️ 系统设置', desc: '注册、配额与并发策略' },
]

function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" className={`switch${checked ? ' on' : ''}`} role="switch" aria-checked={checked}
      disabled={disabled} onClick={() => onChange(!checked)} title={checked ? '点击关闭' : '点击开启'}>
      <span className="knob" />
    </button>
  )
}

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
  const [regOpen, setRegOpen] = useState<boolean | null>(null)
  const [newInvite, setNewInvite] = useState<any>(null)
  const [q, setQ] = useState('')
  const [auditQ, setAuditQ] = useState({ action: '', username: '' })
  const [runFilter, setRunFilter] = useState({ days: 30, username: '', node_type: '', status: '', only_failed: false, q: '' })
  const [runSum, setRunSum] = useState<any>(null)
  const [runLogs, setRunLogs] = useState<any>({ total: 0, items: [] })
  const [runDetail, setRunDetail] = useState<any>(null)
  const [versions, setVersions] = useState<any>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      if (tab === 'overview') {
        const o: any = await api.adminOverview()
        setOv(o)
        setRegOpen(!!o.registration_open)
      }
      if (tab === 'users' || tab === 'settings') {
        const st: any = await api.adminSettings()
        setRegOpen(!!st.registration_open)
      }
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
      if (tab === 'runlogs') {
        const f = { ...runFilter, only_failed: runFilter.only_failed || undefined }
        setRunSum(await api.adminRunLogSummary(f))
        setRunLogs(await api.adminRunLogs({ ...f, limit: 50, offset: 0 }))
      }
      if (tab === 'settings') setSettings(await api.adminSettings())
    } catch (e: any) {
      if (e?.response?.status === 403) setDenied(true)
      else toastMsg(errText(e))
    }
    setBusy(false)
  }, [tab, q, auditQ.action, auditQ.username, runFilter, toastMsg])

  useEffect(() => { void load() }, [load])

  async function updateUser(u: any, body: Record<string, unknown>, tip: string) {
    try {
      await api.adminUpdateUser(u.id, body)
      toastMsg(tip)
      await load()
    } catch (e) { toastMsg(errText(e)) }
  }

  async function toggleRegistration(next: boolean) {
    if (next && !confirm('开启后任何人都可以自行注册并消耗 AI 额度（受各账号配额限制），确定开启公开注册？')) return
    try {
      await api.adminSaveSettings({ registration_open: next })
      setRegOpen(next)
      setSettings((st: any) => ({ ...st, registration_open: next }))
      toastMsg(next ? '已开启公开注册：无需邀请码即可注册' : '已关闭公开注册：新用户需邀请码')
    } catch (e) { toastMsg(errText(e)) }
  }

  async function showVersions(templateType: string, templateId: string, title: string) {
    try {
      setVersions({ title, items: await api.adminTemplateVersions({ template_type: templateType, template_id: templateId }) })
    } catch (e) { toastMsg(errText(e)) }
  }

  async function openRunDetail(id: string) {
    try { setRunDetail(await api.adminRunLogDetail(id)) } catch (e) { toastMsg(errText(e)) }
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

        {tab === 'runlogs' ? (
          <>
            <div className="cards">
              <div className="card"><div className="card-num">{runSum?.totals.runs ?? '-'}</div><div className="card-label">近 {runFilter.days} 天运行次数</div></div>
              <div className="card"><div className="card-num ok">{runSum?.totals.ok ?? '-'}</div><div className="card-label">成功</div></div>
              <div className="card"><div className="card-num danger">{runSum?.totals.failed ?? '-'}</div><div className="card-label">失败</div></div>
              <div className="card"><div className="card-num">{runSum?.totals.blocked ?? '-'}</div><div className="card-label">被拦截（配额/排队）</div></div>
              <div className="card"><div className="card-num">{runSum?.totals.users ?? '-'}</div><div className="card-label">使用人数</div></div>
              <div className="card"><div className="card-num">{(runSum?.totals.prompt_tokens ?? 0) + (runSum?.totals.completion_tokens ?? 0)}</div><div className="card-label">消耗 token</div></div>
              <div className="card"><div className="card-num">{runSum?.totals.cost_est ?? '-'}</div><div className="card-label">估算费用（元）</div></div>
              <div className="card"><div className="card-num">{Math.round((runSum?.totals.avg_duration_ms ?? 0) / 100) / 10}s</div><div className="card-label">平均耗时</div></div>
            </div>
            <div className="admin-toolbar runlog-bar" style={{ marginTop: 12 }}>
              <select value={runFilter.days} onChange={(e) => setRunFilter({ ...runFilter, days: Number(e.target.value) })}>
                <option value={1}>近 1 天</option><option value={7}>近 7 天</option>
                <option value={30}>近 30 天</option><option value={90}>近 90 天</option><option value={365}>近一年</option>
              </select>
              <select value={runFilter.node_type} onChange={(e) => setRunFilter({ ...runFilter, node_type: e.target.value })}>
                <option value="">全部节点类型</option>
                <option value="draft_input">草稿</option><option value="rewriter">AI 改写</option>
                <option value="transformer">格式转换</option><option value="ai_reviewer">AI 审稿</option>
                <option value="reviewer">人工审定</option><option value="tool">工具</option><option value="exporter">成稿导出</option>
              </select>
              <select value={runFilter.status} onChange={(e) => setRunFilter({ ...runFilter, status: e.target.value })}>
                <option value="">全部状态</option><option value="ok">成功</option>
                <option value="failed">失败</option><option value="blocked">被拦截</option><option value="running">运行中</option>
              </select>
              <input className="rl-q" placeholder="用户/项目/节点/错误关键字" value={runFilter.q}
                onChange={(e) => setRunFilter({ ...runFilter, q: e.target.value })} />
              <span className="check-row" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Switch checked={runFilter.only_failed} onChange={(v) => setRunFilter({ ...runFilter, only_failed: v })} />
                <span className="dim">仅看失败/被拦截</span>
              </span>
              <div className="spacer" />
              <button onClick={() => void load()}>查询</button>
              <button onClick={async () => {
                try {
                  await api.adminDownloadRunLogsCsv({ ...runFilter, only_failed: runFilter.only_failed || undefined })
                  toastMsg('台账已导出（默认不含正文预览）')
                } catch (e) { toastMsg(errText(e)) }
              }}>⬇ 导出 CSV</button>
              <button onClick={async () => {
                if (!confirm('按保留期清理：删除 12 个月前的运行台账，确定？')) return
                try {
                  const r: any = await api.adminPruneRunLogs(12)
                  toastMsg(`已清理 ${r.deleted} 条 12 个月前的台账`)
                  await load()
                } catch (e) { toastMsg(errText(e)) }
              }}>🧹 归档清理</button>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>时间</th><th>用户</th><th>项目</th><th>节点</th><th>触发</th><th>状态</th>
                  <th>模型</th><th>输入→输出</th><th>耗时</th><th>token</th><th>费用</th><th>提示词</th>
                </tr>
              </thead>
              <tbody>
                {(runLogs.items || []).map((r: any) => (
                  <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => void openRunDetail(r.id)}>
                    <td className="dim">{fmtTime(r.created_at)}</td>
                    <td>{r.username || '-'}</td>
                    <td>{r.project_name || <span className="dim">(项目已删除)</span>}</td>
                    <td><b>{r.node_label || r.node_type}</b><div className="dim">{r.node_type}{r.node_subtype ? ':' + r.node_subtype : ''}</div></td>
                    <td>{{ manual: '手动', auto: '一键', retry: '重试' }[r.trigger as string] || r.trigger}</td>
                    <td>{r.status === 'ok' ? <span className="ok">成功</span>
                      : r.status === 'blocked' ? <span className="warn">已拦截</span>
                      : r.status === 'running' ? <span className="dim">运行中</span>
                      : <span className="danger">失败</span>}</td>
                    <td>{modelLabel(r.model)}</td>
                    <td>{r.input_chars} → {r.output_chars}</td>
                    <td>{r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + 's' : '-'}{r.queued_ms ? <span className="dim"> (排队 {Math.round(r.queued_ms / 1000)}s)</span> : null}</td>
                    <td>{r.prompt_tokens}+{r.completion_tokens}{r.retries ? <span className="warn"> ↻{r.retries}</span> : null}</td>
                    <td>{r.cost_est}</td>
                    <td className="dim">
                      {{ node: '节点自定义', global: '全站模板', builtin: '系统内置' }[r.prompt_source as string] || '-'}
                      {r.prompt_template_version ? ` v${r.prompt_template_version}` : ''}
                      {r.prompt_hash ? <div>#{r.prompt_hash}</div> : null}
                    </td>
                  </tr>
                ))}
                {(runLogs.items || []).length === 0 ? (
                  <tr><td colSpan={12} className="dim" style={{ textAlign: 'center', padding: 22 }}>该范围内暂无运行记录</td></tr>
                ) : null}
              </tbody>
            </table>
            <div className="dim" style={{ margin: '8px 0 18px' }}>
              共 {runLogs.total} 条，表格显示最近 {Math.min(50, (runLogs.items || []).length)} 条，点击任意一行查看输入/输出与参数快照。
            </div>
            <div className="two-col">
              <div>
                <h4>📈 模板使用排行（哪个节点用得最多）</h4>
                <table className="tbl">
                  <thead><tr><th>节点</th><th>类型</th><th>模板版本</th><th>次数</th></tr></thead>
                  <tbody>
                    {(runSum?.by_node_template || []).map((t: any, i: number) => (
                      <tr key={i}><td>{t.label}</td><td className="dim">{t.subtype}</td><td>v{t.version}</td><td><b>{t.count}</b></td></tr>
                    ))}
                    {(runSum?.by_node_template || []).length === 0 ? <tr><td colSpan={4} className="dim">暂无</td></tr> : null}
                  </tbody>
                </table>
              </div>
              <div>
                <h4>👤 使用人排行</h4>
                <table className="tbl">
                  <thead><tr><th>用户</th><th>运行次数</th></tr></thead>
                  <tbody>
                    {(runSum?.by_user || []).map((u: any, i: number) => (
                      <tr key={i}><td>{u.username}</td><td><b>{u.count}</b></td></tr>
                    ))}
                    {(runSum?.by_user || []).length === 0 ? <tr><td colSpan={2} className="dim">暂无</td></tr> : null}
                  </tbody>
                </table>
                <h4 style={{ marginTop: 14 }}>🧷 画布模板来源</h4>
                <table className="tbl">
                  <thead><tr><th>模板</th><th>次数</th></tr></thead>
                  <tbody>
                    {(runSum?.by_template || []).map((t: any, i: number) => (
                      <tr key={i}><td>{t.template_key === 'standard_v1' ? '标准流程' : t.template_key === 'ai_review_v1' ? 'AI 审稿流程' : t.template_key === 'blank' ? '空白画布' : t.template_key}</td><td>{t.count}</td></tr>
                    ))}
                    {(runSum?.by_template || []).length === 0 ? <tr><td colSpan={2} className="dim">暂无</td></tr> : null}
                  </tbody>
                </table>
              </div>
            </div>
            {(runSum?.recent_failures || []).length ? (
              <>
                <h4 style={{ marginTop: 16 }}>⚠️ 最近的失败与被拦截</h4>
                <table className="tbl">
                  <thead><tr><th>时间</th><th>用户</th><th>节点</th><th>原因</th></tr></thead>
                  <tbody>
                    {runSum.recent_failures.map((r: any) => (
                      <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => void openRunDetail(r.id)}>
                        <td className="dim">{fmtTime(r.created_at)}</td><td>{r.username}</td>
                        <td>{r.node_label || r.node_type}</td>
                        <td className="danger">{r.error || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </>
        ) : null}

        {tab === 'users' ? (
          <>
            <div className="reg-bar">
              <Switch checked={!!regOpen} onChange={toggleRegistration} disabled={regOpen === null} />
              <div className="reg-text">
                <b>公开注册：{regOpen === null ? '读取中…' : regOpen ? '已开启' : '已关闭'}</b>
                <span className="dim">
                  {regOpen
                    ? '任何人打开登录页即可自行注册（仍受账号配额限制）'
                    : '新用户只能凭邀请码注册 —— 把下方邀请码链接发给同事'}
                </span>
              </div>
            </div>
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
              <thead><tr><th>分组</th><th>节点</th><th>图标</th><th>颜色</th><th>排序</th><th>提示词</th><th>版本</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {nodeTpls.map((t) => (
                  <tr key={t.id}>
                    <td>{t.group}</td>
                    <td><b>{t.label}</b><div className="dim">{t.kind}{t.subtype ? ':' + t.subtype : ''}</div></td>
                    <td style={{ fontSize: 18 }}>{t.icon}</td>
                    <td><span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 99, background: t.color }} /> {t.color}</td>
                    <td>{t.sort}</td>
                    <td>{t.prompt ? <span className="ok">{t.prompt.length} 字</span> : <span className="dim">未设置</span>}</td>
                    <td><b>v{t.version || 1}</b></td>
                    <td>{t.enabled ? <span className="ok">启用</span> : <span className="danger">已停用</span>}</td>
                    <td>
                      <button onClick={() => setEditNode({ ...t })}>编辑</button>
                      <button onClick={() => void showVersions('node', t.id, t.label)}>版本历史</button>
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
              <thead><tr><th>标识</th><th>名称</th><th>字数</th><th>版本</th><th>范围</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {promptTpls.map((t) => (
                  <tr key={t.id}>
                    <td><code>{t.key}</code></td>
                    <td>{t.name}</td>
                    <td>{t.content.length}</td>
                    <td><b>v{t.version || 1}</b></td>
                    <td>{t.scope === 'global' ? '全站' : '个人'}</td>
                    <td>{t.enabled ? <span className="ok">启用</span> : <span className="danger">已停用</span>}</td>
                    <td>
                      <button onClick={() => setEditPrompt({ ...t })}>编辑</button>
                      <button onClick={() => void showVersions('prompt', t.id, t.key)}>版本历史</button>
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
            <label className="check-row" style={{ alignItems: 'center' }}>
              <Switch checked={!!settings.registration_open}
                onChange={(v) => setSettings({ ...settings, registration_open: v })} />
              <span>开放公开注册（关闭时新用户需邀请码）</span>
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
            <label>排队等待上限（秒，超过则提示服务繁忙）</label>
            <input type="number" value={settings.max_queue_wait_seconds ?? 120} style={{ maxWidth: 140 }}
              onChange={(e) => setSettings({ ...settings, max_queue_wait_seconds: Number(e.target.value) })} />
            <button className="primary wide" onClick={async () => {
              try { await api.adminSaveSettings(settings); toastMsg('设置已保存') } catch (e) { toastMsg(errText(e)) }
            }}>💾 保存设置</button>
            <p className="tip">修改配额后对下一次调用立即生效；预算仅用于统计提醒，不自动阻断。</p>
          </div>
        ) : null}
        </main>
      </div>
      {versions ? (
        <div className="modal-mask" onClick={() => setVersions(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>版本历史：{versions.title}</h3>
            <p className="tip">每次保存都会留存快照，便于回看"当时用的是哪一版"。台账中的节点模板版本号即对应这里。</p>
            <table className="tbl">
              <thead><tr><th>版本</th><th>修改人</th><th>时间</th><th>说明</th><th>内容</th></tr></thead>
              <tbody>
                {(versions.items || []).map((v: any) => (
                  <tr key={v.id}>
                    <td><b>v{v.version}</b></td>
                    <td>{v.changed_by || '-'}</td>
                    <td className="dim">{fmtTime(v.created_at)}</td>
                    <td>{v.note || '-'}</td>
                    <td className="dim">{JSON.stringify(v.snapshot).slice(0, 80)}</td>
                  </tr>
                ))}
                {(versions.items || []).length === 0 ? <tr><td colSpan={5} className="dim">暂无版本记录（本次升级后新增的改动才会留存）</td></tr> : null}
              </tbody>
            </table>
            <div className="btn-row right"><button onClick={() => setVersions(null)}>关闭</button></div>
          </div>
        </div>
      ) : null}
      {runDetail ? (
        <div className="modal-mask" onClick={() => setRunDetail(null)}>
          <div className="modal wide-modal" onClick={(e) => e.stopPropagation()}>
            <h3>运行台账详情</h3>
            <p className="tip">
              {fmtTime(runDetail.created_at)} · {runDetail.username} · {runDetail.project_name || '(项目已删除)'}
              {' · '}{runDetail.node_label || runDetail.node_type}
              {runDetail.node_subtype ? '(' + runDetail.node_type + ':' + runDetail.node_subtype + ')' : ''}
              {' · '}{runDetail.status === 'ok' ? '成功' : runDetail.status === 'blocked' ? '被拦截' : runDetail.status}
            </p>
            <div className="run-meta">
              <span>触发：{{ manual: '手动点击', auto: '一键执行', retry: '重试' }[runDetail.trigger as string] || runDetail.trigger}</span>
              <span>模型：{modelLabel(runDetail.model)}</span>
              <span>token：{runDetail.prompt_tokens}+{runDetail.completion_tokens}</span>
              <span>耗时：{runDetail.duration_ms}ms{runDetail.queued_ms ? `（排队 ${runDetail.queued_ms}ms）` : ''}</span>
              <span>重试：{runDetail.retries}</span>
              <span>费用：{runDetail.cost_est} 元</span>
              <span>画布模板：{runDetail.template_key || '-'}</span>
              <span>节点模板版本：v{runDetail.node_template_version || 1}</span>
              <span>提示词来源：{{ node: '节点自定义', global: '全站模板', builtin: '系统内置' }[runDetail.prompt_source as string] || runDetail.prompt_source || '-'}
                {runDetail.prompt_template_version ? ` v${runDetail.prompt_template_version}` : ''}
                {runDetail.prompt_hash ? ` #${runDetail.prompt_hash}` : ''}</span>
            </div>
            {runDetail.error ? <p className="danger">失败原因：{runDetail.error}</p> : null}
            <label>输入（{runDetail.input_chars} 字，前 500 字）</label>
            <pre className="run-pre">{runDetail.input_preview || '（无，例如草稿/PDF 提取类节点）'}</pre>
            <label>生成物（{runDetail.output_chars} 字，前 500 字）</label>
            <pre className="run-pre">{runDetail.output_preview || '（无正文，例如审定/AI 审稿节点）'}</pre>
            {runDetail.output_content ? (
              <>
                <label>生成物开头（来自稿件版本）</label>
                <pre className="run-pre">{runDetail.output_content.slice(0, 800)}</pre>
              </>
            ) : null}
            <label>参数快照</label>
            <pre className="run-pre">{JSON.stringify(runDetail.params || {}, null, 2)}</pre>
            <div className="btn-row right">
              <button onClick={() => setRunDetail(null)}>关闭</button>
            </div>
          </div>
        </div>
      ) : null}
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
