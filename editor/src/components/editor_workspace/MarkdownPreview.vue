<!--
  Markdown preview surface.

  Usage:
  Hosts a read-only Vditor instance and exposes only its preview pane. This
  keeps Preview/Split rendering on the same internal Vditor pipeline as Edit,
  including headings, code block previews, diagrams, and math blocks.
-->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import 'vditor/dist/js/i18n/zh_CN.js'
import lutePath from 'vditor/dist/js/lute/lute.min.js?url'
import Vditor from 'vditor'

import {
  buildRawFileUrl,
  decorateRenderedMarkdownImages,
  rewriteMarkdownImageUrls,
} from '@/components/editor_workspace/markdownImageUrls'
import IcIcon from '@/components/common/IcIcon.vue'
import { hljs } from './codeHighlight'
import { extractPreviewMath, renderMathInPreviewDom } from './mathRender'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { normalizeWikiAnchor } from './wikiLinks'
import { decorateWikiPreview } from './wikiPreview'

import { useImagePreviewer } from '@/components/common/useImagePreviewer'
import type { ImagePreviewItem } from '@/components/common/useImagePreviewer'
import type { ScannerOcrBlock } from '@/api/scanner'

const props = defineProps<{
  content: string
  path?: string
  /** Reduces preview spacing and typography for embedded table cells. */
  compact?: boolean
  /** Adds a download action to each rendered image. */
  imageDownload?: boolean
  /** Requests a one-shot scroll and highlight after navigating through a wiki link. */
  focusAnchor?: { path: string; heading: string; blockId: string; nonce: number } | null
  blocks?: ScannerOcrBlock[]
  activeBlockId?: string
  lockedBlockId?: string
}>()

const emit = defineEmits<{
  scroll: [ratio: number]
  activeHeading: [index: number]
  ready: []
  updateContent: [content: string]
  downloadImage: [src: string, name: string]
  navigateWiki: [destination: string]
  blockHover: [blockId: string]
  blockLeave: []
  blockSelect: [blockId: string]
}>()

interface SourceMarkdownTable {
  startLine: number
  endLine: number
  separatorLine: number
  lines: string[]
}

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const embeddedVditorI18n = (window as unknown as { VditorI18n: Record<string, string> }).VditorI18n

type VditorPreviewInternals = Vditor & {
  vditor?: {
    preview?: {
      element?: HTMLElement
      previewElement?: HTMLElement
    }
  }
}

const imagePreviewer = useImagePreviewer()
const previewHost = ref<HTMLDivElement | null>(null)
const tableOverlayElement = ref<HTMLDivElement | null>(null)
const wikiEmbedCache = new Map<string, string>()
let lastWikiFocusNonce = -1
let wikiHighlightTimer: ReturnType<typeof setTimeout> | null = null
const TABLE_EDGE_BUTTON_SIZE = 9
const TABLE_EDGE_HIT_ZONE = 14
const EDITABLE_PREVIEW_TABLE_SELECTOR = 'table:not([data-metaweave-html-table])'
const tableOverlay = ref<{
  visible: boolean
  showLeftEdge: boolean
  showTopEdge: boolean
  showRightEdge: boolean
  showBottomEdge: boolean
  addRowButtonBottom: number
  left: number
  top: number
  width: number
  height: number
  rowTop: number
  rowHeight: number
  columnLeft: number
  columnWidth: number
  tableIndex: number
  rowIndex: number
  columnIndex: number
}>({
  visible: false,
  showLeftEdge: false,
  showTopEdge: false,
  showRightEdge: false,
  showBottomEdge: false,
  addRowButtonBottom: -TABLE_EDGE_BUTTON_SIZE,
  left: 0,
  top: 0,
  width: 0,
  height: 0,
  rowTop: 0,
  rowHeight: 0,
  columnLeft: 0,
  columnWidth: 0,
  tableIndex: 0,
  rowIndex: 0,
  columnIndex: 0,
})
let instance: Vditor | null = null
let mounted = false
let renderVersion = 0
let programmaticScroll = false
let programmaticScrollTimer: ReturnType<typeof setTimeout> | null = null
let pendingHeadingIndex: number | null = null
let displayBlocks: string[] = []
let inlineBlocks: string[] = []
let previewTableDrag: { type: 'row' | 'column'; tableIndex: number; source: number } | null = null

function parseTableRow(line: string): string[] {
  const trimmed = line.trim()
  const body = trimmed.replace(/^\|/u, '').replace(/\|$/u, '')
  return body.split('|').map((cell) => cell.trim())
}

function isMarkdownTableRow(line: string): boolean {
  const trimmed = line.trim()
  return trimmed.includes('|') && trimmed.split('|').length >= 3
}

