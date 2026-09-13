/*
 * Canvas renderer for reusable knowledge graphs.
 *
 * Usage:
 * Draw a KnowledgeGraphModel onto any 2D canvas context. This file does not
 * depend on Vue or d3-force and can be moved into another application together
 * with graphTypes.ts.
 */

import type {
  KnowledgeGraphLink,
  KnowledgeGraphModel,
  KnowledgeGraphNode,
  KnowledgeGraphRenderState,
  KnowledgeGraphRenderTheme,
} from './graphTypes'

const FILE_COLOR_SLOTS = new Map<string, number>([
  ['md', 2],
  ['markdown', 2],
  ['txt', 2],
  ['ts', 3],
  ['tsx', 3],
  ['js', 3],
  ['vue', 3],
  ['py', 3],
  ['json', 4],
  ['yaml', 4],
  ['yml', 4],
  ['xlsx', 4],
  ['pdf', 5],
  ['docx', 5],
])

/** Stable semantic groups mapped onto the six user appearance tag colors. */
const ENTITY_COLOR_SLOTS: Record<string, number> = {
  person: 0,
  organization: 1,
  project: 2,
  module: 3,
  class: 3,
  function: 3,
  file: 3,
  config: 3,
  concept: 4,
  data: 5,
  other: 5,
}

/** Zoom boundary below which labels would crowd the compact graph silhouette. */
const COMPACT_GRAPH_SCALE = 0.72

function currentUiFont(): string {
  if (typeof document === 'undefined') {
    return 'system-ui, sans-serif'
  }
  return getComputedStyle(document.documentElement).getPropertyValue('--font-ui').trim() || 'system-ui, sans-serif'
}

function linkNode(endpoint: string | KnowledgeGraphNode, nodesById: Map<string, KnowledgeGraphNode>) {
  return typeof endpoint === 'string' ? nodesById.get(endpoint) : endpoint
}

function tagColor(theme: KnowledgeGraphRenderTheme, slot: number, fallback: string): string {
  return theme.tagColors[slot] || fallback
}

/** Resolve one node category through the user's six shared appearance tag colors. */
export function resolveKnowledgeGraphNodeColor(node: KnowledgeGraphNode, theme: KnowledgeGraphRenderTheme): string {
  if (node.kind === 'root') {
    return tagColor(theme, 0, theme.root)
  }
  if (node.kind === 'folder' || node.kind === 'virtual-group') {
    return tagColor(theme, 1, theme.folder)
  }
  if (node.kind === 'document') {
    return tagColor(theme, 2, theme.root)
  }
  if (node.kind === 'library') {
    return tagColor(theme, 0, theme.root)
  }
  if (node.kind === 'entity') {
    return tagColor(theme, ENTITY_COLOR_SLOTS[node.extension ?? 'other'] ?? 5, theme.accent)
  }
  const extension = node.extension ?? ''
  return tagColor(theme, FILE_COLOR_SLOTS.get(extension) ?? 5, theme.file)
}

function shouldShowLabel(node: KnowledgeGraphNode, state: KnowledgeGraphRenderState): boolean {
  if (state.viewport.scale < COMPACT_GRAPH_SCALE) {
    return false
  }
  const isActive = node.id === state.hoveredNodeId || node.id === state.selectedNodeId
  if (!state.showLabels) {
    return node.id === state.hoveredNodeId
  }
  if (node.kind === 'root' || node.kind === 'folder' || node.kind === 'virtual-group' || node.kind === 'document' || node.kind === 'library') {
    return true
  }
  return state.viewport.scale > 0.92 || isActive
}

function endpointId(endpoint: string | KnowledgeGraphNode): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function easeOutCubic(value: number): number {
  const clamped = clamp01(value)
  return 1 - Math.pow(1 - clamped, 3)
}

function hoverSpreadRatio(state: KnowledgeGraphRenderState): number {
  const animation = state.hoverAnimation
  if (!animation || animation.centerNodeId !== state.hoveredNodeId || animation.durationMs <= 0) {
    return state.hoveredNodeId ? 1 : 0
  }
  return clamp01(animation.elapsedMs / animation.durationMs)
}

function centerHighlightProgress(state: KnowledgeGraphRenderState): number {
  return easeOutCubic(hoverSpreadRatio(state) / 0.28)
}

function edgeSpreadProgress(state: KnowledgeGraphRenderState): number {
  return clamp01((hoverSpreadRatio(state) - 0.18) / 0.52)
}

function neighborHighlightProgress(state: KnowledgeGraphRenderState): number {
  return easeOutCubic((hoverSpreadRatio(state) - 0.68) / 0.32)
}

function collectRelatedNodeIds(model: KnowledgeGraphModel, state: KnowledgeGraphRenderState): Set<string> {
  const baseNodeIds = new Set([state.hoveredNodeId, state.selectedNodeId].filter(Boolean))
  const relatedNodeIds = new Set(baseNodeIds)
  for (const link of model.links) {
    const sourceId = endpointId(link.source)
    const targetId = endpointId(link.target)
    if (baseNodeIds.has(sourceId)) {
      relatedNodeIds.add(targetId)
    }
    if (baseNodeIds.has(targetId)) {
      relatedNodeIds.add(sourceId)
    }
  }
  return relatedNodeIds
}

