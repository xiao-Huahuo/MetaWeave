<!--
  Markdown HTML visualization workspace page.

  Usage:
  Provides a visible page for configuring the Agent document visualization
  workflow and for mounting the generated runtime HTML.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import FloatingFileResourcePicker from '@/components/editor_workspace/FloatingFileResourcePicker.vue'
import { materialFileIconForNode } from '@/components/editor_workspace/materialFileIcons'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuPortal,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useSettingsStore } from '@/stores/settings'
import { useTaskListStore } from '@/stores/taskList'
import { useWorkspaceStore } from '@/stores/workspace'
import type { MarkdownHtmlVisualizationOptions, MarkdownHtmlVisualizationPreset } from '@/types/knowledge'

const settingsStore = useSettingsStore()
const taskListStore = useTaskListStore()
const workspaceStore = useWorkspaceStore()
const modeSwitchRef = ref<HTMLElement | null>(null)
const modeSliderStyle = ref({ width: '0px', left: '0px' })
const pickerOpen = ref(false)
const advancedOptionsOpen = ref(false)
const advancedOptionsPage = ref<'layout' | 'visual' | 'motion'>('layout')
const taskProgressCardVisible = ref(false)
const taskProgressExpanded = ref(false)
const visualizationStarting = ref(false)

const visualizationPresets: Array<{ value: MarkdownHtmlVisualizationPreset; label: string }> = [
  { value: 'balanced', label: '均衡展示' },
  { value: 'reader', label: '阅读导向' },
  { value: 'dashboard', label: '仪表盘导向' },
  { value: 'magazine', label: '杂志导向' },
]

const advancedOptionPages: Array<{ value: typeof advancedOptionsPage.value; label: string }> = [
  { value: 'layout', label: '结构' },
  { value: 'visual', label: '视觉' },
  { value: 'motion', label: '动效' },
]

const visualizationOptionGroups: Record<typeof advancedOptionsPage.value, Array<{ key: keyof MarkdownHtmlVisualizationOptions; label: string }>> = {
  layout: [
    { key: 'visualHierarchy', label: '视觉层级' },
    { key: 'gridLayout', label: '网格系统' },
    { key: 'callouts', label: '重点标注' },
    { key: 'denseLayout', label: '高信息密度' },
  ],
  visual: [
    { key: 'typographyScale', label: '字体层级' },
    { key: 'contrast', label: '对比度' },
    { key: 'accentColor', label: '强调色' },
    { key: 'shadow', label: '阴影' },
    { key: 'rounded', label: '圆角' },
  ],
  motion: [
    { key: 'microInteractions', label: '微交互' },
    { key: 'scrollReveal', label: '滚动揭示' },
    { key: 'strongMotion', label: '强动效' },
    { key: 'emoji', label: 'emoji' },
  ],
}

const currentVisualizationOptions = computed(() => {
  return visualizationOptionGroups[advancedOptionsPage.value]
})

const taskStatusLabels: Record<string, string> = {
  pending: '等待',
  in_progress: '进行中',
  completed: '完成',
  failed: '失败',
}

const selectedDocumentName = computed(() => {
  const node = workspaceStore.selectedNode
  if (!node || node.isDir) {
    return ''
  }
  return node.name
})

const selectedDocumentIcon = computed(() => {
  const node = workspaceStore.selectedNode
  if (!node || node.isDir) {
    return ''
  }
  return materialFileIconForNode(node).src
})

const knowledgeSaveDirectory = computed(() => {
  const userId = workspaceStore.markdownHtmlVisualization
    ? settingsStore.profile.userId
    : ''
  return userId ? `${userId}_html/` : '{user_id}_html/'
})

const hasMountedVisualization = computed(() => {
  return Boolean(workspaceStore.markdownHtmlVisualizationOpen && workspaceStore.markdownHtmlVisualization)
})

const showVisualizationResult = computed(() => hasMountedVisualization.value && !visualizationStarting.value)

const visualizationActionLabel = computed(() => {
  return hasMountedVisualization.value ? '重新可视化' : '一键可视化'
})

const showTaskProgressCard = computed(() => {
  return taskProgressCardVisible.value
    && !hasMountedVisualization.value
    && taskListStore.taskList !== null
    && taskListStore.taskList.status !== 'completed'
})

const taskProgressText = computed(() => {
  const total = taskListStore.taskList?.items.length ?? 0
  return `${taskListStore.completedCount}/${total}`
})