function isMarkdownTableSeparator(line: string): boolean {
  const cells = parseTableRow(line)
  if (cells.length < 2) {
    return false
  }
  return cells.every((cell) => /^:?-{3,}:?$/u.test(cell.trim()))
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.map((cell) => cell.trim() || ' ').join(' | ')} |`
}

function formatTableSeparator(columnCount: number): string {
  return `| ${Array.from({ length: Math.max(1, columnCount) }, () => '---').join(' | ')} |`
}

function normalizeTableRows(lines: string[]): string[] {
  const columnCount = Math.max(...lines.map((line) => parseTableRow(line).length), 1)
  return lines.map((line) => {
    if (isMarkdownTableSeparator(line)) {
      return formatTableSeparator(columnCount)
    }
    const cells = parseTableRow(line)
    while (cells.length < columnCount) {
      cells.push('')
    }
    return formatTableRow(cells.slice(0, columnCount))
  })
}

function sourceMarkdownTables(content: string): SourceMarkdownTable[] {
  const lines = content.split('\n')
  const tables: SourceMarkdownTable[] = []
  let lineIndex = 0
  while (lineIndex < lines.length) {
    if (!isMarkdownTableRow(lines[lineIndex] ?? '')) {
      lineIndex += 1
      continue
    }
    const startLine = lineIndex
    let endLine = lineIndex
    while (endLine < lines.length - 1 && isMarkdownTableRow(lines[endLine + 1] ?? '')) {
      endLine += 1
    }
    const separatorLine = lines.findIndex((line, index) => (
      index >= startLine && index <= endLine && isMarkdownTableSeparator(line)
    ))
    if (separatorLine >= startLine && separatorLine <= endLine) {
      tables.push({ startLine, endLine, separatorLine, lines: lines.slice(startLine, endLine + 1) })
    }
    lineIndex = endLine + 1
  }
  return tables
}

function replaceSourceTable(table: SourceMarkdownTable, nextLines: string[]) {
  const lines = props.content.split('\n')
  lines.splice(table.startLine, table.endLine - table.startLine + 1, ...normalizeTableRows(nextLines))
  emit('updateContent', lines.join('\n'))
}

function insertSourceTableRow(tableIndex: number, rowIndex: number, position: 'above' | 'below') {
  const table = sourceMarkdownTables(props.content)[tableIndex]
  if (!table) return
  const rows = normalizeTableRows(table.lines)
  const columnCount = parseTableRow(rows[0] ?? '').length || 2
  const emptyRow = formatTableRow(Array.from({ length: columnCount }, () => ''))
  const separatorIndex = table.separatorLine - table.startLine
  let insertAt = position === 'above' ? rowIndex : rowIndex + 1
  if (insertAt <= separatorIndex) {
    insertAt = separatorIndex + 1
  }
  rows.splice(insertAt, 0, emptyRow)
  replaceSourceTable(table, rows)
}

function renderedRowToSourceRow(tableIndex: number, renderedRowIndex: number): number {
  const table = sourceMarkdownTables(props.content)[tableIndex]
  if (!table) return renderedRowIndex
  const separatorIndex = table.separatorLine - table.startLine
  return renderedRowIndex >= separatorIndex ? renderedRowIndex + 1 : renderedRowIndex
}

function insertSourceTableColumn(tableIndex: number, columnIndex: number, side: 'left' | 'right') {
  const table = sourceMarkdownTables(props.content)[tableIndex]
  if (!table) return
  const rows = normalizeTableRows(table.lines)
  const insertAt = columnIndex + (side === 'right' ? 1 : 0)
  const nextRows = rows.map((line) => {
    const cells = parseTableRow(line)
    cells.splice(Math.max(0, Math.min(insertAt, cells.length)), 0, '')
    return isMarkdownTableSeparator(line) ? formatTableSeparator(cells.length) : formatTableRow(cells)
  })
  replaceSourceTable(table, nextRows)
}

function moveSourceTableRow(tableIndex: number, sourceRow: number, targetRow: number) {
  const table = sourceMarkdownTables(props.content)[tableIndex]
  if (!table || sourceRow === targetRow) return
  const separatorIndex = table.separatorLine - table.startLine
  if (sourceRow === separatorIndex || targetRow === separatorIndex) return
  const rows = normalizeTableRows(table.lines)
  const [row] = rows.splice(sourceRow, 1)
  if (!row) return
  rows.splice(Math.max(0, Math.min(targetRow, rows.length)), 0, row)
  replaceSourceTable(table, rows)
}

function moveSourceTableColumn(tableIndex: number, sourceColumn: number, targetColumn: number) {
  const table = sourceMarkdownTables(props.content)[tableIndex]
  if (!table || sourceColumn === targetColumn) return
  const rows = normalizeTableRows(table.lines)
  const nextRows = rows.map((line) => {
    const cells = parseTableRow(line)
    const sourceIndex = Math.max(0, Math.min(sourceColumn, cells.length - 1))
    const targetIndex = Math.max(0, Math.min(targetColumn, cells.length - 1))
    const [cell] = cells.splice(sourceIndex, 1)
    if (cell === undefined) return line
    cells.splice(targetIndex, 0, cell)
    return isMarkdownTableSeparator(line) ? formatTableSeparator(cells.length) : formatTableRow(cells)
  })
  replaceSourceTable(table, nextRows)
}

/** Converts ==highlight== outside fenced and inline code into native mark elements. */
function rewriteMarkdownHighlights(content: string): string {
  let fenceChar = ''
  let fenceLength = 0
  return content.split('\n').map((line) => {
    const fence = line.match(/^\s{0,3}(`{3,}|~{3,})/u)?.[1] ?? ''
    if (fence) {
      const marker = fence[0] ?? ''
      if (!fenceChar) {
        fenceChar = marker
        fenceLength = fence.length
      } else if (marker === fenceChar && fence.length >= fenceLength) {
        fenceChar = ''
        fenceLength = 0
      }
      return line
    }
    if (fenceChar) return line
    return line.split(/(`+[^`]*`+)/u).map((segment, index) => {
      if (index % 2 === 1) return segment
      return segment.replace(
        /(^|[^\\=])==(\S(?:[^\n]*?\S)?)==(?=$|[^=])/gu,
        (_match, prefix: string, text: string) => `${prefix}<mark>${text}</mark>`,
      )
    }).join('')
  }).join('\n')
}

/** Marks source HTML tables as read-only without changing fenced or inline code examples. */
function markPreviewHtmlTables(content: string): string {
  let fenceChar = ''
  let fenceLength = 0
  return content.split('\n').map((line) => {
    const fence = line.match(/^\s{0,3}(`{3,}|~{3,})/u)?.[1] ?? ''
    if (fence) {
      const marker = fence[0] ?? ''
      if (!fenceChar) {
        fenceChar = marker
        fenceLength = fence.length
      } else if (marker === fenceChar && fence.length >= fenceLength) {
        fenceChar = ''
        fenceLength = 0
      }
      return line
    }
    if (fenceChar) return line
    return line.split(/(`+[^`]*`+)/u).map((segment, index) => (
      index % 2 === 1
        ? segment
        : segment.replace(/<table(?=[\s>])/giu, '<table data-metaweave-html-table')
    )).join('')
  }).join('\n')
}

function preparePreviewMarkdown(content: string): string {
  const highlightedContent = markPreviewHtmlTables(rewriteMarkdownHighlights(content))
  const renderContent = rewriteMarkdownImageUrls(highlightedContent, getImageUrlContext())
  const { markdown, displayBlocks: nextDisplayBlocks, inlineBlocks: nextInlineBlocks } = extractPreviewMath(renderContent)
  displayBlocks = nextDisplayBlocks
  inlineBlocks = nextInlineBlocks
  return markdown
}

function decodeUrlPath(path: string) {
  try {
    return decodeURIComponent(path)
  } catch {
    return path
  }
}

function getImageUrlContext() {
  const filePath = props.path || workspaceStore.selectedPath
  const userId = settingsStore.profile.userId
  return { currentFilePath: filePath, userId }
}

function getPreviewElement() {
  const internalPreview = (instance as VditorPreviewInternals | null)?.vditor?.preview?.element
  return internalPreview ?? previewHost.value?.querySelector<HTMLElement>('.vditor-preview') ?? null
}

function ensurePreviewPaneIsRenderable() {
  const previewElement = getPreviewElement()
  if (!previewElement) {
    return
  }
  // Guardrail: Vditor.preview.render() checks preview.element.style.display,
  // not computed CSS. Scoped display:block CSS is insufficient if the inline
  // value was left as "none", so this must run before every renderPreview().
  previewElement.style.display = 'block'
}

function decoratePreviewImages(previewEl: HTMLElement | null) {
  if (!previewEl) {
    return
  }
  const context = getImageUrlContext()
  if (!context.currentFilePath || !context.userId) {
    return
  }
  decorateRenderedMarkdownImages(previewEl, context)
  previewEl.querySelectorAll<HTMLImageElement>('img.markdown-image').forEach((image) => {
    const parent = image.parentElement
    const isStandalone = parent?.classList.contains('vditor-reset')
      || parent?.classList.contains('markdown-image-block')
    image.classList.toggle('markdown-html-image-block', Boolean(isStandalone))
  })
}

/** Turns rendered iframe embeds into constrained, lazy video blocks. */
function decoratePreviewVideoBlocks(previewEl: HTMLElement | null) {
  if (!previewEl) return
  const context = getImageUrlContext()
  previewEl.querySelectorAll<HTMLIFrameElement>('iframe[src]').forEach((iframe) => {
    const src = iframe.getAttribute('src') ?? ''
    if (src && context.currentFilePath && context.userId) {
      iframe.src = buildRawFileUrl(src, context)
    }
    iframe.classList.add('markdown-video-block')
    iframe.setAttribute('loading', 'lazy')
    iframe.setAttribute('allowfullscreen', '')
    iframe.setAttribute('allow', 'autoplay; fullscreen; picture-in-picture')
    if (!iframe.title) iframe.title = '视频预览'
  })
}

/** Decorates the final preview HTML before Vditor writes it into the preview pane. */
function transformPreviewHtml(html: string): string {
  const root = document.createElement('div')
  root.innerHTML = html
  decoratePreviewImages(root)
  decoratePreviewVideoBlocks(root)
  return root.innerHTML
}

/** Adds per-image download controls only for callers that explicitly request them. */
function injectImageDownloadButtons(previewEl: HTMLElement | null) {
  if (!props.imageDownload || !previewEl) return
  previewEl.querySelectorAll<HTMLImageElement>('img.markdown-image').forEach((image) => {
    if (image.parentElement?.classList.contains('markdown-image-download-wrap')) return
    const wrapper = document.createElement('span')
    wrapper.className = 'markdown-image-download-wrap'
    image.parentNode?.insertBefore(wrapper, image)
    wrapper.appendChild(image)
    const button = document.createElement('button')
    button.className = 'markdown-image-download-button'
    button.type = 'button'
    button.title = '下载图片'
    button.textContent = '↓'
    button.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      emit('downloadImage', image.currentSrc || image.src, image.alt || 'image')
    })
    wrapper.appendChild(button)
  })
}

function getAnchorHash(link: HTMLAnchorElement) {
  const href = link.getAttribute('href') || ''
  if (href.startsWith('#')) {
    return href
  }
  try {
    const url = new URL(href, window.location.href)
    if (!url.hash) {
      return ''
    }
    const currentWithoutHash = `${window.location.origin}${window.location.pathname}${window.location.search}`
    const targetWithoutHash = `${url.origin}${url.pathname}${url.search}`
    return targetWithoutHash === currentWithoutHash ? url.hash : ''
  } catch {
    return ''
  }
}

function findAnchorTarget(root: HTMLElement, hash: string) {
  const decoded = decodeUrlPath(hash.slice(1))
  if (!decoded) {
    return null
  }
  const escaped = CSS.escape(decoded)
  const rawEscaped = CSS.escape(hash.slice(1))
  const byIdOrName = (
    root.querySelector<HTMLElement>(`#${escaped}`)
    ?? root.querySelector<HTMLElement>(`[name="${escaped}"]`)
    ?? root.querySelector<HTMLElement>(`#${rawEscaped}`)
    ?? root.querySelector<HTMLElement>(`[name="${rawEscaped}"]`)
  )
  if (byIdOrName) {
    return byIdOrName
  }
  const normalizedTargetText = decoded.replace(/[-_\s]+/g, '').toLowerCase()
  const headings = root.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')
  return [...headings].find((heading) => {
    const headingText = (heading.textContent ?? '').trim()
    return headingText === decoded
      || headingText.replace(/[-_\s]+/g, '').toLowerCase() === normalizedTargetText
  }) ?? null
}

