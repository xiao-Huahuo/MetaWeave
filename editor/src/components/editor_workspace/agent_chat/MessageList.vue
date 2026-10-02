<!--
  Agent chat message list.

  Usage:
  Displays streamed chat messages and keeps the scroll pinned to bottom unless
  the user scrolls upward to inspect history.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import LoadingState from '@/components/common/LoadingState.vue'
import LoaderCube from '@/components/editor_workspace/agent_chat/LoaderCube.vue'
import FinalTurnSummary from '@/components/editor_workspace/agent_chat/FinalTurnSummary.vue'
import AgentSearchResultBlocks from '@/components/editor_workspace/agent_chat/AgentSearchResultBlocks.vue'
import MessageBubble from '@/components/editor_workspace/agent_chat/MessageBubble.vue'
import { undoSessionChange } from '@/api/agentChanges'
import type { AgentChangeSnapshot } from '@/api/agentChanges'
import { useAvatar } from '@/components/editor_workspace/agent_chat/useAvatar'
import type { AgentChatMessage, SourceItem } from '@/stores/chat'
import { asSourceMap, useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import type { UnifiedSearchResult } from '@/types/unifiedSearch'

const props = defineProps<{
  messages: AgentChatMessage[]
  isStreaming?: boolean
  mergeAssistants?: boolean
  suggestions?: string[]
  /** Reduces secondary details when mounted in the narrow workspace sidebar. */
  compact?: boolean
}>()

const emit = defineEmits<{
  'bottom-change': [isAtBottom: boolean]
  'select-suggestion': [suggestion: string]
}>()

const { userAvatar, agentAvatar } = useAvatar()
const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const containerRef = ref<HTMLDivElement | null>(null)
const isPinnedToBottom = ref(true)
const isThinkingActive = computed(() => Boolean(props.isStreaming))
const undoingSnapshotId = ref('')
let scrollRafId = 0
let contentScrollRafId = 0
let layoutScrollRafId = 0
let layoutScrollTimeoutId = 0
let followsSubmittedPrompt = false
let userScrollRevision = 0
const MESSAGE_TIME_SEPARATOR_MS = 30 * 60 * 1000
/** Stable empty props let Vue skip completed bubbles during body updates. */
const emptyCitationMap: Record<string, SourceItem> = {}
const emptyKnowledgeSources: SourceItem[] = []

function mergeConsecutiveSameNode(messages: AgentChatMessage[]) {
  return messages.filter((message) => message.role !== 'system').reduce<AgentChatMessage[]>((acc, message) => {
    const previous = acc[acc.length - 1]
    const isChildAgentEvent = message.node === 'child_agent' || previous?.node === 'child_agent'
    if (message.role === 'assistant' && previous?.role === 'assistant' && previous.node === message.node && !isChildAgentEvent) {
      const merged: AgentChatMessage = {
        ...previous,
        content: previous.content + message.content,
        tool_calls: [...(previous.tool_calls ?? []), ...(message.tool_calls ?? [])],
        metadata: { ...(previous.metadata ?? {}), ...(message.metadata ?? {}) },
        trace: [...(previous.trace ?? []), ...(message.trace ?? [])],
      }
      acc[acc.length - 1] = merged
    } else {
      acc.push(message)
    }
    return acc
  }, [])
}

const visibleMessages = computed(() => {
  const base = props.messages.filter((message) => message.role !== 'system')
  return mergeConsecutiveSameNode(base)
})

/** Formats one persisted message time in the viewer's local timezone. */
function formatMessageTime(timestamp: number) {
  const date = new Date(timestamp)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}年${pad(date.getMonth() + 1)}月${pad(date.getDate())}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Derives sparse timeline labels without duplicating persisted message data. */
const visibleMessageEntries = computed(() => {
  let previousTimestamp: number | null = null
  return visibleMessages.value.map((message) => {
    const timestamp = Date.parse(message.created_at ?? '')
    const validTimestamp = Number.isFinite(timestamp) ? timestamp : null
    const showTime = validTimestamp !== null
      && (previousTimestamp === null || validTimestamp - previousTimestamp >= MESSAGE_TIME_SEPARATOR_MS)
    if (validTimestamp !== null) previousTimestamp = validTimestamp
    return {
      message,
      timeLabel: showTime && validTimestamp !== null ? formatMessageTime(validTimestamp) : '',
    }
  })
})

const showThinkingBubble = computed(() => {
  if (!props.isStreaming) {
    return false
  }
  const list = visibleMessages.value
  const last = list[list.length - 1]
  return !last || last.role !== 'assistant'
})

function isNearBottom() {
  const container = containerRef.value
  if (!container) {
    return true
  }
  return container.scrollHeight - container.scrollTop - container.clientHeight <= 24
}

function setPinnedToBottom(value: boolean) {
  if (isPinnedToBottom.value === value) {
    return
  }
  isPinnedToBottom.value = value
  emit('bottom-change', value)
}

function scrollToBottom(options: ScrollToOptions = {}) {
  const container = containerRef.value
  if (container) {
    container.scrollTo({
      top: container.scrollHeight,
      ...options,
    })
  }
}

function handleScroll() {
  if (scrollRafId !== 0) return
  scrollRafId = window.requestAnimationFrame(() => {
    scrollRafId = 0
    setPinnedToBottom(isNearBottom())
  })
}

function handleUserScrollIntent() {
  followsSubmittedPrompt = false
  userScrollRevision += 1
}

/** Reads the streamed body's new height once per frame after Vue has patched it. */
function scheduleScrollIfNeeded() {
  if (contentScrollRafId !== 0 || !(isPinnedToBottom.value || isNearBottom())) return
  const scheduledRevision = userScrollRevision
  contentScrollRafId = window.requestAnimationFrame(() => {
    contentScrollRafId = 0
    // A pending body update must not pull the user away from history inspection.
    if (scheduledRevision !== userScrollRevision || !(isPinnedToBottom.value || isNearBottom())) return
    scrollToBottom()
    setPinnedToBottom(true)
  })
}

/** Keeps the bottom pinned across Vue updates and delayed Markdown/card layout. */
function schedulePinnedScroll(onSettled?: () => void) {
  const scheduledRevision = userScrollRevision
  void nextTick(() => {
    if (layoutScrollRafId !== 0) window.cancelAnimationFrame(layoutScrollRafId)
    layoutScrollRafId = window.requestAnimationFrame(() => {
      layoutScrollRafId = 0
      if (scheduledRevision !== userScrollRevision) return
      scrollToBottom()
      setPinnedToBottom(true)
    })
  })
  if (layoutScrollTimeoutId !== 0) window.clearTimeout(layoutScrollTimeoutId)
  layoutScrollTimeoutId = window.setTimeout(() => {
    layoutScrollTimeoutId = 0
    if (scheduledRevision !== userScrollRevision) return
    scrollToBottom()
    setPinnedToBottom(true)
    onSettled?.()
  }, 100)
}

function getLastMessageContent() {
  const last = props.messages[props.messages.length - 1]
  return last?.content ?? ''
}

function shouldShowAvatar(message: AgentChatMessage, index: number) {
  if (message.role !== 'assistant') return true

  // A completed final reply keeps its avatar after streaming stops.
  if (isFinalAssistantAnswer(message, index)) return true

  // Keep one avatar on the currently active assistant item. Empty placeholders
  // no longer consume the avatar before a later tool result becomes visible.
  for (let nextIndex = index + 1; nextIndex < visibleMessages.value.length; nextIndex += 1) {
    const next = visibleMessages.value[nextIndex]
    if (next?.role === 'user') break
    if (next?.role === 'assistant') return false
  }
  return true
}

function hasCopyableAssistantContent(message: AgentChatMessage) {
  return message.role === 'assistant' && Boolean(message.content?.trim())
}

function isFinalAnswerNode(message: AgentChatMessage) {
  const node = String(message.node || message.metadata?.node || '')
  return node === 'agent' || node === 'error' || node === 'interrupted' || node === ''
}

function isCompletedAssistantContentMessage(message: AgentChatMessage) {
  return hasCopyableAssistantContent(message) && isFinalAnswerNode(message)
}

function isFinalAssistantAnswer(message: AgentChatMessage, index: number) {
  if (!hasCopyableAssistantContent(message)) {
    return false
  }

  // A turn ends at the next user message. Only the last assistant message
  // with visible content in that turn is the final answer shown to the user.
  for (let nextIndex = index + 1; nextIndex < visibleMessages.value.length; nextIndex += 1) {
    const nextMessage = visibleMessages.value[nextIndex]
    if (!nextMessage) {
      continue
    }
    if (nextMessage.role === 'user') {
      break
    }
    if (hasCopyableAssistantContent(nextMessage)) {
      return false
    }
  }
  return true
}

function isLatestFinalAssistantAnswer(message: AgentChatMessage, index: number) {
  if (!isFinalAssistantAnswer(message, index)) return false
  return !visibleMessages.value.slice(index + 1).some((nextMessage) => nextMessage.role === 'user')
}

function shouldShowActions(message: AgentChatMessage, index: number) {
  if (message.role !== 'assistant') {
    return true
  }
  return !isThinkingActive.value
    && isCompletedAssistantContentMessage(message)
    && isFinalAssistantAnswer(message, index)
}

function extractCitationIds(content: string) {
  const ids: string[] = []
  const seen = new Set<string>()
  const pattern = /\[([A-Z]?\d+)\]/g
  let match = pattern.exec(content)
  while (match) {
    const id = match[1]
    if (id && !seen.has(id)) {
      ids.push(id)
      seen.add(id)
    }
    match = pattern.exec(content)
  }
  return ids
}

function citationMapForMessage(message: AgentChatMessage, messageIndex = -1): Record<string, SourceItem> {
  if (isThinkingActive.value || !isCompletedAssistantContentMessage(message)) {
    return emptyCitationMap
  }
  const persisted = asSourceMap(message.metadata?.citation_map)
  if (Object.keys(persisted).length > 0 || messageIndex < 0) return persisted
  for (let index = messageIndex - 1; index >= 0; index -= 1) {
    const candidate = visibleMessages.value[index]
    if (candidate?.role !== 'user') continue
    const attachments = candidate.attachments?.filter((item) => item.uri?.startsWith('session-upload://')) ?? []
    return Object.fromEntries(attachments.map((attachment, attachmentIndex) => [
      `A${attachmentIndex + 1}`,
      {
        source_uri: attachment.uri,
        content: attachment.summary ?? '',
        source: 'session_attachment',
        title: attachment.filename,
      },
    ]))
  }
  return persisted
}

function knowledgeSourcesForMessage(message: AgentChatMessage, messageIndex = -1): SourceItem[] {
  const citationMap = citationMapForMessage(message, messageIndex)
  const metadataUsed = Array.isArray(message.metadata?.used_citations)
    ? message.metadata.used_citations.filter((item): item is string => typeof item === 'string')
    : []
  const usedIds = metadataUsed.length > 0 ? metadataUsed : extractCitationIds(message.content)
  const sources: SourceItem[] = []
  const sourceIndexByUri = new Map<string, number>()
  for (const id of usedIds) {
    const source = citationMap[id]
    if (!source || !source.source_uri) {
      continue
    }
    const existingIndex = sourceIndexByUri.get(source.source_uri)
    if (existingIndex !== undefined) {
      const existing = sources[existingIndex]
      if (!existing) {
        continue
      }
      const existingIds = (existing.citation_id ?? '').split(',').map((item) => item.trim()).filter(Boolean)
      if (!existingIds.includes(id)) {
        existing.citation_id = [...existingIds, id].join(', ')
      }
      continue
    }
    sourceIndexByUri.set(source.source_uri, sources.length)
    sources.push({ ...source, citation_id: id })
  }
  return sources
}

/** Mount only search results the Agent actually cited in its final answer. */
function searchResultsForMessage(message: AgentChatMessage, messageIndex = -1): UnifiedSearchResult[] {
  if (isThinkingActive.value || !isCompletedAssistantContentMessage(message)) return []
  const citationMap = citationMapForMessage(message, messageIndex)
  const metadataUsed = Array.isArray(message.metadata?.used_citations)
    ? message.metadata.used_citations.filter((item): item is string => typeof item === 'string')
    : []
  const usedIds = metadataUsed.length > 0 ? metadataUsed : extractCitationIds(message.content)
  const seen = new Set<string>()
  return usedIds.flatMap((id) => {
    const result = citationMap[id]?.search_result
    const key = result ? `${result.source}:${result.id}` : ''
    if (!result || seen.has(key)) return []
    seen.add(key)
    return [result]
  })
}

function changeSnapshotForMessage(message: AgentChatMessage): AgentChangeSnapshot | null {
  const snapshot = message.metadata?.change_snapshot
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return null
  const record = snapshot as Partial<AgentChangeSnapshot>
  return typeof record.snapshot_id === 'string' && typeof record.session_id === 'string'
    ? record as AgentChangeSnapshot
    : null
}

/** Finds the finalized snapshot for an action message before the next user turn. */
function changeSnapshotForAction(index: number): AgentChangeSnapshot | null {
  for (let cursor = index + 1; cursor < visibleMessages.value.length; cursor += 1) {
    const candidate = visibleMessages.value[cursor]
    if (candidate?.role === 'user') break
    if (candidate) {
      const snapshot = changeSnapshotForMessage(candidate)
      if (snapshot) return snapshot
    }
  }
  return null
}

async function undoMessageChange(message: AgentChatMessage) {
  const snapshot = changeSnapshotForMessage(message)
  const sessionId = snapshot?.session_id
  const snapshotId = snapshot?.snapshot_id
  const userId = settingsStore.profile.userId
  if (typeof sessionId !== 'string' || typeof snapshotId !== 'string' || !userId) return
  undoingSnapshotId.value = snapshotId
  try {
    const result = await undoSessionChange(sessionId, snapshotId, userId)
    message.metadata = { ...(message.metadata ?? {}), change_snapshot: result.change_snapshot ?? snapshot }
  } finally {
    undoingSnapshotId.value = ''
  }
}

watch(() => props.messages.length, (newLen, oldLen) => {
  const lastRole = props.messages[newLen - 1]?.role
  if (newLen > oldLen && lastRole === 'user') followsSubmittedPrompt = true
  // A submitted prompt must stay visible after the composer changes the viewport.
  if (newLen > oldLen && (lastRole === 'user' || (lastRole === 'assistant' && followsSubmittedPrompt))) {
    schedulePinnedScroll(() => {
      if (lastRole === 'assistant') followsSubmittedPrompt = false
    })
    return
  }
  scheduleScrollIfNeeded()
})
watch(getLastMessageContent, scheduleScrollIfNeeded)
watch(() => props.suggestions?.length ?? 0, scheduleScrollIfNeeded)
watch(() => props.isStreaming, (isStreaming, wasStreaming) => {
  if (!isStreaming && wasStreaming && (isPinnedToBottom.value || isNearBottom())) {
    schedulePinnedScroll(() => {
      followsSubmittedPrompt = false
    })
  }
})

onMounted(() => {
  scrollToBottom()
  setPinnedToBottom(true)
})

onBeforeUnmount(() => {
  if (scrollRafId !== 0) window.cancelAnimationFrame(scrollRafId)
  if (contentScrollRafId !== 0) window.cancelAnimationFrame(contentScrollRafId)
  if (layoutScrollRafId !== 0) window.cancelAnimationFrame(layoutScrollRafId)
  if (layoutScrollTimeoutId !== 0) window.clearTimeout(layoutScrollTimeoutId)
})

defineExpose({
  scrollToBottom,
})
</script>

<template>
  <div
    ref="containerRef"
    class="message-list"
    :class="{ compact }"
    @scroll="handleScroll"
    @wheel="handleUserScrollIntent"
    @touchmove="handleUserScrollIntent"
  >
    <template v-for="({ message, timeLabel }, index) in visibleMessageEntries" :key="message.message_id ?? `${message.role}-${index}`">
      <time v-if="timeLabel" class="message-time-separator" :datetime="message.created_at">{{ timeLabel }}</time>
      <MessageBubble
        :message="message"
        :is-streaming="isStreaming && index === visibleMessages.length - 1"
        :is-thinking-active="isThinkingActive"
        :user-avatar="userAvatar"
        :agent-avatar="agentAvatar"
        :show-avatar="shouldShowAvatar(message, index)"
        :show-actions="shouldShowActions(message, index)"
        :knowledge-sources="emptyKnowledgeSources"
        :citation-map="message.role === 'assistant' ? citationMapForMessage(message, index) : emptyCitationMap"
        :change-snapshot="message.node === 'action' ? changeSnapshotForAction(index) : changeSnapshotForMessage(message)"
      />
      <AgentSearchResultBlocks
        v-if="searchResultsForMessage(message, index).length"
        class="assistant-summary-offset"
        :results="searchResultsForMessage(message, index)"
        :compact="compact"
      />
      <FinalTurnSummary
        v-if="message.role === 'assistant' && isFinalAssistantAnswer(message, index) && !isThinkingActive"
        class="assistant-summary-offset"
        :sources="knowledgeSourcesForMessage(message, index)"
        :change-snapshot="changeSnapshotForMessage(message)"
        :undoing="undoingSnapshotId === changeSnapshotForMessage(message)?.snapshot_id"
        :compact="compact"
        @undo="undoMessageChange(message)"
      />
      <div
        v-if="suggestions?.length && message.role === 'assistant' && isLatestFinalAssistantAnswer(message, index) && !isThinkingActive"
        class="task-suggestions assistant-summary-offset"
        :class="{ compact }"
        aria-label="接下来可以"
      >
        <button
          v-for="suggestion in suggestions.slice(0, 3)"
          :key="suggestion"
          class="suggestion-button"
          type="button"
          @click="emit('select-suggestion', suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
    </template>
    <div v-if="showThinkingBubble" class="thinking-row">
      <img :src="agentAvatar" class="thinking-avatar" alt="agent" />
      <LoadingState label="Thinking" variant="Drive" :started-at-ms="chatStore.streamStartedAtMs" />
      <span class="thinking-spinner" aria-label="Preparing response"><LoaderCube /></span>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  padding: var(--space-16);
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--color-text-muted) 52%, transparent) transparent;
}