const taskProgressPercent = computed(() => {
  const total = taskListStore.taskList?.items.length ?? 0
  if (total <= 0) return 0
  return Math.round((taskListStore.completedCount / total) * 100)
})

const taskProgressTitle = computed(() => {
  return taskListStore.taskList?.title || 'Agent 任务列表'
})

const taskProgressCurrent = computed(() => {
  return taskListStore.currentItem?.title || '等待 Agent 更新任务进度'
})

watch(() => taskListStore.eventSerial, () => {
  if (taskListStore.lastEventType === 'created' || taskListStore.lastEventType === 'updated') {
    if (taskListStore.lastEventType === 'created') {
      taskProgressExpanded.value = false
    }
    taskProgressCardVisible.value = true
    return
  }
  taskProgressCardVisible.value = false
})

watch(hasMountedVisualization, (mounted) => {
  if (mounted) {
    taskProgressCardVisible.value = false
  }
})

function updateModeSlider() {
  nextTick(() => {
    const container = modeSwitchRef.value
    if (!container) return
    const active = container.querySelector('.mode-button.active') as HTMLElement | null
    if (!active) return
    modeSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

function setMode(mode: 'structure' | 'insight') {
  workspaceStore.setMarkdownHtmlVisualizationMode(mode)
  updateModeSlider()
}

onMounted(updateModeSlider)

function setPreset(preset: MarkdownHtmlVisualizationPreset) {
  workspaceStore.setMarkdownHtmlVisualizationPreset(preset)
}

function setOption(key: keyof MarkdownHtmlVisualizationOptions, event: Event) {
  workspaceStore.setMarkdownHtmlVisualizationOption(key, (event.target as HTMLInputElement).checked)
}

function setCustomRequirement(event: Event) {
  workspaceStore.setMarkdownHtmlVisualizationCustomRequirement((event.target as HTMLTextAreaElement).value)
}

async function startVisualization() {
  if (!workspaceStore.selectedNode || workspaceStore.selectedNode.isDir || workspaceStore.refreshing) {
    return
  }
  visualizationStarting.value = true
  try {
    await workspaceStore.startMarkdownHtmlVisualization()
  } catch {
    visualizationStarting.value = false
  }
}

async function openSelectedFileInEditorSidebar(): Promise<void> {
  const node = workspaceStore.selectedNode
  if (!node || node.isDir) return
  await workspaceStore.openEditorSidebar(node)
}

watch(() => workspaceStore.markdownHtmlVisualization, (visualization) => {
  if (visualization) {
    visualizationStarting.value = false
  }
})
</script>

<template>
  <section class="visualization-page">
    <header class="visualization-toolbar">
      <div ref="modeSwitchRef" class="mode-pill">
        <div class="mode-slider" :style="modeSliderStyle"></div>
        <button
          type="button"
          class="mode-button"
          aria-label="原结构模式"
          title="原结构模式"
          :class="{ active: workspaceStore.markdownHtmlVisualizationMode === 'structure' }"
          @click="setMode('structure')"
        >
          <IcIcon name="view-column" :size="17" />
          <span>原结构模式</span>
        </button>
        <button
          type="button"
          class="mode-button"
          aria-label="AI提炼模式"
          title="AI提炼模式"
          :class="{ active: workspaceStore.markdownHtmlVisualizationMode === 'insight' }"
          @click="setMode('insight')"
        >
          <IcIcon name="auto-awesome" :size="17" />
          <span>AI提炼模式</span>
        </button>
      </div>
      <div class="toolbar-actions">
        <button type="button" class="tool-button v1-icon-button" title="选择文件" aria-label="选择文件" @click="pickerOpen = true">
          <IcIcon name="folder-open" :size="15" />
        </button>
        <DropdownMenu v-model:open="advancedOptionsOpen">
          <DropdownMenuTrigger as-child>
            <button class="filter-capsule-btn" type="button" aria-label="高级选项" title="高级选项">
              <IcIcon name="tune" :size="17" />
              <span>高级选项</span>
              <IcIcon class="filter-chevron" name="chevron-down" :size="14" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="md-html-advanced-menu" align="end">
            <section class="advanced-section">
              <span class="advanced-section-title">展示预设</span>
              <div class="preset-grid" aria-label="HTML 可视化展示预设">
                <button
                  v-for="preset in visualizationPresets"
                  :key="preset.value"
                  type="button"
                  :class="{ active: workspaceStore.markdownHtmlVisualizationPreset === preset.value }"
                  @click.stop="setPreset(preset.value)"
                >
                  {{ preset.label }}
                </button>
              </div>
            </section>
            <section class="advanced-section">
              <div class="advanced-page-tabs" aria-label="高级选项分页">
                <button
                  v-for="page in advancedOptionPages"
                  :key="page.value"
                  type="button"
                  :class="{ active: advancedOptionsPage === page.value }"
                  @click.stop="advancedOptionsPage = page.value"
                >
                  {{ page.label }}
                </button>
              </div>
              <div class="option-row">
                <label v-for="option in currentVisualizationOptions" :key="option.key">
                  <input
                    type="checkbox"
                    :checked="workspaceStore.markdownHtmlVisualizationOptions[option.key]"
                    @change="setOption(option.key, $event)"
                    @click.stop
                  />
                  <span>{{ option.label }}</span>
                </label>
              </div>
            </section>
            <label class="custom-requirement-field">
              <span>自定义要求</span>
              <textarea
                rows="3"
                placeholder="例如: 更像论文导读, 减少装饰, 突出关键结论"
                :value="workspaceStore.markdownHtmlVisualizationCustomRequirement"
                @input="setCustomRequirement"
                @click.stop
              ></textarea>
            </label>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenu>
        <button
          type="button"
          class="visualize-button"
          :aria-label="visualizationActionLabel"
          :title="visualizationActionLabel"
          :disabled="!workspaceStore.selectedNode || workspaceStore.selectedNode.isDir || workspaceStore.refreshing"
          @click="startVisualization"
        >
          <IcIcon name="play" :size="15" />
          <span>{{ visualizationActionLabel }}</span>
        </button>
      </div>
    </header>

    <Transition name="task-progress-float">
      <aside v-if="showTaskProgressCard" class="task-progress-card" aria-live="polite">
        <div class="task-progress-head">
          <div>
            <span>{{ taskProgressTitle }}</span>
            <strong>{{ taskProgressText }}</strong>
          </div>
          <button
            type="button"
            class="task-progress-toggle"
            :aria-expanded="taskProgressExpanded"
            @click="taskProgressExpanded = !taskProgressExpanded"
          >
            <IcIcon name="chevron-down" :size="14" />
          </button>
        </div>
        <div class="task-progress-bar" aria-hidden="true">
          <span :style="{ width: `${taskProgressPercent}%` }"></span>
        </div>
        <p>{{ taskProgressCurrent }}</p>
        <Transition name="task-list-expand">
          <ol v-if="taskProgressExpanded" class="task-progress-list">
            <li
              v-for="item in taskListStore.taskList?.items ?? []"
              :key="item.id"
              :class="`status-${item.status}`"
            >
              <span>{{ item.title }}</span>
              <strong>{{ taskStatusLabels[item.status] ?? item.status }}</strong>
            </li>
          </ol>
        </Transition>
      </aside>
    </Transition>

    <section
      v-if="showVisualizationResult"
      class="visualization-result"
    >
      <header class="result-header">
        <div class="result-title">
          <strong>{{ workspaceStore.markdownHtmlVisualization.title }}</strong>
          <span>{{ workspaceStore.markdownHtmlVisualization.filename }}</span>
        </div>
        <div class="result-actions">
          <button
            type="button"
            :title="`保存到知识库 ${knowledgeSaveDirectory}`"
            @click="workspaceStore.saveMarkdownHtmlVisualizationToKnowledge"
          >
            <IcIcon name="download" :size="15" />
          </button>
          <button type="button" title="打开系统资源管理器保存" @click="workspaceStore.revealMarkdownHtmlVisualization">
            <IcIcon name="folder-open" :size="15" />
          </button>
          <button type="button" title="关闭" @click="workspaceStore.closeMarkdownHtmlVisualization">
            <IcIcon name="close" :size="15" />
          </button>
        </div>
      </header>
      <iframe
        class="result-frame"
        :src="workspaceStore.markdownHtmlVisualizationUrl"
        sandbox="allow-scripts allow-same-origin"
      ></iframe>
    </section>

    <section v-else class="visualization-empty">
      <template v-if="visualizationStarting">
        <LoadingState class="visualization-pixel-loader" variant="Drive" :show-label="false" :show-elapsed="false" />
        <strong>正在进行可视化...</strong>
      </template>
      <template v-else-if="selectedDocumentName">
        <button
          class="selected-file-card"
          type="button"
          :aria-label="`双击在编辑区侧边栏打开 ${selectedDocumentName}`"
          @dblclick="openSelectedFileInEditorSidebar"
        >
          <img class="selected-file-icon" :src="selectedDocumentIcon" alt="" aria-hidden="true" />
          <span class="selected-file-card-name" :title="selectedDocumentName">{{ selectedDocumentName }}</span>
          <span class="selected-file-card-hint">双击打开编辑区侧边栏</span>
        </button>
      </template>
      <template v-else>
        <IcIcon name="code" :size="28" />
        <strong>还没有生成 HTML 可视化</strong>
        <span>右键文件选择“HTML可视化”，或在本页选择文件后再一键可视化。</span>
      </template>
    </section>

    <FloatingFileResourcePicker v-if="pickerOpen" @close="pickerOpen = false" />
  </section>
</template>

<style scoped>
.visualization-page {
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-canvas-soft);
}

.visualization-toolbar,
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  min-width: 0;
  border-bottom: 0;
  background: var(--color-canvas);
}

.visualization-toolbar {
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
  font-size: calc(12px * var(--font-scale));
}

.result-title strong,
.result-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-pill {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  flex-shrink: 0;
}

.mode-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-softer);
  transition: left 250ms ease, width 250ms ease;
  z-index: 0;
  pointer-events: none;
}

