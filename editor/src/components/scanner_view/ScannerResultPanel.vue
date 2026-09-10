<!--
  Scanner split result workspace.

  Both panes reuse the formal editor toolbar and its mode/save controls while
  presenting editable OCR and no-OCR drafts around a draggable boundary.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import CodeEditor from '@/components/editor_workspace/CodeEditor.vue'
import CodePreview from '@/components/editor_workspace/CodePreview.vue'
import EditorPaneToolbar from '@/components/editor_workspace/EditorPaneToolbar.vue'
import MarkdownPreview from '@/components/editor_workspace/MarkdownPreview.vue'
import MultimodalPreview from '@/components/editor_workspace/MultimodalPreview.vue'
import { type ScannerRecord, type ScannerVariant } from '@/api/scanner'
import { previewKnowledgeFile } from '@/api/knowledge'
import { useScannerStore } from '@/stores/scanner'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { EditorWorkspaceMode, FilePreviewPayload } from '@/types/knowledge'
import { preferredScannerVariant, useScannerRecordActions } from '@/components/scanner_view/useScannerRecordActions'

const props = defineProps<{ record: ScannerRecord }>()
const emit = defineEmits<{ back: []; updated: [record: ScannerRecord] }>()

const scannerStore = useScannerStore()
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const scannerActions = useScannerRecordActions()
const variant = ref<ScannerVariant>(preferredScannerVariant(props.record))
const viewMode = ref<EditorWorkspaceMode>('preview')
const sourceViewMode = ref<EditorWorkspaceMode>(props.record.source_text !== null ? 'edit' : 'preview')
const markdownDraft = ref('')
const sourceDraft = ref('')
const sourcePreview = ref<FilePreviewPayload | null>(null)
const resultGrid = ref<HTMLElement | null>(null)
const paneSplitRatio = ref(0.5)
const busyAction = ref('')
const hoveredBlockId = ref('')
const lockedBlockId = ref('')
let draftTimer: number | null = null
let sourceTimer: number | null = null
let draggingPaneDivider = false

const viewOptions = [
  { mode: 'edit' as EditorWorkspaceMode, label: '编辑', icon: 'edit' },
  { mode: 'preview' as EditorWorkspaceMode, label: '预览', icon: 'visibility' },
  { mode: 'split' as EditorWorkspaceMode, label: '分栏', icon: 'view-column' },
]
const sourceEditable = computed(() => props.record.source_text !== null)
const sourceOptions = computed(() => sourceEditable.value
  ? [
      { mode: 'edit' as EditorWorkspaceMode, label: '编辑', icon: 'edit' },
      { mode: 'preview' as EditorWorkspaceMode, label: '预览', icon: 'visibility' },
    ]
  : [{ mode: 'preview' as EditorWorkspaceMode, label: '预览', icon: 'visibility' }])
const sourceLanguage = computed(() => props.record.source_name.split('.').pop()?.toLowerCase() || 'text')
const virtualMarkdownPath = computed(() => `.mw/scan/${props.record.scan_id}/result.md`)
const resultFilename = computed(() => `${props.record.source_name.replace(/\.[^.]+$/u, '')}.md`)
const resultGridStyle = computed(() => ({
  '--scanner-source-ratio': `${paneSplitRatio.value}fr`,
  '--scanner-markdown-ratio': `${1 - paneSplitRatio.value}fr`,
}))
const previewBlocks = computed(() => variant.value === 'ocr' ? (props.record.ocr_blocks ?? []) : [])
const sourceOverlayBlocks = computed(() => props.record.ocr_preview_path ? previewBlocks.value : [])
const activeBlockId = computed(() => hoveredBlockId.value || lockedBlockId.value)

/** Share hover state between both preview surfaces without touching editors. */
function hoverBlock(blockId: string): void {
  hoveredBlockId.value = blockId
}

/** Keep a clicked block selected until it is clicked again. */
function selectBlock(blockId: string): void {
  lockedBlockId.value = lockedBlockId.value === blockId ? '' : blockId
}

/** Replace local editor state when another history record or variant is selected. */
function syncDrafts(): void {
  markdownDraft.value = variant.value === 'ocr' ? props.record.ocr_markdown : props.record.no_ocr_markdown
  sourceDraft.value = props.record.source_text ?? ''
}

