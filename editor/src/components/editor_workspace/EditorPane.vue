<!--
  Main editor pane.

  Usage:
  Renders open tabs, file metadata, Vditor edit surface, preview surface, and
  save/view-mode controls.
-->
<script setup lang="ts">
import { computed, nextTick, onErrorCaptured, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import IcIcon from '@/components/common/IcIcon.vue'
import EditorSidebarCloseButton from '@/components/editor_workspace/EditorSidebarCloseButton.vue'
import BacklinksPanel from '@/components/editor_workspace/BacklinksPanel.vue'
import CodeEditor from '@/components/editor_workspace/CodeEditor.vue'
import CodePreview from '@/components/editor_workspace/CodePreview.vue'
import EditorPaneToolbar from '@/components/editor_workspace/EditorPaneToolbar.vue'
import MarkdownHtmlVisualizationPanel from '@/components/editor_workspace/MarkdownHtmlVisualizationPanel.vue'
import MarkdownOutline from '@/components/editor_workspace/MarkdownOutline.vue'
import MarkdownPreview from '@/components/editor_workspace/MarkdownPreview.vue'
import MultimodalPreview from '@/components/editor_workspace/MultimodalPreview.vue'
import LatexPreview from '@/components/editor_workspace/LatexPreview.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useSettingsStore } from '@/stores/settings'
import type { EditorWorkspaceMode } from '@/types/knowledge'
import { resolveEditorFilePipeline } from '@/utils/editorFilePipeline'
import { fetchSessionChanges } from '@/api/agentChanges'
import { readKnowledgeFile } from '@/api/knowledge'
import {
  cancelLatexInstall,
  compileLatexFile,
  fetchLatexStatus,
  installLatexRuntime,
  type LatexCompileError,
  type LatexCompileResult,
  type LatexRuntimeStatus,
} from '@/api/latex'
import { useSessionStore } from '@/stores/session'
import { buildBacklinks } from './backlinks'
import {
  flattenMarkdownOutline,
  headingAtOffset,
  parseMarkdownOutline,
  type MarkdownOutlineItem,
} from './markdownOutline'
import { flattenWikiFiles, parseWikiLink, resolveWikiTargetPath } from './wikiLinks'

const props = withDefaults(defineProps<{
  /** Whether this pane is embedded as the independent editor sidebar. */
  sidebar?: boolean
}>(), {
  sidebar: false,
})

const emit = defineEmits<{
  /** Requests that the parent hide the independent editor sidebar. */
  close: []
}>()

const workspaceStore = useWorkspaceStore()
const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()
const { editorMode } = storeToRefs(workspaceStore)
const codeEditorRef = ref<InstanceType<typeof CodeEditor> | null>(null)
const markdownPreviewRef = ref<InstanceType<typeof MarkdownPreview> | null>(null)
type EditorScrollSnapshot = {
  ratio: number
  cursorOffset: number
  contentLength: number
  cursorViewportRatio: number
}

const lastEditorScroll = ref<EditorScrollSnapshot>({ ratio: 0, cursorOffset: 0, contentLength: 0, cursorViewportRatio: 0.16 })
let previewFeedbackLocked = false
let previewFeedbackTimer: ReturnType<typeof setTimeout> | null = null
const outlineOpen = ref(false)
const activeHeadingOffset = ref(0)
const wikiFocusAnchor = ref<{ path: string; heading: string; blockId: string; nonce: number } | null>(null)
let wikiFocusNonce = 0
const backlinkDocuments = ref<Record<string, string>>({})
const backlinksLoading = ref(false)
let backlinksLoadNonce = 0
const latexRuntimeStatus = ref<LatexRuntimeStatus | null>(null)
const latexCompileResult = ref<LatexCompileResult | null>(null)
const latexCompiling = ref(false)
let latexStatusTimer: ReturnType<typeof setInterval> | null = null
const backlinks = computed(() => buildBacklinks(
  workspaceStore.selectedPath,
  workspaceStore.tree,
  backlinkDocuments.value,
))
const shouldShowBacklinks = computed(() => (
  Boolean(settingsStore.profile.showBacklinks)
  && isMarkdownViewer.value
  && Boolean(workspaceStore.activeTab)
))

async function loadBacklinks() {
  if (!shouldShowBacklinks.value || !settingsStore.profile.userId) {
    backlinkDocuments.value = {}
    return
  }
  const nonce = ++backlinksLoadNonce
  backlinksLoading.value = true
  try {
    if (workspaceStore.tree.length === 0) await workspaceStore.loadKnowledgeTree()
    const markdownFiles = flattenWikiFiles(workspaceStore.tree)
      .filter((node) => /\.(?:md|markdown)$/iu.test(node.path))
    const results = await Promise.allSettled(markdownFiles.map(async (node) => [
      node.path,
      node.path === workspaceStore.selectedPath
        ? activeContent.value
        : (await readKnowledgeFile(settingsStore.profile.userId, node.path)).content,
    ] as const))
    if (nonce !== backlinksLoadNonce) return
    backlinkDocuments.value = Object.fromEntries(
      results.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []),
    )
  } finally {
    if (nonce === backlinksLoadNonce) backlinksLoading.value = false
  }
}

