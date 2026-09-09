<!--
  PDF preview mode switcher.

  Usage:
  Preview1 lazily mounts rasterized PDF pages in a continuous light canvas and
  keeps Ctrl+wheel zoom anchored beneath the pointer. Preview2 preserves the
  browser's native PDF iframe as a fallback.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { buildApiUrl } from '@/api/client'
import IcIcon from '@/components/common/IcIcon.vue'
import OcrBlockOverlay from '@/components/common/OcrBlockOverlay.vue'
import type { ScannerOcrBlock } from '@/api/scanner'
import type { FilePreviewPayload, PdfPreviewPage } from '@/types/knowledge'

const props = defineProps<{
  preview: FilePreviewPayload
  source: string
  blocks?: ScannerOcrBlock[]
  activeBlockId?: string
  lockedBlockId?: string
}>()
const emit = defineEmits<{
  blockHover: [blockId: string]
  blockLeave: []
  blockSelect: [blockId: string]
}>()

type PdfPreviewMode = 'pages' | 'native'

const MIN_SCALE = 0.5
const MAX_SCALE = 4
const viewerMode = ref<PdfPreviewMode>('pages')
const scale = ref(1)
const fitWidth = ref(900)
const scrollElement = ref<HTMLElement | null>(null)
const loadedPages = ref(new Set<number>([1]))
const failedPages = ref(new Set<number>())
const pageElements = new Map<number, HTMLElement>()
let pageObserver: IntersectionObserver | null = null
let resizeObserver: ResizeObserver | null = null
let zoomFrame = 0
let pendingWheelDelta = 0
let pendingPointer = { x: 0, y: 0 }

const pages = computed(() => props.preview.pdf_pages ?? [])
const isCompiledLatexPdf = computed(() => props.preview.path.replace(/\\/gu, '/').startsWith('.mw/latex/'))
const maxPageWidth = computed(() => Math.max(...pages.value.map((page) => page.width), 1))
const zoomLabel = computed(() => `${Math.round(scale.value * 100)}%`)

/** Return fixed page geometry so unloaded placeholders never disturb scroll positions. */
function pageStyle(page: PdfPreviewPage): Record<string, string> {
  const width = fitWidth.value * scale.value * page.width / maxPageWidth.value
  return {
    width: `${width}px`,
    height: `${width * page.height / page.width}px`,
  }
}

/** Register page placeholders with the viewport-near lazy loader. */
function setPageElement(pageNumber: number, value: unknown) {
  const element = value instanceof HTMLElement ? value : null
  const previous = pageElements.get(pageNumber)
  if (previous && previous !== element) pageObserver?.unobserve(previous)
  if (!element) {
    pageElements.delete(pageNumber)
    return
  }
  pageElements.set(pageNumber, element)
  pageObserver?.observe(element)
}

/** Mount image sources only for pages near the current scroll viewport. */
function connectPageObserver() {
  pageObserver?.disconnect()
  if (!scrollElement.value || viewerMode.value !== 'pages') return
  pageObserver = new IntersectionObserver((entries) => {
    const next = new Set(loadedPages.value)
    let changed = false
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      const pageNumber = Number((entry.target as HTMLElement).dataset.page)
      if (!next.has(pageNumber)) {
        next.add(pageNumber)
        changed = true
      }
      pageObserver?.unobserve(entry.target)
    }
    if (changed) loadedPages.value = next
  }, { root: scrollElement.value, rootMargin: '800px 0px' })
  pageElements.forEach((element) => pageObserver?.observe(element))
}

/** Keep the 100% page width fitted to the available editor surface. */
function connectResizeObserver() {
  resizeObserver?.disconnect()
  if (!scrollElement.value || viewerMode.value !== 'pages') return
  const update = () => {
    if (!scrollElement.value) return
    fitWidth.value = Math.min(960, Math.max(240, scrollElement.value.clientWidth - 48))
  }
  update()
  resizeObserver = new ResizeObserver(update)
  resizeObserver.observe(scrollElement.value)
}

/** Pick a stable page-local point to preserve while its layout size changes. */
function findAnchorPage(clientX: number, clientY: number): HTMLElement | null {
  let nearest: HTMLElement | null = null
  let nearestDistance = Number.POSITIVE_INFINITY
  pageElements.forEach((element) => {
    const rect = element.getBoundingClientRect()
    const dx = clientX < rect.left ? rect.left - clientX : clientX > rect.right ? clientX - rect.right : 0
    const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0
    const distance = dx * dx + dy * dy
    if (distance < nearestDistance) {
      nearest = element
      nearestDistance = distance
    }
  })
  return nearest
}

