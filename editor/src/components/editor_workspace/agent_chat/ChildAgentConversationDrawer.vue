<!--
  子 Agent 完整对话详情栏。

  用途：复用 Agent 页 MessageList 显示一个只读子 Session；运行中的子 Agent
  会独立轮询自己的消息，不创建左侧历史项，也不影响其他子对话的加载状态。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import MessageList from '@/components/editor_workspace/agent_chat/MessageList.vue'
import type { ChildAgentRecord } from '@/api/agent'
import {
  childAgentConversationState,
  loadChildAgentConversation,
} from '@/components/editor_workspace/agent_chat/childAgentConversations'

defineOptions({ name: 'ChildAgentConversationDrawer' })
const props = defineProps<{
  child: ChildAgentRecord
  userId: string
}>()
const emit = defineEmits<{ close: [] }>()
const state = computed(() => childAgentConversationState(props.child.conversation_session_id))
const isRunning = computed(() => ['created', 'running'].includes(props.child.status))
let pollTimer: number | null = null

function load(force = false) {
  return loadChildAgentConversation(props.child.conversation_session_id, props.userId, force)
}

function syncPolling() {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = isRunning.value
    ? window.setInterval(() => void load(true), 1500)
    : null
}

watch(() => props.child.conversation_session_id, () => {
  void load()
  syncPolling()
})
watch(isRunning, syncPolling)
onMounted(() => {
  void load()
  syncPolling()
})
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <aside class="child-conversation" aria-label="子 Agent 完整对话">
    <button class="child-conversation-close" type="button" title="关闭子 Agent 对话" @click="emit('close')">
      <IcIcon name="close" :size="15" />
    </button>
    <div class="child-conversation-body">
      <MessageList
        v-if="state.messages.length"
        :messages="state.messages"
        :is-streaming="isRunning"
        compact
      />
      <p v-else-if="state.loading" class="child-conversation-state">正在加载完整对话...</p>
      <p v-else-if="state.error" class="child-conversation-state error">{{ state.error }}</p>
      <p v-else class="child-conversation-state">暂无对话消息</p>
    </div>
  </aside>
</template>

<style scoped>
.child-conversation {
  box-sizing: border-box;
  position: relative;
  display: flex;
  flex: 0 0 min(520px, 44vw);
  width: min(520px, 44vw);
  min-width: 320px;
  min-height: 0;
  margin: var(--space-10);
  flex-direction: column;
  overflow: hidden;
  border: 0;
  outline: 2px solid var(--workspace-panel-outline);
  outline-offset: 2px;
  border-radius: var(--workspace-card-radius);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  box-shadow: 0 0 0 2px var(--library-form-ring);
}

.child-conversation-close {
  position: absolute;
  z-index: 2;
  top: var(--space-10);
  right: var(--space-10);
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.child-conversation-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.child-conversation-body :deep(.message-list) {
  padding-top: 48px;
  padding-bottom: var(--space-16);
}

.child-conversation-state {
  margin: auto;
  padding: var(--space-16);
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.child-conversation-state.error { color: var(--color-danger); }

.child-conversation-slide-enter-active,
.child-conversation-slide-leave-active {
  transition: width 220ms ease, flex-basis 220ms ease, opacity 160ms ease, transform 220ms ease;
}

.child-conversation-slide-enter-from,
.child-conversation-slide-leave-to {
  flex-basis: 0;
  width: 0;
  min-width: 0;
  opacity: 0;
  transform: translateX(24px);
}

@media (max-width: 1100px) {
  .child-conversation {
    position: absolute;
    z-index: 20;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(520px, 72vw);
    min-width: 0;
  }
}

@media (max-width: 640px) {
  .child-conversation {
    left: 0;
    width: auto;
  }
}
</style>