.message-list.compact {
  padding: var(--space-10);
}

.message-time-separator {
  align-self: center;
  margin: var(--space-8) 0 var(--space-16);
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.4;
}

/* Completed offscreen messages retain their measured scroll size while
   Chromium skips layout and paint for their expensive Markdown/tool DOM. */
.message-list :deep(.bubble-row),
.message-list :deep(.tool-action-row),
.message-list :deep(.child-agent-event-row) {
  content-visibility: auto;
  contain-intrinsic-size: auto 140px;
}

.message-list::-webkit-scrollbar {
  width: 10px;
}

.message-list::-webkit-scrollbar-track {
  background: transparent;
}

.message-list::-webkit-scrollbar-thumb {
  border: 3px solid transparent;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-text-muted) 52%, transparent);
  background-clip: content-box;
}

.message-list::-webkit-scrollbar-thumb:hover {
  background-color: color-mix(in srgb, var(--color-text-muted) 76%, transparent);
}

.thinking-row {
  display: flex;
  align-items: center;
  align-self: flex-start;
  gap: var(--space-6);
  padding: var(--space-8) 0;
}

.thinking-avatar {
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  object-fit: cover;
}

.thinking-spinner {
  display: inline-flex;
  font-size: 0.55em;
}

/* Final cards share the assistant text column rather than the avatar column. */
.assistant-summary-offset {
  margin-left: calc(36px + var(--space-8));
}

.assistant-summary-offset.compact {
  width: calc(100% - 36px - var(--space-8));
}

/* Keep the original task-suggestion buttons; only their flow position moved
   from above the composer to beneath the latest completed Agent response. */
.task-suggestions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-6);
  width: min(100%, 760px);
  margin-bottom: var(--space-16);
}

.suggestion-button {
  max-width: 100%;
  min-height: 26px;
  padding: 0 var(--space-8);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.2;
  cursor: pointer;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast);
}

.suggestion-button:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-text);
  transform: translateY(-1px);
}

</style>