function getPreviewScrollContainer(target: HTMLElement) {
  const previewEl = getPreviewElement()
  if (previewEl?.contains(target)) {
    return previewEl
  }
  const resetEl = previewHost.value?.querySelector<HTMLElement>('.vditor-reset')
  if (resetEl?.contains(target)) {
    return resetEl
  }
  return null
}

function tableFromPointerTarget(target: Element | null) {
  const table = target?.closest<HTMLTableElement>('table')
  const previewElement = getPreviewElement()
  if (!table || !previewElement?.contains(table)) {
    return null
  }
  const tables = [...previewElement.querySelectorAll<HTMLTableElement>(EDITABLE_PREVIEW_TABLE_SELECTOR)]
  const tableIndex = tables.indexOf(table)
  if (tableIndex < 0) {
    return null
  }
  return { table, tableIndex }
}

function rectContainsPoint(rect: DOMRect, clientX: number, clientY: number, padding = 0): boolean {
  return clientX >= rect.left - padding
    && clientX <= rect.right + padding
    && clientY >= rect.top - padding
    && clientY <= rect.bottom + padding
}

function tableFromPointerEvent(event: MouseEvent) {
  const eventTarget = event.target instanceof Element ? event.target : null
  const targetHit = tableFromPointerTarget(eventTarget)
  if (targetHit) {
    return targetHit
  }
  const previewElement = getPreviewElement()
  if (!previewElement) {
    return null
  }
  const tables = [...previewElement.querySelectorAll<HTMLTableElement>(EDITABLE_PREVIEW_TABLE_SELECTOR)]
  const table = tables.find((candidate) => (
    rectContainsPoint(tableContentRect(candidate), event.clientX, event.clientY, TABLE_EDGE_BUTTON_SIZE)
    || rectContainsPoint(candidate.getBoundingClientRect(), event.clientX, event.clientY, TABLE_EDGE_BUTTON_SIZE)
  ))
  if (!table) {
    return null
  }
  return { table, tableIndex: tables.indexOf(table) }
}

function tableCellFromPointer(table: HTMLTableElement, event: MouseEvent) {
  const cells = [...table.querySelectorAll<HTMLTableCellElement>('th,td')]
  return cells.find((cell) => {
    const rect = cell.getBoundingClientRect()
    return event.clientX >= rect.left
      && event.clientX <= rect.right
      && event.clientY >= rect.top
      && event.clientY <= rect.bottom
  }) ?? null
}

function tableRowIndex(table: HTMLTableElement, cell: HTMLTableCellElement | null): number {
  const row = cell?.parentElement instanceof HTMLTableRowElement ? cell.parentElement : null
  return row ? [...table.rows].indexOf(row) : 0
}

function tableColumnIndex(cell: HTMLTableCellElement | null): number {
  if (!cell?.parentElement) return 0
  return [...cell.parentElement.children].indexOf(cell)
}

function tableRowIndexFromPointer(table: HTMLTableElement, event: MouseEvent, fallbackCell: HTMLTableCellElement | null): number {
  const tableRect = tableContentRect(table)
  if (event.clientY < tableRect.top) return 0
  if (event.clientY > tableRect.bottom) return Math.max(0, table.rows.length - 1)
  const rowIndex = [...table.rows].findIndex((row) => {
    const rect = tableRowContentRect(row, tableRect)
    return event.clientY >= rect.top && event.clientY <= rect.bottom
  })
  return rowIndex >= 0 ? rowIndex : tableRowIndex(table, fallbackCell)
}

function tableColumnIndexFromPointer(table: HTMLTableElement, event: MouseEvent, fallbackCell: HTMLTableCellElement | null): number {
  const tableRect = tableContentRect(table)
  const firstRow = table.rows[0]
  const fallbackColumn = tableColumnIndex(fallbackCell)
  if (!firstRow) return fallbackColumn
  if (event.clientX < tableRect.left) return 0
  if (event.clientX > tableRect.right) return Math.max(0, firstRow.cells.length - 1)
  const columnIndex = [...firstRow.cells].findIndex((_, index) => {
    const rect = tableColumnContentRect(table, index, tableRect)
    return event.clientX >= rect.left && event.clientX <= rect.right
  })
  return columnIndex >= 0 ? columnIndex : fallbackColumn
}

function unionRects(rects: DOMRect[]): DOMRect | null {
  if (!rects.length) return null
  const left = Math.min(...rects.map((rect) => rect.left))
  const top = Math.min(...rects.map((rect) => rect.top))
  const right = Math.max(...rects.map((rect) => rect.right))
  const bottom = Math.max(...rects.map((rect) => rect.bottom))
  return DOMRect.fromRect({ x: left, y: top, width: right - left, height: bottom - top })
}

function renderedCellRects(cells: Iterable<HTMLTableCellElement>): DOMRect[] {
  return [...cells]
    .map((cell) => cell.getBoundingClientRect())
    .filter((rect) => rect.width > 0 && rect.height > 0)
}

