<!--
  Memory and prompt settings section.

  Usage:
  Displays system prompt entries and custom memory entries. SettingsView owns
  add/delete handlers and API synchronization.
-->
<script setup lang="ts">
import type { MemoryEntry, SystemPromptEntry } from '@/api/settings'

const newPromptContent = defineModel<string>('newPromptContent', { required: true })
const newMemoryContent = defineModel<string>('newMemoryContent', { required: true })
const longTermMemoryEnabled = defineModel<boolean>('longTermMemoryEnabled', { required: true })

defineProps<{
  promptEntries: SystemPromptEntry[]
  addingPrompt: boolean
  promptMsg: string
  memories: MemoryEntry[]
  addingMemory: boolean
  memoryMsg: string
  showIndexColumn: boolean
  showGraphColumn: boolean
  showFavoriteColumn: boolean
}>()

defineEmits<{
  addPrompt: []
  deletePrompt: [promptId: string]
  addMemory: []
  deleteMemory: [memoryId: string]
  setShowIndexColumn: [value: boolean]
  setShowGraphColumn: [value: boolean]
  setShowFavoriteColumn: [value: boolean]
  saveMemoryConfig: []
}>()
</script>

<template>
  <div class="setting-section">
    <h3>长期记忆</h3>
    <div class="setting-row toggle-row">
      <label>启用长期记忆</label>
      <input v-model="longTermMemoryEnabled" type="checkbox" @change="$emit('saveMemoryConfig')" />
      <span class="hint-text">关闭后跳过固定召回，并移除 Agent 的长期记忆工具</span>
    </div>
    <h3>系统提示</h3>
    <div class="input-row memory-input-row">
      <textarea
        v-model="newPromptContent"
        rows="3"
        aria-label="输入系统指令"
        placeholder="输入系统指令"
      ></textarea>
      <button class="add-btn" :disabled="addingPrompt || !newPromptContent.trim()" @click="$emit('addPrompt')">
        {{ addingPrompt ? '...' : '添加' }}
      </button>
    </div>
    <p v-if="promptMsg" class="feedback">{{ promptMsg }}</p>
    <ul v-if="promptEntries.length" class="entry-list">
      <li v-for="entry in promptEntries" :key="entry.prompt_id" class="entry-row">
        <span class="entry-text">{{ entry.content }}</span>
        <button class="entry-del" title="删除" @click="$emit('deletePrompt', entry.prompt_id)">&times;</button>
      </li>
    </ul>

    <h3 class="memory-title">记忆注入</h3>
    <div class="input-row memory-input-row">
      <textarea
        v-model="newMemoryContent"
        rows="3"
        aria-label="输入记忆内容"
        placeholder="输入记忆内容"
      ></textarea>
      <button class="add-btn" :disabled="addingMemory || !newMemoryContent.trim()" @click="$emit('addMemory')">
        {{ addingMemory ? '...' : '添加' }}
      </button>
    </div>
    <p v-if="memoryMsg" class="feedback">{{ memoryMsg }}</p>
    <ul v-if="memories.length" class="entry-list memory-entry-list">
      <li v-for="entry in memories" :key="entry.memory_id" class="entry-row memory-entry-row">
        <span class="entry-text">{{ entry.content }}</span>
        <button class="entry-del" title="删除" @click="$emit('deleteMemory', entry.memory_id)">&times;</button>
      </li>
    </ul>
    <h3 style="margin-top: 20px">显示</h3>
    <div class="setting-row toggle-row">
      <label>索引状态</label>
      <input
        :checked="showIndexColumn"
        type="checkbox"
        @change="$emit('setShowIndexColumn', ($event.target as HTMLInputElement).checked)"
      />
      <span class="hint-text">在文件树和文件资源管理器中显示入库状态</span>
    </div>
    <div class="setting-row toggle-row">
      <label>图谱状态</label>
      <input
        :checked="showGraphColumn"
        type="checkbox"
        @change="$emit('setShowGraphColumn', ($event.target as HTMLInputElement).checked)"
      />
      <span class="hint-text">在文件树和文件资源管理器中显示语义图谱状态</span>
    </div>
    <div class="setting-row toggle-row">
      <label>收藏状态</label>
      <input
        :checked="showFavoriteColumn"
        type="checkbox"
        @change="$emit('setShowFavoriteColumn', ($event.target as HTMLInputElement).checked)"
      />
      <span class="hint-text">在文件树中显示收藏按钮</span>
    </div>
  </div>
</template>

<style scoped>
.memory-input-row {
  flex-direction: column;
  gap: var(--space-8);
}

.memory-input-row textarea {
  flex: none;
  width: 100%;
  min-width: 0;
  height: auto;
  min-height: 88px;
  padding: var(--space-8) var(--space-10);
  line-height: 1.5;
  resize: vertical;
}

.memory-input-row .add-btn {
  align-self: flex-start;
}

/* Keep a one-line capsule's radius as explicit or wrapped lines increase height. */
.entry-row {
  align-self: flex-start;
  min-width: 0;
  max-width: 100%;
  border-radius: calc(max(1lh, 20px) / 2 + var(--space-4));
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-text) 6%);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.5;
}

.entry-text {
  min-width: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.hint-text {
  display: none;
}
</style>