.mode-button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  height: 28px;
  padding: 0 var(--space-8);
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  outline: none;
  white-space: nowrap;
}

.mode-button:hover {
  color: var(--color-primary);
}

.mode-button.active {
  color: var(--color-primary);
}

.toolbar-actions button,
.preset-grid button,
.advanced-page-tabs button,
.result-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.preset-grid button,
.advanced-page-tabs button {
  padding: 0 var(--space-8);
  border-radius: var(--radius-sm);
}

.preset-grid button:hover,
.advanced-page-tabs button:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.toolbar-actions > button {
  padding: 0 var(--space-8);
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: white;
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  flex: 0 0 auto;
}

.toolbar-actions > button.visualize-button {
  border-color: var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary);
  color: #fff;
  font: inherit;
}

.toolbar-actions > button.visualize-button:hover:not(:disabled) {
  border-color: var(--color-primary-hover, var(--color-primary));
  background: var(--color-primary-hover, var(--color-primary));
  color: #fff;
}

.toolbar-actions > button.tool-button {
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
}

.toolbar-actions > button.tool-button:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.toolbar-actions > button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.md-html-advanced-menu {
  display: grid;
  gap: var(--space-12);
  width: 360px;
  padding: var(--space-12);
  max-height: min(520px, var(--reka-dropdown-menu-content-available-height));
  overflow-y: auto;
}

