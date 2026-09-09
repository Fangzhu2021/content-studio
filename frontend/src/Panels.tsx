import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { errText, useStore, type FlowNode } from './store'
import { FORMATS, STATUS_TEXT, TYPE_META } from './types'
import type { Revision } from './types'

function copyText(text: string) {
  const done = () => useStore.getState().toastMsg('已复制到剪贴板')
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done))
  } else fallbackCopy(text, done)
}
function fallbackCopy(text: string, done: () => void) {
  const ta = document.createElement('textarea')
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy'); done() } catch { /* ignore */ }
  document.body.removeChild(ta)
}

function chips(rev: Revision | null) {
  if (!rev) return null
  return (
    <div className="meta-chips">
      <span className={`chip st-${rev.status}`}>{STATUS_TEXT[rev.status] || rev.status}</span>
      <span className="chip">{FORMATS[rev.format_type] || rev.format_type || '原始'}</span>
      {rev.model ? <span className="chip">{rev.model}</span> : null}
    </div>
  )
}

function useRevision(nodeId?: string | null) {
  const [rev, setRev] = useState<Revision | null>(null)
  const reload = useCallback(async () => {
    if (!nodeId) { setRev(null); return }
    try { setRev(await api.nodeRevision(nodeId)) } catch { setRev(null) }
  }, [nodeId])
  useEffect(() => { void reload() }, [reload])
  return { rev, reload }
}

function OutBox({ rev, hint }: { rev: Revision | null; hint?: string }) {
  if (!rev) return <div className="empty">{hint || '暂无输出'}</div>
  return (
    <div className="outbox">
      {chips(rev)}
      <div className="rev-title">{rev.title || '（无标题）'}</div>
      {rev.review_comment ? <div className="comment">审定意见：{rev.review_comment}</div> : null}
      <textarea className="rev-content" readOnly value={rev.content} spellCheck={false} />
      {rev.content ? <button onClick={() => copyText(rev.content)}>📋 复制全文</button> : null}
    </div>
  )
}