/** Zoom around the pointer by compensating the scroll offset after Vue relayouts every page. */
async function zoomAt(nextScale: number, clientX: number, clientY: number) {
  const boundedScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, nextScale))
  if (boundedScale === scale.value) return
  const root = scrollElement.value
  const anchor = findAnchorPage(clientX, clientY)
  if (!root || !anchor) {
    scale.value = boundedScale
    return
  }

  const before = anchor.getBoundingClientRect()
  const relativeX = (clientX - before.left) / before.width
  const relativeY = (clientY - before.top) / before.height
  scale.value = boundedScale
  await nextTick()

  const after = anchor.getBoundingClientRect()
  root.scrollLeft += after.left + relativeX * after.width - clientX
  root.scrollTop += after.top + relativeY * after.height - clientY
}

/** Convert Ctrl+wheel deltas once per frame to smooth multiplicative zoom. */
function handleWheel(event: WheelEvent) {
  if (!event.ctrlKey) return
  event.preventDefault()
  pendingWheelDelta += event.deltaY
  pendingPointer = { x: event.clientX, y: event.clientY }
  if (zoomFrame) return
  zoomFrame = requestAnimationFrame(() => {
    const delta = pendingWheelDelta
    const pointer = pendingPointer
    pendingWheelDelta = 0
    zoomFrame = 0
    void zoomAt(scale.value * Math.exp(-delta * 0.002), pointer.x, pointer.y)
  })
}

/** Zoom from toolbar controls using the viewport center as the anchor. */
function zoomFromCenter(factor: number) {
  const rect = scrollElement.value?.getBoundingClientRect()
  if (!rect) return
  void zoomAt(scale.value * factor, rect.left + rect.width / 2, rect.top + rect.height / 2)
}

/** Mark a failed raster request without collapsing its reserved page geometry. */
function markPageFailed(pageNumber: number) {
  failedPages.value = new Set(failedPages.value).add(pageNumber)
}

/** Download this generated TeX PDF through the existing raw-file attachment response. */
function downloadCompiledPdf() {
  const downloadUrl = new URL(props.source, window.location.href)
  downloadUrl.searchParams.set('download', 'true')
  const anchor = document.createElement('a')
  anchor.href = downloadUrl.toString()
  anchor.download = props.preview.path.replace(/\\/gu, '/').split('/').pop() || 'document.pdf'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

watch(() => props.preview.path, () => {
  viewerMode.value = 'pages'
  scale.value = 1
  loadedPages.value = new Set([1])
  failedPages.value = new Set()
})

watch(() => props.lockedBlockId, async (blockId) => {
  if (!blockId) return
  const block = (props.blocks ?? []).find((item) => `${item.page}:${item.id ?? item.order}` === blockId)
  if (!block) return
  await nextTick()
  pageElements.get(block.page)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
})

watch([() => props.preview.path, viewerMode], async () => {
  pageObserver?.disconnect()
  resizeObserver?.disconnect()
  await nextTick()
  connectPageObserver()
  connectResizeObserver()
}, { immediate: true, flush: 'post' })

onBeforeUnmount(() => {
  pageObserver?.disconnect()
  resizeObserver?.disconnect()
  if (zoomFrame) cancelAnimationFrame(zoomFrame)
})
</script>

<template>
  <section class="pdf-viewer">
    <header class="pdf-toolbar">
      <div class="preview-toggle" :class="{ native: viewerMode === 'native' }" aria-label="PDF 预览模式">
        <button class="preview-option" :class="{ active: viewerMode === 'pages' }" type="button" @click="viewerMode = 'pages'">Preview1</button>
        <button class="preview-option" :class="{ active: viewerMode === 'native' }" type="button" @click="viewerMode = 'native'">Preview2</button>
      </div>

      <div class="pdf-toolbar-actions">
        <div v-if="viewerMode === 'pages'" class="zoom-controls">
          <button type="button" title="缩小" aria-label="缩小" @click="zoomFromCenter(0.8)"><IcIcon name="remove" :size="16" /></button>
          <button type="button" class="zoom-value" title="重置缩放" @click="zoomFromCenter(1 / scale)">{{ zoomLabel }}</button>
          <button type="button" title="放大" aria-label="放大" @click="zoomFromCenter(1.25)"><IcIcon name="add" :size="16" /></button>
          <button type="button" class="zoom-reset-button" title="重置缩放" aria-label="重置缩放" @click="zoomFromCenter(1 / scale)"><IcIcon name="replay" :size="15" /></button>
        </div>
        <button
          v-if="isCompiledLatexPdf"
          type="button"
          class="pdf-download-button"
          title="下载编译 PDF"
          aria-label="下载编译 PDF"
          @click="downloadCompiledPdf"
        >
          <IcIcon name="download" :size="16" />
        </button>
      </div>
    </header>

    <div v-if="viewerMode === 'pages'" ref="scrollElement" class="pdf-pages-scroll" @wheel="handleWheel">
      <div v-if="pages.length" class="pdf-pages">
        <figure
          v-for="(page, index) in pages"
          :key="index"
          :ref="(element) => setPageElement(index + 1, element)"
          class="pdf-page"
          :data-page="index + 1"
          :style="pageStyle(page)"
        >
          <img
            v-if="loadedPages.has(index + 1) && !failedPages.has(index + 1)"
            :src="buildApiUrl(page.url)"
            :alt="`PDF 第 ${index + 1} 页`"
            loading="lazy"
            draggable="false"
            @error="markPageFailed(index + 1)"
          />
          <span v-else-if="failedPages.has(index + 1)" class="page-message">第 {{ index + 1 }} 页加载失败</span>
          <span v-else class="page-number">{{ index + 1 }}</span>
          <OcrBlockOverlay
            :blocks="blocks ?? []"
            :page="index + 1"
            :width="page.width"
            :height="page.height"
            :active-block-id="activeBlockId"
            :locked-block-id="lockedBlockId"
            @block-hover="emit('blockHover', $event)"
            @block-leave="emit('blockLeave')"
            @block-select="emit('blockSelect', $event)"
          />
        </figure>
      </div>
      <div v-else class="page-message">无法读取 PDF 页面，您可以切换到 Preview2。</div>
    </div>

    <iframe v-else class="native-preview" :src="source" title="PDF Preview2"></iframe>
  </section>
</template>

<style scoped>
.pdf-viewer {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  container-type: inline-size;
  flex-direction: column;
  background: var(--color-canvas);
}

.pdf-toolbar {
  z-index: 3;
  display: flex;
  min-height: 40px;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-10);
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-canvas) 92%, transparent);
  backdrop-filter: blur(12px);
}