async function toggleBacklinks() {
  try {
    await settingsStore.setShowBacklinks(!settingsStore.profile.showBacklinks)
  } catch {
    workspaceStore.showToast('反向链接显示设置保存失败')
  }
}

async function closeBacklinks() {
  try {
    await settingsStore.setShowBacklinks(false)
  } catch {
    workspaceStore.showToast('反向链接显示设置保存失败')
  }
}

async function openBacklinkSource(path: string) {
  const node = workspaceStore.flatNodes.find((item) => !item.isDir && item.path === path)
  if (node) await workspaceStore.selectFile(node)
}

async function saveActiveFileAndRefreshBacklinks() {
  await workspaceStore.saveActiveFile()
  if (isLatexViewer.value) await compileActiveLatex({ save: false })
  await loadBacklinks()
}

const splitRatio = ref(0.5)
const splitBodyRef = ref<HTMLElement | null>(null)
let isDragging = false

function onSplitDividerPointerdown(event: PointerEvent) {
  if (event.button !== 0) return
  isDragging = true
  event.preventDefault()
  document.addEventListener('pointermove', onSplitDividerPointermove)
  document.addEventListener('pointerup', onSplitDividerPointerup)
}

function onSplitDividerPointermove(event: PointerEvent) {
  if (!isDragging || !splitBodyRef.value) return
  const rect = splitBodyRef.value.getBoundingClientRect()
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  splitRatio.value = x
}

function onSplitDividerPointerup() {
  isDragging = false
  document.removeEventListener('pointermove', onSplitDividerPointermove)
  document.removeEventListener('pointerup', onSplitDividerPointerup)
}

const activeContent = computed({
  get: () => workspaceStore.activeContent,
  set: (value: string) => workspaceStore.updateActiveContent(value),
})

const activeLanguage = computed(() => {
  const name = workspaceStore.selectedPath.toLowerCase()
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex < 0) {
    return 'text'
  }
  const extension = name.slice(dotIndex + 1)
  if (extension === 'txt') {
    return 'text'
  }
  return extension
})
const latestChangeSnapshot = ref<Awaited<ReturnType<typeof fetchSessionChanges>>['change_snapshot']>(null)
const activeChangeRanges = computed(() => {
  const snapshot = latestChangeSnapshot.value
  if (!snapshot) return []
  return snapshot.edits.flatMap((edit) => {
    if (edit.path !== workspaceStore.selectedPath || activeContent.value !== edit.after) return []
    const beforeLines = (edit.before ?? '').split('\n')
    const afterLines = edit.after.split('\n')
    let prefix = 0
    while (prefix < beforeLines.length && prefix < afterLines.length && beforeLines[prefix] === afterLines[prefix]) prefix += 1
    let suffix = 0
    while (
      suffix < beforeLines.length - prefix
      && suffix < afterLines.length - prefix
      && beforeLines[beforeLines.length - 1 - suffix] === afterLines[afterLines.length - 1 - suffix]
    ) suffix += 1
    const afterChanged = Math.max(0, afterLines.length - prefix - suffix)
    const beforeChanged = Math.max(0, beforeLines.length - prefix - suffix)
    const line = prefix + 1
    return [
      ...(afterChanged ? [{ startLine: line, endLine: line + afterChanged - 1, kind: 'added' as const }] : []),
      ...(beforeChanged ? [{ startLine: line, endLine: line, kind: 'removed' as const }] : []),
    ]
  })
})

