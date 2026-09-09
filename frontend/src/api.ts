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
  async register(username: string, password: string) {
    const { data } = await http.post('/auth/register', { username, password })
    return data as { token: string; user: { id: string; username: string } }
  },
  async login(username: string, password: string) {
    const { data } = await http.post('/auth/login', { username, password })
    return data as { token: string; user: { id: string; username: string } }
  },
  async listProjects() {
    const { data } = await http.get('/projects')
    return data as { id: string; name: string; created_at?: string | null }[]
  },
  async createProject(name: string, template: boolean) {
    const { data } = await http.post('/projects', { name, template })
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