.advanced-section {
  display: grid;
  gap: var(--space-8);
  min-width: 0;
}

.advanced-section-title {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  font-weight: 650;
}

.preset-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.advanced-page-tabs {
  display: inline-grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}

.preset-grid button.active,
.advanced-page-tabs button.active {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: white;
}

.option-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-12);
  min-width: 0;
}

.option-row label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  min-height: 28px;
  padding: 0 var(--space-8);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.option-row label:hover {
  border-color: color-mix(in srgb, var(--color-primary) 32%, transparent);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.option-row input {
  width: 14px;
  height: 14px;
  accent-color: var(--color-primary);
}

.custom-requirement-field {
  display: grid;
  gap: var(--space-6);
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
}

.custom-requirement-field textarea {
  width: 100%;
  min-width: 0;
  min-height: 68px;
  resize: vertical;
  border: 1px solid var(--color-border);
  border-radius: 28px;
  padding: var(--space-8);
  background: var(--color-canvas);
  color: var(--color-text);
  font: inherit;
  line-height: 1.45;
}

.custom-requirement-field textarea:focus {
  border-color: var(--color-primary);
  outline: none;
}

.task-progress-card {
  position: absolute;
  top: calc(52px + var(--space-12));
  right: var(--space-16);
  z-index: 20;
  display: grid;
  gap: var(--space-8);
  width: min(340px, calc(100% - 32px));
  padding: var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
  color: var(--color-text);
}

.task-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  min-width: 0;
}

.task-progress-head div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.task-progress-head span,
.task-progress-card p {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-head span {
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
  font-weight: 650;
}

.task-progress-head strong,
.task-progress-list strong {
  color: var(--color-primary);
  font-size: calc(11px * var(--font-scale));
  font-weight: 650;
}

.task-progress-toggle {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast);
}

.task-progress-toggle[aria-expanded="true"] {
  color: var(--color-primary);
  transform: rotate(180deg);
}

.task-progress-bar {
  height: 3px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.task-progress-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
  transition: width 220ms ease;
}

