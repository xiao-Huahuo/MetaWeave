/*
 * Reusable knowledge graph domain types.
 *
 * Usage:
 * Keep this file free of Vue and MetaWeave store imports. Other applications
 * can reuse the graph model, layout options, and Canvas renderer contracts by
 * providing the same node/link shape.
 */

/** Supported graph node categories. */
export type KnowledgeGraphNodeKind = 'root' | 'folder' | 'file' | 'virtual-group' | 'document' | 'entity' | 'library'

/** Supported graph edge categories. Semantic graph relation types may use domain-specific strings. */
export type KnowledgeGraphLinkKind = 'parent-child' | 'reference' | 'semantic' | string

/** One graph node with optional d3-force simulation fields. */
export interface KnowledgeGraphNode {
  /** Stable id used by links and interaction events. */
  id: string
  /** Short display label shown near the node. */
  label: string
  /** Knowledge-root-relative file path when the node maps to a file tree item. */
  path: string
  /** Node category used by layout and rendering. */
  kind: KnowledgeGraphNodeKind
  /** Normalized file extension without a leading dot. */
  extension?: string
  /** Tree depth, with root at depth 0. */
  depth: number
  /** Optional parent node id for layered positioning. */
  parentId?: string
  /** Index among siblings after directory-first sorting. */
  siblingIndex: number
  /** Number of siblings under the same parent. */
  siblingCount: number
  /** Ring index used when siblings overflow one circle. */
  ringIndex: number
  /** Visual radius in graph world units. */
  radius: number
  /** Layout anchor x coordinate in graph world units. */
  targetX: number
  /** Layout anchor y coordinate in graph world units. */
  targetY: number
  /** d3-force x coordinate. */
  x?: number
  /** d3-force y coordinate. */
  y?: number
  /** d3-force x velocity. */
  vx?: number
  /** d3-force y velocity. */
  vy?: number
  /** Fixed x coordinate while dragging. */
  fx?: number | null
  /** Fixed y coordinate while dragging. */
  fy?: number | null
}

/** One graph edge. */
export interface KnowledgeGraphLink {
  /** Stable edge id. */
  id: string
  /** Source node id before d3-force resolves it to a node object. */
  source: string | KnowledgeGraphNode
  /** Target node id before d3-force resolves it to a node object. */
  target: string | KnowledgeGraphNode
  /** Edge category used by layout and rendering. */
  kind: KnowledgeGraphLinkKind
  /** Optional edge weight for semantic/reference graphs. */
  weight?: number
}

/** Complete graph data consumed by the reusable renderer. */
export interface KnowledgeGraphModel {
  /** Graph nodes. */
  nodes: KnowledgeGraphNode[]
  /** Graph links. */
  links: KnowledgeGraphLink[]
}

/** Canvas viewport transform from graph world to screen. */
export interface KnowledgeGraphViewport {
  /** Screen-space x translation. */
  x: number
  /** Screen-space y translation. */
  y: number
  /** World-to-screen scale. */
  scale: number
}

/** Layout knobs for the layered force simulation. */
export interface LayeredForceLayoutOptions {
  /** Maximum direct siblings before a new ring is created. */
  maxNodesPerRing: number
  /** Radius of the first child ring. */
  baseRingRadius: number
  /** Added radius per overflow ring. */
  ringGap: number
  /** Node collision padding. */
  collisionPadding: number
  /** Strength that pulls nodes toward precomputed ring targets. */
  anchorStrength: number
  /** Base many-body charge. */
  chargeStrength: number
}

/** Visual theme passed into the Canvas renderer. */
export interface KnowledgeGraphRenderTheme {
  /** Whether the current editor theme is dark, used for theme-specific graph colors. */
  isDark: boolean
  canvas: string
  grid: string
  text: string
  mutedText: string
  edge: string
  edgeActive: string
  root: string
  folder: string
  file: string
  selected: string
  accent: string
  surface: string
  /** Six user-configurable appearance tag colors used by graph categories. */
  tagColors: string[]
  /** Preloaded logo image for the library node. */
  libraryImage?: HTMLImageElement
}

/** Hover highlight spread animation state. */
export interface KnowledgeGraphHoverAnimation {
  /** Node where the animated shape and color highlight starts. */
  centerNodeId: string
  /** Elapsed animation time in milliseconds. */
  elapsedMs: number
  /** Full spread duration in milliseconds. */
  durationMs: number
}

/** Current renderer interaction state. */
export interface KnowledgeGraphRenderState {
  viewport: KnowledgeGraphViewport
  hoveredNodeId: string
  selectedNodeId: string
  /** Whether labels should be rendered by default. Disabled mode only shows active labels. */
  showLabels: boolean
  /** Optional hover/drag spread animation progress. */
  hoverAnimation?: KnowledgeGraphHoverAnimation
}

/** Public node interaction event emitted by the Vue shell. */
export interface KnowledgeGraphNodeEvent {
  id: string
  label: string
  path: string
  kind: KnowledgeGraphNodeKind
}

/** Right-click node event with viewport coordinates for a fixed context menu. */
export interface KnowledgeGraphNodeContextEvent {
  node: KnowledgeGraphNodeEvent
  clientX: number
  clientY: number
}
