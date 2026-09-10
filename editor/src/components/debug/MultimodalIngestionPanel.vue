<!--
  Multimodal ingestion observation panel.

  Usage:
  Debug-only view for inspecting one file's structured JSON, semantic sections,
  and overlapped chunks without opening the editor or writing vector records.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import MarkdownPreview from '@/components/editor_workspace/MarkdownPreview.vue'
import { fetchMultimodalIngestionObservation } from '@/api/debug'
import type {
  MultimodalIngestionObservation,
  MultimodalOverlapChunk,
  MultimodalSemanticChunk,
} from '@/api/debug'
import {
  displayMtime,
  fileKind,
  formatSize,
  nodeSize,
  normalizeTreePath,
  parentPath,
  timestampOf,
} from '@/components/editor_workspace/fileResourceManagerUtils'
import { materialFileIconForNode } from '@/components/editor_workspace/materialFileIcons'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { KnowledgeFileNode } from '@/types/knowledge'

type ObservationTab = 'markdown' | 'json' | 'semantic' | 'overlap'
type SortKey = 'name' | 'mtime' | 'type' | 'size'
type SortDirection = 'asc' | 'desc'

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()

const currentDir = ref('')
const selectedPath = ref('')
const activeObservationTab = ref<ObservationTab>('markdown')
const observationTabsRef = ref<HTMLElement | null>(null)
const observationSliderStyle = ref({ width: '0px', left: '0px' })
const observation = ref<MultimodalIngestionObservation | null>(null)
const loading = ref(false)
const error = ref('')
const paneVisible = ref(false)
const abortController = ref<AbortController | null>(null)
const directoryBackStack = ref<string[]>([])
const directoryForwardStack = ref<string[]>([])
const sortMenuOpen = ref(false)
const sortKey = ref<SortKey>('name')
const sortDirection = ref<SortDirection>('asc')
const collapsedSemanticChunkKeys = ref<Set<string>>(new Set())
const collapsedOverlapChunkKeys = ref<Set<string>>(new Set())

const sortKeyOptions: { value: SortKey; label: string }[] = [
  { value: 'name', label: '名称排序' },
  { value: 'mtime', label: '修改时间排序' },
  { value: 'type', label: '类型排序' },
  { value: 'size', label: '大小排序' },
]
const sortDirectionOptions: { value: SortDirection; label: string }[] = [
  { value: 'asc', label: '递增' },
  { value: 'desc', label: '递减' },
]

const canGoBack = computed(() => directoryBackStack.value.length > 0)
const canGoForward = computed(() => directoryForwardStack.value.length > 0)
const canGoUp = computed(() => Boolean(currentDir.value))
const hasObservationPane = computed(() => paneVisible.value && (Boolean(observation.value) || loading.value || Boolean(error.value)))
const currentDirLabel = computed(() => currentDir.value || settingsStore.profile.knowledgeDir || 'Knowledge')
const jsonText = computed(() => observation.value ? JSON.stringify(observation.value.json_result, null, 2) : '')
const listGridColumns = computed(() => {
  const indexColumn = settingsStore.showIndexColumn ? ' minmax(110px, 0.55fr)' : ''
  return `minmax(220px, 1.6fr) minmax(150px, 0.8fr) minmax(90px, 0.5fr) minmax(80px, 0.4fr)${indexColumn}`
})