.task-progress-card p {
  margin: 0;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.task-progress-list {
  display: grid;
  gap: var(--space-6);
  max-height: 180px;
  margin: 0;
  padding: var(--space-4) 0 0;
  overflow: auto;
  list-style: none;
}

.task-progress-list li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-8);
  min-height: 26px;
  padding: 0 var(--space-8);
  border-left: 2px solid var(--color-border);
  background: var(--color-canvas-soft);
}

.task-progress-list li.status-completed {
  border-left-color: var(--color-success);
}

.task-progress-list li.status-in_progress {
  border-left-color: var(--color-primary);
}

.task-progress-list li.status-failed {
  border-left-color: var(--color-danger);
}

.task-progress-list span {
  overflow: hidden;
  color: var(--color-text);
  font-size: calc(11px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-float-enter-active,
.task-progress-float-leave-active,
.task-list-expand-enter-active,
.task-list-expand-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms ease;
}

.task-progress-float-enter-from,
.task-progress-float-leave-to,
.task-list-expand-enter-from,
.task-list-expand-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.visualization-result {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  margin: var(--space-12);
  overflow: hidden;
  border: 0;
  border-radius: var(--radius-md);
  background: var(--color-canvas);
}

.result-header {
  min-height: 38px;
  padding: 0 var(--space-10);
}

.result-title {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.result-title strong {
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
}

.result-title span {
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
}

.result-actions {
  display: inline-flex;
  gap: var(--space-4);
  flex: 0 0 auto;
}

.result-actions button {
  width: 26px;
  padding: 0;
  color: var(--color-text-muted);
}

.result-actions button:hover {
  border-color: var(--color-primary);
  color: var(--color-text);
}

.result-frame {
  flex: 1;
  min-width: 0;
  min-height: 0;
  border: 0;
  background: white;
}

.visualization-empty {
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--space-8);
  min-width: 0;
  min-height: 0;
  padding: var(--space-16);
  color: var(--color-text-muted);
  text-align: center;
}

.selected-file-card {
  display: grid;
  grid-template-rows: minmax(112px, 1fr) auto auto;
  align-items: center;
  justify-items: center;
  gap: var(--space-8);
  width: min(220px, calc(100vw - 48px));
  min-height: 210px;
  padding: var(--space-12);
  border: 1px solid transparent;
  border-radius: 28px;
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    box-shadow var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast);
}

.selected-file-card:hover {
  border-color: color-mix(in srgb, var(--color-primary) 32%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  box-shadow: 0 10px 24px color-mix(in srgb, var(--color-primary) 12%, transparent);
  color: var(--color-primary);
  transform: translateY(-2px);
}

.selected-file-card:focus-visible {
  border-color: var(--color-primary);
  outline: 2px solid color-mix(in srgb, var(--color-primary) 32%, transparent);
  outline-offset: 2px;
}

.selected-file-icon {
  width: 112px;
  height: 112px;
  object-fit: contain;
}

.selected-file-card-name {
  width: 100%;
  overflow: hidden;
  color: var(--color-primary);
  font-size: calc(13px * var(--font-scale));
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
}

.selected-file-card-hint {
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.visualization-pixel-loader {
  min-height: 16px;
}

.visualization-empty strong {
  color: var(--color-text);
  font-size: calc(14px * var(--font-scale));
}

.visualization-empty span {
  font-size: calc(12px * var(--font-scale));
}

@media (max-width: 780px) {
  .visualization-toolbar {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-8);
    padding: var(--space-8) var(--space-10);
  }

  .mode-pill {
    align-self: flex-start;
  }

  .toolbar-actions {
    display: grid;
    grid-template-columns: 28px auto auto;
    align-items: center;
    justify-content: end;
  }

  .md-html-advanced-menu {
    width: min(360px, calc(100vw - 100px));
    max-height: calc(100vh - 132px);
  }

  .toolbar-actions > button {
    width: auto;
  }

  .task-progress-card {
    top: calc(84px + var(--space-12));
  }
}

@media (max-width: 420px) {
  .mode-pill {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .mode-button {
    min-width: 0;
  }
}

@media (max-width: 360px) {
  .toolbar-actions {
    grid-template-columns: repeat(3, 28px);
  }

  .filter-capsule-btn,
  .toolbar-actions > button.visualize-button {
    width: 28px;
    padding: 0;
  }

  .mode-button span,
  .filter-capsule-btn span,
  .filter-capsule-btn .filter-chevron,
  .toolbar-actions > button.visualize-button span {
    display: none;
  }
}
</style>
