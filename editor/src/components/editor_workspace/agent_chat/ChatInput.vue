<!--
  Agent chat input.

  Usage:
  Emits a send event when the user presses Enter without Shift or clicks the
  send button. Supports optional quoted reference text displayed as a gray bar
  above the input area.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { AGENT_STARTER_COLORS } from '@/stores/settings'
import { promptStarters, samplePromptStarters, type PromptStarter } from './promptStarters'

import IcIcon from '@/components/common/IcIcon.vue'
import AttachmentBlocks from '@/components/editor_workspace/agent_chat/AttachmentBlocks.vue'
import ContextProgress from '@/components/editor_workspace/agent_chat/ContextProgress.vue'
import AgentQuestionBox from './AgentQuestionBox.vue'
import { checkModelDisk, fetchModelStatus } from '@/api/settings'
import type { AgentAccessMode, AgentQuestionAnswer, AgentQuestionRequest } from '@/api/agent'
import type { AgentUploadedAttachment } from '@/stores/chat'

const props = defineProps<{
  disabled?: boolean
  centered?: boolean
  compact?: boolean
  /** Full Agent page keeps starters available even in its mobile panel layout. */
  page?: boolean
  /** Changes when a conversation is selected or a new blank draft is requested. */
  conversationKey?: string
  webSearchEnabled?: boolean
  modelLabel?: string
  agentAccessMode?: AgentAccessMode
  reference?: string
  attachments?: AgentUploadedAttachment[]
  contextTokens?: number
  maxContextTokens?: number
  isStreaming?: boolean
  questionRequest?: AgentQuestionRequest | null
  questionSubmitting?: boolean
  questionError?: string
}>()

const emit = defineEmits<{
  send: [text: string, reference?: string]
  'toggle-web-search': []
  'configure-model': []
  'set-agent-access-mode': [mode: AgentAccessMode]
  'clear-reference': []
  'remove-attachment': [attachment: AgentUploadedAttachment]
  'file-select': [file: File]
  'cancel-stream': []
  'create-task-list': [title: string, items: string[]]
  'answer-question': [answers: Record<string, AgentQuestionAnswer>]
}>()

const text = ref('')
const accessModeMenu = ref<HTMLDetailsElement | null>(null)
const accessModeTrigger = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const inputContainer = ref<HTMLDivElement | null>(null)

const menuVisible = ref(false)
const menuStyle = ref<Record<string, string>>({})
const activeStarterPrefix = ref('')

/** Discardable UI selection, owned by this input and reset for each new draft. */
const selectedPromptStarters = ref(samplePromptStarters())
const accessModeOptions: Array<{ value: AgentAccessMode; label: string; hint: string }> = [
  { value: 'readonly', label: '只读', hint: '全目录只读' },
  { value: 'sandbox', label: '沙盒', hint: '知识库内写' },
  { value: 'full_access', label: '完全访问', hint: '不限制边界' },
]

const selectedAccessMode = computed<AgentAccessMode>(() => props.agentAccessMode || 'sandbox')
const selectedAccessModeLabel = computed(() => {
  return accessModeOptions.find((option) => option.value === selectedAccessMode.value)?.label || '沙盒'
})
const displayedModelLabel = computed(() => props.modelLabel?.trim() || '配置模型')
const promptInput = computed(() => text.value.trim())
const activeStarter = computed(() => {
  const input = promptInput.value
  if (!input) return undefined

  const lockedStarter = promptStarters.find((starter) => starter.prefix === activeStarterPrefix.value)
  if (lockedStarter && matchesPromptStarter(lockedStarter, input)) {
    return lockedStarter
  }
  return promptStarters.find((starter) => matchesPromptStarter(starter, input))
})
const matchedPromptSuggestions = computed(() => {
  const input = promptInput.value
  if (!activeStarter.value || !input) return []
  return activeStarter.value.suggestions.filter((suggestion) => suggestion.startsWith(input))
})
const showPromptStarters = computed(() => {
  return (!props.compact || props.page) && props.centered && !promptInput.value && !props.reference && !props.attachments?.length
})
const showPromptWaterfall = computed(() => {
  return (!props.compact || props.page) && props.centered && matchedPromptSuggestions.value.length > 0 && !props.reference && !props.attachments?.length
})
const availableWidth = ref(920)
let starterResizeObserver: ResizeObserver | undefined
const visiblePromptStarters = computed(() => {
  const count = Math.floor((availableWidth.value + 12) / 222)
  return selectedPromptStarters.value.slice(0, Math.min(4, Math.max(1, count)))
})
/** Measure the actual conversation column, including sidebars and ultra-narrow layouts. */
function handleViewportResize() {
  const column = inputContainer.value?.parentElement?.parentElement
  availableWidth.value = Math.max(1, Math.min(920, (column?.clientWidth || window.innerWidth) - 48))
}

