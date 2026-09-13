/*
 * Knowledge graph Canvas renderer regression tests.
 *
 * Usage:
 * Run this focused Vitest file to verify zoom-dependent graph presentation
 * without mounting the Vue shell or starting a browser.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import { drawKnowledgeGraph, resolveKnowledgeGraphNodeColor } from '../graphRenderer'
import canvasSource from '../KnowledgeGraphCanvas.vue?raw'
import type {
  KnowledgeGraphModel,
  KnowledgeGraphRenderState,
  KnowledgeGraphRenderTheme,
} from '../graphTypes'

/** Creates the smallest Canvas 2D spy required by the graph renderer. */
function createCanvasContext() {
  return {
    arc: vi.fn(),
    beginPath: vi.fn(),
    clearRect: vi.fn(),
    clip: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    lineTo: vi.fn(),
    moveTo: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    scale: vi.fn(),
    setLineDash: vi.fn(),
    stroke: vi.fn(),
    translate: vi.fn(),
  } as unknown as CanvasRenderingContext2D
}

const model: KnowledgeGraphModel = {
  nodes: [
    {
      id: 'root',
      label: '知识库',
      path: '',
      kind: 'root',
      depth: 0,
      siblingIndex: 0,
      siblingCount: 1,
      ringIndex: 0,
      radius: 18,
      targetX: 50,
      targetY: 50,
    },
  ],
  links: [],
}

const theme: KnowledgeGraphRenderTheme = {
  isDark: true,
  canvas: '#111111',
  grid: 'rgba(255,255,255,0.04)',
  text: '#ffffff',
  mutedText: '#999999',
  edge: 'rgba(255,255,255,0.2)',
  edgeActive: '#4224eb',
  root: '#4224eb',
  folder: '#4224eb',
  file: '#cccccc',
  selected: '#eb2463',
  accent: '#eb2463',
  surface: '#202026',
  tagColors: ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666'],
}
const uiSystemSource = readFileSync(resolve(process.cwd(), 'src/assets/ui-system.css'), 'utf8')

/** Creates renderer state at the requested graph zoom. */
function stateAtScale(scale: number): KnowledgeGraphRenderState {
  return {
    viewport: { x: 0, y: 0, scale },
    hoveredNodeId: 'root',
    selectedNodeId: 'root',
    showLabels: true,
  }
}

describe('knowledge graph compact rendering', () => {
  it('maps structural, file, and entity categories onto the shared tag palette', () => {
    const node = (kind: KnowledgeGraphModel['nodes'][number]['kind'], extension = '') => ({
      ...model.nodes[0]!,
      kind,
      extension,
    })

    expect(resolveKnowledgeGraphNodeColor(node('root'), theme)).toBe('#111111')
    expect(resolveKnowledgeGraphNodeColor(node('folder'), theme)).toBe('#222222')
    expect(resolveKnowledgeGraphNodeColor(node('document'), theme)).toBe('#333333')
    expect(resolveKnowledgeGraphNodeColor(node('file', 'ts'), theme)).toBe('#444444')
    expect(resolveKnowledgeGraphNodeColor(node('file', 'json'), theme)).toBe('#555555')
    expect(resolveKnowledgeGraphNodeColor(node('file', 'pdf'), theme)).toBe('#666666')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'person'), theme)).toBe('#111111')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'organization'), theme)).toBe('#222222')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'project'), theme)).toBe('#333333')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'function'), theme)).toBe('#444444')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'concept'), theme)).toBe('#555555')
    expect(resolveKnowledgeGraphNodeColor(node('entity', 'data'), theme)).toBe('#666666')
  })

  it('reads all six appearance tag colors and the lighter theme edge variable', () => {
    expect(canvasSource).toContain("cssVar(`--color-tag-${index + 1}`")
    expect(canvasSource).toContain("edge: cssVar('--color-graph-edge'")
    expect(uiSystemSource).toContain('--color-graph-edge: rgba(199, 203, 220, 0.22);')
    expect(uiSystemSource).toContain('--color-graph-edge: rgba(63, 66, 82, 0.18);')
  })

  it('hides every label while the graph is strongly zoomed out', () => {
    const context = createCanvasContext()

    drawKnowledgeGraph(context, model, stateAtScale(0.55), theme, 100, 100)

    expect(context.fillText).not.toHaveBeenCalled()
  })

  it('keeps labels at a readable graph scale', () => {
    const context = createCanvasContext()

    drawKnowledgeGraph(context, model, stateAtScale(1), theme, 100, 100)

    expect(context.fillText).toHaveBeenCalledWith('知识库', 50, 75)
  })
})
