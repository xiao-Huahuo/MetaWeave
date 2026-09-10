<!--
  Language trace and context assembly panel.

  Usage:
  AgentTracePanel renders this component twice: once for the thinking language
  trace and once for the context assembly view.
-->

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import ThinkingSteps from '@/components/chat/ThinkingSteps.vue'
import DropdownSelect from '@/components/ui/dropdown-menu/DropdownSelect.vue'
import { buildExactRequestAssembly, useObsData, type AssemblyBlock } from '@/composable/useObsData'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'

const props = withDefaults(defineProps<{
  mode?: 'trace' | 'context'
}>(), {
  mode: 'trace',
})

const contextMode = ref<'raw' | 'readable'>('readable')
const contextToggleRef = ref<HTMLElement | null>(null)
const contextSliderStyle = ref({ width: '0px', left: '0px' })
const obs = useObsData()
const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const selectedCallIndex = ref(0)

/** Keeps the Debug toggle slider aligned with the active mode button. */
function updateContextSlider(): void {
  void nextTick(() => {
    const active = contextToggleRef.value?.querySelector<HTMLElement>('.mode-button.active')
    if (!active) return
    contextSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

onMounted(updateContextSlider)
watch(contextMode, updateContextSlider)

const cardTitle = computed(() => props.mode === 'trace' ? '语言轨迹' : '上下文拼装')

const thinkingModeLabel = computed(() => {
  const mode = chatStore.activeAgentMode !== 'auto' ? chatStore.activeAgentMode : settingsStore.agentLoopMode
  const labels: Record<string, string> = {
    auto: '自动',
    simple: '简单',
    react: 'ReAct',
    plan: '规划',
  }
  return labels[mode] ?? mode
})

const contextSnapshots = computed(() => obs.contextSnapshots.value)
const contextCallOptions = computed(() => contextSnapshots.value.map((snapshot, index) => ({
  value: index,
  label: `#${snapshot.call_index} ${snapshot.node} · ${snapshot.model}`,
})))
watch(() => contextSnapshots.value.length, (length) => {
  selectedCallIndex.value = Math.max(0, length - 1)
}, { immediate: true })
const selectedSnapshot = computed(() => contextSnapshots.value[selectedCallIndex.value])
const contextAssemblyState = computed(() => selectedSnapshot.value
  ? buildExactRequestAssembly(selectedSnapshot.value)
  : {
  blocks: [],
  stats: { blockCount: 0, lineCount: 0, memoryCount: 0, knowledgeCount: 0 },
})

const assemblyBlocks = computed<AssemblyBlock[]>(() => contextAssemblyState.value.blocks)

const rawContextJson = computed(() => {
  return selectedSnapshot.value ? JSON.stringify(selectedSnapshot.value, null, 2) : ''
})
</script>

<template>
  <section class="trace-card">
    <div class="panel-heading">
      <h3>{{ cardTitle }}</h3>
    </div>

    <div class="panel-surface" :class="{ 'trace-surface': props.mode === 'trace' }">
      <span v-if="props.mode === 'trace'" class="mode-pill">思考模式 {{ thinkingModeLabel }}</span>

      <div v-if="props.mode === 'trace'" class="card-scroll trace-view">
        <ThinkingSteps
          v-if="obs.currentMessageThinkingTraces.value.length > 0"
          :traces="obs.currentMessageThinkingTraces.value"
          :is-streaming="obs.isStreaming.value"
          :default-expanded="true"
        />
        <div v-else class="empty-state">
          <span class="placeholder-text">$ 等待 Agent 生成可观察的思考轨迹</span>
        </div>
      </div>

      <div v-else class="card-scroll context-view">
        <div class="context-toolbar">
          <div ref="contextToggleRef" class="context-mode-toggle">
            <span class="context-mode-slider" :style="contextSliderStyle" aria-hidden="true"></span>
            <button
              class="mode-button"
              :class="{ active: contextMode === 'readable' }"
              type="button"
              @click="contextMode = 'readable'"
            >
              可读格式
            </button>
            <button
              class="mode-button"
              :class="{ active: contextMode === 'raw' }"
              type="button"
              @click="contextMode = 'raw'"
            >
              Raw
            </button>
          </div>
          <DropdownSelect
            v-if="contextSnapshots.length > 0"
            v-model="selectedCallIndex"
            class="call-select"
            aria-label="选择模型调用"
            :options="contextCallOptions"
          />
        </div>

        <div v-if="contextMode === 'readable'" class="source-groups">
          <div class="assembly-overview">
            <div class="metric-row">
              <span class="metric-label">消息</span>
              <span class="metric-value">{{ selectedSnapshot?.messages.length ?? 0 }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">工具定义</span>
              <span class="metric-value">{{ selectedSnapshot?.tools.length ?? 0 }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">模型层级</span>
              <span class="metric-value metric-text">{{ selectedSnapshot?.model_tier ?? '—' }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">有效窗口</span>
              <span class="metric-value">{{ selectedSnapshot?.context_budget?.effective_window_tokens ?? 0 }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">最终输入</span>
              <span class="metric-value">{{ selectedSnapshot?.context_budget?.final_input_tokens ?? 0 }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">表示降级</span>
              <span class="metric-value">{{ selectedSnapshot?.context_budget?.representations?.filter(item => item.representation !== 'full').length ?? 0 }}</span>
            </div>
          </div>

          <div v-if="assemblyBlocks.length > 0" class="assembly-list">
            <div
              v-for="block in assemblyBlocks"
              :key="block.id"
              class="assembly-block"
              :style="{ '--source-accent': block.accent }"
            >
              <div class="assembly-header">
                <div class="assembly-meta">
                  <span class="assembly-order">#{{ block.order }}</span>
                  <span class="source-dot"></span>
                  <span class="assembly-title">{{ block.title }}</span>
                </div>
                <div class="assembly-status">
                  <span class="assembly-kind">{{ block.status }}</span>
                  <span class="assembly-count">{{ block.lineCount }} 行</span>
                </div>
              </div>

              <div class="assembly-body">
                <p
                  v-for="(line, lineIndex) in block.lines"
                  :key="`${block.id}-${lineIndex}`"
                  class="source-text"
                >
                  {{ line }}
                </p>
              </div>
            </div>
          </div>

          <div v-else class="empty-state">
            <span class="placeholder-text">$ 当前轮次尚未调用模型，没有可展示的最终请求</span>
          </div>
        </div>

        <pre v-else class="raw-context"><code>{{ rawContextJson || '$ 当前轮次没有模型请求' }}</code></pre>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trace-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.panel-heading {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 30px;
  padding: 0 2px var(--space-6);
}

.panel-heading h3 {
  margin: 0;
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}

.panel-surface {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 0;
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: 0 0 0 4px var(--library-form-ring);
  margin-inline: 4px;
}

.trace-surface {
  padding-top: 30px;
}

.mode-pill {
  position: absolute;
  top: var(--space-8);
  right: var(--space-10);
  z-index: 2;
  padding: 3px 10px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 32%, var(--color-border));
  border-radius: 999px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  line-height: 1.2;
}

.card-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-10);
}

.trace-view {
  padding-top: 0;
}

.summary-label,
.summary-value,
.source-title,
.source-count,
.placeholder-text,
.metric-label,
.metric-value {
  font-family: var(--font-ui);
}

.source-text,
.raw-context {
  font-family: var(--font-text);
}

.context-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-10);
}

.context-mode-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
}

.context-mode-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  transition: left 250ms ease, width 250ms ease;
  z-index: 0;
  pointer-events: none;
}

:deep(.call-select.ui-dropdown-select-trigger) {
  min-width: 160px;
  height: 28px;
  margin-left: auto;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  background: var(--color-canvas);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

:deep(.call-select.ui-dropdown-select-trigger:hover) {
  border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
  color: var(--color-primary);
}

:deep(.call-select.ui-dropdown-select-trigger[data-state='open']) {
  border-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

:deep(.call-select.ui-dropdown-select-trigger > svg) {
  opacity: 0.62;
  transition: transform var(--transition-fast);
}

:deep(.call-select.ui-dropdown-select-trigger[data-state='open'] > svg) {
  transform: rotate(180deg);
}

.mode-button {
  position: relative;
  z-index: 1;
  border: 0;
  border-radius: 999px;
  height: 28px;
  padding: 0 8px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  transition: color var(--transition-fast);
}

.mode-button:hover {
  color: var(--color-primary);
}

.mode-button.active {
  color: var(--color-primary);
}

.source-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.assembly-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-8);
}

.metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-10);
  min-height: 58px;
  min-width: 0;
  border: 0;
  border-radius: 6px;
  padding: var(--space-10) var(--space-12);
  background: rgba(255, 255, 255, 0.02);
}

