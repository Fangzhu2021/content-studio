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
function looksLikeHtml(text: string) {
  return /^\s*<(p|h1|h2|h3|section|div|span|blockquote|br|strong|ul|ol)\b/i.test(text || '')
}

function htmlToPlain(html: string) {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|h1|h2|h3|div|section|blockquote)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** 复制为富文本（HTML）：粘贴进秀米 / 微信编辑器可保留排版 */
async function copyRichHtml(html: string) {
  const msg = (t: string) => useStore.getState().toastMsg(t)
  const CI = (window as unknown as { ClipboardItem?: any }).ClipboardItem
  try {
    if (!navigator.clipboard || !CI) throw new Error('unsupported')
    await navigator.clipboard.write([new CI({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([htmlToPlain(html)], { type: 'text/plain' }),
    })])
    msg('已复制富文本，可直接粘贴进秀米 / 微信编辑器')
  } catch {
    // 回退一：用 contenteditable + execCommand 复制，多数浏览器仍能保留富文本格式
    const box = document.createElement('div')
    box.contentEditable = 'true'
    box.innerHTML = html
    box.style.position = 'fixed'
    box.style.left = '-9999px'
    box.style.top = '0'
    document.body.appendChild(box)
    const range = document.createRange()
    range.selectNodeContents(box)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(range)
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    sel?.removeAllRanges()
    document.body.removeChild(box)
    if (ok) {
      msg('已复制成稿，可直接粘贴进秀米 / 微信编辑器')
      return
    }
    // 回退二：复制源码，提示用编辑器的 HTML 模式
    const ta = document.createElement('textarea')
    ta.value = html
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      msg('已复制 HTML 源码：请在编辑器的「HTML/源码」模式粘贴')
    } catch { msg('复制失败，请手动选中复制') }
    document.body.removeChild(ta)
  }
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

/** 节点执行失败时的提示条 + 一键重试 */
function FailBanner({ node, onRetry, busy }: { node: FlowNode; onRetry: () => void; busy: boolean }) {
  if (node.data.status !== 'failed') return null
  return (
    <div className="fail-banner">
      <div className="fail-text">⚠ 上次执行失败：{node.data.error || '未知错误'}</div>
      <button className="primary" disabled={busy} onClick={onRetry}>↻ 重试执行</button>
    </div>
  )
}

