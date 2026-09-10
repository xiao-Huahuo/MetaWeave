<!--
  InjectedEntriesCard —— editable injected rule/memory list used by the memory dashboard.
-->

<script setup lang="ts">
import IcIcon from '@/components/common/IcIcon.vue'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'

export interface InjectedEntry {
  id: string
  content: string
}

const newContent = defineModel<string>('newContent', { required: true })

defineProps<{
  title: string
  entries: InjectedEntry[]
  isAdding?: boolean
  isLoading?: boolean
  message?: string
  placeholder: string
  emptyText: string
}>()

defineEmits<{
  add: []
  delete: [id: string]
}>()
</script>

<template>
  <DashboardCardFrame :title="title" :status="`${entries.length} items`">
    <div class="inject-card-body">
      <div class="inject-input-row">
        <input
          v-model="newContent"
          class="inject-input"
          :placeholder="placeholder"
          :disabled="isLoading"
          @keydown.enter="$emit('add')"
        />
        <button
          class="icon-button add-button"
          type="button"
          title="添加"
          :disabled="isAdding || isLoading || !newContent.trim()"
          @click="$emit('add')"
        >
          <IcIcon name="add" :size="14" />
        </button>
      </div>

      <p v-if="message" class="feedback-text">{{ message }}</p>

      <div v-if="isLoading" class="empty-state">
        <span class="placeholder-text">$ 正在加载注入内容</span>
      </div>

      <div v-else-if="entries.length > 0" class="entry-list">
        <div v-for="entry in entries" :key="entry.id" class="entry-row">
          <p class="entry-content">{{ entry.content }}</p>
          <button
            class="icon-button delete-button"
            type="button"
            title="删除"
            @click="$emit('delete', entry.id)"
          >
            <IcIcon name="trash" :size="13" />
          </button>
        </div>
      </div>

      <div v-else class="empty-state">
        <span class="placeholder-text">$ {{ emptyText }}</span>
      </div>
    </div>
  </DashboardCardFrame>
</template>

<style scoped>
.inject-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  flex: 1;
  min-height: 0;
  padding: var(--space-10);
  overflow: hidden;
}

.inject-input-row {
  display: flex;
  gap: var(--space-6);
  flex-shrink: 0;
  min-width: 0;
}

.inject-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0 var(--space-8);
  background: var(--color-surface-raised);
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  outline: none;
}

.inject-input:focus {
  border-color: color-mix(in srgb, var(--color-primary) 38%, var(--color-border));
  background: var(--color-primary-softer);
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
}

.icon-button:hover:not(:disabled) {
  color: var(--color-text-secondary);
  background: var(--color-bg-hover);
}

.icon-button:disabled {
  cursor: default;
  opacity: 0.45;
}

.add-button:not(:disabled) {
  color: var(--color-primary);
  border-color: color-mix(in srgb, var(--color-primary) 32%, var(--color-border));
  background: var(--color-primary-soft);
}

.feedback-text,
.placeholder-text {
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.feedback-text {
  margin: 0;
}

.entry-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.entry-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--space-8);
  border: 0;
  border-radius: 18px;
  padding: var(--space-8);
  background: var(--color-surface-raised);
}

.entry-content {
  margin: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-text);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
}

.delete-button {
  width: 24px;
  height: 24px;
}

.delete-button:hover {
  color: var(--color-danger, #ff6b6b);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
  border-radius: 6px;
  text-align: center;
}
</style>