function nodeHighlightProgress(node: KnowledgeGraphNode, state: KnowledgeGraphRenderState, relatedNodeIds: Set<string>): number {
  if (node.id === state.selectedNodeId) {
    return 1
  }
  if (!state.hoveredNodeId && state.selectedNodeId) {
    // 仅选中节点改变轮廓，关联节点保持原样。
    return 0
  }
  if (!state.hoveredNodeId || !relatedNodeIds.has(node.id)) {
    return 0
  }
  if (node.id === state.hoveredNodeId) {
    return centerHighlightProgress(state)
  }
  return neighborHighlightProgress(state)
}

function drawHighlightCircle(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
  progress: number,
  viewportScale: number,
) {
  if (progress <= 0) {
    return
  }
  const scaleProgress = clamp01(viewportScale)
  ctx.save()
  ctx.beginPath()
  ctx.arc(x, y, radius + 3 + 3 * scaleProgress * progress, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.globalAlpha = 0.1 * progress
  ctx.fill()
  ctx.globalAlpha = 1
  ctx.strokeStyle = color
  ctx.lineWidth = 0.8 + 0.4 * progress
  ctx.stroke()
  ctx.restore()
}

function drawGrid(ctx: CanvasRenderingContext2D, width: number, height: number, theme: KnowledgeGraphRenderTheme) {
  const step = 32
  ctx.save()
  ctx.strokeStyle = theme.grid
  ctx.lineWidth = 1
  for (let x = 0; x < width; x += step) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
    ctx.stroke()
  }
  for (let y = 0; y < height; y += step) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }
  ctx.restore()
}

function drawLink(
  ctx: CanvasRenderingContext2D,
  link: KnowledgeGraphLink,
  nodesById: Map<string, KnowledgeGraphNode>,
  state: KnowledgeGraphRenderState,
  theme: KnowledgeGraphRenderTheme,
  relatedNodeIds: Set<string>,
) {
  const source = linkNode(link.source, nodesById)
  const target = linkNode(link.target, nodesById)
  if (!source || !target) {
    return
  }
  const touchesHovered = Boolean(state.hoveredNodeId) && (source.id === state.hoveredNodeId || target.id === state.hoveredNodeId)
  const hoverProgress = touchesHovered ? edgeSpreadProgress(state) : 0
  const hasActive = Boolean(state.hoveredNodeId || state.selectedNodeId)
  const isRelated = relatedNodeIds.has(source.id) && relatedNodeIds.has(target.id)
  const sourceX = source.x ?? source.targetX
  const sourceY = source.y ?? source.targetY
  const targetX = target.x ?? target.targetX
  const targetY = target.y ?? target.targetY
  ctx.save()
  ctx.globalAlpha = hasActive && !isRelated ? 0.2 : 1
  ctx.beginPath()
  ctx.moveTo(sourceX, sourceY)
  ctx.lineTo(targetX, targetY)
  ctx.strokeStyle = theme.edge
  const bothEntity = source.kind === 'entity' && target.kind === 'entity'
  const oneEntity = source.kind === 'entity' || target.kind === 'entity'
  const zoomCompensation = 1 / Math.max(state.viewport.scale, 0.18)
  ctx.lineWidth = (bothEntity ? 1.1 : oneEntity ? 0.9 : 1.1) * zoomCompensation
  ctx.stroke()
  ctx.restore()
  if (!touchesHovered || hoverProgress <= 0) {
    return
  }
  const spreadSource = source.id === state.hoveredNodeId ? source : target
  const spreadTarget = source.id === state.hoveredNodeId ? target : source
  const startX = spreadSource.x ?? spreadSource.targetX
  const startY = spreadSource.y ?? spreadSource.targetY
  const endX = spreadTarget.x ?? spreadTarget.targetX
  const endY = spreadTarget.y ?? spreadTarget.targetY
  const highlightEndX = startX + (endX - startX) * hoverProgress
  const highlightEndY = startY + (endY - startY) * hoverProgress
  const hoverColor = resolveKnowledgeGraphNodeColor(spreadSource, theme)
  ctx.save()
  ctx.globalAlpha = 0.2 + 0.8 * hoverProgress
  ctx.strokeStyle = hoverColor
  ctx.lineWidth = 0.8 + 0.9 * hoverProgress
  ctx.beginPath()
  ctx.moveTo(startX, startY)
  ctx.lineTo(highlightEndX, highlightEndY)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc(highlightEndX, highlightEndY, 2.2 + 1.8 * hoverProgress, 0, Math.PI * 2)
  ctx.fillStyle = hoverColor
  ctx.globalAlpha = 0.18 + 0.28 * hoverProgress
  ctx.fill()
  ctx.restore()
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: KnowledgeGraphNode,
  state: KnowledgeGraphRenderState,
  theme: KnowledgeGraphRenderTheme,
  relatedNodeIds: Set<string>,
) {
  const x = node.x ?? node.targetX
  const y = node.y ?? node.targetY
  const isSelected = node.id === state.selectedNodeId
  const isHovered = node.id === state.hoveredNodeId
  const highlightProgress = nodeHighlightProgress(node, state, relatedNodeIds)
  const hasActive = Boolean(state.hoveredNodeId || state.selectedNodeId)
  const isRelated = relatedNodeIds.has(node.id)
  const color = resolveKnowledgeGraphNodeColor(node, theme)
  ctx.save()
  ctx.globalAlpha = hasActive && !isRelated ? 0.38 : 1
  if (highlightProgress > 0) {
    drawHighlightCircle(ctx, x, y, node.radius, color, highlightProgress, state.viewport.scale)
  }
  ctx.beginPath()
  ctx.arc(x, y, node.radius, 0, Math.PI * 2)
  if (node.kind === 'folder' || node.kind === 'virtual-group' || node.kind === 'document') {
    ctx.setLineDash([4, 3])
    ctx.fillStyle = theme.surface
    ctx.strokeStyle = color
    ctx.lineWidth = 1.4 + 1.6 * highlightProgress
    ctx.fill()
    ctx.stroke()
  } else if (node.kind === 'library' || node.kind === 'root') {
    ctx.fillStyle = theme.surface
    ctx.fill()
    ctx.save()
    ctx.beginPath()
    ctx.arc(x, y, node.radius, 0, Math.PI * 2)
    ctx.clip()
    if (theme.libraryImage) {
      const imgSize = node.radius * 1.6
      ctx.drawImage(theme.libraryImage, x - imgSize / 2, y - imgSize / 2, imgSize, imgSize)
    }
    ctx.restore()
    ctx.beginPath()
    ctx.arc(x, y, node.radius, 0, Math.PI * 2)
    ctx.strokeStyle = color
    ctx.lineWidth = 1.4 + 1.6 * highlightProgress
    ctx.stroke()
  } else {
    ctx.fillStyle = color
    ctx.fill()
    if (highlightProgress > 0 || isHovered || isSelected) {
      ctx.strokeStyle = color
      ctx.lineWidth = 1 + 2 * highlightProgress
      ctx.stroke()
    }
  }
  if (highlightProgress > 0) {
    ctx.beginPath()
    ctx.setLineDash([])
    ctx.arc(x, y, node.radius + 3 + 3 * clamp01(state.viewport.scale), 0, Math.PI * 2)
    ctx.strokeStyle = color
    ctx.globalAlpha = isRelated ? highlightProgress : hasActive ? 0.08 : 0.38
    ctx.lineWidth = 0.8 + 0.4 * highlightProgress
    ctx.stroke()
  }
  ctx.restore()
}

