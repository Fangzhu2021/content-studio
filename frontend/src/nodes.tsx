import { Handle, Position } from '@xyflow/react'
import { FORMATS, STATUS_ICON, STATUS_TEXT, TYPE_META, catOf } from './types'
import { Icon, groupIcon, iconNameFor } from './icons'
import type { FlowNode } from './store'

export function nodeLabel(kind: string, subtype: string): string {
  const meta = TYPE_META[kind as keyof typeof TYPE_META]
  const base = meta?.label || kind
  return subtype ? `${base} · ${FORMATS[subtype] || subtype}` : base
}

export function nodeDesc(kind: string, subtype: string): string {
  const meta = TYPE_META[kind as keyof typeof TYPE_META]
  return subtype ? `${meta?.label || kind} → ${FORMATS[subtype] || subtype}` : meta?.desc || ''
}

/** 画布节点：208×96 / 圆角 12 / 分类色条 / 状态胶囊 / 耗时（规范 6.1） */
export function CSNode(props: any) {
  const data: FlowNode['data'] = props.data
  const kind = data.kind
  const cat = catOf(kind)
  const meta = TYPE_META[kind as keyof typeof TYPE_META]
  const st = data.status || 'idle'
  const iconName = iconNameFor(kind, data.subtype, data.icon)
  const subtitle = nodeDesc(kind, data.subtype)
  const durMs = (data as any).durationMs as number | undefined
  const chars = (data as any).chars as number | undefined

  const stateClass = st === 'done' || st === 'approved' ? 's-done'
    : st === 'running' ? 's-running'
      : st === 'queued' ? 's-queued'
        : st === 'failed' ? 's-failed' : 's-idle'

  return (
    <div
      className={`csnode ${stateClass}${props.selected ? ' sel' : ''}`}
      style={{ ['--cat' as any]: cat.cssVar }}
    >
      <Handle type="target" position={Position.Left} style={{ ['--cat' as any]: cat.cssVar }} />
      <div className="csnode-head">
        <span className="csnode-ico"><Icon name={iconName} size={16} /></span>
        <span className="csnode-name" title={data.label || nodeLabel(kind, data.subtype)}>
          {data.label || nodeLabel(kind, data.subtype)}
        </span>
      </div>
      <div className="csnode-sub" title={subtitle}>{subtitle}</div>
      <div className="csnode-foot">
        <span className={`pill st-${st === 'approved' ? 'approved' : st}`}>
          <Icon name={STATUS_ICON[st] || 'square'} size={10} />
          {STATUS_TEXT[st] || st}
        </span>
        {st === 'failed' && data.error
          ? <span className="csnode-err" title={data.error}><Icon name="alert-triangle" size={13} /></span>
          : durMs ? <span className="csnode-dur">{(durMs / 1000).toFixed(1)}s</span>
            : chars ? <span className="csnode-dur">{chars} 字</span> : null}
      </div>
      {st === 'failed' && data.error
        ? <div className="csnode-error-line" title={data.error}>{data.error}</div>
        : null}
      {/* 选中态：四角 L 形角标 */}
      <span className="corners" aria-hidden="true"><i /><i /><i /><i /></span>
      <Handle type="source" position={Position.Right} style={{ ['--cat' as any]: cat.cssVar }} />
    </div>
  )
}

export const nodeTypes = { cs: CSNode }

export interface PaletteItem { kind: string; subtype: string; icon: string; label?: string }
export interface PaletteGroup { group: string; hint?: string; items: PaletteItem[] }

/* 内置节点库兜底（接口不可用时使用）：图标一律为 Lucide 名称 */
export const PALETTE: PaletteGroup[] = [
  { group: '输入', items: [{ kind: 'draft_input', subtype: '', icon: 'square-pen' }] },
  {
    group: '工具', hint: '（从草稿取稿）',
    items: [
      { kind: 'tool', subtype: 'condense', icon: 'scissors' },
      { kind: 'tool', subtype: 'style_prompt', icon: 'palette' },
      { kind: 'tool', subtype: 'pdf_extract', icon: 'file-text' },
      { kind: 'tool', subtype: 'audio_transcribe', icon: 'mic' },
      { kind: 'tool', subtype: 'topic_plan', icon: 'lightbulb' },
      { kind: 'tool', subtype: 'report_plan', icon: 'clipboard-list' },
    ],
  },
  {
    group: 'AI 改写', hint: '（原稿 → TV/报刊稿）',
    items: [
      { kind: 'rewriter', subtype: 'tv_script', icon: 'tv' },
      { kind: 'rewriter', subtype: 'newspaper', icon: 'newspaper' },
    ],
  },
  {
    group: '审稿', hint: '（人工 或 AI）',
    items: [
      { kind: 'reviewer', subtype: '', icon: 'user-check' },
      { kind: 'ai_reviewer', subtype: '', icon: 'scan-search' },
    ],
  },
  {
    group: '新媒体转换', hint: '（转成平台风格）',
    items: [
      { kind: 'transformer', subtype: 'wechat', icon: 'message-square-text' },
      { kind: 'transformer', subtype: 'weibo', icon: 'at-sign' },
      { kind: 'transformer', subtype: 'douyin', icon: 'clapperboard' },
      { kind: 'transformer', subtype: 'xiaohongshu', icon: 'book-heart' },
      { kind: 'transformer', subtype: 'toutiao', icon: 'rss' },
    ],
  },
  {
    group: '成稿导出', hint: '（终稿·复制发布）',
    items: [
      { kind: 'exporter', subtype: 'wechat', icon: 'send' },
      { kind: 'exporter', subtype: 'weibo', icon: 'send' },
      { kind: 'exporter', subtype: 'douyin', icon: 'send' },
      { kind: 'exporter', subtype: 'xiaohongshu', icon: 'send' },
      { kind: 'exporter', subtype: 'toutiao', icon: 'send' },
    ],
  },
]

export interface PaletteGroupView { group: string; color: string; hint?: string; items: PaletteItem[] }

export const BUILTIN_GROUPS: PaletteGroupView[] = PALETTE.map((g) => ({
  group: g.group,
  color: catOf(g.items[0].kind).hex,
  hint: g.hint,
  items: g.items,
}))

export function groupsFromApi(nodes: { group: string; kind: string; subtype: string; icon: string; color: string; hint?: string; sort?: number; label?: string }[]): PaletteGroupView[] {
  const map = new Map<string, PaletteGroupView & { _sort: number }>()
  for (const n of nodes) {
    const g = map.get(n.group) || {
      group: n.group, color: catOf(n.kind).hex, hint: n.hint || '', items: [], _sort: n.sort ?? 100,
    }
    if ((n.sort ?? 100) < g._sort) g._sort = n.sort ?? 100
    // 图标：后台可填 Lucide 名；历史 emoji 由 iconNameFor 兜底换算
    g.items.push({
      kind: n.kind, subtype: n.subtype,
      icon: iconNameFor(n.kind, n.subtype, n.icon),
      label: n.label,
    })
    map.set(n.group, g)
  }
  return [...map.values()].sort((a, b) => a._sort - b._sort).map(({ _sort, ...rest }) => rest)
}

export { groupIcon }