async function loadLatestChangeSnapshot() {
  const sessionId = sessionStore.currentSessionId
  if (!sessionId) { latestChangeSnapshot.value = null; return }
  try {
    latestChangeSnapshot.value = (await fetchSessionChanges(sessionId)).change_snapshot
  } catch {
    latestChangeSnapshot.value = null
  }
}

const isMarkdownViewer = computed(() => workspaceStore.activeViewerKind === 'markdown')
const isLatexViewer = computed(() => /\.tex$/iu.test(workspaceStore.selectedPath))
const outlineItems = computed(() => parseMarkdownOutline(activeContent.value))
const flatOutlineItems = computed(() => flattenMarkdownOutline(outlineItems.value))
const activeOutlineId = computed(() => (
  headingAtOffset(outlineItems.value, activeHeadingOffset.value)?.id ?? ''
))
const activePipeline = computed(() => resolveEditorFilePipeline(
  workspaceStore.selectedPath,
  workspaceStore.activePreview?.kind,
))
const effectiveEditorMode = computed<EditorWorkspaceMode>(() => (
  activePipeline.value.modes.some((item) => item.mode === editorMode.value)
    ? editorMode.value
    : activePipeline.value.defaultMode
))
const isEditableTextMode = computed(() => (
  ['edit', 'text', 'code'].includes(effectiveEditorMode.value)
  || (isMarkdownViewer.value && effectiveEditorMode.value === 'split')
  || (isLatexViewer.value && effectiveEditorMode.value === 'split')
))
const isProjectionMode = computed(() => effectiveEditorMode.value === 'markdown')

const splitBodyStyle = computed(() => {
  if (effectiveEditorMode.value !== 'split') return {}
  const r = Math.max(0.15, Math.min(0.85, splitRatio.value))
  return { gridTemplateColumns: `${r * 100}% 6px ${(1 - r) * 100}%` } as const
})

function setEditorMode(mode: EditorWorkspaceMode) {
  if (!activePipeline.value.modes.some((item) => item.mode === mode)) return
  editorMode.value = mode
  if (isLatexViewer.value && ['preview', 'split'].includes(mode)) {
    void compileActiveLatex({ save: true })
  }
}

/** Refresh compiler status without starting a download or changing the machine. */
async function refreshLatexStatus() {
  if (!isLatexViewer.value || !settingsStore.profile.userId) return
  try {
    latexRuntimeStatus.value = await fetchLatexStatus(settingsStore.profile.userId)
  } catch {
    latexRuntimeStatus.value = null
  }
}

/** Save when requested, compile the active `.tex`, and preserve compiler diagnostics. */
async function compileActiveLatex({ save }: { save: boolean }) {
  if (!isLatexViewer.value || !settingsStore.profile.userId || latexCompiling.value) return
  latexCompiling.value = true
  try {
    const loadDeadline = Date.now() + 8_000
    while (workspaceStore.isFileLoading && Date.now() < loadDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 40))
    }
    if (workspaceStore.isFileLoading) {
      workspaceStore.showToast('文件仍在加载，暂不能编译')
      return
    }
    if (save) await workspaceStore.saveActiveFile()
    await refreshLatexStatus()
    if (latexRuntimeStatus.value?.status !== 'ready') return
    latexCompileResult.value = await compileLatexFile(
      settingsStore.profile.userId,
      workspaceStore.selectedPath,
    )
  } catch {
    await refreshLatexStatus()
    workspaceStore.showToast('LaTeX 编译请求失败')
  } finally {
    latexCompiling.value = false
  }
}

/** Start user-confirmed managed MiKTeX installation and poll the real backend state. */
async function startLatexInstall() {
  if (!settingsStore.profile.userId) return
  try {
    latexRuntimeStatus.value = await installLatexRuntime(settingsStore.profile.userId)
  } catch {
    workspaceStore.showToast('MiKTeX 安装启动失败')
    return
  }
  if (latexStatusTimer) clearInterval(latexStatusTimer)
  latexStatusTimer = setInterval(async () => {
    await refreshLatexStatus()
    const status = latexRuntimeStatus.value?.status
    if (!status || ['downloading', 'installing', 'cancelling'].includes(status)) return
    if (latexStatusTimer) clearInterval(latexStatusTimer)
    latexStatusTimer = null
    if (status === 'ready') void compileActiveLatex({ save: false })
  }, 1000)
}