/* ---------------- 草稿输入 ---------------- */
function DraftPanel({ node }: { node: FlowNode }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const { rev, reload } = useRevision(node.id)
  useEffect(() => { if (rev) { setTitle(rev.title); setContent(rev.content) } }, [rev?.id])
  async function save() {
    setSaving(true)
    try {
      await api.saveContent(node.id, title, content)
      useStore.getState().toastMsg('草稿已保存')
      await reload()
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
    setSaving(false)
  }
  return (
    <div className="panel-body">
      <p className="tip">录入原始稿件，保存后选择下游「AI 改写」节点执行。</p>
      <label>标题</label>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="稿件标题" />
      <label>正文</label>
      <textarea className="rev-content" rows={14} value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴原始稿件内容…" />
      <button onClick={save} disabled={saving}>{saving ? '保存中…' : '💾 保存草稿'}</button>
      {rev?.content ? <div className="ok">已保存（{new Date(rev.created_at || '').toLocaleString('zh-CN')}）</div> : null}
    </div>
  )
}

/* ---------------- AI 改写 / 转换 ---------------- */
function AiPanel({ node }: { node: FlowNode }) {
  const { rev, reload } = useRevision(node.id)
  const [busy, setBusy] = useState(false)
  const isTransform = node.data.kind === 'transformer'
  async function run() {
    setBusy(true)
    try {
      const r = await api.executeNode(node.id, {})
      useStore.getState().toastMsg(`执行完成（${r.model || ''}）`)
      useStore.getState().syncNode(node.id, { status: 'done' })
      await reload()
    } catch (e) {
      useStore.getState().toastMsg(errText(e))
      useStore.getState().syncNode(node.id, { status: 'failed', error: errText(e) })
    }
    setBusy(false)
  }
  const meta = TYPE_META[node.data.kind as keyof typeof TYPE_META]
  return (
    <div className="panel-body">
      <p className="tip">
        {isTransform
          ? `把上游已审定稿件转换为「${FORMATS[node.data.subtype]}」风格。`
          : `把草稿改写为「${FORMATS[node.data.subtype]}」。上游：草稿输入或上一层输出。`}
      </p>
      <button className="primary" onClick={run} disabled={busy}>{busy ? '⏳ 执行中…' : '⚡ 执行改写'}</button>
      <h4>输出预览</h4>
      <OutBox rev={rev} hint="执行后在此预览改写结果；未配置 DeepSeek Key 时为模拟模式。" />
      {rev?.content ? <button onClick={() => copyText(rev.content)}>📋 复制全文</button> : null}
    </div>
  )
}

/* ---------------- 人工审定 ---------------- */
function ReviewPanel({ node }: { node: FlowNode }) {
  const [comment, setComment] = useState('')
  const [items, setItems] = useState<Revision[]>([])
  const [busy, setBusy] = useState('')
  const edges = useStore((s) => s.edges)
  const upstreamIds = edges.filter((e) => e.target === node.id).map((e) => e.source)

  const load = useCallback(async () => {
    const list: Revision[] = []
    for (const uid of upstreamIds) {
      const r = await api.nodeRevision(uid)
      if (r) list.push(r)
    }
    setItems(list)
  }, [upstreamIds.join(',')])

  useEffect(() => { void load() }, [load])

  async function act(revId: string, status: string) {
    setBusy(revId + status)
    try {
      await api.reviewRevision(revId, status, comment)
      useStore.getState().toastMsg(status === 'approved' ? '已通过' : '已打回')
      await load()
      await useStore.getState().refreshCanvas()
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
    setBusy('')
  }
  const pending = items.filter((r) => ['rewritten', 'reviewed'].includes(r.status))
  return (
    <div className="panel-body">
      <p className="tip">对上游改写稿逐篇审定：通过或打回（可填意见）。</p>
      <label>审定意见（可选）</label>
      <textarea className="small" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="批注/修改意见…" />
      {items.length === 0 ? <div className="empty">上游暂没有稿件，请先执行改写节点。</div> : null}
      {items.map((r) => (
        <div className="rev-card" key={r.id}>
          <div className="rev-card-head">
            <b>{FORMATS[r.format_type] || r.format_type}</b>
            <span className={`pill st-${r.status}`}>{STATUS_TEXT[r.status] || r.status}</span>
          </div>
          <div className="rev-card-title">{r.title || '（无标题）'}</div>
          {r.review_comment ? <div className="comment">意见：{r.review_comment}</div> : null}
          {pending.some((p) => p.id === r.id) ? (
            <div className="btn-row">
              <button className="ok-btn" disabled={!!busy} onClick={() => act(r.id, 'approved')}>✓ 通过</button>
              <button className="no-btn" disabled={!!busy} onClick={() => act(r.id, 'draft')}>✗ 打回</button>
            </div>
          ) : null}
        </div>
      ))}
      <h4>来源对比</h4>
      <div className="small-note">展开上游改写稿内容查看：</div>
      {items.filter((r) => !pending.some((p) => p.id === r.id)).map((r) => <OutBox key={r.id} rev={r} />)}
    </div>
  )
}

/* ---------------- 成稿导出 ---------------- */
function ExportPanel({ node }: { node: FlowNode }) {
  const edges = useStore((s) => s.edges)
  const upstreamIds = edges.filter((e) => e.target === node.id).map((e) => e.source)
  const [sources, setSources] = useState<Revision[]>([])
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const [finalRev, setFinalRev] = useState<Revision | null>(null)

  const load = useCallback(async () => {
    const list: Revision[] = []
    for (const uid of upstreamIds) {
      const r = await api.nodeRevision(uid)
      if (r) list.push(r)
    }
    setSources(list)
    setPick('')
    setFinalRev(null)
  }, [upstreamIds.join(',')])
  useEffect(() => { void load() }, [load])

  async function run() {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {}
      if (pick) payload.revision_id = pick
      const r = await api.executeNode(node.id, payload)
      useStore.getState().toastMsg('已生成最终成稿')
      useStore.getState().syncNode(node.id, { status: 'done' })
      const revId = r.revision_id || pick
      if (revId) {
        // 导出目标即上游某篇 Revision；直接按其 ID 拉取最终内容
        const s = sources.find((x) => x.id === revId)
        if (s) setFinalRev({ ...s, status: 'finalized' })
      }
      await load()
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
    setBusy(false)
  }

  function download() {
    const content = finalRev?.content || ''
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${finalRev?.title || '成稿'}.md`
    a.click()
    URL.revokeObjectURL(a.href)
    useStore.getState().toastMsg('已下载 .md 文件')
  }

  return (
    <div className="panel-body">
      <p className="tip">把选定的平台稿标记为最终成稿；复制/下载后粘贴到对应平台后台发布（系统不做平台直推）。</p>
      <h4>选择上游成稿来源</h4>
      {sources.length === 0 ? <div className="empty">上游还没有成稿，请先执行新媒体转换节点。</div> : null}
      {sources.map((s) => (
        <label className="radio-row" key={s.id}>
          <input type="radio" name="pick" checked={pick === s.id} onChange={() => setPick(s.id)} />
          <span>{FORMATS[s.format_type] || s.format_type} {s.status === 'finalized' ? '（已成稿）' : ''} — {s.title || '（无标题）'}</span>
        </label>
      ))}
      <button className="primary" onClick={run} disabled={busy || sources.length === 0}>
        {busy ? '⏳ 执行中…' : '📤 生成最终成稿'}
      </button>
      <h4>最终成稿</h4>
      <OutBox rev={finalRev} hint="生成后在此预览，点击下方按钮复制/下载，再粘贴到平台发布。" />
      {finalRev?.content ? (
        <div className="btn-row">
          <button onClick={() => copyText(finalRev.content)}>📋 复制全文</button>
          <button onClick={download}>⬇ 下载 .md</button>
        </div>
      ) : null}
    </div>
  )
}

export default function ConfigPanel() {
  const selected = useStore((s) => s.selected)
  const nodes = useStore((s) => s.nodes)
  const node = nodes.find((n) => n.id === selected) || null
  const meta = node ? TYPE_META[node.data.kind as keyof typeof TYPE_META] : null
  return (
    <aside className="panel">
      <div className="panel-head">
        {node ? <>{meta?.icon} {node.data.label}</> : '节点配置'}
      </div>
      {!node ? (
        <div className="panel-body"><div className="empty">点击画布中的节点查看/配置。\n从左侧拖入节点，连线形成工作流。</div></div>
      ) : node.data.kind === 'draft_input' ? <DraftPanel node={node} />
        : node.data.kind === 'rewriter' || node.data.kind === 'transformer' ? <AiPanel node={node} />
        : node.data.kind === 'reviewer' ? <ReviewPanel node={node} />
        : <ExportPanel node={node} />}
    </aside>
  )
}
