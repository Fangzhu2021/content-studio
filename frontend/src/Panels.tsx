import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { errText, useStore, type FlowNode } from './store'
import { FORMATS, STATUS_TEXT, TYPE_META } from './types'
import type { Revision } from './types'

let promptDefaults: { prompts: Record<string, string>; labels: Record<string, string>; models: string[] } | null = null
async function loadPromptDefaults() {
  if (!promptDefaults) promptDefaults = await api.getPrompts()
  return promptDefaults
}

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
      <textarea className="rev-content out-content" readOnly value={rev.content} spellCheck={false} />
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

/* ---------------- 通用：提示词编辑器（预填默认模板，可在其上修改） ---------------- */
function PromptEditor({ node, defaultKey }: { node: FlowNode; defaultKey: string }) {
  const [show, setShow] = useState(false)
  const [draft, setDraft] = useState('')
  const [model, setModel] = useState('deepseek-chat')
  const [defaultPrompt, setDefaultPrompt] = useState('')
  const [models, setModels] = useState<string[]>(['deepseek-chat', 'deepseek-reasoner'])
  const [saved, setSaved] = useState(false)
  const initRef = useRef('')

  const cfg = (node.data.config || {}) as Record<string, any>
  const custom = !!(cfg.prompt && String(cfg.prompt).trim())
  const effectiveModel = cfg.model ? String(cfg.model) : 'deepseek-chat'

  useEffect(() => {
    void (async () => {
      try {
        const d = await loadPromptDefaults()
        setDefaultPrompt(d.prompts[defaultKey] || '')
        if (d.models?.length) setModels(d.models)
      } catch { /* 忽略 */ }
    })()
  }, [defaultKey])

  useEffect(() => {
    const key = `${node.id}|${defaultKey}|${defaultPrompt ? 1 : 0}`
    if (!defaultPrompt || initRef.current === key) return
    initRef.current = key
    setDraft(cfg.prompt ? String(cfg.prompt) : defaultPrompt)
    setModel(cfg.model ? String(cfg.model) : 'deepseek-chat')
  }, [defaultPrompt, node.id, defaultKey, cfg.prompt, cfg.model])

  useEffect(() => { setSaved(false) }, [node.id])

  const dirty = draft.trim() !== (custom ? String(cfg.prompt).trim() : (defaultPrompt || '').trim())
    || model !== effectiveModel

  async function save(nextPrompt: string, nextModel: string, resetToDefault = false) {
    const nextCfg: Record<string, unknown> = { ...cfg }
    const trimmed = nextPrompt.trim()
    const sameAsDefault = !trimmed || trimmed === (defaultPrompt || '').trim()
    if (sameAsDefault) delete nextCfg.prompt
    else nextCfg.prompt = nextPrompt
    if (nextModel && nextModel !== 'deepseek-chat') nextCfg.model = nextModel
    else delete nextCfg.model
    try {
      const updated = await api.updateNode(node.id, { config: nextCfg })
      useStore.getState().syncNode(node.id, { config: (updated as any).config || nextCfg })
      if (resetToDefault || sameAsDefault) {
        setDraft(defaultPrompt)
        setModel(nextModel || 'deepseek-chat')
      }
      useStore.getState().toastMsg(sameAsDefault
        ? '已恢复为系统默认提示词（编辑器保留默认文本）'
        : '提示词已保存到该节点')
      setSaved(true)
      setTimeout(() => setSaved(false), 2600)
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

  return (
    <div className="prompt-box">
      <div className="prompt-head">
        <span>🧠 提示词设置 {custom ? <span className="chip on">已自定义</span> : <span className="chip">默认模板</span>}</span>
        <button onClick={() => setShow(!show)}>{show ? '收起' : '修改'}</button>
      </div>
      {show ? (
        <>
          <label>模型档位</label>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m} value={m}>
                {m === 'deepseek-reasoner' ? 'deepseek-reasoner（深度思考，更慢更细）' : 'deepseek-chat（默认，推荐）'}
              </option>
            ))}
          </select>
          <label>该节点提示词（已预填{cfg.prompt ? '本节点已保存的内容' : '系统默认模板'}，可直接修改）</label>
          <textarea className="rev-content" rows={10} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="btn-row">
            <button className="primary" onClick={() => save(draft, model)}>💾 保存提示词</button>
            <button onClick={() => save('', 'deepseek-chat', true)}>↺ 恢复默认</button>
            <button onClick={() => setDraft(defaultPrompt)}>⤵ 重新载入默认模板</button>
          </div>
          {dirty ? <div className="hint-warn">⚠ 提示词已修改但尚未保存，保存后点执行生效</div> : null}
          {saved ? <div className="ok">✔ 已保存</div> : null}
        </>
      ) : null}
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

  return (
    <div className="panel-body">
      <p className="tip">
        {isTransform
          ? `把上游已审定稿件转换为「${FORMATS[node.data.subtype]}」风格。`
          : `把草稿改写为「${FORMATS[node.data.subtype]}」。上游：草稿输入或上一层输出。`}
      </p>
      <button className="primary wide" onClick={run} disabled={busy}>{busy ? '⏳ 执行中…' : '⚡ 执行改写'}</button>
      <PromptEditor node={node} defaultKey={node.data.subtype} />
      <h4>输出预览</h4>
      <OutBox rev={rev} hint="执行后在此预览改写结果。" />
      {rev?.content ? (
        <div className="btn-row">
          <button onClick={() => copyText(rev.content)}>📋 一键复制全文（{rev.content.length} 字）</button>
        </div>
      ) : null}
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
  const [preview, setPreview] = useState<Revision | null>(null)
  const [finalRev, setFinalRev] = useState<Revision | null>(null)
  const [busy, setBusy] = useState(false)

  const loadSources = useCallback(async () => {
    const list: Revision[] = []
    for (const uid of upstreamIds) {
      const r = await api.nodeRevision(uid)
      if (r) list.push(r)
    }
    setSources(list)
    return list
  }, [upstreamIds.join(',')])

  // 仅在切换节点时重置状态（此前 bug：生成后刷新来源把成稿预览清空了）
  useEffect(() => {
    setPick('')
    setPreview(null)
    setFinalRev(null)
    void loadSources().then((list) => {
      if (list.length) { setPick(list[0].id); setPreview(list[0]) }
    })
  }, [node.id])

  function choose(s: Revision) { setPick(s.id); setPreview(s) }

  async function run() {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {}
      if (pick) payload.revision_id = pick
      const r = await api.executeNode(node.id, payload)
      useStore.getState().syncNode(node.id, { status: 'done' })
      const rid = r.revision_id || pick
      if (rid) {
        const rev = await api.getRevision(rid)
        setFinalRev(rev)
        setPreview(rev)
      }
      await loadSources()
      useStore.getState().toastMsg('已生成最终成稿，可复制/下载后到平台发布')
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
    setBusy(false)
  }

  function download(rev: Revision) {
    const blob = new Blob([rev.content || ''], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${rev.title || '成稿'}.md`
    a.click()
    URL.revokeObjectURL(a.href)
    useStore.getState().toastMsg('已下载 .md 文件')
  }

  const chars = preview?.content ? preview.content.length : 0

  return (
    <div className="panel-body">
      <p className="tip">选择一篇上游平台稿生成最终成稿；复制/下载后到对应平台后台粘贴发布（系统不做平台直推）。</p>

      <h4>1. 选择来源稿（点击即预览）</h4>
      {sources.length === 0 ? (
        <div className="empty">上游还没有成稿。\n请先执行「新媒体转换」节点（公众号/微博/抖音）。</div>
      ) : null}
      {sources.map((s) => (
        <label className={`radio-row${pick === s.id ? ' on' : ''}`} key={s.id}>
          <input type="radio" name="pick" checked={pick === s.id} onChange={() => choose(s)} />
          <span>
            <b>{FORMATS[s.format_type] || s.format_type}</b>
            <span className={`pill st-${s.status}`}>{STATUS_TEXT[s.status] || s.status}</span>
            <span className="dim"> {s.title || '（无标题）'} · {s.content?.length || 0} 字</span>
          </span>
        </label>
      ))}
      <button className="primary wide" onClick={run} disabled={busy || sources.length === 0}>
        {busy ? '⏳ 生成中…' : '📤 生成最终成稿'}
      </button>

      <h4>2. 成稿预览 {preview ? <span className="dim">（{chars} 字）</span> : null}</h4>
      {preview ? (
        <div className={`preview-box${finalRev ? ' is-final' : ''}`}>
          <div className="meta-chips">
            <span className={`chip st-${preview.status}`}>{preview.status === 'finalized' ? '已成稿' : (STATUS_TEXT[preview.status] || preview.status)}</span>
            <span className="chip">{FORMATS[preview.format_type] || preview.format_type}</span>
            {preview.model ? <span className="chip">{preview.model}</span> : null}
            <span className="chip">{preview.content?.length || 0} 字</span>
          </div>
          <div className="rev-title">{preview.title || '（无标题）'}</div>
          {preview.review_comment ? <div className="comment">审定意见：{preview.review_comment}</div> : null}
          <textarea className="rev-content preview-content" readOnly value={preview.content || ''} spellCheck={false} />
          {preview.content ? (
            <div className="btn-row">
              <button className="primary wide" onClick={() => copyText(preview.content || '')}>
                📋 一键复制预览全文（{preview.content.length} 字）
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty">选择来源稿后在此预览内容。</div>
      )}

      {finalRev ? (
        <div className="final-box">
          <div className="final-head">✅ 最终成稿已就绪 — 复制或下载后发布</div>
          <div className="btn-row">
            <button className="primary" onClick={() => copyText(finalRev.content || '')}>📋 复制全文</button>
            <button onClick={() => download(finalRev)}>⬇ 下载 .md</button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

/* ---------------- AI 审稿 ---------------- */
function AiReviewPanel({ node }: { node: FlowNode }) {
  const edges = useStore((s) => s.edges)
  const upstreamIds = edges.filter((e) => e.target === node.id).map((e) => e.source)
  const [items, setItems] = useState<Revision[]>([])
  const [busy, setBusy] = useState(false)
  const [summary, setSummary] = useState('')
  const cfg = (node.data.config || {}) as Record<string, any>
  const [strict, setStrict] = useState(!!cfg.strict)
  useEffect(() => { setStrict(!!cfg.strict) }, [node.id])

  async function toggleStrict(v: boolean) {
    setStrict(v)
    const nextCfg: Record<string, unknown> = { ...cfg }
    if (v) nextCfg.strict = true
    else delete nextCfg.strict
    try {
      const updated = await api.updateNode(node.id, { config: nextCfg })
      useStore.getState().syncNode(node.id, { config: (updated as any).config || nextCfg })
      useStore.getState().toastMsg(v ? '已开启严格模式' : '已切换为标准模式')
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

  const load = useCallback(async () => {
    const list: Revision[] = []
    for (const uid of upstreamIds) {
      const r = await api.nodeRevision(uid)
      if (r) list.push(r)
    }
    setItems(list)
  }, [upstreamIds.join(',')])

  useEffect(() => { void load() }, [load])

  async function run() {
    setBusy(true); setSummary('')
    try {
      const r: any = await api.executeNode(node.id, {})
      if (r.status === 'waiting') {
        setSummary('没有待审稿件：请先执行上游改写节点')
        useStore.getState().toastMsg('没有待审稿件')
      } else {
        setSummary(`AI 审稿完成：共 ${r.count} 篇，通过 ${r.passed} 篇`)
        useStore.getState().toastMsg(`AI 审稿完成：通过 ${r.passed}/${r.count}`)
      }
      useStore.getState().syncNode(node.id, { status: 'done' })
      await load()
      await useStore.getState().refreshCanvas()
    } catch (e) {
      useStore.getState().toastMsg(errText(e))
      useStore.getState().syncNode(node.id, { status: 'failed', error: errText(e) })
    }
    setBusy(false)
  }

  const pending = items.filter((r) => ['rewritten', 'reviewed'].includes(r.status))
  return (
    <div className="panel-body">
      <p className="tip">
        AI 自动审稿：检查事实逻辑、错别字、可发布性。通过 → 稿件标记「已通过」；不通过 → 打回草稿并附审稿意见。
        <b> 无需人工确认。</b>
      </p>
      <button className="primary wide" onClick={run} disabled={busy}>
        {busy ? '🤖 审稿中…' : '🤖 开始 AI 审稿'}
      </button>
      <label className="check-row strict-row">
        <input type="checkbox" checked={strict} onChange={(e) => toggleStrict(e.target.checked)} />
        <span>严格模式（发现问题即打回，适合重要稿件）<br />
          <span className="dim">默认标准模式：只拦下事实矛盾/敏感违规/严重语病等实质问题</span></span>
      </label>
      {summary ? <div className="ok">{summary}</div> : null}
      <h4>上游稿件（{items.length} 篇，待审 {pending.length} 篇）</h4>
      {items.length === 0 ? <div className="empty">上游暂无稿件，请先执行改写节点。</div> : null}
      {items.map((r) => (
        <div className="rev-card" key={r.id}>
          <div className="rev-card-head">
            <b>{FORMATS[r.format_type] || r.format_type}</b>
            <span className={`pill st-${r.status}`}>{STATUS_TEXT[r.status] || r.status}</span>
          </div>
          <div className="rev-card-title">{r.title || '（无标题）'} · {r.content?.length || 0} 字</div>
          {r.review_comment ? <div className="comment">{r.review_comment}</div> : null}
        </div>
      ))}
      <PromptEditor node={node} defaultKey="ai_review" />
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
        : node.data.kind === 'ai_reviewer' ? <AiReviewPanel node={node} />
        : <ExportPanel node={node} />}
    </aside>
  )
}