/** Cancel an active managed runtime installation. */
async function stopLatexInstall() {
  if (!settingsStore.profile.userId) return
  latexRuntimeStatus.value = await cancelLatexInstall(settingsStore.profile.userId)
}

/** Open the compiler-reported source file and move its editable pane to the diagnostic line. */
async function openLatexError(error: LatexCompileError) {
  const reported = error.file.replace(/\\/gu, '/').replace(/^\(+|\)+$/gu, '')
  const rootPath = latexCompileResult.value?.root_path ?? workspaceStore.selectedPath
  const rootParent = rootPath.includes('/') ? rootPath.slice(0, rootPath.lastIndexOf('/')) : ''
  const relativeCandidate = reported.match(/^[A-Za-z]:\//u)
    ? ''
    : [rootParent, reported].filter(Boolean).join('/').replace(/\/\.\//gu, '/')
  const targetNode = workspaceStore.flatNodes.find((node) => !node.isDir && (
    node.path === relativeCandidate
    || node.path === reported
    || node.path.endsWith(`/${reported}`)
  ))
  if (targetNode && targetNode.path !== workspaceStore.selectedPath) {
    await workspaceStore.selectFile(targetNode)
  }
  const sourceLines = activeContent.value.split('\n')
  const line = Math.max(1, error.line)
  const offset = sourceLines.slice(0, line - 1).reduce((total, value) => total + value.length + 1, 0)
  editorMode.value = 'split'
  await nextTick()
  codeEditorRef.value?.scrollToSourceOffset(offset, 'smooth')
}

/** Prevents a programmatic preview move from feeding the same scroll back into the editor. */
function lockPreviewFeedback() {
  previewFeedbackLocked = true
  if (previewFeedbackTimer) clearTimeout(previewFeedbackTimer)
  previewFeedbackTimer = setTimeout(() => {
    previewFeedbackLocked = false
    previewFeedbackTimer = null
  }, 180)
}

/** Keeps the rendered caret block at the same visual height without feedback scrolling the editor. */
function syncMarkdownPreviewToCaret(snapshot: EditorScrollSnapshot, behavior: ScrollBehavior = 'auto') {
  if (effectiveEditorMode.value !== 'split' || !isMarkdownViewer.value) return
  lockPreviewFeedback()
  markdownPreviewRef.value?.scrollToSourceOffset(
    snapshot.cursorOffset,
    snapshot.contentLength,
    behavior,
    snapshot.cursorViewportRatio,
  )
}

/** Maps wheel/scroll movement across panes by each surface's complete scrollable range. */
function syncMarkdownPreviewToRatio(ratio: number) {
  if (effectiveEditorMode.value !== 'split' || !isMarkdownViewer.value) return
  lockPreviewFeedback()
  markdownPreviewRef.value?.scrollToRatio(ratio)
}

function handleEditorScroll(payload: EditorScrollSnapshot) {
  lastEditorScroll.value = payload
  activeHeadingOffset.value = payload.cursorOffset
  syncMarkdownPreviewToRatio(payload.ratio)
}

/** Tracks the heading that owns the editable Markdown caret. */
function handleEditorCursor(offset: number) {
  activeHeadingOffset.value = offset
  if (effectiveEditorMode.value === 'split' && isMarkdownViewer.value) {
    void nextTick(() => {
      const snapshot = codeEditorRef.value?.getScrollSnapshot() ?? lastEditorScroll.value
      lastEditorScroll.value = snapshot
      syncMarkdownPreviewToCaret(snapshot)
    })
  }
}

/** Maps the rendered preview heading order back to its Markdown source offset. */
function handlePreviewActiveHeading(index: number) {
  const heading = flatOutlineItems.value[index]
  if (heading) activeHeadingOffset.value = heading.offset
}

/** Navigates every visible Markdown surface to the selected outline heading. */
function navigateToOutlineHeading(item: MarkdownOutlineItem) {
  activeHeadingOffset.value = item.offset
  const index = flatOutlineItems.value.findIndex((heading) => heading.id === item.id)
  if (['edit', 'split'].includes(effectiveEditorMode.value)) {
    codeEditorRef.value?.scrollToSourceOffset(item.offset, 'smooth')
  }
  if (index >= 0 && ['preview', 'split'].includes(effectiveEditorMode.value)) {
    markdownPreviewRef.value?.scrollToHeading(index)
  }
}

function handlePreviewScroll(ratio: number) {
  if (!previewFeedbackLocked && effectiveEditorMode.value === 'split' && isMarkdownViewer.value) {
    codeEditorRef.value?.scrollToRatio(ratio)
  }
}

function handleMarkdownPreviewReady() {
  if (effectiveEditorMode.value !== 'split' || !isMarkdownViewer.value) {
    return
  }
  const snapshot = codeEditorRef.value?.getScrollSnapshot() ?? lastEditorScroll.value
  lastEditorScroll.value = snapshot
  syncMarkdownPreviewToCaret(snapshot)
}

async function handleWikiNavigate(rawDestination: string) {
  const destination = parseWikiLink(rawDestination)
  if (!destination) return
  const targetPath = resolveWikiTargetPath(
    destination.file,
    workspaceStore.tree,
    workspaceStore.selectedPath,
  )
  const targetNode = workspaceStore.flatNodes.find((node) => !node.isDir && node.path === targetPath)
  if (!targetNode) {
    workspaceStore.showToast(`找不到链接文件：${destination.file}`)
    return
  }
  workspaceStore.setMainView('editor')
  await workspaceStore.selectFile(targetNode)
  if (/\.(?:md|markdown)$/iu.test(targetPath)) {
    workspaceStore.setEditorMode('preview')
    wikiFocusAnchor.value = {
      path: targetPath,
      heading: destination.heading,
      blockId: destination.blockId,
      nonce: ++wikiFocusNonce,
    }
  }
}

watch(effectiveEditorMode, async (mode, previousMode) => {
  if (!isMarkdownViewer.value || mode === previousMode) return
  await nextTick()

  const activeIndex = flatOutlineItems.value.findIndex((heading) => heading.id === activeOutlineId.value)
  if (previousMode === 'preview' && ['edit', 'split'].includes(mode)) {
    codeEditorRef.value?.scrollToSourceOffset(activeHeadingOffset.value, 'auto')
  }
  if (mode === 'preview') {
    if (activeIndex >= 0) markdownPreviewRef.value?.scrollToHeading(activeIndex)
    return
  }
  if (mode !== 'split' || previousMode === 'split') return

  const snapshot = codeEditorRef.value?.getScrollSnapshot() ?? lastEditorScroll.value
  lastEditorScroll.value = snapshot
  if (previousMode === 'preview' && activeIndex >= 0) {
    markdownPreviewRef.value?.scrollToHeading(activeIndex)
  } else {
    syncMarkdownPreviewToCaret(snapshot)
  }
})

watch(() => workspaceStore.selectedPath, () => {
  activeHeadingOffset.value = 0
  latexCompileResult.value = null
  void loadLatestChangeSnapshot()
  void loadBacklinks()
  void refreshLatexStatus()
})

watch(isMarkdownViewer, (isMarkdown) => {
  if (!isMarkdown) outlineOpen.value = false
})

watch(() => settingsStore.profile.showBacklinks, () => void loadBacklinks())

watch(() => sessionStore.currentSessionId, () => void loadLatestChangeSnapshot(), { immediate: true })

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!workspaceStore.hasDirtyTabs) {
    return
  }
  event.preventDefault()
  event.returnValue = ''
}

