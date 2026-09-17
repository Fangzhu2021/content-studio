/* 图标系统：Lucide 线性图标（1.75px 描边 / 圆头端点 / currentColor）
 *
 * 规范要求：不得使用 emoji（渲染不可控、视觉重量不可控、无法继承颜色）。
 * 后端节点模板的 icon 字段既可存 Lucide 图标名（推荐，如 "mic"），
 * 也兼容历史 emoji —— 后者按 kind/subtype 映射到对应线性图标。
 */
import type { ComponentType, CSSProperties } from 'react'
import {
  Activity, AlertTriangle, AtSign, BadgeCheck, BookHeart, Check, CheckCircle2, ChevronDown,
  ChevronRight, Clapperboard, ClipboardList, Clock, Copy, Download, FileOutput, FileText,
  FolderOpen, Headphones, KeyRound, Lightbulb, ListChecks, Loader2, LogIn, LogOut, Maximize2, MessageSquare,
  MessageSquareText, Mic, Newspaper, Palette, Play, Plus, RefreshCw, Rss, ScanSearch, Scissors,
  Search, Send, Settings, Share2, ShieldCheck, Sparkles, Square, SquarePen, Trash2, Tv, Upload,
  UserCheck, Video, Wrench, X, ZoomIn, ZoomOut,
} from 'lucide-react'

type IconComp = ComponentType<{ size?: number | string; strokeWidth?: number | string; className?: string; style?: CSSProperties; color?: string }>

/** 图标注册表：同时支持 kebab-case（规范写法）与 PascalCase */
const REGISTRY: Record<string, IconComp> = {}
function reg(name: string, comp: IconComp) {
  REGISTRY[name] = comp
  REGISTRY[name.replace(/(^|-)([a-z])/g, (_m, _s, c) => c.toUpperCase())] = comp
}

reg('activity', Activity as IconComp)
reg('alert-triangle', AlertTriangle as IconComp)
reg('at-sign', AtSign as IconComp)
reg('badge-check', BadgeCheck as IconComp)
reg('book-heart', BookHeart as IconComp)
reg('check', Check as IconComp)
reg('check-circle-2', CheckCircle2 as IconComp)
reg('chevron-down', ChevronDown as IconComp)
reg('chevron-right', ChevronRight as IconComp)
reg('clapperboard', Clapperboard as IconComp)
reg('clipboard-list', ClipboardList as IconComp)
reg('clock', Clock as IconComp)
reg('copy', Copy as IconComp)
reg('download', Download as IconComp)
reg('file-output', FileOutput as IconComp)
reg('file-text', FileText as IconComp)
reg('folder-open', FolderOpen as IconComp)
reg('headphones', Headphones as IconComp)
reg('key-round', KeyRound as IconComp)
reg('lightbulb', Lightbulb as IconComp)
reg('list-checks', ListChecks as IconComp)
reg('loader-2', Loader2 as IconComp)
reg('log-in', LogIn as IconComp)
reg('log-out', LogOut as IconComp)
reg('maximize-2', Maximize2 as IconComp)
reg('message-square', MessageSquare as IconComp)
reg('message-square-text', MessageSquareText as IconComp)
reg('mic', Mic as IconComp)
reg('newspaper', Newspaper as IconComp)
reg('palette', Palette as IconComp)
reg('play', Play as IconComp)
reg('plus', Plus as IconComp)
reg('refresh-cw', RefreshCw as IconComp)
reg('rss', Rss as IconComp)
reg('scan-search', ScanSearch as IconComp)
reg('scissors', Scissors as IconComp)
reg('search', Search as IconComp)
reg('send', Send as IconComp)
reg('settings', Settings as IconComp)
reg('share-2', Share2 as IconComp)
reg('shield-check', ShieldCheck as IconComp)
reg('sparkles', Sparkles as IconComp)
reg('square', Square as IconComp)
reg('square-pen', SquarePen as IconComp)
reg('trash-2', Trash2 as IconComp)
reg('tv', Tv as IconComp)
reg('upload', Upload as IconComp)
reg('user-check', UserCheck as IconComp)
reg('video', Video as IconComp)
reg('wrench', Wrench as IconComp)
reg('x', X as IconComp)
reg('zoom-in', ZoomIn as IconComp)
reg('zoom-out', ZoomOut as IconComp)

/** 节点图标：kind:subtype → 图标名（规范 7.3 映射表 + 同族补齐） */
const NODE_ICONS: Record<string, string> = {
  'draft_input:*': 'square-pen',
  'tool:condense': 'scissors',
  'tool:style_prompt': 'palette',
  'tool:pdf_extract': 'file-text',
  'tool:topic_plan': 'lightbulb',
  'tool:report_plan': 'clipboard-list',
  'tool:audio_transcribe': 'mic',
  'tool:*': 'wrench',
  'rewriter:tv_script': 'tv',
  'rewriter:newspaper': 'newspaper',
  'rewriter:*': 'sparkles',
  'transformer:wechat': 'message-square-text',
  'transformer:weibo': 'at-sign',
  'transformer:douyin': 'clapperboard',
  'transformer:xiaohongshu': 'book-heart',
  'transformer:toutiao': 'rss',
  'transformer:*': 'share-2',
  'reviewer:*': 'user-check',
  'ai_reviewer:*': 'scan-search',
  'exporter:*': 'send',
}

/** 分组图标（规范 7.3）：按分组名关键字匹配，兼容后台自定义分组 */
export function groupIcon(group: string): string {
  const g = group || ''
  if (g.includes('输入')) return 'log-in'
  if (g.includes('工具')) return 'wrench'
  if (g.includes('改写')) return 'sparkles'
  if (g.includes('审稿')) return 'shield-check'
  if (g.includes('转换')) return 'share-2'
  if (g.includes('导出')) return 'send'
  return 'folder-open'
}

/** 解析某个节点该用哪个图标名 */
export function iconNameFor(kind: string, subtype: string, dbIcon?: string | null): string {
  const raw = (dbIcon || '').trim()
  if (raw && REGISTRY[raw]) return raw                    // 后台已配置 Lucide 名
  return NODE_ICONS[`${kind}:${subtype || ''}`] || NODE_ICONS[`${kind}:*`] || 'wrench'
}

/**
 * 图标组件。size 按规范取 16 / 18 / 20 三档，描边统一 1.75px。
 * 若传入的 name 既不是 Lucide 名也不是已知别名（例如后台仍存着历史 emoji），
 * 则原样渲染该文本，避免出现空白。
 */
export function Icon({ name, size = 16, strokeWidth = 1.75, className, style }: {
  name: string
  size?: number
  strokeWidth?: number
  className?: string
  style?: CSSProperties
}) {
  const Comp = REGISTRY[name]
  if (!Comp) {
    return <span className={className} style={{ fontSize: size * 0.9, lineHeight: 1, ...style }}>{name}</span>
  }
  return <Comp size={size} strokeWidth={strokeWidth} className={className} style={style} />
}

export function hasIcon(name: string): boolean { return !!REGISTRY[name] }