function tableContentRect(table: HTMLTableElement): DOMRect {
  return unionRects(renderedCellRects(table.querySelectorAll<HTMLTableCellElement>('th,td')))
    ?? table.getBoundingClientRect()
}

function tableRowContentRect(row: HTMLTableRowElement | undefined, fallback: DOMRect): DOMRect {
  return row ? (unionRects(renderedCellRects(row.querySelectorAll<HTMLTableCellElement>('th,td'))) ?? fallback) : fallback
}

function tableColumnContentRect(table: HTMLTableElement, columnIndex: number, fallback: DOMRect): DOMRect {
  const columnCells = [...table.rows]
    .map((row) => row.cells[columnIndex])
    .filter((cell): cell is HTMLTableCellElement => cell instanceof HTMLTableCellElement)
  return unionRects(renderedCellRects(columnCells)) ?? fallback
}

function updateTableOverlayFromEvent(event: MouseEvent) {
  if (previewTableDrag) {
    return
  }
  const eventTarget = event.target instanceof Element ? event.target : null
  if (eventTarget && tableOverlayElement.value?.contains(eventTarget)) {
    return
  }
  const tableHit = tableFromPointerEvent(event)
  if (!tableHit) {
    tableOverlay.value.visible = false
    return
  }
  const cell = tableCellFromPointer(tableHit.table, event)
  const rowIndex = Math.max(0, tableRowIndexFromPointer(tableHit.table, event, cell))
  const columnIndex = Math.max(0, tableColumnIndexFromPointer(tableHit.table, event, cell))
  const hostRect = previewHost.value?.getBoundingClientRect()
  if (!hostRect) {
    tableOverlay.value.visible = false
    return
  }
  const tableRect = tableContentRect(tableHit.table)
  const tableElementRect = tableHit.table.getBoundingClientRect()
  const tableBottomGutter = Math.max(0, tableElementRect.bottom - tableRect.bottom)
  const withinHorizontalEdgeBand = event.clientX >= tableRect.left - TABLE_EDGE_BUTTON_SIZE
    && event.clientX <= tableRect.right + TABLE_EDGE_BUTTON_SIZE
  const withinVerticalEdgeBand = event.clientY >= tableRect.top - TABLE_EDGE_BUTTON_SIZE
    && event.clientY <= tableRect.bottom + TABLE_EDGE_BUTTON_SIZE
  const showLeftEdge = withinVerticalEdgeBand
    && event.clientX >= tableRect.left - TABLE_EDGE_BUTTON_SIZE
    && event.clientX <= tableRect.left + TABLE_EDGE_HIT_ZONE
  const showTopEdge = withinHorizontalEdgeBand
    && event.clientY >= tableRect.top - TABLE_EDGE_BUTTON_SIZE
    && event.clientY <= tableRect.top + TABLE_EDGE_HIT_ZONE
  const showRightEdge = withinVerticalEdgeBand
    && event.clientX >= tableRect.right - TABLE_EDGE_HIT_ZONE
    && event.clientX <= tableRect.right + TABLE_EDGE_BUTTON_SIZE
  const showBottomEdge = withinHorizontalEdgeBand
    && event.clientY >= tableRect.bottom - TABLE_EDGE_HIT_ZONE
    && event.clientY <= tableElementRect.bottom + TABLE_EDGE_BUTTON_SIZE
  if (!showLeftEdge && !showTopEdge && !showRightEdge && !showBottomEdge) {
    tableOverlay.value.visible = false
    return
  }
  const rowRect = tableRowContentRect(tableHit.table.rows[rowIndex], tableRect)
  const columnRect = tableColumnContentRect(tableHit.table, columnIndex, cell?.getBoundingClientRect() ?? tableRect)
  tableOverlay.value = {
    visible: true,
    showLeftEdge,
    showTopEdge,
    showRightEdge,
    showBottomEdge,
    addRowButtonBottom: -(tableBottomGutter + TABLE_EDGE_BUTTON_SIZE),
    left: tableRect.left - hostRect.left,
    top: tableRect.top - hostRect.top,
    width: tableRect.width,
    height: tableRect.height,
    rowTop: rowRect.top - hostRect.top,
    rowHeight: rowRect.height,
    columnLeft: columnRect.left - hostRect.left,
    columnWidth: columnRect.width,
    tableIndex: tableHit.tableIndex,
    rowIndex,
    columnIndex,
  }
}

function addPreviewTableRow() {
  const overlay = tableOverlay.value
  insertSourceTableRow(overlay.tableIndex, renderedRowToSourceRow(overlay.tableIndex, overlay.rowIndex), 'below')
}

function addPreviewTableColumn() {
  const overlay = tableOverlay.value
  insertSourceTableColumn(overlay.tableIndex, overlay.columnIndex, 'right')
}

function beginPreviewTableDrag(type: 'row' | 'column', event: PointerEvent) {
  if (!tableOverlay.value.visible) return
  event.preventDefault()
  previewTableDrag = {
    type,
    tableIndex: tableOverlay.value.tableIndex,
    source: type === 'row' ? tableOverlay.value.rowIndex : tableOverlay.value.columnIndex,
  }
  document.addEventListener('pointerup', finishPreviewTableDrag)
}

function finishPreviewTableDrag(event: PointerEvent) {
  document.removeEventListener('pointerup', finishPreviewTableDrag)
  const drag = previewTableDrag
  previewTableDrag = null
  if (!drag) return
  const eventTarget = event.target instanceof Element ? event.target : null
  const tableHit = tableFromPointerTarget(eventTarget)
  if (!tableHit || tableHit.tableIndex !== drag.tableIndex) {
    return
  }
  const cell = tableCellFromPointer(tableHit.table, event)
  if (drag.type === 'row') {
    moveSourceTableRow(
      drag.tableIndex,
      renderedRowToSourceRow(drag.tableIndex, drag.source),
      renderedRowToSourceRow(drag.tableIndex, Math.max(0, tableRowIndex(tableHit.table, cell))),
    )
  } else {
    moveSourceTableColumn(drag.tableIndex, drag.source, Math.max(0, tableColumnIndex(cell)))
  }
}

function getPreviewScrollRatio() {
  const previewElement = getPreviewElement()
  if (!previewElement) return 0
  const maxScrollTop = Math.max(0, previewElement.scrollHeight - previewElement.clientHeight)
  return maxScrollTop > 0 ? previewElement.scrollTop / maxScrollTop : 0
}

