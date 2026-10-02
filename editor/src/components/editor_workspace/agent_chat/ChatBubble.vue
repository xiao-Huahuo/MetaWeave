<!--
  Chat mode message bubble.

  Usage:
  Ported from console ChatBubble. Assistant thinking is deduplicated and can
  collapse once final content starts streaming.
  Shows retrieved knowledge sources below assistant content.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import ThinkingSummary from '@/components/editor_workspace/agent_chat/ThinkingSummary.vue'
import AttachmentBlocks from '@/components/editor_workspace/agent_chat/AttachmentBlocks.vue'
import KnowledgeSources from '@/components/editor_workspace/agent_chat/KnowledgeSources.vue'
import MarkdownContent from '@/components/editor_workspace/agent_chat/MarkdownContent.vue'
import ThinkRow from '@/components/editor_workspace/agent_chat/ThinkRow.vue'
import ToolCallInline from '@/components/editor_workspace/agent_chat/ToolCallInline.vue'
import ThinkingInline from '@/components/editor_workspace/agent_chat/ThinkingInline.vue'
import type { AgentChangeSnapshot } from '@/api/agentChanges'
import { useChatStore } from '@/stores/chat'
import { useWorkspaceStore } from '@/stores/workspace'
import type { AgentChatMessage, AgentUploadedAttachment, SourceItem } from '@/stores/chat'

const props = withDefaults(defineProps<{
  message: AgentChatMessage
  isStreaming?: boolean
  isThinkingActive?: boolean
  userAvatar: string
  agentAvatar: string
  showAvatar?: boolean
  showActions?: boolean
  knowledgeSources?: SourceItem[]
  citationMap?: Record<string, SourceItem>
  changeSnapshot?: AgentChangeSnapshot | null
}>(), {
  showActions: true,
})

const workspaceStore = useWorkspaceStore()
const chatStore = useChatStore()
const copied = ref(false)
const feedback = ref<'up' | 'down' | null>(null)
const feedbackBurst = ref<'up' | 'down' | null>(null)

const bubbleRadius = computed(() => {
  return props.message.role === 'user' ? '18px 4px 18px 18px' : '4px 18px 18px 18px'
})

const thinkingRevealed = ref(true)
const thinkingAutoCollapsed = ref(false)

watch(
  () => props.isThinkingActive,
  (thinkingActive) => {
    if (!thinkingActive) {
      thinkingRevealed.value = false
    }
  },
)

watch(
  () => props.message.content,
  (content) => {
    if (thinkingAutoCollapsed.value) {
      return
    }
    if (props.isStreaming && thinkingRevealed.value && content && content !== '​') {
      thinkingRevealed.value = false
      thinkingAutoCollapsed.value = true
    }
  },
)

watch(
  () => props.message.message_id,
  () => {
    thinkingAutoCollapsed.value = false
    thinkingRevealed.value = true
  },
)

const thinkingTraces = computed(() => {
  const seen = new Set<string>()
  return (props.message.trace ?? []).filter((trace) => {
    const humanReadable = typeof trace.human_readable === 'string' ? trace.human_readable : ''
    const isChatVisible = trace.chat_visible === true || trace.event === 'tool_call_end'
    if (!humanReadable || seen.has(humanReadable)) {
      return false
    }
    if (!isChatVisible) {
      return false
    }
    seen.add(humanReadable)
    return true
  })
})

const hasAssistantContent = computed(() => {
  return Boolean(props.message.content && props.message.content !== '​')
})

/** Keeps a remounted loading indicator tied to its original user turn. */
const turnStartedAtMs = computed(() => {
  const value = props.message.metadata?.turn_started_at_ms
  return typeof value === 'number' ? value : undefined
})

/** Action messages use the shared lifecycle-aware tool rows in both chat modes. */
const hasToolTrace = computed(() => (props.message.trace ?? []).some((trace) => (
  Boolean(trace.tool_name) && (trace.event === 'tool_call_start' || trace.event === 'tool_call_end')
)))

const shouldRenderAssistant = computed(() => {
  return props.message.role === 'assistant'
    && (hasAssistantContent.value || thinkingTraces.value.length > 0 || props.isStreaming)
})

const shouldRenderAssistantBubble = computed(() => {
  return hasAssistantContent.value
})

const copyableContent = computed(() => {
  return props.message.content?.trim() || ''
})

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