/** Switch OCR variants from the page toolbar while flushing the current draft. */
function selectVariant(next: ScannerVariant): void {
  if (next === variant.value) return
  flushDraftSave()
  variant.value = next
  hoveredBlockId.value = ''
  lockedBlockId.value = ''
}

/** Start resizing the two scanner editor panes through their shared boundary. */
function startPaneResize(event: PointerEvent): void {
  if (event.button !== 0 || window.matchMedia('(max-width: 768px)').matches) return
  draggingPaneDivider = true
  event.preventDefault()
  document.addEventListener('pointermove', resizePanes)
  document.addEventListener('pointerup', stopPaneResize)
}

/** Keep both editor panes usable while following the pointer horizontally. */
function resizePanes(event: PointerEvent): void {
  if (!draggingPaneDivider || !resultGrid.value) return
  const bounds = resultGrid.value.getBoundingClientRect()
  paneSplitRatio.value = Math.max(0.25, Math.min(0.75, (event.clientX - bounds.left) / bounds.width))
}

/** Finish one resize gesture and release document-level listeners. */
function stopPaneResize(): void {
  draggingPaneDivider = false
  document.removeEventListener('pointermove', resizePanes)
  document.removeEventListener('pointerup', stopPaneResize)
}

/** Load the original binary preview through the existing knowledge preview API. */
async function loadSourcePreview(): Promise<void> {
  sourcePreview.value = null
  if (sourceEditable.value || !props.record.source_path) return
  try {
    const previewPath = variant.value === 'ocr' && props.record.ocr_preview_path
      ? props.record.ocr_preview_path
      : props.record.source_path
    sourcePreview.value = await previewKnowledgeFile(settingsStore.profile.userId, previewPath)
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '原文件预览失败', 5000)
  }
}

/** Debounce business-draft persistence through the scanner backend. */
function scheduleDraftSave(): void {
  if (draftTimer !== null) window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(async () => {
    draftTimer = null
    await scannerStore.saveDraft(variant.value, markdownDraft.value, props.record.scan_id)
    if (scannerStore.active) emit('updated', scannerStore.active)
  }, 500)
}

/** Debounce edits made to a text original stored in the managed scanner copy. */
function scheduleSourceSave(): void {
  if (sourceTimer !== null) window.clearTimeout(sourceTimer)
  sourceTimer = window.setTimeout(async () => {
    sourceTimer = null
    await scannerStore.saveSource(sourceDraft.value, props.record.scan_id)
    if (scannerStore.active) emit('updated', scannerStore.active)
  }, 500)
}

/** Flush a pending Markdown debounce before switching records or variants. */
function flushDraftSave(): void {
  if (draftTimer === null) return
  window.clearTimeout(draftTimer)
  draftTimer = null
  void scannerStore.saveDraft(variant.value, markdownDraft.value, props.record.scan_id)
}

/** Flush a pending original-text debounce before leaving the result page. */
function flushSourceSave(): void {
  if (sourceTimer === null) return
  window.clearTimeout(sourceTimer)
  sourceTimer = null
  void scannerStore.saveSource(sourceDraft.value, props.record.scan_id)
}

/** Reveal the managed original copy in the operating-system file manager. */
async function revealSource(): Promise<void> {
  await scannerActions.revealSource(props.record)
}

/** Toggle scanner favorites through the shared persisted favorites store. */
async function toggleFavorite(): Promise<void> {
  await scannerActions.toggleFavorite(props.record)
}

/** Save into the knowledge root after the existing conflict dialog resolves. */
async function saveToKnowledge(): Promise<void> {
  busyAction.value = 'save'
  try {
    await scannerActions.saveToKnowledge(props.record, variant.value)
  } finally {
    busyAction.value = ''
  }
}

/** Fetch the backend package and open the native save-as dialog. */
async function exportOutside(): Promise<void> {
  busyAction.value = 'export'
  try {
    await scannerActions.exportOutside(props.record, variant.value)
  } finally {
    busyAction.value = ''
  }
}

/** Copy one short or full scanner value to the system clipboard. */
async function copyText(value: string, label: string): Promise<void> {
  await scannerActions.copyText(value, label)
}