/** Resolves the rendered heading nearest the top of the preview viewport. */
function getActivePreviewHeadingIndex() {
  const previewElement = getPreviewElement()
  if (!previewElement) return -1
  const headings = [...previewElement.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')]
  if (headings.length === 0) return -1
  const top = previewElement.getBoundingClientRect().top + 20
  let activeIndex = 0
  headings.forEach((heading, index) => {
    if (heading.getBoundingClientRect().top <= top) activeIndex = index
  })
  return activeIndex
}

function handlePreviewScroll() {
  tableOverlay.value.visible = false
  emit('activeHeading', getActivePreviewHeadingIndex())
  if (!programmaticScroll) {
    emit('scroll', getPreviewScrollRatio())
  }
}

/** Scrolls the rendered Markdown pane without sending a feedback event. */
function scrollToRatio(ratio: number, behavior: ScrollBehavior = 'auto') {
  const previewElement = getPreviewElement()
  if (!previewElement) return
  const maxScrollTop = Math.max(0, previewElement.scrollHeight - previewElement.clientHeight)
  programmaticScroll = true
  const top = Math.max(0, Math.min(1, ratio)) * maxScrollTop
  if (behavior === 'smooth') {
    previewElement.scrollTo({ top, behavior })
    if (programmaticScrollTimer !== null) {
      clearTimeout(programmaticScrollTimer)
    }
    programmaticScrollTimer = setTimeout(() => {
      programmaticScroll = false
      programmaticScrollTimer = null
    }, 800)
    return
  }
  previewElement.scrollTop = top
  requestAnimationFrame(() => { programmaticScroll = false })
}

/** Anchors the rendered source block at the same visual height as the editor caret. */
function scrollToSourceOffset(
  offset: number,
  contentLength: number,
  behavior: ScrollBehavior = 'auto',
  viewportRatio = 0.16,
) {
  const previewElement = getPreviewElement()
  const resetElement = previewElement?.querySelector<HTMLElement>('.vditor-reset')
  const blocks = resetElement
    ? [...resetElement.children].filter((child): child is HTMLElement => child instanceof HTMLElement)
    : []
  if (!previewElement || blocks.length === 0) {
    scrollToRatio(contentLength > 0 ? offset / contentLength : 0, behavior)
    return
  }
  const sourceLineCount = Math.max(1, props.content.split('\n').length)
  const boundedOffset = Math.max(0, Math.min(offset, props.content.length))
  const sourceLine = props.content.slice(0, boundedOffset).split('\n').length - 1
  const blockIndex = Math.round((sourceLine / Math.max(1, sourceLineCount - 1)) * (blocks.length - 1))
  const target = blocks[Math.max(0, Math.min(blockIndex, blocks.length - 1))]
  if (!target) return
  const previewRect = previewElement.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const anchorRatio = Math.max(0.05, Math.min(0.95, viewportRatio))
  const top = Math.max(0, previewElement.scrollTop + targetRect.top - previewRect.top - previewElement.clientHeight * anchorRatio)
  programmaticScroll = true
  if (behavior === 'smooth') {
    previewElement.scrollTo({ top, behavior })
    if (programmaticScrollTimer !== null) clearTimeout(programmaticScrollTimer)
    programmaticScrollTimer = setTimeout(() => {
      programmaticScroll = false
      programmaticScrollTimer = null
    }, 800)
    return
  }
  previewElement.scrollTop = top
  requestAnimationFrame(() => { programmaticScroll = false })
}

/** Scrolls to an actual rendered heading rather than estimating by source ratio. */
function flushPendingHeadingScroll() {
  if (pendingHeadingIndex === null) return
  const previewElement = getPreviewElement()
  const target = previewElement?.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')[pendingHeadingIndex]
  if (!target) return
  const index = pendingHeadingIndex
  pendingHeadingIndex = null
  scrollToPreviewElement(target)
  emit('activeHeading', index)
}

/** Queues one heading navigation if Vditor has not rendered its heading DOM yet. */
function scrollToHeading(index: number) {
  pendingHeadingIndex = index
  flushPendingHeadingScroll()
}

defineExpose({ scrollToRatio, scrollToSourceOffset, scrollToHeading })

function injectCodeCopyButtons() {
  const root = getPreviewElement()
  if (!root) return
  root.querySelectorAll('pre').forEach((pre) => {
    if ((pre as HTMLElement).querySelector('.code-copy-btn')) return
    const btn = document.createElement('button')
    btn.className = 'code-copy-btn'
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
    btn.title = '复制代码'
    btn.addEventListener('click', () => {
      const code = pre.querySelector('code')
      const text = code?.textContent ?? ''
      navigator.clipboard.writeText(text).then(() => {
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
        setTimeout(() => { btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' }, 1500)
      })
    })
    ;(pre as HTMLElement).style.position = 'relative'
    pre.appendChild(btn)
  })
}

function highlightVueCodeBlocks(root: HTMLElement | null) {
  if (!root) return
  root.querySelectorAll<HTMLElement>('pre code[class*="language-vue"]').forEach((code) => {
    // Vditor 内置 hljs 不注册 vue 语言,未知围栏会回退为纯文本;
    // 此处用 xml 语法补齐,仅在尚未产生高亮 span 时执行,避免破坏已高亮的块。
    if (code.querySelector('.hljs-keyword, .hljs-string, .hljs-tag, .hljs-attr')) return
    const raw = code.textContent ?? ''
    code.innerHTML = hljs.highlight(raw, { language: 'xml' }).value
    code.classList.add('hljs')
  })
}

// Vditor 的 Preview.render 在 setTimeout(preview.delay) 里才写入 innerHTML,renderPreview()
// 之后同步执行的一切都会被随后写入的 HTML 覆盖。preview.parse 在每次渲染完成、innerHTML
// 写入之后同步回调,是"渲染后处理"的可靠时机,数学占位符还原等必须放这里。
function handlePreviewParse(element: HTMLElement) {
  // element 是 vditor.preview.element(.vditor-preview)。数学占位符写入在 .vditor-reset
  // (previewElement)里,必须把 .vditor-reset 而非 .vditor-preview 交给 renderMathInPreviewDom:
  // 它在字符串层用 root.innerHTML 还原占位符,若 root 是整个 .vditor-preview 会把
  // .vditor-reset 元素自身重建,导致 Vditor 的 previewElement 引用指向已销毁的节点,
  // 后续 renderPreview 全部写进离线节点,预览从此冻结不再更新。
  const resetEl = element.querySelector<HTMLElement>('.vditor-reset') ?? element
  renderMathInPreviewDom(resetEl, displayBlocks, inlineBlocks)
  decoratePreviewImages(element)
  decoratePreviewVideoBlocks(element)
  injectImageDownloadButtons(element)
  highlightVueCodeBlocks(element)
  decorateOcrBlocks(resetEl)
  injectCodeCopyButtons()
  tableOverlay.value.visible = false
  flushPendingHeadingScroll()
  emit('ready')
  void decorateWikiPreview(resetEl, {
    tree: workspaceStore.tree,
    currentPath: props.path ?? workspaceStore.selectedPath,
    userId: settingsStore.profile.userId,
    cache: wikiEmbedCache,
  }).then(() => focusWikiAnchor())
}

/** Attach persisted OCR block ids to the nearest rendered semantic elements. */
function decorateOcrBlocks(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>('[data-ocr-block-id]').forEach((element) => {
    delete element.dataset.ocrBlockId
    element.classList.remove('ocr-semantic-block', 'active', 'locked')
  })
  const candidates = [...root.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6,p,table,pre,blockquote,li')]
  const used = new Set<HTMLElement>()
  const normalize = (value: string) => {
    const holder = document.createElement('div')
    holder.innerHTML = value
    return (holder.textContent ?? value).replace(/\s+/gu, '').replace(/[$\\{}]/gu, '').toLowerCase()
  }
  for (const block of [...(props.blocks ?? [])].sort((a, b) => a.order - b.order)) {
    const source = normalize(block.content)
    const target = candidates.find((element) => {
      if (used.has(element)) return false
      const rendered = normalize(element.textContent ?? '')
      const sample = source.slice(0, 24)
      return Boolean(sample && rendered && (rendered.includes(sample) || source.includes(rendered)))
    })
    if (!target) continue
    used.add(target)
    target.dataset.ocrBlockId = `${block.page}:${block.id ?? block.order}`
    target.classList.add('ocr-semantic-block')
  }
  applyOcrBlockState()
}

/** Reflect the shared hover/locked id after either preview changes it. */
function applyOcrBlockState() {
  const root = getPreviewElement()
  if (!root) return
  root.querySelectorAll<HTMLElement>('[data-ocr-block-id]').forEach((element) => {
    element.classList.toggle('active', element.dataset.ocrBlockId === props.activeBlockId)
    element.classList.toggle('locked', element.dataset.ocrBlockId === props.lockedBlockId)
  })
}

function handleOcrBlockMove(event: PointerEvent) {
  const target = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-ocr-block-id]') : null
  if (target?.dataset.ocrBlockId) emit('blockHover', target.dataset.ocrBlockId)
  else emit('blockLeave')
}

function scrollToPreviewElement(target: HTMLElement) {
  const previewEl = getPreviewScrollContainer(target)
  if (previewEl) {
    const previewRect = previewEl.getBoundingClientRect()
    const targetRect = target.getBoundingClientRect()
    const top = previewEl.scrollTop + targetRect.top - previewRect.top - 12
    previewEl.scrollTo({ top, behavior: 'smooth' })
    return
  }
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function focusWikiAnchor() {
  const request = props.focusAnchor
  if (!request || request.nonce === lastWikiFocusNonce || request.path !== props.path) return
  const root = getPreviewElement()
  if (!root) return
  let target: HTMLElement | null = null
  if (request.heading) {
    const normalizedHeading = normalizeWikiAnchor(request.heading)
    target = [...root.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')]
      .find((heading) => normalizeWikiAnchor(heading.textContent ?? '') === normalizedHeading) ?? null
  } else if (request.blockId) {
    const marker = `^${request.blockId}`
    target = [...root.querySelectorAll<HTMLElement>('p, li, blockquote, pre, table')]
      .find((element) => (element.textContent ?? '').includes(marker)) ?? null
  }
  if (!target) return
  lastWikiFocusNonce = request.nonce
  if (wikiHighlightTimer !== null) clearTimeout(wikiHighlightTimer)
  root.querySelector('.wiki-anchor-highlight')?.classList.remove('wiki-anchor-highlight')
  target.classList.add('wiki-anchor-highlight')
  scrollToPreviewElement(target)
  wikiHighlightTimer = setTimeout(() => {
    target?.classList.remove('wiki-anchor-highlight')
    wikiHighlightTimer = null
  }, 2200)
}

function syncPreviewContent() {
  if (!instance) {
    return
  }
  try {
    // 数学公式先提取为占位符再交给 Vditor:块级 $$...$$ 会被 lute 撕裂,行内 $...$
    // 里的反斜杠/下划线也可能先被 Markdown 解析消费,统一占位后在 parse 钩子还原。
    const markdown = preparePreviewMarkdown(props.content)
    if (instance.getValue() !== markdown) {
      instance.setValue(markdown, true)
    }
    ensurePreviewPaneIsRenderable()
    instance.renderPreview()
    emit('activeHeading', getActivePreviewHeadingIndex())
    flushPendingHeadingScroll()
  } catch (err) {
    console.warn('[MarkdownPreview] syncPreviewContent failed:', err)
  }
}

function waitForAnimationFrame() {
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => resolve())
  })
}

async function queuePreviewRender() {
  const version = ++renderVersion
  await nextTick()
  await waitForAnimationFrame()
  if (!mounted || version !== renderVersion) {
    return
  }
  syncPreviewContent()
}

function syncPreviewContentImmediately() {
  renderVersion += 1
  if (!mounted) {
    return
  }
  syncPreviewContent()
}

function handleClick(event: MouseEvent) {
  const eventTarget = event.target instanceof Element ? event.target : null
  const ocrBlock = eventTarget?.closest<HTMLElement>('[data-ocr-block-id]')
  if (ocrBlock?.dataset.ocrBlockId) emit('blockSelect', ocrBlock.dataset.ocrBlockId)

  const wikiLink = eventTarget?.closest<HTMLAnchorElement>('a[data-wiki-destination]')
  if (wikiLink) {
    event.preventDefault()
    event.stopPropagation()
    emit('navigateWiki', wikiLink.dataset.wikiDestination ?? '')
    return
  }

  // image preview — stopPropagation prevents Vditor's native lightbox
  const img = eventTarget?.closest<HTMLImageElement>('img[src]')
  if (img && img.src) {
    event.stopPropagation()
    const root = previewHost.value
    if (root) {
      const allImgs = root.querySelectorAll<HTMLImageElement>('img[src]')
      const items: ImagePreviewItem[] = []
      let clickIndex = -1
      allImgs.forEach((el, i) => {
        if (el === img) clickIndex = i
        items.push({ src: el.src, alt: el.alt || undefined })
      })
      if (clickIndex >= 0) {
        imagePreviewer.open(items, clickIndex)
      }
    }
    event.preventDefault()
    return
  }

  const link = eventTarget?.closest<HTMLAnchorElement>('a[href]')
  if (!link) {
    return
  }
  const hash = getAnchorHash(link)
  if (!hash || hash === '#') {
    return
  }
  event.preventDefault()
  event.stopPropagation()
  const root = previewHost.value
  if (!root) {
    return
  }
  const target = findAnchorTarget(root, hash)
  if (!target) {
    return
  }
  scrollToPreviewElement(target)
}

function handleKnowledgeFileChange() {
  wikiEmbedCache.clear()
}

onMounted(() => {
  if (!previewHost.value) {
    return
  }
  previewHost.value.addEventListener('click', handleClick, { capture: true })
  window.addEventListener('metaweave-knowledge-file-change', handleKnowledgeFileChange)
  try {
    instance = new Vditor(previewHost.value, {
      i18n: embeddedVditorI18n,
      _lutePath: lutePath,
      icon: '',
      value: preparePreviewMarkdown(props.content),
      height: '100%',
      mode: 'sv',
      cache: { enable: false },
      preview: {
        delay: 0,
        mode: 'both',
        actions: [],
        markdown: {
          codeBlockPreview: true,
          mathBlockPreview: true,
        },
        render: {
          media: { enable: true },
        },
        transform: transformPreviewHtml,
        parse: handlePreviewParse,
      },
      after() {
        mounted = true
        getPreviewElement()?.addEventListener('scroll', handlePreviewScroll, { passive: true })
        try { instance?.disabledCache() } catch { /* best-effort */ }
        try { instance?.clearCache() } catch { /* best-effort */ }
        void queuePreviewRender()
      },
    })
  } catch (err) {
    console.warn('[MarkdownPreview] Vditor init failed:', err)
  }
})

onUnmounted(() => {
  previewHost.value?.removeEventListener('click', handleClick, { capture: true })
  window.removeEventListener('metaweave-knowledge-file-change', handleKnowledgeFileChange)
})

watch(
  () => [props.content, props.path],
  () => {
    // Split 模式输入时必须让右侧预览在同一个响应式 tick 里发起渲染。
    // 这里不能再排队到 nextTick/requestAnimationFrame,否则用户会看到明显慢一拍。
    syncPreviewContentImmediately()
  },
)

watch(() => props.focusAnchor?.nonce, () => void nextTick(focusWikiAnchor))
watch(() => [props.activeBlockId, props.lockedBlockId], () => {
  applyOcrBlockState()
  if (!props.lockedBlockId) return
  const target = getPreviewElement()?.querySelector<HTMLElement>(`[data-ocr-block-id="${CSS.escape(props.lockedBlockId)}"]`)
  if (target) scrollToPreviewElement(target)
})

onBeforeUnmount(() => {
  mounted = false
  document.removeEventListener('pointerup', finishPreviewTableDrag)
  if (programmaticScrollTimer !== null) {
    clearTimeout(programmaticScrollTimer)
    programmaticScrollTimer = null
  }
  if (wikiHighlightTimer !== null) {
    clearTimeout(wikiHighlightTimer)
    wikiHighlightTimer = null
  }
  getPreviewElement()?.removeEventListener('scroll', handlePreviewScroll)
  try {
    instance?.destroy()
  } catch (err) {
    console.warn('[MarkdownPreview] destroy failed:', err)
  }
  instance = null
})
</script>

<template>
  <article
    class="markdown-preview"
    :class="{ compact: props.compact }"
    @mousemove="updateTableOverlayFromEvent"
    @pointermove="handleOcrBlockMove"
    @mouseleave="tableOverlay.visible = false; emit('blockLeave')"
  >
    <div
      ref="previewHost"
      class="markdown-preview-renderer"
    ></div>
    <div
      ref="tableOverlayElement"
      v-if="tableOverlay.visible"
      class="markdown-preview-table-overlay"
      :style="{
        left: `${tableOverlay.left}px`,
        top: `${tableOverlay.top}px`,
        width: `${tableOverlay.width}px`,
        height: `${tableOverlay.height}px`,
      }"
    >
      <button
        v-if="tableOverlay.showLeftEdge"
        class="preview-table-row-drag-handle"
        type="button"
        title="拖动表格行"
        :style="{ top: `${tableOverlay.rowTop - tableOverlay.top}px`, height: `${tableOverlay.rowHeight}px` }"
        @pointerdown="beginPreviewTableDrag('row', $event)"
      >
        <IcIcon name="unfold" :size="10" />
      </button>
      <button
        v-if="tableOverlay.showTopEdge"
        class="preview-table-column-drag-handle"
        type="button"
        title="拖动表格列"
        :style="{ left: `${tableOverlay.columnLeft - tableOverlay.left}px`, width: `${tableOverlay.columnWidth}px` }"
        @pointerdown="beginPreviewTableDrag('column', $event)"
      >
        <IcIcon name="unfold" :size="10" />
      </button>
      <button
        v-if="tableOverlay.showBottomEdge"
        class="preview-table-add-row-button"
        :style="{ bottom: `${tableOverlay.addRowButtonBottom}px` }"
        type="button"
        title="添加空行"
        @click="addPreviewTableRow"
      >
        <IcIcon name="add" :size="10" />
      </button>
      <button
        v-if="tableOverlay.showRightEdge"
        class="preview-table-add-column-button"
        type="button"
        title="添加空列"
        @click="addPreviewTableColumn"
      >
        <IcIcon name="add" :size="10" />
      </button>
    </div>
  </article>
</template>

<style scoped>
.markdown-preview {
  display: flex;
  position: relative;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: var(--color-surface-raised);
  color: var(--color-text-secondary);
}

.markdown-preview-renderer {
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.markdown-preview-table-overlay {
  position: absolute;
  z-index: 4;
  pointer-events: none;
}

.markdown-preview-table-overlay button {
  position: absolute;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 0;
  background: var(--color-surface-raised);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-border) 34%, transparent);
  color: var(--color-text-tertiary);
  pointer-events: auto;
  cursor: pointer;
}