async function copyBubbleContent() {
  const text = copyableContent.value
  if (!text) {
    return
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
  } else {
    fallbackCopy(text)
  }
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1200)
}

function setFeedback(kind: 'up' | 'down') {
  feedback.value = kind
  feedbackBurst.value = null
  window.requestAnimationFrame(() => {
    feedbackBurst.value = kind
    window.setTimeout(() => {
      feedbackBurst.value = null
    }, 420)
  })
}

async function handleNavigateSource(uri: string) {
  if (/^session-upload:\/\//i.test(uri)) {
    // MarkdownContent resolves attachment URIs through the exact raw endpoint.
    return
  }
  if (/^https?:\/\//i.test(uri)) {
    workspaceStore.openBrowserSidebar(uri)
    return
  }
  const flatNodes = workspaceStore.flatNodes ?? []
  const normalizePath = (value: string) => value.replace(/\\/g, '/').replace(/^\/+/, '')
  const normalizedUri = normalizePath(uri)
  let node = flatNodes.find((n) => normalizePath(n.path) === normalizedUri)
  if (!node) {
    const parts = normalizedUri.split('/').filter(Boolean)
    const name = parts[parts.length - 1] ?? uri
    node = flatNodes.find((n) => {
      const normalizedPath = normalizePath(n.path)
      return normalizedPath.endsWith(`/${normalizedUri}`)
        || normalizedPath.endsWith(`/${name}`)
        || n.name === name
    })
  }
  if (node) {
    if (workspaceStore.mainView === 'agent') {
      await workspaceStore.openEditorSidebar(node)
      return
    }
    workspaceStore.setMainView('editor')
    await workspaceStore.selectFile(node)
  }
}

function removeAttachment(attachment: AgentUploadedAttachment) {
  void chatStore.deleteAttachment(attachment)
}
</script>

<template>
  <ToolCallInline
    v-if="message.role === 'assistant' && message.node === 'action' && hasToolTrace"
    :traces="message.trace ?? []"
    :is-streaming="isStreaming"
    :change-snapshot="changeSnapshot"
  />
  <div v-else-if="shouldRenderAssistant" class="bubble-row assistant">
    <span class="avatar-slot"><img v-if="showAvatar !== false" :src="agentAvatar" class="avatar" alt="agent" /></span>
    <div class="bubble-col">
      <span v-if="message.node && message.node !== 'assistant'" class="node-label">{{ message.node }}</span>
      <Transition name="think-slide">
        <div v-if="thinkingTraces.length > 0 && (isThinkingActive || thinkingRevealed)" class="thinking-wrapper">
          <ThinkingInline
            :traces="thinkingTraces"
            :is-streaming="isThinkingActive"
            :default-expanded="thinkingRevealed"
            @collapse="thinkingRevealed = false"
          />
          <button
            v-if="!isThinkingActive && thinkingRevealed"
            class="thinking-toggle thinking-close"
            type="button"
            @click="thinkingRevealed = false"
          >
            收起
          </button>
        </div>
      </Transition>
      <Transition name="think-fade">
        <button
          v-if="thinkingTraces.length > 0 && !isThinkingActive && !thinkingRevealed"
          class="thinking-toggle"
          type="button"
          @click="thinkingRevealed = true"
        >
          思考过程
        </button>
      </Transition>
      <ThinkRow
        v-if="message.thinking"
        :text="message.thinking"
        :running="isStreaming"
      />
      <ThinkingSummary
        v-if="typeof message.thinking_seconds === 'number' && hasAssistantContent && showActions === true"
        :seconds="message.thinking_seconds"
      />
      <div v-if="shouldRenderAssistantBubble" class="bubble assistant" :style="{ borderRadius: bubbleRadius }">
        <MarkdownContent
          v-if="hasAssistantContent"
          :content="message.content"
          :is-streaming="isStreaming"
          :citation-map="citationMap"
          :on-navigate-source="handleNavigateSource"
        />
      </div>
      <LoadingState
        v-if="isStreaming && !hasAssistantContent"
        label="Thinking"
        variant="Drive"
        :started-at-ms="turnStartedAtMs"
      />
      <div v-if="showActions !== false && !isStreaming && copyableContent" class="message-actions">
        <button
          class="copy-action"
          type="button"
          :title="copied ? 'Copied' : 'Copy'"
          :aria-label="copied ? 'Copied' : 'Copy message'"
          @click="copyBubbleContent"
        >
          <IcIcon :name="copied ? 'check' : 'copy'" :size="14" morph />
        </button>
        <button
          class="feedback-action feedback-up"
          :class="{ active: feedback === 'up', burst: feedbackBurst === 'up' }"
          type="button"
          title="Like"
          aria-label="Like response"
          @click="setFeedback('up')"
        >
          <IcIcon name="thumb-up" :size="14" />
        </button>
        <button
          class="feedback-action feedback-down"
          :class="{ active: feedback === 'down', burst: feedbackBurst === 'down' }"
          type="button"
          title="Dislike"
          aria-label="Dislike response"
          @click="setFeedback('down')"
        >
          <IcIcon name="thumb-down" :size="14" />
        </button>
      </div>
      <div
        v-if="!isStreaming && knowledgeSources && knowledgeSources.length > 0"
        class="sources-reveal"
      >
        <KnowledgeSources
          :sources="knowledgeSources"
        />
      </div>
    </div>
  </div>

  <div v-else-if="message.role === 'user'" class="bubble-row user">
    <div class="bubble-col">
      <AttachmentBlocks
        v-if="message.attachments?.length"
        class="message-attachments"
        :attachments="message.attachments"
        align="right"
        @remove="removeAttachment"
      />
      <div v-if="message.reference" class="reference-block">
        <span class="reference-content">{{ message.reference }}</span>
      </div>
      <div class="bubble user" :style="{ borderRadius: bubbleRadius }">
        <pre class="content">{{ message.content }}</pre>
      </div>
      <button
        v-if="copyableContent"
        class="copy-action"
        type="button"
        :title="copied ? 'Copied' : 'Copy'"
        :aria-label="copied ? 'Copied' : 'Copy message'"
        @click="copyBubbleContent"
      >
        <IcIcon :name="copied ? 'check' : 'copy'" :size="14" morph />
      </button>
    </div>
    <img :src="userAvatar" class="avatar" alt="user" />
  </div>

  <div v-else class="bubble-row system">
    <div class="bubble system-bubble">
      <span class="system-role">{{ message.role }}</span>
      <pre class="content system-content">{{ message.content }}</pre>
    </div>
    <button
      v-if="copyableContent"
      class="copy-action"
      type="button"
      :title="copied ? 'Copied' : 'Copy'"
      :aria-label="copied ? 'Copied' : 'Copy message'"
      @click="copyBubbleContent"
    >
      <IcIcon :name="copied ? 'check' : 'copy'" :size="14" morph />
    </button>
  </div>