/** Aligns the observation slider after its data or active tab changes. */
function updateObservationSlider(): void {
  void nextTick(() => {
    const active = observationTabsRef.value?.querySelector<HTMLElement>('.observation-tab.active')
    if (!active) return
    observationSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

watch([activeObservationTab, observation], updateObservationSlider)

const visibleItems = computed(() => {
  const targetDir = currentDir.value
  return workspaceStore.flatNodes
    .filter((node) => parentPath(node.path) === targetDir)
    .sort(compareNodes)
})

function compareNodes(a: KnowledgeFileNode, b: KnowledgeFileNode): number {
  const dirOrder = Number(b.isDir) - Number(a.isDir)
  if (dirOrder !== 0) {
    return dirOrder
  }

  let result = 0
  if (sortKey.value === 'name') {
    result = a.name.localeCompare(b.name, 'zh-CN', { sensitivity: 'base' })
  } else if (sortKey.value === 'mtime') {
    result = timestampOf(a.mtime) - timestampOf(b.mtime)
  } else if (sortKey.value === 'type') {
    result = fileKind(a).localeCompare(fileKind(b), 'zh-CN', { sensitivity: 'base' })
  } else {
    result = nodeSize(a) - nodeSize(b)
  }

  if (result === 0) {
    result = a.name.localeCompare(b.name, 'zh-CN', { sensitivity: 'base' })
  }
  return sortDirection.value === 'asc' ? result : -result
}

function navigateToDirectory(path: string, recordHistory = true) {
  const normalizedPath = normalizeTreePath(path)
  if (normalizedPath === currentDir.value) {
    return
  }
  if (recordHistory) {
    directoryBackStack.value = [...directoryBackStack.value, currentDir.value]
    directoryForwardStack.value = []
  }
  currentDir.value = normalizedPath
  selectedPath.value = ''
  sortMenuOpen.value = false
}

function goBackDirectory() {
  const previousPath = directoryBackStack.value[directoryBackStack.value.length - 1]
  if (previousPath === undefined) {
    return
  }
  directoryBackStack.value = directoryBackStack.value.slice(0, -1)
  directoryForwardStack.value = [...directoryForwardStack.value, currentDir.value]
  navigateToDirectory(previousPath, false)
}

function goForwardDirectory() {
  const nextPath = directoryForwardStack.value[directoryForwardStack.value.length - 1]
  if (nextPath === undefined) {
    return
  }
  directoryForwardStack.value = directoryForwardStack.value.slice(0, -1)
  directoryBackStack.value = [...directoryBackStack.value, currentDir.value]
  navigateToDirectory(nextPath, false)
}

function goUpDirectory() {
  if (!currentDir.value) {
    return
  }
  navigateToDirectory(parentPath(currentDir.value))
}

async function refreshTree() {
  await workspaceStore.loadKnowledgeTree()
  if (currentDir.value && !workspaceStore.flatNodes.some((node) => node.path === currentDir.value && node.isDir)) {
    navigateToDirectory('', false)
  }
}

function selectSortKey(value: SortKey) {
  sortKey.value = value
}

function selectSortDirection(value: SortDirection) {
  sortDirection.value = value
  sortMenuOpen.value = false
}

function indexStatusLabel(node: KnowledgeFileNode): string {
  if (node.isDir) return '-'
  if (node.indexStatus === 'indexed' || node.indexStatus === 'clean') return '已入库'
  if (node.indexStatus === 'ignored') return '已屏蔽'
  if (node.indexStatus === 'failed') return '失败'
  if (node.indexStatus === 'indexing') return '入库中'
  return '待入库'
}

function semanticChunkKey(chunk: MultimodalSemanticChunk): string {
  return chunk.section_id || String(chunk.index)
}

function overlapChunkKey(chunk: MultimodalOverlapChunk): string {
  return String(chunk.index)
}

function isSemanticChunkCollapsed(chunk: MultimodalSemanticChunk): boolean {
  return collapsedSemanticChunkKeys.value.has(semanticChunkKey(chunk))
}

function isOverlapChunkCollapsed(chunk: MultimodalOverlapChunk): boolean {
  return collapsedOverlapChunkKeys.value.has(overlapChunkKey(chunk))
}

function toggleSemanticChunk(chunk: MultimodalSemanticChunk) {
  const key = semanticChunkKey(chunk)
  const next = new Set(collapsedSemanticChunkKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  collapsedSemanticChunkKeys.value = next
}

function toggleOverlapChunk(chunk: MultimodalOverlapChunk) {
  const key = overlapChunkKey(chunk)
  const next = new Set(collapsedOverlapChunkKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  collapsedOverlapChunkKeys.value = next
}

function closeObservationPane() {
  paneVisible.value = false
  if (loading.value) {
    abortController.value?.abort()
    loading.value = false
  }
}

async function openNode(node: KnowledgeFileNode) {
  selectedPath.value = node.path
  if (node.isDir) {
    navigateToDirectory(node.path)
    return
  }

  abortController.value?.abort()
  const controller = new AbortController()
  abortController.value = controller
  paneVisible.value = true
  loading.value = true
  error.value = ''
  observation.value = null
  activeObservationTab.value = 'markdown'
  collapsedSemanticChunkKeys.value = new Set()
  collapsedOverlapChunkKeys.value = new Set()
  sortMenuOpen.value = false

  try {
    observation.value = await fetchMultimodalIngestionObservation(settingsStore.profile.userId, node.path, controller.signal)
  } catch (err: unknown) {
    if (!(err instanceof DOMException && err.name === 'AbortError')) {
      error.value = err instanceof Error ? err.message : '加载多模态入库观测失败'
    }
  } finally {
    if (abortController.value === controller) {
      abortController.value = null
    }
    loading.value = false
  }
}

onMounted(() => {
  void refreshTree()
})

onBeforeUnmount(() => {
  abortController.value?.abort()
})
</script>

<template>
  <section class="multimodal-panel" :class="{ split: hasObservationPane }">
    <div class="file-browser" @click="sortMenuOpen = false">
      <div class="browser-toolbar" @click.stop>
        <div class="navigation-tools">
          <button class="icon-button" type="button" title="回退" :disabled="!canGoBack" @click="goBackDirectory">
            <IcIcon name="arrow-left" :size="15" />
          </button>
          <button class="icon-button" type="button" title="反回退" :disabled="!canGoForward" @click="goForwardDirectory">
            <IcIcon name="arrow-right" :size="15" />
          </button>
          <button class="icon-button" type="button" title="去上级文件夹" :disabled="!canGoUp" @click="goUpDirectory">
            <IcIcon name="arrow-up" :size="15" />
          </button>
        </div>
        <div class="path-label">{{ currentDirLabel }}</div>
        <div class="right-tools">
          <button
            class="icon-button"
            :class="{ active: settingsStore.showIndexColumn }"
            type="button"
            :title="settingsStore.showIndexColumn ? '隐藏索引状态' : '显示索引状态'"
            @click="settingsStore.setShowIndexColumn(!settingsStore.showIndexColumn)"
          >
            <IcIcon name="filter" :size="15" />
          </button>
          <div class="sort-control">
            <button
              class="icon-button"
              :class="{ active: sortMenuOpen }"
              type="button"
              title="排序"
              @click="sortMenuOpen = !sortMenuOpen"
            >
              <IcIcon name="sort" :size="15" />
            </button>
            <div v-if="sortMenuOpen" class="sort-menu" @click.stop>
              <button v-for="option in sortKeyOptions" :key="option.value" type="button" @click="selectSortKey(option.value)">
                <IcIcon v-if="sortKey === option.value" name="check" :size="14" />
                <span v-else class="sort-check-placeholder"></span>
                <span>{{ option.label }}</span>
              </button>
              <hr />
              <button
                v-for="option in sortDirectionOptions"
                :key="option.value"
                type="button"
                @click="selectSortDirection(option.value)"
              >
                <IcIcon v-if="sortDirection === option.value" name="check" :size="14" />
                <span v-else class="sort-check-placeholder"></span>
                <span>{{ option.label }}</span>
              </button>
            </div>
          </div>
          <button class="icon-button" type="button" title="刷新" :disabled="workspaceStore.treeLoading" @click="refreshTree">
            <IcIcon name="refresh" :size="15" />
          </button>
        </div>
      </div>

      <div class="file-table">
        <div class="file-header" :style="{ gridTemplateColumns: listGridColumns }">
          <span>名称</span>
          <span>最后修改日期</span>
          <span>类型</span>
          <span>大小</span>
          <span v-if="settingsStore.showIndexColumn">入库状态</span>
        </div>
        <button
          v-for="(node, index) in visibleItems"
          :key="node.path"
          class="file-row"
          :class="{ selected: selectedPath === node.path }"
          :style="{
            gridTemplateColumns: listGridColumns,
            animationDelay: `${Math.min(index, 24) * 18}ms`,
          }"
          type="button"
          @click="selectedPath = node.path"
          @dblclick="openNode(node)"
        >
          <span class="name-cell">
            <img class="material-file-icon" :src="materialFileIconForNode(node).src" alt="" aria-hidden="true" />
            <span class="file-name">{{ node.name }}</span>
          </span>
          <span>{{ displayMtime(node) }}</span>
          <span>{{ fileKind(node) }}</span>
          <span>{{ formatSize(nodeSize(node)) }}</span>
          <span v-if="settingsStore.showIndexColumn" class="status-cell">{{ indexStatusLabel(node) }}</span>
        </button>
      </div>
    </div>

    <aside class="observation-pane" :class="{ open: hasObservationPane }" :aria-hidden="!hasObservationPane">
      <div class="pane-title">
        <span>多模态入库</span>
        <strong>{{ observation?.name || selectedPath }}</strong>
        <button class="icon-button close-button" type="button" title="关闭侧边栏" @click="closeObservationPane">
          <IcIcon name="close" :size="15" />
        </button>
      </div>

      <div v-if="loading" class="empty-state">
        <IcIcon name="manage-search" :size="20" />
        <span>正在生成观测结果</span>
      </div>
      <div v-else-if="error" class="empty-state error">
        <span>{{ error }}</span>
      </div>
      <template v-else-if="observation">
        <div class="stats-row">
          <div class="stat-item">
            <span>结构章节</span>
            <strong>{{ observation.stats.section_count }}</strong>
          </div>
          <div class="stat-item">
            <span>重叠切片</span>
            <strong>{{ observation.stats.overlap_chunk_count }}</strong>
          </div>
          <div class="stat-item">
            <span>窗口/重叠</span>
            <strong>{{ observation.chunk_size }}/{{ observation.chunk_overlap }}</strong>
          </div>
        </div>

        <div ref="observationTabsRef" class="observation-tabs">
          <span class="observation-slider" :style="observationSliderStyle" aria-hidden="true"></span>
          <button
            class="observation-tab"
            :class="{ active: activeObservationTab === 'markdown' }"
            type="button"
            @click="activeObservationTab = 'markdown'"
          >
            Markdown 中间层
          </button>
          <button
            class="observation-tab"
            :class="{ active: activeObservationTab === 'json' }"
            type="button"
            @click="activeObservationTab = 'json'"
          >
            Json结构化结果
          </button>
          <button
            class="observation-tab"
            :class="{ active: activeObservationTab === 'semantic' }"
            type="button"
            @click="activeObservationTab = 'semantic'"
          >
            语义切块
          </button>
          <button
            class="observation-tab"
            :class="{ active: activeObservationTab === 'overlap' }"
            type="button"
            @click="activeObservationTab = 'overlap'"
          >
            重叠切片
          </button>
        </div>

        <MarkdownPreview
          v-if="activeObservationTab === 'markdown'"
          class="markdown-result-view"
          :content="observation.markdown_result"
          :path="observation.path"
        />
        <pre v-else-if="activeObservationTab === 'json'" class="json-view">{{ jsonText }}</pre>
        <div v-else-if="activeObservationTab === 'semantic'" class="chunk-list">
          <article
            v-for="chunk in observation.semantic_chunks"
            :key="chunk.section_id || chunk.index"
            class="chunk-card"
            :class="{ collapsed: isSemanticChunkCollapsed(chunk) }"
          >
            <header>
              <strong>{{ chunk.heading || `Section ${chunk.index + 1}` }}</strong>
              <span>{{ chunk.char_count }} chars · {{ chunk.start_char }}-{{ chunk.end_char }}</span>
              <button
                class="chunk-toggle"
                type="button"
                :title="isSemanticChunkCollapsed(chunk) ? '展开切片' : '关闭切片'"
                @click="toggleSemanticChunk(chunk)"
              >
                <IcIcon name="chevron-down" :size="14" />
              </button>
            </header>
            <div class="chunk-body">
              <div class="chunk-body-inner">
                <small>{{ chunk.title_path.join(' / ') }}</small>
                <pre>{{ chunk.content }}</pre>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="chunk-list">
          <article
            v-for="chunk in observation.overlap_chunks"
            :key="chunk.index"
            class="chunk-card"
            :class="{ collapsed: isOverlapChunkCollapsed(chunk) }"
          >
            <header>
              <strong>#{{ chunk.index + 1 }} · {{ chunk.section_heading }}</strong>
              <span>overlap {{ chunk.overlap_chars }} · {{ chunk.chunk_start_char }}-{{ chunk.chunk_end_char }}</span>
              <button
                class="chunk-toggle"
                type="button"
                :title="isOverlapChunkCollapsed(chunk) ? '展开切片' : '关闭切片'"
                @click="toggleOverlapChunk(chunk)"
              >
                <IcIcon name="chevron-down" :size="14" />
              </button>
            </header>
            <div class="chunk-body">
              <div class="chunk-body-inner">
                <small>{{ JSON.stringify(chunk.source_range) }}</small>
                <pre>{{ chunk.ingestion_content }}</pre>
              </div>
            </div>
          </article>
        </div>
      </template>
    </aside>
  </section>
</template>

<style scoped>
.multimodal-panel {
  position: relative;
  --observation-pane-width: clamp(420px, 58%, calc(100% - 340px));
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  gap: 0;
  background: var(--color-bg-app);
  overflow: hidden;
}

.file-browser,
.observation-pane {
  min-height: 0;
  border: 0;
  border-radius: 28px;
  background: var(--color-surface-raised);
  box-shadow: 0 0 0 4px var(--library-form-ring);
  overflow: hidden;
}

.file-browser {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: auto;
  margin: 4px;
  padding-right: 0;
  transition: padding-right 260ms ease;
}

.multimodal-panel.split .file-browser {
  padding-right: var(--observation-pane-width);
}

.browser-toolbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-8);
  border-bottom: 0;
}

.navigation-tools,
.right-tools {
  display: flex;
  align-items: center;
  gap: 2px;
}

.icon-button {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.icon-button:hover:not(:disabled),
.icon-button.active {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}
.icon-button:hover:not(:disabled) :deep(svg) { transform: rotate(90deg); }
.icon-button :deep(svg) { transition: transform 0.3s; }

.icon-button:disabled {
  cursor: default;
  opacity: 0.38;
}

.path-label {
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sort-control {
  position: relative;
}

.sort-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 20;
  min-width: 150px;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: 0 14px 30px color-mix(in srgb, var(--color-text) 12%, transparent);
}

.sort-menu button {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  width: 100%;
  align-items: center;
  gap: var(--space-6);
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: var(--font-size-xs);
  text-align: left;
  cursor: pointer;
}

.sort-menu button:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.sort-menu hr {
  height: 1px;
  margin: 5px 0;
  border: 0;
  background: var(--color-border);
}

.sort-check-placeholder {
  width: 14px;
  height: 14px;
}

.file-table {
  min-height: 0;
  overflow: auto;
}

.file-header,
.file-row {
  display: grid;
  align-items: center;
  gap: var(--space-10);
  min-width: 660px;
}

.file-header {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 9px var(--space-12);
  border-bottom: 0;
  background: var(--color-surface-raised);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.file-row {
  width: 100%;
  min-height: 38px;
  padding: 0 var(--space-12);
  border: 0;
  border-bottom: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: var(--font-size-xs);
  text-align: left;
  cursor: pointer;
  animation: file-row-enter 180ms ease both;
}

.file-row:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.file-row.selected {
  background: var(--color-primary-soft);
  color: var(--color-text);
}

.name-cell {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: var(--space-8);
}

.material-file-icon {
  display: block;
  width: 16px;
  height: 16px;
  object-fit: contain;
}

.file-name,
.status-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.observation-pane {
  position: absolute;
  top: 4px;
  right: 4px;
  bottom: 4px;
  display: flex;
  flex-direction: column;
  width: var(--observation-pane-width);
  border-left: 0;
  transform: translateX(100%);
  transition: transform 260ms ease;
  pointer-events: none;
  will-change: transform;
}

.observation-pane.open {
  transform: translateX(0);
  pointer-events: auto;
}

.pane-title {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 28px;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-10) var(--space-12);
  border-bottom: 0;
  color: var(--color-text);
}

.pane-title span {
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.pane-title strong {
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.close-button {
  justify-self: end;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-8);
  padding: var(--space-10) var(--space-12);
}

.stat-item {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-12);
  border: 0;
  border-radius: 18px;
  background: var(--color-canvas-soft);
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}

.stat-item strong {
  color: var(--color-primary);
  font-size: var(--font-size-lg);
}

.observation-tabs {
  position: relative;
  display: flex;
  gap: 2px;
  align-self: flex-start;
  margin: 0 var(--space-12) var(--space-8);
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-raised);
}

.observation-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  transition: left 250ms ease, width 250ms ease;
  pointer-events: none;
}

.observation-tab {
  position: relative;
  z-index: 1;
  height: 28px;
  border: 0;
  border-radius: 999px;
  padding: 0 10px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: var(--font-size-xs);
  cursor: pointer;
}

.observation-tab:hover {
  color: var(--color-primary);
}

.observation-tab.active {
  color: var(--color-primary);
}

.json-view,
.markdown-result-view,
.chunk-list {
  flex: 1 1 auto;
  min-height: 0;
  margin: 0;
  padding: var(--space-12);
  overflow: auto;
}

.json-view,
.chunk-card pre {
  color: var(--color-text);
  font-family: var(--font-text);
  font-size: var(--font-size-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.chunk-card {
  flex: 0 0 auto;
  border: 0;
  border-radius: 18px;
  background: var(--color-canvas-soft);
  overflow: hidden;
}

.chunk-card header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 24px;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-8) var(--space-10);
  border-bottom: 0;
}

.chunk-card strong {
  overflow: hidden;
  color: var(--color-text);
  font-size: var(--font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-card header span,
.chunk-card small {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.empty-state {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: var(--space-8);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.empty-state.error {
  color: var(--color-danger);
}

@media (max-width: 980px) {
  .multimodal-panel {
    flex-direction: column;
    overflow: auto;
  }

  .multimodal-panel.split .file-browser {
    padding-right: 0;
  }

  .observation-pane {
    position: relative;
    inset: auto;
    width: calc(100% - 8px);
    min-height: 420px;
    margin: 4px;
    border-left: 0;
  }
}

.chunk-toggle {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.chunk-toggle:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.chunk-toggle svg {
  transition: transform 180ms ease;
}

.chunk-card.collapsed .chunk-toggle svg {
  transform: rotate(-90deg);
}

.chunk-body {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition:
    grid-template-rows 220ms ease,
    opacity 160ms ease;
}

.chunk-card.collapsed .chunk-body {
  grid-template-rows: 0fr;
  opacity: 0;
}

.chunk-body-inner {
  min-height: 0;
  overflow: hidden;
}

.chunk-card small {
  display: block;
  padding: var(--space-8) var(--space-10) 0;
}

.chunk-card pre {
  margin: 0;
  padding: var(--space-8) var(--space-10) var(--space-10);
}

@keyframes file-row-enter {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