.markdown-preview-table-overlay button:hover {
  border-color: color-mix(in srgb, var(--color-text-tertiary) 45%, var(--color-border));
  background: var(--color-surface);
  color: var(--color-text-secondary);
}

.markdown-preview-table-overlay button :deep(svg) {
  display: block;
  opacity: 0.72;
}

.preview-table-row-drag-handle {
  left: -9px;
  width: 9px;
  cursor: grab;
}

.preview-table-column-drag-handle {
  top: -9px;
  height: 9px;
  cursor: grab;
}

.preview-table-column-drag-handle :deep(svg) {
  transform: rotate(90deg);
}

.preview-table-row-drag-handle:active,
.preview-table-column-drag-handle:active {
  cursor: grabbing;
}

.preview-table-add-row-button {
  left: 0;
  right: 0;
  bottom: -9px;
  height: 9px;
}

.preview-table-add-column-button {
  top: 0;
  right: -9px;
  bottom: 0;
  width: 9px;
}

.markdown-preview :deep(.vditor) {
  width: 100%;
  height: 100% !important;
  border: 0 !important;
  background: transparent !important;
}

/* Keep these hides scoped to MarkdownPreview. Do not globally hide
   .vditor-preview or Split/Preview rendering will regress. */
.markdown-preview :deep(.vditor-toolbar),
.markdown-preview :deep(.vditor-sv),
.markdown-preview :deep(.vditor-ir),
.markdown-preview :deep(.vditor-wysiwyg) {
  display: none !important;
}

