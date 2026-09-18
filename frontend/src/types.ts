export interface User { id: string; username: string; role?: string }
export interface ProjectItem { id: string; name: string; created_at?: string | null }
export interface Pos { x: number; y: number }
export type NodeType = 'draft_input' | 'rewriter' | 'reviewer' | 'ai_reviewer' | 'transformer' | 'tool' | 'exporter'
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
  source?: string          // ai=AI 生成 / human=人工修订
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
  condense: '稿件精简',
  style_prompt: '风格提取',
  pdf_extract: 'PDF 提取',
  audio_transcript: '录音转写',
  topic_plan: '选题策划',
  report_plan: '报道方案',
}

/* 分类色（规范 4.1.6）：只用于分组色点与节点左侧色条；
 * 不参与状态表达；选中态固定使用品牌蓝 #4F7CFF */
export type CategoryKey = 'input' | 'tool' | 'rewrite' | 'review' | 'media' | 'export'

export const CATEGORY: Record<CategoryKey, { cssVar: string; hex: string; label: string; icon: string }> = {
  input: { cssVar: 'var(--cat-input)', hex: '#22D3EE', label: '输入', icon: 'log-in' },
  tool: { cssVar: 'var(--cat-tool)', hex: '#4F7CFF', label: '工具', icon: 'wrench' },
  rewrite: { cssVar: 'var(--cat-rewrite)', hex: '#8B5CF6', label: 'AI 改写', icon: 'sparkles' },
  review: { cssVar: 'var(--cat-review)', hex: '#F5A524', label: '审稿', icon: 'shield-check' },
  media: { cssVar: 'var(--cat-media)', hex: '#2DD4BF', label: '新媒体转换', icon: 'share-2' },
  export: { cssVar: 'var(--cat-export)', hex: '#7298FF', label: '成稿导出', icon: 'send' },
}

export const TYPE_META: Record<NodeType, { label: string; cat: CategoryKey; desc: string }> = {
  draft_input: { label: '草稿输入', cat: 'input', desc: '录入原始稿件' },
  rewriter: { label: 'AI 改写', cat: 'rewrite', desc: '草稿 → TV/报刊稿' },
  reviewer: { label: '人工审定', cat: 'review', desc: '批注 / 通过 / 打回' },
  ai_reviewer: { label: 'AI 审稿', cat: 'review', desc: '自动审稿，给出意见' },
  transformer: { label: '新媒体转换', cat: 'media', desc: '多平台风格改写' },
  tool: { label: '工具', cat: 'tool', desc: '精简 / 提取 / 转写' },
  exporter: { label: '成稿导出', cat: 'export', desc: '排版成稿，复制发布' },
}

/** 节点类型 → 分类色（CSS 变量 + 十六进制，供缩略图等非 CSS 场景使用） */
export function catOf(kind: string): { cssVar: string; hex: string; label: string } {
  const meta = TYPE_META[kind as NodeType]
  const c = CATEGORY[meta?.cat || 'tool']
  return { cssVar: c.cssVar, hex: c.hex, label: c.label }
}

/* 状态语言：颜色 + 图标 + 文字三重表达（规范 4.1.5） */
export const STATUS_TEXT: Record<string, string> = {
  idle: '待执行', running: '运行中', queued: '排队中', done: '完成',
  failed: '失败', approved: '已通过', waiting: '待人工', canceled: '已取消',
}
export const STATUS_ICON: Record<string, string> = {
  idle: 'square', running: 'loader-2', queued: 'clock', done: 'check',
  failed: 'alert-triangle', approved: 'shield-check', waiting: 'clock', canceled: 'x',
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