/** Resample only for conversation entry/reset; typing and resizing preserve the draw. */
watch(() => props.conversationKey, () => {
  if (!props.centered) return
  selectedPromptStarters.value = samplePromptStarters()
  activeStarterPrefix.value = ''
  text.value = ''
})

function matchesPromptStarter(starter: PromptStarter, input: string) {
  return starter.prefix.startsWith(input) ||
    input.startsWith(starter.prefix) ||
    starter.suggestions.some((suggestion) => suggestion.startsWith(input))
}

function adjustHeight() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const max = 6 * Math.round(parseFloat(getComputedStyle(el).lineHeight)) + 14
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
}

watch(text, () => {
  if (!promptInput.value) {
    activeStarterPrefix.value = ''
  } else if (activeStarter.value) {
    activeStarterPrefix.value = activeStarter.value.prefix
  }
  nextTick(adjustHeight)
})

watch(() => props.centered, (centered) => {
  if (!centered) {
    activeStarterPrefix.value = ''
  }
})

watch(menuVisible, (visible) => {
  if (visible) {
    document.addEventListener('click', handleOutsideClick, true)
    window.addEventListener('scroll', handleScrollResize, true)
    window.addEventListener('resize', handleScrollResize)
  } else {
    document.removeEventListener('click', handleOutsideClick, true)
    window.removeEventListener('scroll', handleScrollResize, true)
    window.removeEventListener('resize', handleScrollResize)
  }
})

const modelModalVisible = ref(false)
const modelModalMessage = ref('')
const modelChecking = ref(false)
const taskModalVisible = ref(false)
const taskTitle = ref('')
const taskItemsText = ref('')

function handleSend() {
  if (props.disabled || props.isStreaming) return
  const trimmed = text.value.trim()
  if (!trimmed) return

  // 先同步推出用户气泡,不被模型状态检查等网络请求阻塞
  const reference = props.reference?.trim() || undefined
  emit('send', trimmed, reference)
  text.value = ''
  emit('clear-reference')

  // 模型状态检查放到发送之后后台执行,发现问题时仅提示不阻断
  void (async () => {
    try {
      const status = await checkModelDisk()
      const blockedModels: string[] = []
      if (status.embedding === 'not_downloaded' || status.embedding === 'error') {
        blockedModels.push('Embedding')
      }
      if (status.rerank === 'not_downloaded' || status.rerank === 'error') {
        blockedModels.push('ReRank')
      }
      if (blockedModels.length > 0) {
        modelModalMessage.value = `以下模型未就绪：${blockedModels.join('、')}，请先下载`
        modelModalVisible.value = true
      }
    } catch {
      // 模型状态检查失败时忽略
    }
  })()
}

async function handleModelModalRetry() {
  modelChecking.value = true
  try {
    const status = await fetchModelStatus()
    const ready = status.embedding === 'ready' && status.rerank === 'ready'
    if (ready) {
      modelModalVisible.value = false
      return
    }
    if (status.embedding === 'downloading' || status.embedding === 'loading' ||
        status.rerank === 'downloading' || status.rerank === 'loading') {
      modelModalMessage.value = '模型下载中，请稍候...'
    }
  } catch {
    // keep current message
  } finally {
    modelChecking.value = false
  }
}

function handleModelModalClose() {
  modelModalVisible.value = false
}

function navigateToSettings() {
  modelModalVisible.value = false
  window.location.hash = '#/settings'
  // SettingsView 监听 agent-settings-tab 事件切换标签页
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('agent-settings-tab', { detail: 'storage' }))
  }, 100)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

function applyPromptStarter(starter: PromptStarter) {
  activeStarterPrefix.value = starter.prefix
  text.value = starter.prefix
  nextTick(() => {
    textareaRef.value?.focus()
  })
}

