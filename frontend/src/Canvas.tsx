import { useCallback, useMemo } from 'react'
import {
  BaseEdge, ReactFlow, getBezierPath,
  Background, BackgroundVariant, Controls, MarkerType, MiniMap,
  ReactFlowProvider, applyEdgeChanges, applyNodeChanges, useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from './api'
import { errText, useStore, type FlowEdge, type FlowNode } from './store'
import { nodeTypes } from './nodes'
import { catOf } from './types'
import { Icon } from './icons'

const DND = 'application/cs-node'

/** 连线：三次贝塞尔，曲率 0.45（规范 6.2；React Flow 默认 0.25 偏直） */
function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style }: any) {
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, curvature: 0.45 })
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
}
const edgeTypes = { flow: FlowEdge }
/* 连线默认色（规范令牌 --edge-default）：SVG 标记色无法用 CSS 变量，这里与令牌同值 */
const EDGE_COLOR = '#566D92'
const EDGE_ACTIVE = '#7298FF'

function CanvasInner() {
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const selected = useStore((s) => s.selected)
  const currentId = useStore((s) => s.currentId)
  const { select, setNodes, setEdges, removeNodeLocal, removeEdgeLocal, toastMsg, refreshCanvas, setZoom } = useStore.getState()
  const rf = useReactFlow()

  const onNodesChange = useCallback((changes: any) => {
    setNodes(applyNodeChanges(changes, useStore.getState().nodes) as unknown as FlowNode[])
  }, [setNodes])

  const onEdgesChange = useCallback((changes: any) => {
    setEdges(applyEdgeChanges(changes, useStore.getState().edges) as unknown as FlowEdge[])
  }, [setEdges])

  const viewNodes = useMemo(() => nodes.map((n) => ({ ...n, selected: n.id === selected })), [nodes, selected])

  /* 连线：运行中的出边做数据流动；选中节点时，上下游连线保持高亮、其余降到 35%（规范 6.2） */
  const viewEdges = useMemo(() => edges.map((e) => {
    const source = nodes.find((n) => n.id === e.source)
    const target = nodes.find((n) => n.id === e.target)
    const active = source?.data.status === 'running' || target?.data.status === 'running'
    const adjacent = selected ? (e.source === selected || e.target === selected) : true
    const cls = active ? 'edge-active' : (selected && !adjacent ? 'edge-dim' : '')
    return {
      ...e,
      className: cls,
      type: 'flow',
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: active ? EDGE_ACTIVE : EDGE_COLOR },
      style: { strokeWidth: 1.5 },
    }
  }), [edges, nodes, selected])

  async function onConnect(conn: any) {
    if (!currentId || !conn.source || !conn.target) return
    try {
      const edge = await api.createEdge(currentId, conn.source, conn.target)
      setEdges([...useStore.getState().edges, edge])
    } catch (e) { toastMsg(errText(e)) }
  }

  async function onNodeDragStop(_: any, node: any) {
    try { await api.updateNode(node.id, { position: node.position }) } catch { /* 忽略 */ }
  }

  async function onNodesDelete(del: any[]) {
    for (const n of del) { try { await api.deleteNode(n.id) } catch (e) { toastMsg(errText(e)) } removeNodeLocal(n.id) }
  }
  async function onEdgeClick(ev: React.MouseEvent, edge: any) {
    ev.stopPropagation()
    if (!confirm('删除这条连线？')) return
    try {
      await api.deleteEdge(edge.id)
      removeEdgeLocal(edge.id)
      toastMsg('连线已删除')
    } catch (e) { toastMsg(errText(e)) }
  }

  async function onEdgesDelete(del: any[]) {
    for (const e of del) { try { await api.deleteEdge(e.id) } catch (err) { toastMsg(errText(err)) } removeEdgeLocal(e.id) }
  }

  /** 删除节点：危险操作移出顶栏，改在画布工具条 + 右栏（规范 5.2） */
  async function removeSelected() {
    const id = useStore.getState().selected
    if (!id) { toastMsg('请先在画布上点选一个节点'); return }
    const node = useStore.getState().nodes.find((n) => n.id === id)
    const label = node?.data.label || '该节点'
    if (!confirm(`确定删除「${label}」？\n该节点及其连线、相关稿件记录都会被删除，且不可恢复。`)) return
    try {
      await api.deleteNode(id)
      removeNodeLocal(id)
      toastMsg(`已删除节点：${label}`)
    } catch (e) { toastMsg(errText(e)) }
  }

  function onDragOver(ev: React.DragEvent) {
    ev.preventDefault()
    ev.dataTransfer.dropEffect = 'move'
  }
  async function onDrop(ev: React.DragEvent) {
    ev.preventDefault()
    const raw = ev.dataTransfer.getData(DND)
    if (!raw || !currentId) return
    try {
      const spec = JSON.parse(raw)
      const pos = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY })
      const node = await api.createNode(currentId, { type: spec.kind, subtype: spec.subtype || '', label: spec.label || '', position: { x: Math.round(pos.x), y: Math.round(pos.y) } })
      useStore.getState().upsertNodeLocal({
        id: node.id, type: 'cs', position: node.position,
        data: { kind: node.type, subtype: node.subtype, label: node.label, status: node.status || 'idle', config: (node as any).config || {}, icon: spec.icon || '' },
      })
      select(node.id)
    } catch (e) { toastMsg(errText(e)) }
  }

  return (
    <div className="canvas-wrap">
      <ReactFlow
        className="dark"
        nodes={viewNodes}
        edges={viewEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => select(node.id)}
        onEdgeClick={onEdgeClick}
        onPaneClick={() => select(null)}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeDragStop={onNodeDragStop}
        onNodesDelete={onNodesDelete}
        onEdgesDelete={onEdgesDelete}
        onMove={(_, viewport) => setZoom(viewport.zoom)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2.5}
        deleteKeyCode={['Backspace', 'Delete']}
        proOptions={{ hideAttribution: true }}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={{
          type: 'flow',
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: EDGE_COLOR },
          style: { strokeWidth: 1.5 },
        }}
      >
        {/* 画布背景：20px 细点阵 + 100px 粗网格线（规范 8.2） */}
        <Background id="grid-fine" variant={BackgroundVariant.Dots} gap={20} size={1} color="#1B2634" />
        <Background id="grid-coarse" variant={BackgroundVariant.Lines} gap={100} size={1} color="#141D29" />
        <Controls showInteractive={false} position="bottom-right" />
        <MiniMap
          pannable zoomable position="bottom-left"
          maskColor="rgba(7, 11, 18, .72)"
          style={{ width: 168, height: 108 }}
          nodeColor={(n: any) => catOf(n.data?.kind || 'tool').hex}
          nodeStrokeWidth={0}
        />
      </ReactFlow>
      <div className="canvas-tools">
        <button className="icon-btn" title="适应视图" onClick={() => { select(null); rf.fitView({ padding: 0.2 }) }}>
          <Icon name="maximize-2" size={16} />
        </button>
        <button className="icon-btn" title="刷新画布" onClick={() => void refreshCanvas()}>
          <Icon name="refresh-cw" size={16} />
        </button>
        <button className="icon-btn danger" title="删除选中节点（危险操作）" onClick={() => void removeSelected()}>
          <Icon name="trash-2" size={16} />
        </button>
        <span className="dim" style={{ fontSize: 12, marginLeft: 2 }}>拖入节点 · 连线编排 · 点节点配置</span>
      </div>
    </div>
  )
}

export default function Canvas() {
  return <ReactFlowProvider><CanvasInner /></ReactFlowProvider>
}