.preview-toggle {
  position: relative;
  isolation: isolate;
  display: inline-flex;
  padding: 3px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-surface) 92%, var(--color-text) 8%);
}

.preview-toggle::before {
  position: absolute;
  inset: 3px auto 3px 3px;
  z-index: -1;
  width: calc(50% - 3px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  content: '';
  transition: transform 180ms ease;
}

.preview-toggle.native::before {
  transform: translateX(100%);
}

.preview-option {
  min-height: 26px;
  padding: 0 11px;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.preview-option.active {
  color: var(--color-primary);
  font-weight: 650;
}

.zoom-controls {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.pdf-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
}

.zoom-controls button,
.pdf-download-button {
  display: inline-grid;
  min-width: 28px;
  height: 28px;
  place-items: center;
  padding: 0 5px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  cursor: pointer;
}

.zoom-controls button:hover,
.pdf-download-button:hover {
  background: color-mix(in srgb, var(--color-surface) 92%, var(--color-text) 8%);
  color: var(--color-text);
}

.zoom-controls .zoom-value {
  min-width: 50px;
  font-size: calc(11px * var(--font-scale));
  font-variant-numeric: tabular-nums;
}

@container (max-width: 420px) {
  .zoom-value,
  .zoom-reset-button {
    display: none;
  }

  .pdf-toolbar {
    padding-inline: var(--space-6);
  }
}

.pdf-pages-scroll {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  background: color-mix(in srgb, var(--color-canvas) 84%, var(--color-text) 16%);
}

.pdf-pages {
  display: flex;
  width: max-content;
  min-width: 100%;
  min-height: 100%;
  box-sizing: border-box;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px 24px 48px;
}

.pdf-page {
  position: relative;
  flex: 0 0 auto;
  margin: 0;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 1px 5px color-mix(in srgb, #111 14%, transparent);
}

.pdf-page img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: fill;
  user-select: none;
}

.page-number,
.page-message {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.pdf-pages-scroll > .page-message {
  position: static;
  min-height: 100%;
}

.native-preview {
  flex: 1;
  min-width: 0;
  min-height: 0;
  border: 0;
  background: var(--color-canvas);
  color-scheme: light dark;
}

:global(:root[data-theme="light"]) .native-preview {
  color-scheme: light;
}

:global(:root[data-theme="dark"]) .native-preview {
  color-scheme: dark;
}
</style>