/** 把重试/排队信息拼成提示后缀 */
function execExtra(r: any) {
  const parts: string[] = []
  if (r?.retries) parts.push(`重试 ${r.retries} 次`)
  if (r?.queued_ms > 800) parts.push(`排队 ${(r.queued_ms / 1000).toFixed(1)}s`)
  return parts.length ? '（' + parts.join(' · ') + '）' : ''
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
  const [myList, setMyList] = useState<{ id: string; key: string; name: string; content: string }[]>([])
  const [minePick, setMinePick] = useState('')
  const initRef = useRef('')

  async function loadMine() {
    try { setMyList(await api.myPrompts()) } catch { /* 忽略 */ }
  }
  async function saveAsMine() {
    const name = prompt('模板名称', `${FORMATS[defaultKey] || defaultKey} · 我的版本`)
    if (!name) return
    try {
      await api.createMyPrompt(defaultKey, name, draft)
      await loadMine()
      useStore.getState().toastMsg('已保存到「我的模板」')
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }
  async function removeMine(id: string) {
    if (!confirm('删除这个模板？')) return
    try {
      await api.deleteMyPrompt(id)
      setMinePick('')
      await loadMine()
      useStore.getState().toastMsg('模板已删除')
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

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

  useEffect(() => { setSaved(false); void loadMine() }, [node.id])

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
          <label>我的模板（个人库，载入后可保存到本节点）</label>
          <div className="btn-row">
            <select className="mine-select" value={minePick} onChange={(e) => {
              setMinePick(e.target.value)
              const t = myList.find((x) => x.id === e.target.value)
              if (t) setDraft(t.content)
            }} style={{ flex: 1 }}>
              <option value="">— 选择载入 —</option>
              {myList.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button onClick={saveAsMine}>＋ 另存为我的模板</button>
            {minePick ? <button onClick={() => removeMine(minePick)}>🗑</button> : null}
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

  async function run(isRetry = false) {
    setBusy(true)
    try {
      const r: any = await api.executeNode(node.id, isRetry ? { trigger: 'retry' } : {})
      useStore.getState().toastMsg(`执行完成（${r.model || ''}）${execExtra(r)}`)
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
      <button className="primary wide" onClick={() => run()} disabled={busy}>{busy ? '⏳ 执行中…' : '⚡ 执行改写'}</button>
      <FailBanner node={node} onRetry={() => run(true)} busy={busy} />
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
    // 先取本节点已生成的成稿（排版 HTML），再列上游来源；成稿优先作为预览
    void (async () => {
      let mine: Revision | null = null
      try { mine = await api.nodeRevision(node.id) } catch { mine = null }
      const list = await loadSources()
      if (mine && (mine.content || '').trim()) {
        setFinalRev(mine)
        setPreview(mine)
      } else if (list.length) {
        setPick(list[0].id)
        setPreview(list[0])
      }
    })()
  }, [node.id])

  function choose(s: Revision) { setPick(s.id); setPreview(s) }

  async function run(isRetry = false) {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {}
      if (pick) payload.revision_id = pick
      if (isRetry) payload.trigger = 'retry'
      const r: any = await api.executeNode(node.id, payload)
      useStore.getState().syncNode(node.id, { status: 'done' })
      const rid = r.revision_id || pick
      if (rid) {
        const rev = await api.getRevision(rid)
        setFinalRev(rev)
        setPreview(rev)
      }
      await loadSources()
      useStore.getState().toastMsg('已生成最终成稿，可复制/下载后到平台发布' + execExtra(r))
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
    setBusy(false)
  }

  function download(rev: Revision) {
    const html = looksLikeHtml(rev.content || '')
    const blob = new Blob([rev.content || ''], { type: html ? 'text/html;charset=utf-8' : 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${rev.title || '成稿'}.${html ? 'html' : 'md'}`
    a.click()
    URL.revokeObjectURL(a.href)
    useStore.getState().toastMsg(html ? '已下载 .html（可用浏览器打开/导入编辑器）' : '已下载 .md 文件')
  }

  const chars = preview?.content ? preview.content.length : 0

  return (
    <div className="panel-body">
      <p className="tip">
        选择一篇上游平台稿 → 点「生成最终成稿」：系统按<b>排版提示词</b>把 Markdown 稿排成成稿。
        公众号会输出<b>内联样式 HTML</b>，可一键复制富文本后直接粘贴进秀米 / 微信编辑器（无需再手动排版）。
      </p>

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
      <button className="primary wide" onClick={() => run()} disabled={busy || sources.length === 0}>
        {busy ? '⏳ 排版中…' : '📤 排版并生成最终成稿'}
      </button>
      <FailBanner node={node} onRetry={() => run(true)} busy={busy} />
      <PromptEditor node={node} defaultKey={`export_${node.data.subtype || 'wechat'}`} />

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
          {looksLikeHtml(preview.content || '') ? (
            <>
              <div className="html-preview" dangerouslySetInnerHTML={{ __html: preview.content }} />
              <details className="raw-detail">
                <summary className="dim">查看 HTML 源码</summary>
                <textarea className="rev-content preview-content" readOnly value={preview.content || ''} spellCheck={false} />
              </details>
            </>
          ) : (
            <textarea className="rev-content preview-content" readOnly value={preview.content || ''} spellCheck={false} />
          )}
          {preview.content ? (
            <div className="btn-row">
              {looksLikeHtml(preview.content) ? (
                <button className="primary wide" onClick={() => copyRichHtml(preview.content || '')}>
                  📋 一键复制富文本（粘贴进秀米/微信编辑器）
                </button>
              ) : (
                <button className="primary wide" onClick={() => copyText(preview.content || '')}>
                  📋 一键复制预览全文（{preview.content.length} 字）
                </button>
              )}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty">选择来源稿后在此预览内容。</div>
      )}

      {finalRev ? (
        <div className="final-box">
          <div className="final-head">
            ✅ 最终成稿已就绪 — {looksLikeHtml(finalRev.content || '') ? '复制富文本后粘贴进秀米 / 微信编辑器' : '复制后到平台后台发布'}
          </div>
          <div className="btn-row">
            {looksLikeHtml(finalRev.content || '') ? (
              <button className="primary" onClick={() => copyRichHtml(finalRev.content || '')}>📋 复制富文本（带排版）</button>
            ) : null}
            <button onClick={() => copyText(finalRev.content || '')}>📋 复制全文</button>
            <button onClick={() => download(finalRev)}>⬇ 下载 {looksLikeHtml(finalRev.content || '') ? '.html' : '.md'}</button>
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

/* ---------------- 工具：PDF 版面提取 ---------------- */
function PdfPanel({ node }: { node: FlowNode }) {
  const { rev, reload } = useRevision(node.id)
  const [info, setInfo] = useState<any>(null)
  const [picked, setPicked] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const d = await api.pdfStatus(node.id)
      setInfo(d)
      if (d.uploaded && d.blocks?.length) {
        const sel = (d.selected && d.selected.length) ? d.selected : d.blocks.map((b) => b.index)
        setPicked(sel)
      }
    } catch { setInfo({ uploaded: false }) }
  }, [node.id])

  useEffect(() => { void load(); void reload() }, [node.id])

  async function upload(file: File) {
    setBusy(true); setMsg('')
    try {
      const d = await api.uploadPdf(node.id, file)
      setInfo({ uploaded: true, ...d })
      setPicked(d.blocks.map((b) => b.index))
      useStore.getState().toastMsg(`已解析：${d.pages} 页 / ${d.blocks.length} 个版块`)
    } catch (e) { setMsg(errText(e)); useStore.getState().toastMsg(errText(e)) }
    setBusy(false)
  }

  async function generate() {
    if (!picked.length) { setMsg('请至少选择一个版块'); return }
    setBusy(true); setMsg('')
    try {
      const r = await api.pdfSelect(node.id, picked)
      useStore.getState().toastMsg(`已生成稿件：${r.chars} 字`)
      useStore.getState().syncNode(node.id, { status: 'done' })
      await reload()
      await load()
    } catch (e) { setMsg(errText(e)); useStore.getState().toastMsg(errText(e)) }
    setBusy(false)
  }

  async function remove() {
    if (!confirm('移除已上传的 PDF？已生成的稿件会保留。')) return
    try { await api.pdfRemove(node.id); setInfo({ uploaded: false }); setPicked([]); await load() } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

  const blocks: any[] = info?.blocks || []
  const toggle = (i: number) => setPicked((p) => (p.includes(i) ? p.filter((x) => x !== i) : [...p, i]))
  const pickedChars = blocks.filter((b) => picked.includes(b.index)).reduce((sum, b) => sum + b.chars, 0)

  return (
    <div className="panel-body">
      <p className="tip">
        上传报纸/文件 PDF（文字版），系统按<b>版面版块</b>切分并还原断字断行；勾选需要的版块生成稿件，
        再连到「AI 改写 / 审稿 / 转换」节点继续处理。扫描图片版 PDF 需先 OCR，暂不支持。
      </p>

      <input ref={inputRef} type="file" accept="application/pdf,.pdf" style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }} />
      <div className="btn-row">
        <button className="primary" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? '⏳ 处理中…' : info?.uploaded ? '📄 重新上传 PDF' : '📄 上传 PDF 文件'}
        </button>
        {info?.uploaded ? <button onClick={remove} disabled={busy}>移除</button> : null}
      </div>

      {info?.uploaded ? (
        <>
          <div className="meta-chips">
            <span className="chip">{info.filename}</span>
            <span className="chip">{info.pages} 页</span>
            <span className="chip">{info.total_chars} 字</span>
            <span className="chip">{blocks.length} 个版块</span>
            <span className="chip">已选 {picked.length} 个 · {pickedChars} 字</span>
          </div>
          <div className="btn-row">
            <button onClick={() => setPicked(blocks.map((b) => b.index))}>全选</button>
            <button onClick={() => setPicked([])}>全不选</button>
            <button className="primary" disabled={busy || !picked.length} onClick={generate}>
              {busy ? '⏳ 生成中…' : '✂️ 生成稿件（用所选版块）'}
            </button>
          </div>
          <h4>版块列表（勾选需要的）</h4>
          {blocks.map((b) => (
            <label className={`pdf-block${picked.includes(b.index) ? ' on' : ''}`} key={b.index}>
              <input type="checkbox" checked={picked.includes(b.index)} onChange={() => toggle(b.index)} />
              <span className="pdf-block-main">
                <b>第{b.page}版 · 第{b.column + 1}栏 · {b.chars}字</b>
                {b.title ? <span className="pdf-block-title">《{b.title}》</span> : <span className="dim">（未识别标题）</span>}
                <span className="pdf-block-preview">{b.preview}</span>
              </span>
            </label>
          ))}
        </>
      ) : (
        <div className="empty">还没有上传 PDF。
支持文字版 PDF（报纸版面、公文、材料）。</div>
      )}

      {msg ? <div className="hint-warn">{msg}</div> : null}
      <h4>生成的稿件</h4>
      <OutBox rev={rev} hint="勾选版块后点「生成稿件」，结果会显示在这里。" />
      {rev?.content ? (
        <div className="btn-row">
          <button onClick={() => copyText(rev.content)}>📋 一键复制（{rev.content.length} 字）</button>
        </div>
      ) : null}
    </div>
  )
}

/* ---------------- 工具：稿件精简 / 风格提取 / 新闻选题策划 ---------------- */
const TOOL_UI: Record<string, { tip: string; action: string; header: string; hint?: string }> = {
  condense: {
    tip: '从上游草稿提取精简稿：保留核心事实（时间/地点/主体/事件/数据/要求），压缩到指定篇幅。可用精简稿继续做多平台改写。',
    action: '✂️ 提取精简稿', header: '精简稿预览',
  },
  style_prompt: {
    tip: '从上游草稿提炼「写作风格提示词」。把它连线到「AI 改写 / 新媒体转换」节点，该风格会自动带入下游节点的提示词。',
    action: '🎨 提取风格提示词', header: '风格提示词预览',
    hint: '提示：把本节点连线到「AI 改写 / 新媒体转换」节点，该风格会自动生效。',
  },
  topic_plan: {
    tip: '根据上游草稿的基本信息，策划 3~5 个可落地的新闻选题：每条含核心角度、目标受众与传播点、采访对象与必问问题、呈现形式与平台、时效与风险提示，最后给出总体策划思路。',
    action: '💡 策划新闻选题', header: '选题策划方案预览',
    hint: '提示：把选定的选题复制到「草稿输入」节点，即可继续走改写/转换/审稿流程。',
  },
  report_plan: {
    tip: '把上游素材（通常是「新闻选题策划」的结果，也可以是草稿）组合成一份可执行的报道方案：报道主题与定位、报道框架、稿件清单、采访提纲、人员分工、物料清单、风险与预案、待核实信息。',
    action: '📋 生成报道方案', header: '报道方案预览',
    hint: '提示：方案里的稿件清单可拆成多个「草稿输入」节点分别改写；采访提纲可直接打印给记者使用。',
  },
}

function ToolPanel({ node }: { node: FlowNode }) {
  const { rev, reload } = useRevision(node.id)
  const [busy, setBusy] = useState(false)
  const cfg = (node.data.config || {}) as Record<string, any>
  const sub = node.data.subtype || 'condense'
  const ui = TOOL_UI[sub] || TOOL_UI.condense
  const isCondense = sub === 'condense'
  const ratio = String(cfg.ratio || '0.35')

  async function saveRatio(v: string) {
    const nextCfg: Record<string, unknown> = { ...cfg, ratio: Number(v) }
    try {
      const updated = await api.updateNode(node.id, { config: nextCfg })
      useStore.getState().syncNode(node.id, { config: (updated as any).config || nextCfg })
      useStore.getState().toastMsg('目标篇幅已设置为 ' + Math.round(Number(v) * 100) + '%')
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

  async function run(isRetry = false) {
    setBusy(true)
    try {
      const r: any = await api.executeNode(node.id, isRetry ? { trigger: 'retry' } : {})
      useStore.getState().toastMsg(`${ui.header.replace('预览', '')}已生成（${r.chars || 0} 字）${execExtra(r)}`)
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
      <p className="tip">{ui.tip}</p>
      <button className="primary wide" onClick={() => run()} disabled={busy}>
        {busy ? '⏳ 处理中…' : ui.action}
      </button>
      <FailBanner node={node} onRetry={() => run(true)} busy={busy} />
      {isCondense ? (
        <>
          <label>目标篇幅</label>
          <select value={ratio} onChange={(e) => saveRatio(e.target.value)}>
            <option value="0.25">极简（约原稿 1/4，适合短讯/摘要）</option>
            <option value="0.35">标准（约原稿 1/3，推荐）</option>
            <option value="0.5">宽松（约原稿 1/2，保留更多细节）</option>
          </select>
        </>
      ) : null}
      <PromptEditor node={node} defaultKey={sub} />
      <h4>{ui.header}</h4>
      <OutBox rev={rev} hint="执行后在此预览结果。" />
      {rev?.content ? (
        <div className="btn-row">
          <button onClick={() => copyText(rev.content)}>📋 一键复制（{rev.content.length} 字）</button>
        </div>
      ) : null}
      {ui.hint && rev?.content ? <div className="hint-warn">{ui.hint}</div> : null}
    </div>
  )
}

export default function ConfigPanel() {
  const selected = useStore((s) => s.selected)
  const nodes = useStore((s) => s.nodes)
  const node = nodes.find((n) => n.id === selected) || null
  const meta = node ? TYPE_META[node.data.kind as keyof typeof TYPE_META] : null

  async function removeNode() {
    if (!node) return
    const label = node.data.label || '该节点'
    if (!confirm(`确定删除「${label}」？\n该节点及其连线、相关稿件记录都会被删除，且不可恢复。`)) return
    try {
      await api.deleteNode(node.id)
      useStore.getState().removeNodeLocal(node.id)
      useStore.getState().toastMsg(`已删除节点：${label}`)
    } catch (e) { useStore.getState().toastMsg(errText(e)) }
  }

  return (
    <aside className="panel">
      <div className="panel-head">
        <span className="ph-title">{node ? <>{meta?.icon} {node.data.label}</> : '节点配置'}</span>
        {node ? (
          <button className="del-btn" onClick={removeNode} title="删除该节点（也可选中后按 Delete 键）">🗑 删除节点</button>
        ) : null}
      </div>
      {!node ? (
        <div className="panel-body"><div className="empty">点击画布中的节点查看/配置。\n从左侧拖入节点，连线形成工作流。</div></div>
      ) : node.data.kind === 'draft_input' ? <DraftPanel node={node} />
        : node.data.kind === 'rewriter' || node.data.kind === 'transformer' ? <AiPanel node={node} />
        : node.data.kind === 'tool' && node.data.subtype === 'pdf_extract' ? <PdfPanel node={node} />
        : node.data.kind === 'tool' ? <ToolPanel node={node} />
        : node.data.kind === 'reviewer' ? <ReviewPanel node={node} />
        : node.data.kind === 'ai_reviewer' ? <AiReviewPanel node={node} />
        : <ExportPanel node={node} />}
    </aside>
  )
}