function handleEditorShortcut(event: KeyboardEvent) {
  const isModifier = event.ctrlKey || event.metaKey
  if (!isModifier || event.altKey || event.shiftKey) {
    return
  }
  const target = event.target
  if (!(target instanceof HTMLElement) || !target.closest('.editor-panel')) {
    return
  }
  const key = event.key.toLowerCase()
  if (!isMarkdownViewer.value && !isLatexViewer.value) return
  const modeByKey: Record<string, EditorWorkspaceMode> = {
    e: isLatexViewer.value ? 'code' : 'edit',
    p: 'preview',
    t: 'split',
  }
  const nextMode = modeByKey[key]
  if (!nextMode) {
    return
  }
  event.preventDefault()
  setEditorMode(nextMode)
}

/** Refreshes the persisted Agent patch after a streamed turn completes. */
function handleAgentTurnFinished() {
  void loadLatestChangeSnapshot()
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('agent-turn-finished', handleAgentTurnFinished)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('agent-turn-finished', handleAgentTurnFinished)
  if (latexStatusTimer) clearInterval(latexStatusTimer)
  if (previewFeedbackTimer) clearTimeout(previewFeedbackTimer)
})

onErrorCaptured((err, vm, info) => {
  console.warn(`[EditorPane] Caught error (${info}):`, err)
  // Prevent child-component errors (e.g. Vditor destruction during rapid file
  // switching) from taking down the entire editor pane.
  return false
})