</template>

<style scoped>
.bubble-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-8);
  max-width: min(90%, 960px);
  margin-bottom: var(--space-12);
}

.bubble-row.user {
  position: relative;
  align-self: flex-end;
}

.bubble-row.assistant {
  align-self: flex-start;
}

.avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  margin-top: 2px;
  border: 0;
  border-radius: 50%;
  object-fit: cover;
}

.avatar-slot {
  display: block;
  width: 36px;
  flex: 0 0 36px;
}

.bubble-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.bubble-row.assistant .bubble-col {
  align-items: flex-start;
}

.bubble-row.user .bubble-col {
  align-items: flex-end;
}

.message-attachments {
  width: min(100%, 360px);
  max-width: 100%;
  margin-bottom: var(--space-6);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.node-label {
  margin-bottom: var(--space-4);
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(9px * var(--font-scale));
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.thinking-wrapper {
  margin-bottom: var(--space-8);
  overflow: hidden;
}

.think-slide-enter-active {
  overflow: hidden;
  transition:
    max-height 0.35s ease,
    opacity 0.25s ease,
    margin-bottom 0.35s ease;
}

.think-slide-leave-active {
  overflow: hidden;
  transition:
    max-height 0.25s ease,
    opacity 0.2s ease,
    margin-bottom 0.25s ease;
}

.think-slide-enter-from {
  max-height: 0;
  margin-bottom: 0;
  opacity: 0;
}

.think-slide-enter-to {
  max-height: 800px;
  margin-bottom: var(--space-8);
  opacity: 1;
}

.think-slide-leave-from {
  max-height: 800px;
  margin-bottom: var(--space-8);
  opacity: 1;
}

.think-slide-leave-to {
  max-height: 0;
  margin-bottom: 0;
  opacity: 0;
}

.think-fade-enter-active {
  transition: opacity 0.25s ease;
}

.think-fade-leave-active {
  transition: opacity 0.15s ease;
}

.think-fade-enter-from,
.think-fade-leave-to {
  opacity: 0;
}

.thinking-toggle {
  display: inline-block;
  padding: 0 0 var(--space-6);
  border: 0;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  font-family: var(--font-ui);
  font-size: calc(9px * var(--font-scale));
  opacity: 0.45;
  transition:
    opacity var(--transition-fast),
    color var(--transition-fast);
}

.thinking-toggle:hover {
  color: var(--color-accent);
  opacity: 0.8;
}

.thinking-close {
  padding: var(--space-6) 0 0;
}

.copy-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-top: var(--space-4);
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary);
  opacity: 0.56;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.copy-action:hover {
  background: rgba(148, 163, 184, 0.12);
  color: var(--color-text-secondary);
  opacity: 1;
}

.message-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  animation: response-controls-in 360ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

.sources-reveal {
  animation: response-controls-in 360ms cubic-bezier(0.23, 1, 0.32, 1) 60ms both;
}

.message-actions .copy-action {
  margin-top: 0;
}

.feedback-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary);
  opacity: 0.56;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    opacity var(--transition-fast),
    transform 120ms ease;
}