function drawLabel(
  ctx: CanvasRenderingContext2D,
  node: KnowledgeGraphNode,
  state: KnowledgeGraphRenderState,
  theme: KnowledgeGraphRenderTheme,
  relatedNodeIds: Set<string>,
) {
  if (!shouldShowLabel(node, state)) {
    return
  }
  const x = node.x ?? node.targetX
  const y = node.y ?? node.targetY
  const hasActive = Boolean(state.hoveredNodeId || state.selectedNodeId)
  const isRelated = relatedNodeIds.has(node.id)
  const label = node.label.length > 34 ? `${node.label.slice(0, 31)}...` : node.label
  ctx.save()
  ctx.globalAlpha = hasActive && !isRelated ? 0.4 : 1
  const baseFontSize = node.kind === 'root' || node.id === state.hoveredNodeId ? 13 : 11
  ctx.font = `${Math.round(baseFontSize / Math.max(state.viewport.scale, 0.1))}px ${currentUiFont()}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillStyle = node.id === state.hoveredNodeId || node.id === state.selectedNodeId ? theme.text : theme.mutedText
  ctx.fillText(label, x, y + node.radius + 7)
  ctx.restore()
}

/** Draw the full graph to the provided Canvas 2D context. */
export function drawKnowledgeGraph(
  ctx: CanvasRenderingContext2D,
  model: KnowledgeGraphModel,
  state: KnowledgeGraphRenderState,
  theme: KnowledgeGraphRenderTheme,
  width: number,
  height: number,
) {
  const nodesById = new Map(model.nodes.map((node) => [node.id, node]))
  const relatedNodeIds = collectRelatedNodeIds(model, state)
  ctx.save()
  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = theme.canvas
  ctx.fillRect(0, 0, width, height)
  drawGrid(ctx, width, height, theme)
  ctx.translate(state.viewport.x, state.viewport.y)
  ctx.scale(state.viewport.scale, state.viewport.scale)
  model.links.forEach((link) => drawLink(ctx, link, nodesById, state, theme, relatedNodeIds))
  model.nodes.forEach((node) => drawNode(ctx, node, state, theme, relatedNodeIds))
  model.nodes.forEach((node) => drawLabel(ctx, node, state, theme, relatedNodeIds))
  ctx.restore()
}
