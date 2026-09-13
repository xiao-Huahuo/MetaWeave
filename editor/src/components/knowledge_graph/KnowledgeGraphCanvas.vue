<!--
  Reusable Canvas knowledge graph component.

  Usage:
  Receives a framework-neutral KnowledgeGraphModel, runs the layered D3 force
  layout, and emits node interaction events. The data adapter and renderer live
  in separate modules so other applications can reuse them without this Vue UI.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { Simulation } from 'd3-force'

import { fitGraphToViewport, focusNodeViewport, hitTestNode, screenToWorld } from './graphGeometry'
import { drawKnowledgeGraph } from './graphRenderer'
import { createLayeredForceSimulation } from './layeredForceLayout'
import type {
  KnowledgeGraphLink,
  KnowledgeGraphModel,
  KnowledgeGraphNode,
  KnowledgeGraphNodeContextEvent,
  KnowledgeGraphNodeEvent,
  KnowledgeGraphRenderTheme,
  KnowledgeGraphViewport,
} from './graphTypes'

const props = defineProps<{
  model: KnowledgeGraphModel
  selectedNodeId?: string
  showLabels?: boolean
}>()

const emit = defineEmits<{
  'node-select': [event: KnowledgeGraphNodeEvent]
  'node-open': [event: KnowledgeGraphNodeEvent]
  'node-context': [event: KnowledgeGraphNodeContextEvent]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const hostRef = ref<HTMLElement | null>(null)
const runtimeModel = shallowRef<KnowledgeGraphModel>({ nodes: [], links: [] })

// Preload library node logo image (light/dark variants)
const libraryLogoLight = new Image()
libraryLogoLight.src = new URL('../../assets/images/亮色无底图标.png', import.meta.url).href
const libraryLogoDark = new Image()
libraryLogoDark.src = new URL('../../assets/images/暗色无底图标.png', import.meta.url).href
const hoveredNodeId = ref('')
const selectedNodeId = ref(props.selectedNodeId ?? '')
const frozen = ref(false)
const viewport = ref<KnowledgeGraphViewport>({ x: 0, y: 0, scale: 1 })
const canvasSize = ref({ width: 1, height: 1 })
const loadingOverlay = ref(false)

const HOVER_SPREAD_DURATION_MS = 720
const HOVER_TRIGGER_DELAY_MS = 200

let simulation: Simulation<KnowledgeGraphNode, KnowledgeGraphLink> | null = null
let resizeObserver: ResizeObserver | null = null
let animationFrame = 0
let hoverAnimationFrame = 0
let hoverTriggerTimer = 0
let pendingHoverNodeId = ''
let hoverAnimationNodeId = ''
let hoverAnimationStartedAt = 0
let pointerMode: 'none' | 'pan' | 'node' = 'none'
let activePointerId = 0
let draggedNode: KnowledgeGraphNode | null = null
let pointerStart = { x: 0, y: 0 }
let viewportStart: KnowledgeGraphViewport = { x: 0, y: 0, scale: 1 }
let movedDuringPointer = false

const graphStats = computed(() => ({
  nodes: runtimeModel.value.nodes.length,
  links: runtimeModel.value.links.length,
}))

function endpointId(endpoint: string | KnowledgeGraphNode): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id
}

function cloneGraphModel(model: KnowledgeGraphModel): KnowledgeGraphModel {
  return {
    nodes: model.nodes.map((node) => ({ ...node, fx: null, fy: null })),
    links: model.links.map((link) => ({
      ...link,
      source: endpointId(link.source),
      target: endpointId(link.target),
    })),
  }
}

