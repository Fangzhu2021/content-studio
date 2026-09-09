import { useCallback, useMemo } from 'react'
import {
  ReactFlow,
  Background, BackgroundVariant, Controls, MarkerType, MiniMap,
  ReactFlowProvider, applyEdgeChanges, applyNodeChanges, useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from './api'
import { errText, useStore, type FlowEdge, type FlowNode } from './store'
import { nodeTypes } from './nodes'

const DND = 'application/cs-node'

function CanvasInner() {
  const nodes = useStore((s) => s.nodes)
  const edges = useStore((s) => s.edges)
  const selected = useStore((s) => s.selected)
  const currentId = useStore((s) => s.currentId)
  const { select, setNodes, setEdges, removeNodeLocal, removeEdgeLocal, toastMsg, refreshCanvas, runProject, upsertNodeLocal } = useStore.getState()
  const rf = useReactFlow()

  const onNodesChange = useCallback((changes: any) => {
    setNodes(applyNodeChanges(changes, useStore.getState().nodes) as unknown as FlowNode[])
  }, [setNodes])

  const onEdgesChange = useCallback((changes: any) => {
    setEdges(applyEdgeChanges(changes, useStore.getState().edges) as unknown as FlowEdge[])
  }, [setEdges])

  const viewNodes = useMemo(() => nodes.map((n) => ({ ...n, selected: n.id === selected })), [nodes, selected])
  const viewEdges = useMemo(() => edges.map((e) => {
    const target = nodes.find((n) => n.id === e.target)
    return { ...e, animated: target?.data.status === 'running' }
  }), [edges, nodes])

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
  async function onEdgesDelete(del: any[]) {
    for (const e of del) { try { await api.deleteEdge(e.id) } catch (err) { toastMsg(errText(err)) } removeEdgeLocal(e.id) }
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
      const node = await api.createNode(currentId, { type: spec.kind, subtype: spec.subtype || '', position: { x: Math.round(pos.x), y: Math.round(pos.y) } })
      upsertNodeLocal({ id: node.id, type: 'cs', position: node.position, data: { kind: node.type, subtype: node.subtype, label: node.label, status: node.status || 'idle' } })
      select(node.id)
    } catch (e) { toastMsg(errText(e)) }
  }

  return (
    <div className="canvas-wrap">
      <ReactFlow
        nodes={viewNodes}
        edges={viewEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => select(node.id)}
        onPaneClick={() => select(null)}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeDragStop={onNodeDragStop}
        onNodesDelete={onNodesDelete}
        onEdgesDelete={onEdgesDelete}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2.5}
        deleteKeyCode={['Backspace', 'Delete']}
        defaultEdgeOptions={{ markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: '#94a3b8', strokeWidth: 1.6 } }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} color="#cbd5e1" />
        <Controls />
        <MiniMap pannable zoomable nodeColor={(n: any) => ({ draft_input: '#64748b', rewriter: '#6366f1', reviewer: '#d97706', transformer: '#0ea5e9', exporter: '#16a34a' })[n.data.kind] || '#94a3b8'} />
      </ReactFlow>
      <div className="canvas-tools">
        <button onClick={() => { select(null); rf.fitView({ padding: 0.2 }) }}>⤢ 适应视图</button>
        <button onClick={runProject} disabled={!currentId || useStore.getState().running.length > 0}>▶ 自动执行</button>
        <button onClick={refreshCanvas}>↻ 刷新</button>
      </div>
    </div>
  )
}

export default function Canvas() {
  return <ReactFlowProvider><CanvasInner /></ReactFlowProvider>
}