watch(() => [props.record.scan_id, variant.value, props.record.updated_at], syncDrafts, { immediate: true })
watch(() => [props.record.scan_id, variant.value], () => {
  hoveredBlockId.value = ''
  lockedBlockId.value = ''
  void loadSourcePreview()
}, { immediate: true })
watch(markdownDraft, scheduleDraftSave)
watch(sourceDraft, scheduleSourceSave)
onBeforeUnmount(() => {
  stopPaneResize()
  flushDraftSave()
  flushSourceSave()
})
</script>

<template>
  <section class="scanner-result">
    <header class="scanner-result-toolbar">
      <div class="scanner-result-title">
        <button type="button" title="返回上传页" aria-label="返回上传页" @click="emit('back')"><IcIcon name="back" :size="18" /></button>
        <strong :title="record.source_name">{{ record.source_name }}</strong>
        <button type="button" title="复制文件名" aria-label="复制文件名" @click="copyText(record.source_name, '文件名')"><IcIcon name="copy" :size="15" /></button>
      </div>
      <div class="scanner-result-actions">
        <div v-if="record.ocr_enabled" class="settings-resource-page-switch scanner-variant-switch" role="group" aria-label="OCR 版本">
          <span
            class="settings-resource-page-slider"
            :style="{ left: variant === 'ocr' ? '2px' : '50%', width: 'calc(50% - 2px)' }"
          ></span>
          <button class="settings-resource-page-button" :class="{ active: variant === 'ocr' }" type="button" @click="selectVariant('ocr')">OCR</button>
          <button class="settings-resource-page-button" :class="{ active: variant === 'no_ocr' }" type="button" @click="selectVariant('no_ocr')">No OCR</button>
        </div>
        <button type="button" title="打开文件夹" aria-label="打开文件夹" @click="revealSource"><IcIcon name="folder-open" :size="17" /></button>
        <button type="button" title="收藏" aria-label="收藏" @click="toggleFavorite"><IcIcon name="star" :size="17" /></button>
        <button type="button" title="保存到知识库" aria-label="保存到知识库" :disabled="Boolean(busyAction)" @click="saveToKnowledge"><IcIcon name="save" :size="17" /></button>
        <button type="button" title="导出" aria-label="导出" :disabled="Boolean(busyAction)" @click="exportOutside"><IcIcon name="download" :size="17" /></button>
        <button type="button" title="复制全文" aria-label="复制全文" @click="copyText(markdownDraft, '全文')"><IcIcon name="copy" :size="17" /></button>
      </div>
    </header>
    <div ref="resultGrid" class="scanner-result-grid" :style="resultGridStyle">
      <section class="scanner-source-pane">
        <EditorPaneToolbar
          v-model="sourceViewMode"
          :title="record.source_name"
          :options="sourceOptions"
          compact
          :save-label="sourceEditable ? '保存' : ''"
          @save="scannerStore.saveSource(sourceDraft, record.scan_id)"
        />
        <CodeEditor v-if="sourceEditable && sourceViewMode === 'edit'" v-model="sourceDraft" :language="sourceLanguage" @save="scannerStore.saveSource(sourceDraft, record.scan_id)" />
        <CodePreview v-else-if="sourceEditable" :content="sourceDraft" :language="sourceLanguage" />
        <MultimodalPreview
          v-else
          :preview="sourcePreview"
          :blocks="sourceViewMode === 'preview' ? sourceOverlayBlocks : []"
          :active-block-id="activeBlockId"
          :locked-block-id="lockedBlockId"
          @block-hover="hoverBlock"
          @block-leave="hoveredBlockId = ''"
          @block-select="selectBlock"
        />
      </section>
      <div class="scanner-pane-divider" role="separator" aria-label="调整编辑区宽度" aria-orientation="vertical" @pointerdown="startPaneResize"></div>
      <section class="scanner-markdown-pane">
        <EditorPaneToolbar
          v-model="viewMode"
          :title="resultFilename"
          :options="viewOptions"
          compact
          save-label="保存"
          @save="scannerStore.saveDraft(variant, markdownDraft, record.scan_id)"
        />
        <div class="scanner-markdown-body" :data-mode="viewMode">
          <CodeEditor v-if="viewMode === 'edit' || viewMode === 'split'" v-model="markdownDraft" language="markdown" @save="scannerStore.saveDraft(variant, markdownDraft, record.scan_id)" />
          <MarkdownPreview
            v-if="viewMode === 'preview' || viewMode === 'split'"
            :content="markdownDraft"
            :path="virtualMarkdownPath"
            :blocks="previewBlocks"
            :active-block-id="activeBlockId"
            :locked-block-id="lockedBlockId"
            @block-hover="hoverBlock"
            @block-leave="hoveredBlockId = ''"
            @block-select="selectBlock"
          />
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.scanner-result { position: relative; display: grid; grid-template-rows: auto minmax(0,1fr); width: 100%; height: 100%; min-width: 0; min-height: 0; background: var(--color-bg-app); }
.scanner-result-toolbar { display: flex; min-width: 0; min-height: 44px; align-items: center; justify-content: space-between; gap: 12px; padding: var(--space-8) var(--space-12); background: var(--color-surface-raised); }
.scanner-result-title,.scanner-result-actions { display: inline-flex; min-width: 0; align-items: center; gap: 4px; }
.scanner-result-actions { flex-shrink: 0; }
.scanner-result-title strong { max-width: min(42vw,520px); overflow: hidden; font-size: calc(13px * var(--font-scale)); text-overflow: ellipsis; white-space: nowrap; }
.scanner-result-toolbar button { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--color-text-secondary); transition: background 150ms ease, color 150ms ease, transform 120ms ease; }
.scanner-result-toolbar button:hover:not(:disabled) { background: var(--color-primary-softer); color: var(--color-primary); }
.scanner-result-toolbar button:active:not(:disabled) { transform: scale(.9); }
.scanner-result-toolbar button:disabled { opacity: .4; }
.scanner-variant-switch { margin-right: var(--space-6); }
.scanner-variant-switch .settings-resource-page-button { min-width: 58px; white-space: nowrap; }
.scanner-variant-switch .settings-resource-page-button:hover { background: transparent !important; box-shadow: none !important; }
.scanner-result-grid { display: grid; grid-template-columns: minmax(0,var(--scanner-source-ratio)) 6px minmax(0,var(--scanner-markdown-ratio)); min-width: 0; min-height: 0; }
.scanner-source-pane,.scanner-markdown-pane { display: grid; grid-template-rows: auto minmax(0,1fr); min-width: 0; min-height: 0; overflow: hidden; background: var(--color-canvas); }
.scanner-pane-divider { position: relative; min-width: 6px; cursor: col-resize; touch-action: none; }
.scanner-pane-divider::after { position: absolute; inset: 0 auto 0 50%; width: 1px; background: var(--color-border); content: ''; transform: translateX(-50%); transition: background 120ms ease; }
.scanner-pane-divider:hover::after { background: var(--color-primary); }
.scanner-source-pane > :deep(.code-editor),.scanner-source-pane > :deep(.code-preview),.scanner-source-pane > :deep(.multimodal-preview) { min-width: 0; min-height: 0; border: 0; border-radius: 0; }
.scanner-markdown-body { display: grid; min-width: 0; min-height: 0; overflow: hidden; }
.scanner-markdown-body[data-mode='edit'],.scanner-markdown-body[data-mode='preview'] { grid-template-columns: minmax(0,1fr); }
.scanner-markdown-body[data-mode='split'] { grid-template-columns: minmax(0,1fr) minmax(0,1fr); }
.scanner-markdown-body > :deep(*) { min-width: 0; min-height: 0; border: 0; border-radius: 0; }
@media (max-width: 1024px) { .scanner-markdown-body[data-mode='split'] { grid-template-columns: minmax(0,1fr); grid-template-rows: minmax(0,1fr) minmax(0,1fr); gap: var(--space-6); } }
@media (max-width: 768px) { .scanner-result-grid { grid-template-columns: minmax(0,1fr) !important; grid-template-rows: minmax(280px,42%) 1px minmax(0,1fr); overflow: auto; } .scanner-pane-divider { min-width: 0; min-height: 1px; cursor: default; pointer-events: none; } .scanner-pane-divider::after { inset: 0; width: auto; transform: none; } }
@media (max-width: 560px) { .scanner-result-title strong { max-width: 70px; } .scanner-result-title button:nth-of-type(2),.scanner-result-actions > button:nth-last-child(-n+2) { display: none; } .scanner-variant-switch { margin-right: 0; } .scanner-variant-switch .settings-resource-page-button { min-width: 52px; padding: 0 var(--space-4); font-size: calc(11px * var(--font-scale)); } }
@media (prefers-reduced-motion: reduce) { .scanner-result-toolbar button { transition: none; } }
</style>