.metric-label {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-value {
  flex: 0 0 auto;
  color: var(--color-primary);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
}

.metric-text {
  font-size: var(--font-size-sm);
}

.assembly-list,
.fallback-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.assembly-block,
.source-group {
  border: 0;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.assembly-header,
.source-header {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6) var(--space-8);
  border-bottom: 0;
}

.assembly-header {
  justify-content: space-between;
}

.assembly-meta,
.assembly-status {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  min-width: 0;
}

.source-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--source-accent);
}

.source-title {
  color: var(--source-accent);
  font-size: calc(12px * var(--font-scale));
}

.assembly-order,
.assembly-title,
.assembly-kind,
.assembly-count {
  font-family: var(--font-ui);
}

.assembly-order {
  color: var(--color-text-tertiary);
  font-size: calc(12px * var(--font-scale));
}

.assembly-title {
  color: var(--source-accent);
  font-size: calc(12px * var(--font-scale));
}

.assembly-kind,
.assembly-count {
  color: var(--color-text-tertiary);
  font-size: calc(12px * var(--font-scale));
}

.source-count {
  margin-left: auto;
  color: var(--color-text-tertiary);
  font-size: calc(12px * var(--font-scale));
}

.source-items,
.assembly-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-8);
}

.source-text {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
}

.raw-context {
  min-height: 100%;
  margin: 0;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  border-radius: 6px;
}

.placeholder-text {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
  line-height: var(--line-height-relaxed);
  text-align: center;
}

.trace-view :deep(.thinking-panel),
.trace-view :deep(.thinking-steps),
.trace-view :deep(.thinking-step),
.trace-view :deep(.thinking-step-card),
.trace-view :deep(.step-card) {
  border: 0;
  border-radius: 0;
}

.trace-view :deep(.thinking-steps),
.trace-view :deep(.step-item),
.trace-view :deep(.step-detail) {
  border: 0;
}

.trace-view :deep(.bar-text),
.trace-view :deep(.step-chevron),
.trace-view :deep(.step-node),
.trace-view :deep(.step-summary),
.trace-view :deep(.step-tool-tag),
.trace-view :deep(.detail-label),
.trace-view :deep(.detail-value) {
  font-size: calc(12px * var(--font-scale));
}

@media (max-width: 720px) {
  .context-toolbar {
    flex-wrap: wrap;
  }

  :deep(.call-select.ui-dropdown-select-trigger) {
    width: 100%;
    margin-left: 0;
  }
  .assembly-overview {
    grid-template-columns: 1fr;
  }

  .assembly-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
