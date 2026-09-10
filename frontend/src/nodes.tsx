import { Handle, Position } from '@xyflow/react'
import { FORMATS, STATUS_TEXT, TYPE_META } from './types'
import type { FlowNode } from './store'

const KIND_ORDER: string[] = ['draft_input', 'rewriter', 'reviewer', 'transformer', 'exporter']

export function nodeLabel(kind: string, subtype: string): string {
  const meta = TYPE_META[kind as keyof typeof TYPE_META]
  const base = meta?.label || kind
  return subtype ? `${base} · ${FORMATS[subtype] || subtype}` : base
}

export function nodeDesc(kind: string, subtype: string): string {
  const meta = TYPE_META[kind as keyof typeof TYPE_META]
  return subtype ? FORMATS[subtype] || subtype : meta?.desc || ''
}

export function CSNode(props: any) {
  const data: FlowNode['data'] = props.data
  const kind = data.kind
  const meta = TYPE_META[kind as keyof typeof TYPE_META] || TYPE_META.draft_input
  const st = data.status || 'idle'
  const sub = FORMATS[data.subtype] || ''
  return (
    <div className={`csnode k-${kind} s-${st}${props.selected ? ' sel' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="csnode-head">
        <span className="csnode-ico">{meta.icon}</span>
        <span className="csnode-name">{data.label || nodeLabel(kind, data.subtype)}</span>
      </div>
      <div className="csnode-sub">{sub ? `${meta.label} → ${sub}` : meta.desc}</div>
      <div className="csnode-foot">
        <span className={`pill st-${st}`}>{STATUS_TEXT[st] || st}</span>
        {data.error ? <span className="csnode-err" title={data.error}>⚠</span> : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export const nodeTypes = { cs: CSNode }

export interface PaletteItem { kind: string; subtype: string; icon: string; label?: string }
export interface PaletteGroup { group: string; color: string; hint?: string; items: PaletteItem[] }

export const PALETTE: PaletteGroup[] = [
  { group: '输入', color: '#64748b', items: [{ kind: 'draft_input', subtype: '', icon: '📝' }] },
  {
    group: '工具', color: '#7c3aed', hint: '（从草稿取稿）',
    items: [
      { kind: 'tool', subtype: 'condense', icon: '✂️' },
      { kind: 'tool', subtype: 'style_prompt', icon: '🎨' },
    ],
  },
  {
    group: 'AI 改写', color: '#6366f1', hint: '（原稿 → TV/报刊稿）',
    items: [
      { kind: 'rewriter', subtype: 'tv_script', icon: '📺' },
      { kind: 'rewriter', subtype: 'newspaper', icon: '📰' },
    ],
  },
  {
    group: '审稿', color: '#d97706', hint: '（人工 或 AI）',
    items: [
      { kind: 'reviewer', subtype: '', icon: '✅' },
      { kind: 'ai_reviewer', subtype: '', icon: '🤖' },
    ],
  },
  {
    group: '新媒体转换', color: '#0ea5e9', hint: '（转成平台风格）',
    items: [
      { kind: 'transformer', subtype: 'wechat', icon: '💬' },
      { kind: 'transformer', subtype: 'weibo', icon: '🔥' },
      { kind: 'transformer', subtype: 'douyin', icon: '🎬' },
      { kind: 'transformer', subtype: 'xiaohongshu', icon: '📕' },
      { kind: 'transformer', subtype: 'toutiao', icon: '🗞️' },
    ],
  },
  {
    group: '成稿导出', color: '#16a34a', hint: '（终稿·复制发布）',
    items: [
      { kind: 'exporter', subtype: 'wechat', icon: '📤' },
      { kind: 'exporter', subtype: 'weibo', icon: '📤' },
      { kind: 'exporter', subtype: 'douyin', icon: '📤' },
      { kind: 'exporter', subtype: 'xiaohongshu', icon: '📤' },
      { kind: 'exporter', subtype: 'toutiao', icon: '📤' },
    ],
  },
]

export function fmtOf(item: PaletteItem): string { return item.subtype ? ` (${FORMATS[item.subtype] || item.subtype})` : '' }
export const KIND_ORDER_LEGEND = KIND_ORDER

/* ---------- 节点库：数据库配置优先，内置定义兜底 ---------- */
export interface PaletteGroupView { group: string; color: string; hint?: string; items: PaletteItem[] }

export const BUILTIN_GROUPS: PaletteGroupView[] = PALETTE.map((g) => ({ group: g.group, color: g.color, hint: g.hint, items: g.items }))

export function groupsFromApi(nodes: { group: string; kind: string; subtype: string; icon: string; color: string; hint?: string; sort?: number; label?: string }[]): PaletteGroupView[] {
  const map = new Map<string, PaletteGroupView & { _sort: number }>()
  for (const n of nodes) {
    const g = map.get(n.group) || { group: n.group, color: n.color || '#64748b', hint: n.hint || '', items: [], _sort: n.sort ?? 100 }
    if ((n.sort ?? 100) < g._sort) g._sort = n.sort ?? 100
    g.items.push({ kind: n.kind, subtype: n.subtype, icon: n.icon || '🧩', label: n.label })
    map.set(n.group, g)
  }
  return [...map.values()].sort((a, b) => a._sort - b._sort).map(({ _sort, ...rest }) => rest)
}
