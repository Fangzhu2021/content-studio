export interface User { id: string; username: string }
export interface ProjectItem { id: string; name: string; created_at?: string | null }
export interface Pos { x: number; y: number }
export type NodeType = 'draft_input' | 'rewriter' | 'reviewer' | 'ai_reviewer' | 'transformer' | 'exporter'
export interface CanvasNode {
  id: string
  type: NodeType
  subtype: string
  label: string
  position: Pos
  config: Record<string, unknown>
  status: string
  error?: string
}
export interface CanvasEdge { id: string; source: string; target: string }
export interface ProjectDetail { id: string; name: string; nodes: CanvasNode[]; edges: CanvasEdge[] }
export interface Revision {
  id: string
  node_id: string
  parent_revision_id?: string | null
  title: string
  content: string
  format_type: string
  status: string
  model: string
  review_comment: string
  created_at?: string | null
}
export interface ExecResult { node_id: string; status: string; revision_id?: string; model?: string; message?: string }

export const FORMATS: Record<string, string> = {
  '': '原始',
  draft: '原始草稿',
  tv_script: '电视口播稿',
  newspaper: '报刊通稿',
  wechat: '公众号长文',
  weibo: '微博文案',
  douyin: '抖音口播脚本',
  xiaohongshu: '小红书笔记',
  toutiao: '头条新闻',
}

export const TYPE_META: Record<NodeType, { label: string; color: string; icon: string; desc: string }> = {
  draft_input: { label: '草稿输入', color: '#64748b', icon: '📝', desc: '录入原始稿件' },
  rewriter: { label: 'AI 改写', color: '#6366f1', icon: '✍️', desc: '草稿 → TV/报刊稿' },
  reviewer: { label: '人工审定', color: '#d97706', icon: '✅', desc: '批注/通过/打回' },
  ai_reviewer: { label: 'AI 审稿', color: '#0891b2', icon: '🤖', desc: '自动审稿（通过/打回）' },
  transformer: { label: '新媒体转换', color: '#0ea5e9', icon: '🔄', desc: '多平台风格改写' },
  exporter: { label: '成稿导出', color: '#16a34a', icon: '📤', desc: '复制/下载成稿' },
}

export const STATUS_TEXT: Record<string, string> = {
  idle: '待命', running: '执行中', done: '完成', failed: '失败', approved: '已通过', waiting: '待人工',
}

export const FORMAT_OPTIONS: { subtype: string; label: string }[] = [
  { subtype: 'tv_script', label: '电视口播稿' },
  { subtype: 'newspaper', label: '报刊通稿' },
  { subtype: 'wechat', label: '公众号长文' },
  { subtype: 'weibo', label: '微博文案' },
  { subtype: 'douyin', label: '抖音口播脚本' },
  { subtype: 'xiaohongshu', label: '小红书笔记' },
  { subtype: 'toutiao', label: '头条新闻' },
]