.feedback-action:hover {
  background: rgba(148, 163, 184, 0.12);
  opacity: 1;
}

.feedback-action.feedback-up:hover,
.feedback-action.feedback-up.active {
  color: #ef4b72;
}

.feedback-action.feedback-down:hover,
.feedback-action.feedback-down.active {
  color: #7f92b2;
}

.feedback-action.burst {
  animation: feedback-pop 420ms cubic-bezier(0.2, 1.55, 0.35, 1);
}

@keyframes feedback-pop {
  0% { transform: scale(1); }
  42% { transform: scale(1.34) rotate(-8deg); }
  68% { transform: scale(0.88) rotate(4deg); }
  100% { transform: scale(1) rotate(0); }
}

@keyframes response-controls-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.reference-block {
  max-width: 100%;
  margin-bottom: var(--space-4);
  padding: 7px 10px;
  border-left: 2px solid var(--color-border);
  background: rgba(148, 163, 184, 0.08);
  color: var(--color-text-muted);
  font-family: var(--font-chat);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.4;
}

.reference-content {
  display: -webkit-box;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  white-space: pre-wrap;
}

.bubble {
  display: inline-block;
  max-width: 100%;
  padding: 10px 16px;
  border: 1px solid;
  word-break: break-word;
  backdrop-filter: blur(var(--blur-strength));
}

.bubble.user {
  border: none;
  background: var(--color-message-bubble-bg);
  box-shadow: none;
}

.bubble.assistant {
  border: none;
  background: var(--color-message-bubble-bg);
  box-shadow: none;
}

.bubble.user .content {
  color: var(--color-message-bubble-text);
}

/* Theme-specific neutral bubble keeps markdown text readable in both modes. */
.bubble.assistant :deep(.markdown-body) {
  color: var(--color-message-bubble-text);
}

.bubble.assistant :deep(.markdown-body h1),
.bubble.assistant :deep(.markdown-body h2),
.bubble.assistant :deep(.markdown-body h3),
.bubble.assistant :deep(.markdown-body h4),
.bubble.assistant :deep(.markdown-body h5),
.bubble.assistant :deep(.markdown-body h6),
.bubble.assistant :deep(.markdown-body .citation-anchor),
.bubble.assistant :deep(.markdown-body .source-file-link:not(:hover):not(:focus-visible)) {
  color: var(--color-message-bubble-text);
}

.bubble.assistant :deep(.markdown-body blockquote) {
  color: color-mix(in srgb, var(--color-message-bubble-text) 85%, transparent);
}

.bubble.assistant :deep(.markdown-body li)::marker {
  color: color-mix(in srgb, var(--color-message-bubble-text) 70%, transparent);
}

.content {
  margin: 0;
  color: var(--color-text-primary);
  font-family: var(--font-chat);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
}

.bubble-row.system {
  align-self: center;
  max-width: 90%;
  margin-bottom: var(--space-8);
}

.system-bubble {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: 6px 12px;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.02);
}

.system-role {
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(8px * var(--font-scale));
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.system-content {
  max-height: 120px;
  overflow-y: auto;
  color: var(--color-text-tertiary);
  font-size: calc(11px * var(--font-scale));
}

@media (prefers-reduced-motion: reduce) {
  .message-actions,
  .sources-reveal {
    animation: none;
  }
}

</style>