function applyPromptSuggestion(suggestion: string) {
  text.value = suggestion
  activeStarterPrefix.value = ''
  nextTick(() => {
    textareaRef.value?.focus()
    adjustHeight()
  })
}

function handleAccessModeSummaryClick(event: MouseEvent) {
  if (props.disabled) {
    event.preventDefault()
  }
}

function handleAccessModeToggle(event: Event) {
  if ((event.target as HTMLElement)?.tagName !== 'DETAILS') return
  if (accessModeMenu.value?.open && accessModeTrigger.value) {
    const rect = accessModeTrigger.value.getBoundingClientRect()
    menuStyle.value = {
      left: `${rect.left}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
    }
    menuVisible.value = true
  } else {
    menuVisible.value = false
  }
}

function handleOutsideClick(event: MouseEvent) {
  if (!menuVisible.value) return
  const target = event.target as Node
  if (accessModeTrigger.value?.contains(target)) return
  if (accessModeMenu.value?.contains(target)) return
  menuVisible.value = false
  if (accessModeMenu.value) {
    accessModeMenu.value.open = false
  }
}

function handleScrollResize() {
  if (!menuVisible.value || !accessModeTrigger.value) return
  const rect = accessModeTrigger.value.getBoundingClientRect()
  menuStyle.value = {
    left: `${rect.left}px`,
    bottom: `${window.innerHeight - rect.top + 8}px`,
  }
}

function selectAccessMode(mode: AgentAccessMode) {
  emit('set-agent-access-mode', mode)
  if (accessModeMenu.value) {
    accessModeMenu.value.open = false
  }
}

function triggerFilePicker() {
  fileInput.value?.click()
}

function closeTaskModal() {
  taskModalVisible.value = false
}

function submitTaskList() {
  const items = taskItemsText.value
    .split(/\r?\n/)
    .map((line) => line.replace(/^[-*]\s*/, '').trim())
    .filter(Boolean)
  if (items.length === 0) return
  emit('create-task-list', taskTitle.value.trim(), items)
  taskModalVisible.value = false
}

function handleInputMouseMove(e: MouseEvent) {
  const el = inputContainer.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  el.style.setProperty('--mouse-x', String((e.clientX - rect.left) / rect.width))
  el.style.setProperty('--mouse-y', String((e.clientY - rect.top) / rect.height))
  el.style.setProperty('--glow-opacity', '1')
}

onMounted(() => {
  handleViewportResize()
  const column = inputContainer.value?.parentElement?.parentElement
  if (column && typeof ResizeObserver !== 'undefined') {
    starterResizeObserver = new ResizeObserver(handleViewportResize)
    starterResizeObserver.observe(column)
  }
  document.addEventListener('mousemove', handleInputMouseMove)
  window.addEventListener('resize', handleViewportResize)
})

onBeforeUnmount(() => {
  starterResizeObserver?.disconnect()
  document.removeEventListener('mousemove', handleInputMouseMove)
  window.removeEventListener('resize', handleViewportResize)
  document.removeEventListener('click', handleOutsideClick, true)
  window.removeEventListener('scroll', handleScrollResize, true)
  window.removeEventListener('resize', handleScrollResize)
})

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('file-select', file)
  }
  input.value = ''
}
</script>

<template>
  <div class="chat-input-wrap" :class="{ centered, compact }">
    <Transition name="settings-disclosure">
      <div v-if="questionRequest" :key="questionRequest.request_id" class="question-extension">
        <AgentQuestionBox :request="questionRequest" :submitting="questionSubmitting" :error="questionError" @answer="emit('answer-question', $event)" />
      </div>
    </Transition>
    <AttachmentBlocks
      v-if="!centered && !questionRequest && attachments?.length"
      class="input-attachments"
      :attachments="attachments"
      align="left"
      @remove="emit('remove-attachment', $event)"
    />
    <div
      ref="inputContainer"
      class="input-container"
    >
      <div v-if="reference" class="reference-bar">
        <span class="reference-text">{{ reference }}</span>
        <button class="reference-close" type="button" title="移除引用" @click="emit('clear-reference')">
          <IcIcon name="close" :size="13" />
        </button>
      </div>
      <textarea
        v-model="text"
        class="input-area"
        :class="{ 'has-reference': !!reference }"
        ref="textareaRef"
        placeholder="输入消息..."
        rows="1"
        @keydown="handleKeydown"
      ></textarea>
      <div class="input-toolbar">
        <div class="toolbar-left">
          <button
            class="attach-file-btn"
            type="button"
            title="上传文件"
            :disabled="disabled"
            @click="triggerFilePicker"
          >
            <IcIcon name="add" :size="14" />
          </button>
          <input
            ref="fileInput"
            type="file"
            class="file-input-hidden"
            @change="handleFileChange"
          />
          <button
            class="web-search-toggle"
            :class="{ active: webSearchEnabled }"
            type="button"
            title="联网搜索"
            :disabled="disabled"
            @click="emit('toggle-web-search')"
          >
            <IcIcon name="language" :size="14" />
          </button>
          <details ref="accessModeMenu" class="access-mode-dropdown" :class="{ disabled }" @toggle="handleAccessModeToggle">
            <summary
              ref="accessModeTrigger"
              class="access-mode-trigger"
              title="Agent 权限"
              aria-label="Agent 权限"
              @click="handleAccessModeSummaryClick"
            >
              <IcIcon name="shield" :size="12" />
              <span class="access-mode-label">{{ selectedAccessModeLabel }}</span>
              <IcIcon name="chevron-down" :size="11" class="access-mode-caret" />
            </summary>
          </details>
          <Teleport to="body">
            <div v-if="menuVisible" class="access-mode-menu" :style="menuStyle" role="listbox" aria-label="Agent 权限">
              <button
                v-for="option in accessModeOptions"
                :key="option.value"
                class="access-mode-option"
                :class="{ active: selectedAccessMode === option.value }"
                type="button"
                role="option"
                :aria-selected="selectedAccessMode === option.value"
                @click="selectAccessMode(option.value)"
              >
                <span class="access-mode-option-label">{{ option.label }}</span>
                <span class="access-mode-option-hint">{{ option.hint }}</span>
                <IcIcon v-if="selectedAccessMode === option.value" name="check" :size="13" class="access-mode-check" />
              </button>
            </div>
          </Teleport>
        </div>
        <div class="toolbar-right">
          <button
            class="model-config-trigger"
            type="button"
            :disabled="disabled"
            title="配置模型"
            @click="emit('configure-model')"
          >
            <IcIcon name="settings" :size="13" />
            <span>{{ displayedModelLabel }}</span>
          </button>
          <ContextProgress
            :current-tokens="props.contextTokens"
            :max-context-tokens="props.maxContextTokens"
          />
          <button
            class="send-btn"
            :class="{ 'stop-btn': isStreaming }"
            :disabled="!isStreaming && (disabled || !text.trim())"
            type="button"
            :title="isStreaming ? '中断输出' : '发送'"
            @click="isStreaming ? emit('cancel-stream') : handleSend()"
          >
            <IcIcon :name="isStreaming ? 'stop' : 'send'" :size="15" morph />
          </button>
        </div>
      </div>
    </div>
    <Transition name="starter-grid-panel">
      <div v-if="showPromptStarters" class="prompt-starter-grid" :style="{ maxWidth: availableWidth + 'px' }" aria-label="Agent 快捷提示">
        <button
          v-for="starter in visiblePromptStarters"
          :key="starter.prefix"
          class="prompt-starter-card"
          :style="{ '--starter-color': AGENT_STARTER_COLORS[starter.color] }"
          type="button"
          :disabled="disabled"
          @click="applyPromptStarter(starter)"
        >
          <IcIcon :name="starter.icon" class="prompt-starter-icon" :size="16" aria-hidden="true" />
          <span class="prompt-starter-title">{{ starter.title }}</span>
        </button>
      </div>
    </Transition>
    <Transition name="starter-panel">
      <div v-if="showPromptWaterfall" class="prompt-waterfall-list" aria-label="Agent 提示补全">
        <button
          v-for="(suggestion, index) in matchedPromptSuggestions"
          :key="suggestion"
          class="prompt-waterfall-item"
          type="button"
          :disabled="disabled"
          :style="{ '--waterfall-index': String(index), '--starter-color': activeStarter ? AGENT_STARTER_COLORS[activeStarter.color] : undefined }"
          @click="applyPromptSuggestion(suggestion)"
        >
          <IcIcon
            :name="activeStarter?.icon || 'manage-search'"
            class="prompt-waterfall-icon"
            :size="15"
            aria-hidden="true"
          />
          <span>{{ suggestion }}</span>
        </button>
      </div>
    </Transition>
    <AttachmentBlocks
      v-if="centered && attachments?.length"
      class="input-attachments centered-attachments"
      :attachments="attachments"
      align="left"
      @remove="emit('remove-attachment', $event)"
    />
  </div>

  <!-- 模型状态阻断模态框 -->
  <Teleport to="body">
    <div v-if="modelModalVisible" class="model-modal-overlay" @click.self="handleModelModalClose">
      <div class="model-modal">
        <p class="model-modal-message">{{ modelModalMessage }}</p>
        <p class="model-modal-link">
          <a href="#" @click.prevent="navigateToSettings">前往存储管理页面下载</a>
        </p>
        <div class="model-modal-actions">
          <button class="model-modal-btn retry-btn" :disabled="modelChecking" @click="handleModelModalRetry">
            {{ modelChecking ? '检查中...' : '重试' }}
          </button>
          <button class="model-modal-btn close-btn" @click="handleModelModalClose">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="taskModalVisible" class="model-modal-overlay" @click.self="closeTaskModal">
      <div class="model-modal task-list-modal">
        <label class="task-list-field">
          <span>Title</span>
          <input v-model="taskTitle" class="task-list-input" type="text" placeholder="Task list" />
        </label>
        <label class="task-list-field">
          <span>Tasks</span>
          <textarea
            v-model="taskItemsText"
            class="task-list-textarea"
            rows="7"
            placeholder="One task per line"
          ></textarea>
        </label>
        <div class="model-modal-actions">
          <button class="model-modal-btn close-btn" type="button" @click="closeTaskModal">Cancel</button>
          <button
            class="model-modal-btn retry-btn"
            type="button"
            :disabled="!taskItemsText.trim()"
            @click="submitTaskList"
          >
            Start
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.question-extension { --settings-slide-offset: 8px; position: absolute; inset-inline: 0; bottom: calc(100% + var(--space-8)); }
.chat-input-wrap {
  position: absolute;
  left: 50%;
  z-index: 2;
  bottom: 16px;
  width: calc(100% - 32px);
  max-width: 500px;
  transform: translateX(-50%);
  transition:
    bottom 350ms cubic-bezier(0.4, 0, 0.2, 1),
    width 350ms cubic-bezier(0.4, 0, 0.2, 1);
}

.chat-input-wrap.centered {
  bottom: 42%;
  width: min(90%, 400px);
}

.input-attachments {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 1;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 0 var(--space-4);
  scrollbar-width: thin;
}

.input-attachments.centered-attachments {
  top: calc(100% + 8px);
  bottom: auto;
}

.prompt-starter-grid,
.prompt-waterfall-list {
  position: absolute;
  top: calc(100% + 12px);
  left: 0;
  right: 0;
  z-index: 1;
  pointer-events: auto;
}

.prompt-starter-grid {
  display: flex;
  left: 50%;
  right: auto;
  width: max-content;
  max-width: min(920px, calc(100vw - 48px));
  gap: var(--space-12);
  transform: translateX(-50%);
}

.prompt-starter-card {
  display: flex;
  flex-direction: column;
  align-items: start;
  justify-content: space-between;
  gap: var(--space-16);
  flex: 0 1 210px;
  width: 210px;
  min-width: 0;
  min-height: 124px;
  padding: var(--space-16);
  border: 1px solid var(--color-border);
  border-radius: 20px;
  background: color-mix(in srgb, var(--color-surface-raised) 86%, transparent);
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  text-align: left;
  cursor: pointer;
  opacity: 0;
  transform: scale(0.94);
  transform-origin: center;
  animation: starter-card-scale 220ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast);
}

.prompt-starter-card:nth-child(2) {
  animation-delay: 36ms;
}

.prompt-starter-card:nth-child(3) {
  animation-delay: 72ms;
}

.prompt-starter-card:nth-child(4) {
  animation-delay: 108ms;
}

.prompt-starter-card:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-primary) 54%, var(--color-border));
  background: var(--color-primary-softer);
  color: var(--color-text);
  transform: translateY(-2px);
}

.prompt-starter-card:disabled,
.prompt-waterfall-item:disabled {
  cursor: default;
  opacity: 0.5;
}

.prompt-starter-icon {
  flex: 0 0 auto;
  color: var(--starter-color);
}

.prompt-starter-title {
  overflow: hidden;
  min-width: 0;
  color: inherit;
  font-size: calc(13px * var(--font-scale));
  font-weight: 650;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.prompt-waterfall-list {
  display: grid;
  gap: var(--space-6);
}

.prompt-waterfall-item {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  min-height: 34px;
  padding: var(--space-6) var(--space-12);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
  opacity: 0;
  transform: translateY(calc((var(--waterfall-index, 0) + 1) * -6px));
  animation: waterfall-drop 240ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
  animation-delay: calc(var(--waterfall-index, 0) * 48ms);
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast);
}

.prompt-waterfall-item:hover:not(:disabled) {
  background: var(--color-primary-softer);
  color: var(--color-text);
  transform: translateX(4px);
}

.prompt-waterfall-icon {
  flex: 0 0 18px;
  width: 18px;
  color: var(--starter-color);
}

.prompt-waterfall-item span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.starter-panel-enter-active,
.starter-panel-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
  transform-origin: center top;
}

.starter-grid-panel-enter-active,
.starter-grid-panel-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
  transform-origin: center top;
}

.starter-panel-enter-from,
.starter-panel-leave-to {
  opacity: 0;
  transform: scale(0.96);
}

.starter-grid-panel-enter-from,
.starter-grid-panel-leave-to {
  opacity: 0;
  transform: translateX(-50%) scale(0.94);
}

.starter-grid-panel-enter-to,
.starter-grid-panel-leave-from {
  opacity: 1;
  transform: translateX(-50%) scale(1);
}

.input-container {
  position: relative;
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  overflow: visible;
  border: 1px solid var(--input-border);
  border-radius: var(--radius-xl);
  background: var(--input-bg);
  backdrop-filter: blur(var(--blur-strength));
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.input-container:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-accent-muted);
}

/* Specular edge glow */
.input-container::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  z-index: 1;
  pointer-events: none;
  background: radial-gradient(
    1000px circle at calc(var(--mouse-x, 0.5) * 100%) calc(var(--mouse-y, 0.5) * 100%),
    rgba(255, 255, 255, 0.65),
    transparent 35%
  );
  opacity: var(--glow-opacity, 0);
  transition: opacity 0.4s ease;
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  padding: 1px;
}

.reference-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 10px 0;
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas-soft);
}

.reference-text {
  flex: 1;
  overflow: hidden;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reference-close {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 120ms, color 120ms;
}

.reference-close:hover {
  background: var(--color-surface-active);
  color: var(--color-text);
}

.input-area {
  width: 100%;
  min-height: 52px;
  max-height: 140px;
  padding: 14px 14px 0;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: var(--input-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  line-height: 1.5;
}

.input-area.has-reference {
  min-height: 24px;
  padding-top: 8px;
}

.input-area::placeholder {
  color: var(--input-placeholder);
}

.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  height: 38px;
  padding: 0 8px;
}

/* Panel mode keeps the essential controls but collapses their text labels so
   the toolbar remains a single non-overlapping row at sidebar widths. */
.chat-input-wrap.compact .input-toolbar {
  gap: 2px;
  padding: 0 6px;
}

.chat-input-wrap.compact .toolbar-left,
.chat-input-wrap.compact .toolbar-right { gap: 3px; }

.chat-input-wrap.compact .model-config-trigger,
.chat-input-wrap.compact .access-mode-trigger {
  flex: 0 0 28px;
  width: 28px;
  min-width: 28px;
  padding: 0;
}

.chat-input-wrap.compact .model-config-trigger span,
.chat-input-wrap.compact .access-mode-label,
.chat-input-wrap.compact .access-mode-caret {
  display: none;
}

.chat-input-wrap.compact :deep(.context-progress) { display: none; }

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  flex: 0 0 auto;
}

.toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  min-width: 0;
  flex: 0 1 auto;
}

.attach-file-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast),
    background var(--transition-fast);
}

.attach-file-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-softer);
}

.file-input-hidden {
  display: none;
}

.web-search-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  border: 1px solid var(--color-primary);
  border-radius: 50%;
  background: transparent;
  color: var(--color-primary);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast),
    background var(--transition-fast);
}

.web-search-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.web-search-toggle.active {
  border-color: var(--color-primary);
  color: #fff;
  background: var(--color-primary);
}

.web-search-toggle:hover:not(:disabled) {
  border-color: var(--color-primary-hover);
  color: var(--color-primary-hover);
  background: var(--color-primary-softer);
}

.web-search-toggle.active:hover:not(:disabled) {
  border-color: var(--color-primary-hover);
  color: #fff;
  background: var(--color-primary-hover);
}

.access-mode-dropdown {
  position: relative;
  flex: 0 0 auto;
}

.access-mode-dropdown.disabled {
  pointer-events: none;
  opacity: 0.55;
}

.access-mode-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 26px;
  min-width: 64px;
  padding: 0 8px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted, #8b93a7);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
  line-height: 1;
  list-style: none;
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast);
}

.access-mode-trigger::-webkit-details-marker {
  display: none;
}

.access-mode-trigger::marker {
  content: '';
}

.access-mode-trigger:hover,
.access-mode-dropdown[open] .access-mode-trigger {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.access-mode-label {
  color: inherit;
  white-space: nowrap;
}

.access-mode-caret {
  color: inherit;
  transition: transform 120ms ease;
}

.access-mode-dropdown[open] .access-mode-caret {
  transform: rotate(180deg);
}

.access-mode-menu {
  position: fixed;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  width: 180px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  background: var(--color-surface, #111827);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
  animation: loop-menu-pop 140ms ease-out both;
}

.access-mode-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-secondary, #a8b0c1);
  font-family: var(--font-ui);
  text-align: left;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-4px);
  animation: loop-option-drop 150ms ease-out both;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.access-mode-option:nth-child(2) {
  animation-delay: 26ms;
}

.access-mode-option:nth-child(3) {
  animation-delay: 52ms;
}

.access-mode-option:hover,
.access-mode-option.active {
  background: var(--color-primary-softer);
  color: var(--color-text, #e5e7eb);
}

.access-mode-option-label {
  width: 54px;
  color: inherit;
  font-size: calc(11px * var(--font-scale));
}

.access-mode-option-hint {
  flex: 1;
  color: var(--color-text-muted, #7c8496);
  font-size: calc(10px * var(--font-scale));
}

.access-mode-check {
  color: var(--color-primary);
}

.model-config-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-width: 0;
  height: 28px;
  margin-left: auto;
  padding: 0 var(--space-8);
  border: 1px solid color-mix(in srgb, var(--color-primary) 46%, var(--color-border));
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  line-height: 1;
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast);
}

.model-config-trigger span {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-config-trigger:hover:not(:disabled) {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-text-primary);
}

.model-config-trigger:disabled {
  cursor: default;
  opacity: 0.55;
}

.loop-mode-dropdown {
  position: relative;
  margin-left: auto;
}

.loop-mode-dropdown.disabled {
  pointer-events: none;
  opacity: 0.55;
}

.loop-mode-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 26px;
  padding: 0 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-muted, #8b93a7);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
  line-height: 1;
  list-style: none;
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast);
}

.loop-mode-trigger::-webkit-details-marker {
  display: none;
}

.loop-mode-trigger::marker {
  content: '';
}

.loop-mode-trigger:hover,
.loop-mode-dropdown[open] .loop-mode-trigger {
  background: transparent;
  color: var(--color-text-secondary, #a8b0c1);
}

.loop-mode-label {
  min-width: 36px;
  color: inherit;
}

.loop-mode-caret {
  color: inherit;
  transition: transform 120ms ease;
}

.loop-mode-dropdown[open] .loop-mode-caret {
  transform: rotate(180deg);
}

.loop-mode-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 20;
  display: flex;
  flex-direction: column;
  width: 198px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 10px;
  background: var(--color-surface, #111827);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.28);
  animation: loop-menu-pop 140ms ease-out both;
}

.loop-mode-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-secondary, #a8b0c1);
  font-family: var(--font-ui);
  text-align: left;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-4px);
  animation: loop-option-drop 150ms ease-out both;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.loop-mode-menu .loop-mode-option:nth-of-type(1) { animation-delay: 20ms; }
.loop-mode-menu .loop-mode-option:nth-of-type(2) { animation-delay: 38ms; }
.loop-mode-menu .loop-mode-option:nth-of-type(3) { animation-delay: 56ms; }
.loop-mode-menu .loop-mode-option:nth-of-type(4) { animation-delay: 74ms; }

.loop-mode-option:hover,
.loop-mode-option.active {
  background: rgba(66, 36, 235, 0.14);
  color: var(--color-text, #e5e7eb);
}

.loop-mode-option-label {
  color: inherit;
  font-size: calc(12px * var(--font-scale));
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0.02em;
}

.loop-mode-option-hint {
  margin-left: auto;
  color: var(--color-text-tertiary, #7c8496);
  font-size: calc(10px * var(--font-scale));
  line-height: 1.2;
  white-space: nowrap;
}

.loop-mode-check {
  flex-shrink: 0;
  color: var(--color-accent, #4224eb);
}

.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: var(--radius-md);
  background: var(--input-btn-bg);
  color: var(--input-send-disabled);
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

@keyframes loop-menu-pop {
  from { transform: translateY(6px); }
  to { transform: translateY(0); }
}

@keyframes loop-option-drop {
  from { transform: translateY(-4px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

@keyframes starter-card-scale {
  from { transform: scale(0.94); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

@keyframes waterfall-drop {
  from {
    opacity: 0;
    transform: scale(0.96);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.send-btn:hover:not(:disabled) {
  background: var(--color-accent);
  color: #0a0a0a;
}

.send-btn:disabled {
  cursor: default;
  opacity: 0.35;
}

.stop-btn {
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #d32f2f;
  color: #fff;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.stop-btn:hover:not(:disabled) {
  background: transparent;
  box-shadow: inset 0 0 0 1.5px #d32f2f;
  color: #d32f2f;
}

.stop-btn :deep(svg) {
  display: block;
}

@keyframes stop-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(211, 47, 47, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(211, 47, 47, 0); }
}

@container (max-width: 360px) {
  .model-config-trigger {
    flex: 0 0 30px;
    width: 30px;
    padding: 0;
  }

  .model-config-trigger span {
    display: none;
  }
}

@container (max-width: 320px) {
  .attach-file-btn {
    display: none;
  }
}

@container (max-width: 288px) {
  .web-search-toggle {
    display: none;
  }
}

@container (max-width: 252px) {
  .access-mode-trigger {
    min-width: 30px;
    padding: 0;
  }

  .access-mode-label,
  .access-mode-caret {
    display: none;
  }
}

/* Compact panel mode has already removed labels and the context meter, so its
   two primary input actions still fit and must remain discoverable. */
.chat-input-wrap.compact .attach-file-btn,
.chat-input-wrap.compact .web-search-toggle {
  display: inline-flex;
}

/* ---- 模型状态阻断模态框 ---- */
.model-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
}

.model-modal {
  width: 380px;
  max-width: 90vw;
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35);
}

.model-modal-message {
  margin: 0 0 12px;
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  line-height: 1.5;
}

.model-modal-link {
  margin: 0 0 16px;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.model-modal-link a {
  color: var(--color-primary);
  text-decoration: underline;
  cursor: pointer;
}

.model-modal-link a:hover {
  color: var(--color-primary-active);
}

.model-modal-actions {
  display: flex;
  gap: var(--space-8);
  justify-content: flex-end;
}

.model-modal-btn {
  padding: 6px 18px;
  border: 0;
  border-radius: var(--radius-sm);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

.model-modal-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.retry-btn {
  background: var(--color-primary);
  color: #fff;
}

.close-btn {
  background: transparent;
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.task-list-modal {
  display: grid;
  gap: var(--space-12);
}

.task-list-field {
  display: grid;
  gap: var(--space-6);
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.task-list-input,
.task-list-textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  outline: 0;
}

.task-list-input {
  height: 34px;
  padding: 0 var(--space-10);
}

.task-list-textarea {
  min-height: 140px;
  padding: var(--space-8) var(--space-10);
  line-height: 1.45;
  resize: vertical;
}

.task-list-input:focus,
.task-list-textarea:focus {
  border-color: var(--color-primary);
}
</style>
<style src="../../common/settings-disclosure-motion.css" scoped></style>