</script>

<template>
  <main class="editor-panel surface-panel" :class="{ 'sidebar-editor-panel': props.sidebar }" @keydown.capture="handleEditorShortcut">
    <EditorPaneToolbar
      v-if="workspaceStore.activeTab"
      :key="workspaceStore.activeTab.path"
      :title="workspaceStore.activeTab.title"
      :dirty="workspaceStore.activeTab.dirty"
      :model-value="effectiveEditorMode"
      :options="activePipeline.modes"
      closable
      @activate="workspaceStore.activateTab(workspaceStore.activeTab.path)"
      @close="workspaceStore.closeTab(workspaceStore.activeTab.path)"
      @update:model-value="setEditorMode"
    >
      <template #actions>
        <button
          v-if="isMarkdownViewer"
          class="editor-tool-button outline-toggle"
          :class="{ active: outlineOpen }"
          type="button"
          :aria-pressed="outlineOpen"
          aria-label="目录树"
          title="目录树"
          @click="outlineOpen = !outlineOpen"
        >
          <IcIcon name="view-list" :size="15" />
        </button>
        <EditorSidebarCloseButton v-if="props.sidebar" @close="emit('close')" />
      </template>
    </EditorPaneToolbar>

    <div
      v-if="workspaceStore.openTabs.length > 0"
      ref="splitBodyRef"
      class="editor-body"
      :class="{ 'with-backlinks': shouldShowBacklinks }"
      :data-mode="effectiveEditorMode"
      :style="splitBodyStyle"
    >
      <section v-if="isEditableTextMode" class="editor-surface">
        <CodeEditor
          ref="codeEditorRef"
          v-model="activeContent"
          :language="activeLanguage"
          :paste-image="workspaceStore.savePastedEditorImage"
          :readonly="workspaceStore.activeFileReadonly"
          :change-ranges="activeChangeRanges"
          :wiki-files="workspaceStore.tree"
          :show-backlinks="Boolean(settingsStore.profile.showBacklinks)"
          @save="saveActiveFileAndRefreshBacklinks"
          @scroll="handleEditorScroll"
          @cursor="handleEditorCursor"
          @toggle-backlinks="toggleBacklinks"
        />
      </section>
      <div
        v-if="effectiveEditorMode === 'split'"
        class="split-divider"
        @pointerdown="onSplitDividerPointerdown"
      ></div>
      <section v-if="isMarkdownViewer && ['preview', 'split'].includes(effectiveEditorMode)" class="preview-surface">
        <MarkdownPreview
          ref="markdownPreviewRef"
          :key="workspaceStore.selectedPath"
          :content="activeContent"
          :path="workspaceStore.selectedPath"
          :focus-anchor="wikiFocusAnchor"
          @scroll="handlePreviewScroll"
          @active-heading="handlePreviewActiveHeading"
          @update-content="activeContent = $event"
          @ready="handleMarkdownPreviewReady"
          @navigate-wiki="handleWikiNavigate"
        />
      </section>
      <section v-else-if="isLatexViewer && ['preview', 'split'].includes(effectiveEditorMode)" class="preview-surface">
        <LatexPreview
          :status="latexRuntimeStatus"
          :result="latexCompileResult"
          :compiling="latexCompiling"
          @install="startLatexInstall"
          @cancel-install="stopLatexInstall"
          @retry="compileActiveLatex({ save: true })"
          @open-error="openLatexError"
        />
      </section>
      <section v-else-if="isProjectionMode" class="preview-surface projection-source-surface">
        <CodePreview
          :content="workspaceStore.activePreview?.semantic_markdown ?? ''"
          language="markdown"
        />
      </section>
      <section v-else-if="!isEditableTextMode" class="preview-surface">
        <MultimodalPreview :preview="workspaceStore.activePreview" />
      </section>
      <MarkdownOutline
        v-if="isMarkdownViewer"
        :items="outlineItems"
        :active-id="activeOutlineId"
        :open="outlineOpen"
        @navigate="navigateToOutlineHeading"
      />
    </div>
    <div v-else class="editor-empty">
      <p>选择文件以开始编辑。</p>
    </div>
    <BacklinksPanel
      v-if="shouldShowBacklinks"
      :entries="backlinks"
      :loading="backlinksLoading"
      @close="closeBacklinks"
      @open="openBacklinkSource"
    />
    <MarkdownHtmlVisualizationPanel />
  </main>