function toNodeEvent(node: KnowledgeGraphNode): KnowledgeGraphNodeEvent {
  return {
    id: node.id,
    label: node.label,
    path: node.path,
    kind: node.kind,
  }
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function readTheme(): KnowledgeGraphRenderTheme {
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light'
  return {
    isDark,
    canvas: cssVar('--color-canvas-soft', isDark ? '#151517' : '#ffffff'),
    grid: cssVar('--color-primary-softer', isDark ? 'rgba(66, 36, 235, 0.08)' : 'rgba(66, 36, 235, 0.07)'),
    text: cssVar('--color-text', isDark ? '#f4f4f6' : '#171721'),
    mutedText: cssVar('--color-text-muted', isDark ? '#8f93a3' : '#707486'),
    edge: cssVar('--color-graph-edge', isDark ? 'rgba(199, 203, 220, 0.22)' : 'rgba(63, 66, 82, 0.18)'),
    edgeActive: cssVar('--color-primary', '#4224eb'),
    root: cssVar('--color-primary', '#4224eb'),
    folder: cssVar('--color-primary', '#4224eb'),
    file: cssVar('--color-text-secondary', isDark ? '#c7c7d1' : '#3f4252'),
    selected: cssVar('--color-accent', '#eb2463'),
    accent: cssVar('--color-accent', '#eb2463'),
    surface: cssVar('--color-surface-raised', isDark ? '#202026' : '#ffffff'),
    tagColors: ['#d85c6f', '#28a7a1', '#2f8fda', '#4e6fe8', '#7064d8', '#9a5fc4']
      .map((fallback, index) => cssVar(`--color-tag-${index + 1}`, fallback)),
    libraryImage: isDark ? libraryLogoDark : libraryLogoLight,
  }
}

function requestDraw() {
  if (animationFrame) {
    return
  }
  animationFrame = window.requestAnimationFrame(() => {
    animationFrame = 0
    draw()
  })
}

function requestHoverAnimationFrame() {
  if (!hoverAnimationNodeId || hoverAnimationFrame) {
    return
  }
  hoverAnimationFrame = window.requestAnimationFrame(() => {
    hoverAnimationFrame = 0
    requestDraw()
    if (hoverAnimationNodeId && performance.now() - hoverAnimationStartedAt < HOVER_SPREAD_DURATION_MS) {
      requestHoverAnimationFrame()
    }
  })
}

function setHighlightNode(nodeId: string) {
  if (nodeId === hoveredNodeId.value) {
    return
  }
  hoveredNodeId.value = nodeId
  hoverAnimationNodeId = nodeId
  hoverAnimationStartedAt = nodeId ? performance.now() : 0
  if (nodeId) {
    requestHoverAnimationFrame()
  } else if (hoverAnimationFrame) {
    window.cancelAnimationFrame(hoverAnimationFrame)
    hoverAnimationFrame = 0
  }
  requestDraw()
}

/** Delay passive pointer highlights so crossing a node does not trigger its hover effect. */
function scheduleHighlightNode(nodeId: string) {
  if (nodeId && nodeId === pendingHoverNodeId) {
    return
  }
  if (hoverTriggerTimer) {
    window.clearTimeout(hoverTriggerTimer)
    hoverTriggerTimer = 0
  }
  pendingHoverNodeId = ''
  if (nodeId === hoveredNodeId.value) {
    return
  }
  if (!nodeId) {
    setHighlightNode('')
    return
  }
  setHighlightNode('')
  pendingHoverNodeId = nodeId
  hoverTriggerTimer = window.setTimeout(() => {
    hoverTriggerTimer = 0
    const highlightedNodeId = pendingHoverNodeId
    pendingHoverNodeId = ''
    setHighlightNode(highlightedNodeId)
  }, HOVER_TRIGGER_DELAY_MS)
}

function draw() {
  const canvas = canvasRef.value
  const context = canvas?.getContext('2d')
  if (!canvas || !context) {
    return
  }
  const pixelRatio = window.devicePixelRatio || 1
  const highlightNodeId = draggedNode?.id ?? hoveredNodeId.value
  const hoverAnimation = hoverAnimationNodeId && hoverAnimationNodeId === highlightNodeId
    ? {
        centerNodeId: hoverAnimationNodeId,
        elapsedMs: Math.max(0, performance.now() - hoverAnimationStartedAt),
        durationMs: HOVER_SPREAD_DURATION_MS,
      }
    : undefined
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
  drawKnowledgeGraph(
    context,
    runtimeModel.value,
    {
      viewport: viewport.value,
      hoveredNodeId: highlightNodeId,
      selectedNodeId: selectedNodeId.value,
      showLabels: props.showLabels ?? true,
      hoverAnimation,
    },
    readTheme(),
    canvasSize.value.width,
    canvasSize.value.height,
  )
}

function resizeCanvas() {
  const canvas = canvasRef.value
  const host = hostRef.value
  if (!canvas || !host) {
    return
  }
  const rect = host.getBoundingClientRect()
  const width = Math.max(1, rect.width)
  const height = Math.max(1, rect.height)
  const pixelRatio = window.devicePixelRatio || 1
  canvasSize.value = { width, height }
  canvas.width = Math.floor(width * pixelRatio)
  canvas.height = Math.floor(height * pixelRatio)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  requestDraw()
}

function stopSimulation() {
  simulation?.stop()
  simulation = null
}

function startSimulation(shouldFit = true) {
  stopSimulation()
  runtimeModel.value = cloneGraphModel(props.model)
  if (runtimeModel.value.nodes.length === 0) {
    requestDraw()
    return
  }
  simulation = createLayeredForceSimulation(
    runtimeModel.value,
    canvasSize.value.width,
    canvasSize.value.height,
  )
  simulation.on('tick', requestDraw)
  if (shouldFit) {
    loadingOverlay.value = true
    viewport.value = fitGraphToViewport(runtimeModel.value, canvasSize.value.width, canvasSize.value.height)
    setTimeout(() => {
      viewport.value = fitGraphToViewport(runtimeModel.value, canvasSize.value.width, canvasSize.value.height)
      loadingOverlay.value = false
      requestDraw()
    }, 600)
  }
  requestDraw()
}

function fitToView() {
  viewport.value = fitGraphToViewport(runtimeModel.value, canvasSize.value.width, canvasSize.value.height)
  requestDraw()
}

function reheatLayout() {
  simulation?.alpha(0.9).restart()
  requestDraw()
}

function pointerPoint(event: MouseEvent | PointerEvent | WheelEvent) {
  const rect = canvasRef.value?.getBoundingClientRect()
  return {
    x: event.clientX - (rect?.left ?? 0),
    y: event.clientY - (rect?.top ?? 0),
  }
}

function selectNode(node: KnowledgeGraphNode) {
  if (selectedNodeId.value === node.id) {
    selectedNodeId.value = ''
  } else {
    selectedNodeId.value = node.id
  }
  emit('node-select', toNodeEvent(node))
  requestDraw()
}

function handleWheel(event: WheelEvent) {
  event.preventDefault()
  const point = pointerPoint(event)
  const world = screenToWorld(point, viewport.value)
  const zoomDelta = event.deltaY < 0 ? 1.12 : 0.89
  const nextScale = Math.min(2.8, Math.max(0.18, viewport.value.scale * zoomDelta))
  viewport.value = {
    x: point.x - world.x * nextScale,
    y: point.y - world.y * nextScale,
    scale: nextScale,
  }
  requestDraw()
}

function handlePointerDown(event: PointerEvent) {
  const canvas = canvasRef.value
  if (!canvas || event.button !== 0) {
    return
  }
  canvas.setPointerCapture(event.pointerId)
  activePointerId = event.pointerId
  pointerStart = pointerPoint(event)
  viewportStart = { ...viewport.value }
  movedDuringPointer = false
  const node = hitTestNode(runtimeModel.value, screenToWorld(pointerStart, viewport.value))
  scheduleHighlightNode('')
  if (node) {
    // Dragging a node while frozen auto-unfreezes so the button stays accurate
    if (frozen.value) {
      frozen.value = false
    }
    pointerMode = 'node'
    draggedNode = node
    setHighlightNode(node.id)
    node.fx = node.x ?? node.targetX
    node.fy = node.y ?? node.targetY
    // Restart without alphaTarget: a sustained target reheats every node and
    // makes the whole graph expand for as long as one node is held.
    if (simulation) {
      simulation.alpha(Math.max(simulation.alpha(), 0.12)).restart()
    }
    return
  }
  pointerMode = 'pan'
}

function handlePointerMove(event: PointerEvent) {
  const point = pointerPoint(event)
  const world = screenToWorld(point, viewport.value)
  if (pointerMode === 'node' && draggedNode && event.pointerId === activePointerId) {
    draggedNode.fx = world.x
    draggedNode.fy = world.y
    movedDuringPointer = true
    if (hoveredNodeId.value !== draggedNode.id) {
      setHighlightNode(draggedNode.id)
    }
    requestDraw()
    return
  }
  if (pointerMode === 'pan' && event.pointerId === activePointerId) {
    viewport.value = {
      ...viewport.value,
      x: viewportStart.x + point.x - pointerStart.x,
      y: viewportStart.y + point.y - pointerStart.y,
    }
    movedDuringPointer = true
    requestDraw()
    return
  }
  const nextHover = hitTestNode(runtimeModel.value, world)?.id ?? ''
  scheduleHighlightNode(nextHover)
}

function handlePointerUp(event: PointerEvent) {
  if (event.pointerId !== activePointerId) {
    return
  }
  const point = pointerPoint(event)
  const node = draggedNode ?? hitTestNode(runtimeModel.value, screenToWorld(point, viewport.value))
  if (draggedNode) {
    draggedNode.fx = null
    draggedNode.fy = null
  }
  if (node && !movedDuringPointer) {
    selectNode(node)
  } else if (!node && !movedDuringPointer) {
    selectedNodeId.value = ''
    requestDraw()
  }
  pointerMode = 'none'
  activePointerId = 0
  draggedNode = null
  setHighlightNode(hitTestNode(runtimeModel.value, screenToWorld(point, viewport.value))?.id ?? '')
  requestDraw()
}

function handlePointerLeave() {
  if (pointerMode !== 'none') {
    return
  }
  scheduleHighlightNode('')
}

function handleDoubleClick(event: MouseEvent) {
  const point = pointerPoint(event)
  const node = hitTestNode(runtimeModel.value, screenToWorld(point, viewport.value))
  if (!node) {
    fitToView()
    return
  }
  selectNode(node)
  viewport.value = focusNodeViewport(node, canvasSize.value.width, canvasSize.value.height, Math.max(0.95, viewport.value.scale))
  emit('node-open', toNodeEvent(node))
  requestDraw()
}

/** Resolve a right-click against the canvas and request a node context menu. */
function handleContextMenu(event: MouseEvent) {
  event.preventDefault()
  const point = pointerPoint(event)
  const node = hitTestNode(runtimeModel.value, screenToWorld(point, viewport.value))
  if (!node) return
  selectedNodeId.value = node.id
  emit('node-context', { node: toNodeEvent(node), clientX: event.clientX, clientY: event.clientY })
  requestDraw()
}

onMounted(() => {
  window.addEventListener('metaweave:appearance-preview', requestDraw)
  resizeObserver = new ResizeObserver(() => {
    resizeCanvas()
    startSimulation(false)
  })
  if (hostRef.value) {
    resizeObserver.observe(hostRef.value)
  }
  void nextTick(() => {
    resizeCanvas()
    startSimulation()
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('metaweave:appearance-preview', requestDraw)
  resizeObserver?.disconnect()
  resizeObserver = null
  stopSimulation()
  if (animationFrame) {
    window.cancelAnimationFrame(animationFrame)
  }
  if (hoverAnimationFrame) {
    window.cancelAnimationFrame(hoverAnimationFrame)
  }
  if (hoverTriggerTimer) {
    window.clearTimeout(hoverTriggerTimer)
  }
})

watch(
  () => props.model,
  () => startSimulation(),
)

watch(
  () => props.selectedNodeId,
  (value) => {
    selectedNodeId.value = value ?? ''
    requestDraw()
  },
)

watch(
  () => props.showLabels,
  () => requestDraw(),
)

function freezeSimulation() {
  simulation?.stop()
  frozen.value = true
}

function unfreezeSimulation() {
  simulation?.restart()
  frozen.value = false
}

defineExpose({
  fitToView,
  reheatLayout,
  freezeSimulation,
  unfreezeSimulation,
  frozen,
  graphStats,
})
</script>

<template>
  <div ref="hostRef" class="knowledge-graph-canvas">
    <div v-if="loadingOverlay" class="graph-loading-overlay">
      <span class="loading-spinner" />
      <span>加载中...</span>
    </div>
    <canvas
      ref="canvasRef"
      :class="{ hovering: hoveredNodeId }"
      aria-label="Knowledge graph canvas"
      @dblclick="handleDoubleClick"
      @contextmenu="handleContextMenu"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
      @pointerleave="handlePointerLeave"
      @wheel="handleWheel"
    ></canvas>
  </div>
</template>

<style scoped>
.knowledge-graph-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-canvas-soft);
}

canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
  touch-action: none;
}

canvas:active {
  cursor: grabbing;
}

canvas.hovering {
  cursor: pointer;
}

.graph-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: color-mix(in srgb, var(--color-canvas) 70%, transparent);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: var(--color-text-muted);
  font-size: calc(14px * var(--font-scale));
}

.loading-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: graph-loading-spin 700ms linear infinite;
}

@keyframes graph-loading-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
