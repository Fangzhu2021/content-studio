import axios from 'axios'

export const TOKEN_KEY = 'cs_token'
export const USER_KEY = 'cs_user'

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY) }
export function setAuth(token: string, user: unknown) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export const http = axios.create({ baseURL: '/api', timeout: 180000 })

http.interceptors.request.use((cfg) => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response && err.response.status === 401 && !location.pathname.includes('/login')) {
      clearAuth()
      window.dispatchEvent(new Event('cs:logout'))
    }
    return Promise.reject(err)
  },
)

function detail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return (e as Error)?.message || '请求失败'
}

export const api = {
  detail,
  async register(username: string, password: string, inviteCode = '') {
    const { data } = await http.post('/auth/register', { username, password, invite_code: inviteCode })
    return data as { token: string; user: { id: string; username: string; role?: string } }
  },
  async changePassword(oldPassword: string, newPassword: string) {
    const { data } = await http.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
    return data as { token: string; user: { id: string; username: string; role?: string } }
  },
  async registerMode() {
    const { data } = await http.get('/auth/register-mode')
    return data as { registration_open: boolean; invite_required: boolean; password_rule: string }
  },
  async login(username: string, password: string) {
    const { data } = await http.post('/auth/login', { username, password })
    return data as { token: string; user: { id: string; username: string } }
  },
  async listProjects() {
    const { data } = await http.get('/projects')
    return data as { id: string; name: string; created_at?: string | null }[]
  },
  async createProject(name: string, template: boolean, aiReview = false) {
    const { data } = await http.post('/projects', { name, template, ai_review: aiReview })
    return data as { id: string; name: string }
  },
  async getProject(id: string) {
    const { data } = await http.get(`/projects/${id}`)
    return data as import('./types').ProjectDetail
  },
  async getCanvas(id: string) {
    const { data } = await http.get(`/projects/${id}/canvas`)
    return data as { nodes: import('./types').CanvasNode[]; edges: import('./types').CanvasEdge[] }
  },
  async deleteProject(id: string) { await http.delete(`/projects/${id}`) },
  async createNode(pid: string, payload: Record<string, unknown>) {
    const { data } = await http.post(`/projects/${pid}/nodes`, payload)
    return data as import('./types').CanvasNode
  },
  async updateNode(id: string, payload: Record<string, unknown>) {
    const { data } = await http.put(`/nodes/${id}`, payload)
    return data as import('./types').CanvasNode
  },
  async deleteNode(id: string) { await http.delete(`/nodes/${id}`) },
  async createEdge(pid: string, source: string, target: string) {
    const { data } = await http.post(`/projects/${pid}/edges`, { source, target })
    return data as import('./types').CanvasEdge
  },
  async deleteEdge(id: string) { await http.delete(`/edges/${id}`) },
  async saveContent(nodeId: string, title: string, content: string) {
    const { data } = await http.post(`/nodes/${nodeId}/content`, { title, content })
    return data as import('./types').Revision
  },
  // ---------- PDF 版面提取 ----------
  async uploadPdf(nodeId: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post(`/nodes/${nodeId}/pdf`, form)
    return data as {
      filename: string; size: number; pages: number; total_chars: number
      blocks: { index: number; page: number; title: string; chars: number; column: number; preview: string }[]
    }
  },
  async pdfStatus(nodeId: string) {
    const { data } = await http.get(`/nodes/${nodeId}/pdf`)
    return data as {
      uploaded: boolean; filename?: string; size?: number; pages?: number; total_chars?: number
      selected?: number[]; blocks?: { index: number; page: number; title: string; chars: number; column: number; preview: string }[]
    }
  },
  async pdfSelect(nodeId: string, indexes: number[]) {
    const { data } = await http.post(`/nodes/${nodeId}/pdf/select`, { indexes })
    return data as { revision_id: string; title: string; chars: number; selected: number[]; content: string }
  },
  async pdfRemove(nodeId: string) { await http.delete(`/nodes/${nodeId}/pdf`) },

  // ---------- 节点库 / 提示词模板 ----------
  async getTemplates() {
    const { data } = await http.get('/templates')
    return data as {
      nodes: { id: string; group: string; kind: string; subtype: string; label: string; icon: string; color: string; hint?: string; sort?: number; default_config?: Record<string, unknown> }[]
      prompts: Record<string, string>
    }
  },
  async myPrompts() {
    const { data } = await http.get('/my/prompt-templates')
    return data as { id: string; key: string; name: string; content: string }[]
  },
  async createMyPrompt(key: string, name: string, content: string) {
    const { data } = await http.post('/my/prompt-templates', { key, name, content })
    return data
  },
  async deleteMyPrompt(id: string) { await http.delete(`/my/prompt-templates/${id}`) },
  async adminNodeTemplates() { const { data } = await http.get('/admin/node-templates'); return data },
  async adminCreateNodeTemplate(body: Record<string, unknown>) { const { data } = await http.post('/admin/node-templates', body); return data },
  async adminUpdateNodeTemplate(id: string, body: Record<string, unknown>) { const { data } = await http.patch(`/admin/node-templates/${id}`, body); return data },
  async adminDeleteNodeTemplate(id: string) { await http.delete(`/admin/node-templates/${id}`) },
  async adminPromptTemplates() { const { data } = await http.get('/admin/prompt-templates'); return data },
  async adminUpdatePromptTemplate(id: string, body: Record<string, unknown>) { const { data } = await http.patch(`/admin/prompt-templates/${id}`, body); return data },
  // ---------- 管理后台 ----------
  async adminOverview() { const { data } = await http.get('/admin/overview'); return data },
  async adminUsers(q = '') { const { data } = await http.get('/admin/users', { params: { q } }); return data },
  async adminUpdateUser(id: string, body: Record<string, unknown>) {
    const { data } = await http.patch(`/admin/users/${id}`, body); return data
  },
  async adminResetPassword(id: string, newPassword: string) {
    const { data } = await http.post(`/admin/users/${id}/reset-password`, { new_password: newPassword }); return data
  },
  async adminProjects(q = '') { const { data } = await http.get('/admin/projects', { params: { q } }); return data },
  async adminDeleteProject(id: string) { const { data } = await http.delete(`/admin/projects/${id}`); return data },
  async adminTransferProject(id: string, owner: string) {
    const { data } = await http.post(`/admin/projects/${id}/transfer`, { owner_username: owner }); return data
  },
  async adminUsageDaily(days = 14) { const { data } = await http.get('/admin/usage/daily', { params: { days } }); return data },
  async adminUsageUsers(days = 30) { const { data } = await http.get('/admin/usage/users', { params: { days } }); return data },
  async adminAudit(params: Record<string, unknown>) { const { data } = await http.get('/admin/audit', { params }); return data },
  async adminRunLogs(params: Record<string, unknown>) { const { data } = await http.get('/admin/run-logs', { params }); return data },
  async adminRunLogSummary(params: Record<string, unknown>) { const { data } = await http.get('/admin/run-logs/summary', { params }); return data },
  async adminRunLogDetail(id: string) { const { data } = await http.get(`/admin/run-logs/${id}`); return data },
  async adminTemplateVersions(params: Record<string, unknown>) { const { data } = await http.get('/admin/template-versions', { params }); return data },
  async adminPruneRunLogs(months = 12) { const { data } = await http.post('/admin/run-logs/prune', null, { params: { months } }); return data },
  async adminDownloadRunLogsCsv(params: Record<string, unknown>) {
    const token = getToken()
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) qs.set(k, String(v)) })
    const r = await fetch(`/api/admin/run-logs/export.csv?${qs.toString()}`, { headers: { Authorization: `Bearer ${token}` } })
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `run-logs-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  },
  async adminSettings() { const { data } = await http.get('/admin/settings'); return data },
  async adminSaveSettings(body: Record<string, unknown>) {
    const { data } = await http.put('/admin/settings', body); return data
  },
  async adminAiTest(model?: string) {
    const { data } = await http.post('/admin/ai/test', model ? { model } : {}); return data
  },
  async createInvite(role: string, days: number, note = '') {
    const { data } = await http.post('/invites', { role, expires_days: days, note })
    return data as { id: string; code: string; link: string; role: string; expires_at: string | null }
  },
  async listInvites() {
    const { data } = await http.get('/invites')
    return data as { id: string; code: string; link: string; role: string; note: string; used_by: string | null; revoked: boolean; expires_at: string | null; created_at: string | null }[]
  },
  async revokeInvite(id: string) { await http.post(`/invites/${id}/revoke`) },
  async adminDownloadUsageCsv(days = 30) {
    const token = getToken()
    const r = await fetch(`/api/admin/usage/export.csv?days=${days}`, { headers: { Authorization: `Bearer ${token}` } })
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `ai-usage-${days}d.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  },
  async getPrompts() {
    const { data } = await http.get('/prompts')
    return data as { prompts: Record<string, string>; labels: Record<string, string>; models: string[] }
  },
  async getRevision(rid: string) {
    const { data } = await http.get(`/revisions/${rid}`)
    return data as import('./types').Revision
  },
  async nodeRevision(nodeId: string) {
    const { data } = await http.get(`/nodes/${nodeId}/revision`)
    return data as import('./types').Revision | null
  },
  async reviewRevision(rid: string, status: string, comment: string) {
    const { data } = await http.post(`/revisions/${rid}/status`, { status, comment })
    return data as import('./types').Revision
  },
  async executeNode(nodeId: string, payload: Record<string, unknown> = {}) {
    const { data } = await http.post(`/nodes/${nodeId}/execute`, payload)
    return data as import('./types').ExecResult
  },
  async executeProject(pid: string) {
    const { data } = await http.post(`/projects/${pid}/execute`)
    return data as { project_id: string; results: { node_id: string; status: string; message?: string }[] }
  },
}