</template>

<style scoped>
.editor-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 0;
  background: var(--color-canvas-soft);
  font-family: var(--font-ui);
}

.sidebar-editor-panel {
  width: 100%;
  min-width: 0;
}

.editor-tool-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  height: 22px;
  padding: 0 var(--space-8);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text);
  font-family: inherit;
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
  transition:
    background 160ms ease,
    color 160ms ease,
    transform 140ms cubic-bezier(0.23, 1, 0.32, 1);
}

.editor-tool-button:active:not(:disabled) {
  transform: scale(0.94);
}

.outline-toggle.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.outline-toggle {
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 50%;
}

@media (hover: hover) and (pointer: fine) {
  .editor-tool-button:hover:not(:disabled) {
    background: var(--color-primary-softer);
    color: var(--color-primary-hover);
  }

}

.editor-body {
  position: relative;
  display: grid;
  flex: 1;
  min-height: 0;
  gap: var(--space-10);
  margin: 0 var(--space-10) var(--space-10);
  padding: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0 8px 8px 8px;
  background: var(--color-canvas);
}

.editor-body.with-backlinks {
  margin-bottom: var(--space-6);
}

.split-divider {
  cursor: col-resize;
  border-radius: 3px;
  background: var(--color-border);
  transition: background 120ms ease;
  min-height: 100%;
}

.split-divider:hover {
  background: var(--color-primary);
}

.editor-body[data-mode='split'] {
  gap: 0;
}

.editor-body[data-mode='edit'],
.editor-body[data-mode='preview'],
.editor-body[data-mode='text'],
.editor-body[data-mode='forms'],
.editor-body[data-mode='markdown'],
.editor-body[data-mode='code'],
.editor-body[data-mode='binary'] {
  grid-template-columns: minmax(0, 1fr);
}

.editor-surface,
.preview-surface {
  /* These min sizes are required for Split. Without them Vditor can force one
     pane to occupy the full row and leave the preview pane invisible. */
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.editor-surface > *,
.preview-surface > * {
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.editor-body :deep(.code-editor),
.editor-body :deep(.code-preview),
.editor-body :deep(.markdown-preview),
.editor-body :deep(.multimodal-preview) {
  border: 0;
  border-radius: 0;
}

.editor-empty {
  display: grid;
  flex: 1;
  place-items: center;
  min-height: 0;
  color: var(--color-text-muted);
  background: var(--color-canvas-soft);
}

.editor-empty p {
  margin: 0;
  font-size: calc(13px * var(--font-scale));
}

@media (max-width: 920px) {
  .editor-body[data-mode='split'] {
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-rows: minmax(0, 1fr) 6px minmax(0, 1fr);
  }

  .editor-body[data-mode='split'] .split-divider {
    min-height: 6px;
    cursor: row-resize;
  }
}

@media (prefers-reduced-motion: reduce) {
  .editor-tool-button {
    transition: color 160ms ease, background 160ms ease;
  }

  .editor-tool-button:active:not(:disabled) {
    transform: none;
  }
}
</style>