.markdown-preview :deep(.vditor-content) {
  display: block !important;
  width: 100% !important;
  height: 100% !important;
}

.markdown-preview :deep(.vditor-preview) {
  display: block !important;
  width: 100% !important;
  height: 100% !important;
  overflow: auto;
  background: transparent !important;
}

.markdown-preview :deep(.vditor-preview > .vditor-reset) {
  max-width: none !important;
  min-height: 100%;
  margin: 0 !important;
  padding: var(--space-20) !important;
  color: var(--color-text-secondary) !important;
  font-family: var(--font-text) !important;
  font-size: calc(14px * var(--text-font-scale)) !important;
}

.markdown-preview :deep(.vditor-reset li)::marker {
  color: var(--color-primary);
}

.markdown-preview :deep(mark) {
  padding: 0 0.12em;
  border-radius: 2px;
  background: color-mix(in srgb, #ffd84d 48%, transparent);
  color: inherit;
}

.markdown-preview :deep(.wiki-link) {
  color: var(--color-primary) !important;
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
  text-underline-offset: 3px;
  cursor: pointer;
}

.markdown-preview :deep(.wiki-link-unresolved) {
  color: var(--color-text-muted) !important;
  text-decoration-style: dashed;
}

.markdown-preview :deep(.wiki-embed) {
  position: relative;
  display: block;
  min-width: 0;
  margin: var(--space-12) 0;
  padding: var(--space-4) var(--space-24) var(--space-4) var(--space-16);
  border-left: 2px solid var(--color-primary);
}

.markdown-preview :deep(.wiki-embed-open) {
  position: absolute;
  top: 2px;
  right: 4px;
  color: var(--color-text-muted) !important;
  font-size: 15px;
  line-height: 1;
  text-decoration: none;
}

.markdown-preview :deep(.wiki-embed-open:hover) {
  color: var(--color-primary) !important;
}

.markdown-preview :deep(.wiki-embed-content > :first-child) { margin-top: 0; }
.markdown-preview :deep(.wiki-embed-content > :last-child) { margin-bottom: 0; }

.markdown-preview :deep(.wiki-embed-image) {
  display: block;
  max-width: 100%;
  height: auto;
}

.markdown-preview :deep(.wiki-embed-unresolved),
.markdown-preview :deep(.wiki-embed-unsupported),
.markdown-preview :deep(.wiki-embed-limit) {
  color: var(--color-text-muted);
}

.markdown-preview :deep(.wiki-anchor-highlight) {
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-primary) 20%, transparent) !important;
  box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-primary) 10%, transparent);
  transition: background 180ms ease, box-shadow 180ms ease;
}

.markdown-preview :deep(.ocr-semantic-block) { outline: 1px solid color-mix(in srgb,var(--color-primary) 45%,transparent); outline-offset: 3px; transition: outline-color 120ms ease, background 120ms ease; }
.markdown-preview :deep(.ocr-semantic-block.active),.markdown-preview :deep(.ocr-semantic-block.locked) { outline: 2px solid var(--color-primary); background: color-mix(in srgb,var(--color-primary) 10%,transparent); }
.markdown-preview :deep(.ocr-semantic-block.locked) { outline-style: dashed; }

.markdown-preview :deep(h1) { color: var(--color-primary) !important; font-size: calc(2rem * var(--text-font-scale)) !important; }
.markdown-preview :deep(h2) { color: color-mix(in srgb, var(--color-primary) 86.7%, white) !important; font-size: calc(1.35rem * var(--text-font-scale)) !important; }
.markdown-preview :deep(h3) { color: color-mix(in srgb, var(--color-primary) 73.3%, white) !important; font-size: calc(1.05rem * var(--text-font-scale)) !important; }
.markdown-preview :deep(h4) { color: color-mix(in srgb, var(--color-primary) 60%, white) !important; font-size: calc(0.9rem * var(--text-font-scale)) !important; }
.markdown-preview :deep(h5) { color: color-mix(in srgb, var(--color-primary) 46.7%, white) !important; font-size: calc(0.825rem * var(--text-font-scale)) !important; }
.markdown-preview :deep(h6) { color: color-mix(in srgb, var(--color-primary) 33.3%, white) !important; font-size: calc(0.75rem * var(--text-font-scale)) !important; }

.markdown-preview :deep(pre),
.markdown-preview :deep(code) {
  font-family: var(--font-text) !important;
}

.markdown-preview :deep(code) {
  padding: 1px 8px !important;
  border: 0 !important;
  border-radius: 999px !important;
  background: var(--color-code-bg) !important;
  font-size: 0.85em !important;
}

.markdown-preview :deep(pre) {
  padding: var(--space-12) !important;
  border: 0 !important;
  border-radius: var(--radius-md) !important;
  background: var(--color-code-bg) !important;
  line-height: 1.3 !important;
  position: relative !important;
}

.markdown-preview :deep(pre code) {
  padding: 0 !important;
  border: 0 !important;
  border-radius: 0 !important;
  background: transparent !important;
  font-family: var(--font-text) !important;
  font-size: calc(0.9rem * var(--text-font-scale)) !important;
  line-height: 1.3 !important;
}

/* Vditor 内置注入亮色 GitHub hljs 主题,暗色下代码块文字会变黑字;
   用项目 --hljs-* 变量覆盖,亮/暗随主题自动切换(与 agent 回答配色同源)。 */
.markdown-preview :deep(.vditor-reset pre code.hljs) {
  color: var(--hljs-fg, #e6e6e6) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-keyword),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-selector-tag),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-literal),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-type),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-template-variable),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-variable.language_) {
  color: var(--hljs-keyword, #ff79c6) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-string),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-addition),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-regexp) {
  color: var(--hljs-string, #50fa7b) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-number),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-built_in),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-attr),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-attribute),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-operator),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-variable) {
  color: var(--hljs-type, #8be9fd) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-title),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-title.function_) {
  color: var(--hljs-function, #50fa7b) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-title.class_) {
  color: var(--hljs-class, #f1fa8c) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-comment),
.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-quote) {
  color: var(--hljs-comment, #6272a4) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-strong) {
  color: var(--hljs-fg, #e6e6e6) !important;
  font-weight: normal;
  font-style: normal;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-emphasis) {
  color: var(--hljs-fg, #e6e6e6) !important;
  font-weight: normal;
  font-style: normal;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-section) {
  color: var(--hljs-keyword, #ff79c6) !important;
  font-weight: normal;
  font-style: normal;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-bullet) {
  color: var(--hljs-type, #8be9fd) !important;
}

.markdown-preview :deep(.vditor-reset pre code.hljs .hljs-link) {
  color: var(--hljs-string, #50fa7b) !important;
}

.markdown-preview :deep(a) {
  color: var(--color-primary) !important;
}

.markdown-preview :deep(img.markdown-image) {
  max-width: 100%;
  height: auto;
  vertical-align: middle;
}

.markdown-preview :deep(img.markdown-html-image-block),
.markdown-preview :deep(.vditor-reset > p > img:only-child),
.markdown-preview :deep(.vditor-reset > img) {
  display: block;
  width: auto;
  max-width: 100%;
  max-height: min(72vh, 960px);
  margin: var(--space-16) auto;
  object-fit: contain;
}

.markdown-preview :deep(iframe.markdown-video-block),
.markdown-preview :deep(.vditor-reset iframe) {
  display: block;
  width: min(100%, 960px);
  aspect-ratio: 16 / 9;
  margin: var(--space-16) auto;
  border: 0;
  background: #000;
}

.markdown-preview :deep(p.markdown-image-block) {
  display: flex;
  justify-content: center;
  margin: var(--space-16) 0;
}

.markdown-preview :deep(p.markdown-image-block > img.markdown-image) {
  display: block;
  width: auto;
  max-width: 100%;
  max-height: min(72vh, 960px);
  object-fit: contain;
}

.markdown-preview :deep(.markdown-image-download-wrap) {
  position: relative;
  display: inline-flex;
  max-width: 100%;
}

.markdown-preview :deep(.markdown-image-download-button) {
  position: absolute;
  top: 5px;
  right: 5px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: color-mix(in srgb, var(--color-surface-raised) 88%, transparent);
  color: var(--color-text-secondary);
  cursor: pointer;
  opacity: 0;
  transition: opacity 140ms ease;
}

.markdown-preview :deep(.markdown-image-download-wrap:hover .markdown-image-download-button) {
  opacity: 1;
}

.markdown-preview.compact :deep(.vditor-preview > .vditor-reset) {
  padding: 9px 11px !important;
  font-size: calc(13px * var(--font-scale));
  line-height: 1.35;
}

.markdown-preview.compact :deep(.vditor-reset > :first-child) { margin-top: 0 !important; }
.markdown-preview.compact :deep(.vditor-reset > :last-child) { margin-bottom: 0 !important; }
.markdown-preview.compact :deep(h1) { font-size: calc(1.35rem * var(--font-scale)) !important; }
.markdown-preview.compact :deep(h2) { font-size: calc(1.15rem * var(--font-scale)) !important; }
.markdown-preview.compact :deep(h3),
.markdown-preview.compact :deep(h4),
.markdown-preview.compact :deep(h5),
.markdown-preview.compact :deep(h6) { font-size: calc(1rem * var(--font-scale)) !important; }

.markdown-preview :deep(blockquote) {
  border-left-color: var(--color-primary) !important;
  color: var(--color-text-muted) !important;
}

.markdown-preview :deep(.code-copy-btn) {
  position: absolute !important;
  top: var(--space-6) !important;
  right: var(--space-6) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: 28px !important;
  height: 28px !important;
  padding: 0 !important;
  border: 1px solid var(--color-border) !important;
  border-radius: 50% !important;
  background: transparent !important;
  color: var(--color-text-tertiary) !important;
  cursor: pointer !important;
  opacity: 0 !important;
  transition: opacity 160ms ease, color 160ms ease, border-color 160ms ease !important;
  z-index: 2 !important;
}

.markdown-preview :deep(pre:hover .code-copy-btn) {
  opacity: 1 !important;
}

.markdown-preview :deep(.code-copy-btn:hover) {
  color: var(--color-primary) !important;
  border-color: color-mix(in srgb, var(--color-primary) 32%, var(--color-border)) !important;
}
</style>
