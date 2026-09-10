<!--
  Literature row field block.

  Usage:
  LiteratureEntryCard renders one smart-form column through this component in
  the persisted column order. Markdown fields reuse SmartMarkdownCell and all
  edits emit the exact smart-cell string value back to the row API.
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import SmartMarkdownCell from '@/components/smart_forms/SmartMarkdownCell.vue'
import type { SmartCell, SmartColumn } from '@/components/smart_forms/smartLiteratureTable'

const props = defineProps<{
  column: SmartColumn
  cell: SmartCell
  markdownPath: string
  pending?: boolean
}>()

const emit = defineEmits<{
  update: [value: string]
  download: []
  smartFill: []
  contextMenu: [event: MouseEvent]
}>()

const expanded = ref(Boolean(props.cell.value) || props.column.type === 'file')
const editing = ref(false)
const fieldBody = ref<HTMLElement | null>(null)
const markdownEditor = ref<InstanceType<typeof SmartMarkdownCell> | null>(null)
const isSmart = computed(() => props.column.type === 'smart_text' || props.column.type === 'smart_tag')
const hasValue = computed(() => Boolean(props.cell.value.trim()))
const showBody = computed(() => props.column.type === 'file' || expanded.value || hasValue.value)

watch(() => props.cell.value, (value) => {
  if (value.trim()) expanded.value = true
})

async function expandEditor(): Promise<void> {
  if (!props.column.editable) return
  expanded.value = true
  await nextTick()
  if (markdownEditor.value) {
    await markdownEditor.value.startEditing()
    return
  }
  fieldBody.value?.querySelector<HTMLElement>('input, button')?.focus()
}

/** Expanded cards do not upload inline images; the table remains the owner of form assets. */
async function rejectInlineImage(): Promise<{ name: string; relativePath: string }> {
  throw new Error('请在智能表格中粘贴字段图片')
}
</script>

<template>
  <section class="literature-field" :class="{ editing, empty: !hasValue, pending }" @contextmenu.prevent.stop="emit('contextMenu', $event)">
    <header class="field-heading">
      <span>{{ column.title }}</span>
      <span class="field-actions">
        <button v-if="column.editable && !showBody" class="v1-icon-button" type="button" title="输入内容" aria-label="输入内容" @click="expandEditor"><IcIcon name="add" :size="14" /></button>
        <button v-if="isSmart" class="smart-fill-button v1-icon-button" type="button" title="智能填充" aria-label="智能填充" :disabled="pending" @click="emit('smartFill')"><IcIcon name="psychology" :size="14" /></button>
        <span v-if="pending" class="pixel-loader" aria-label="正在智能填充"><i></i><i></i><i></i><i></i><i></i></span>
      </span>
    </header>
    <div v-if="showBody" ref="fieldBody" class="field-body" @dblclick="expandEditor">
      <button v-if="column.type === 'file'" class="file-link" type="button" @click="emit('download')">
        {{ cell.fileName || cell.value || '未上传文件' }}
      </button>
      <div v-else-if="column.type === 'star'" class="star-editor" aria-label="文献星级">
      <button v-for="star in 5" :key="star" type="button" :class="{ active: Number(cell.value || 0) >= star }" @click="emit('update', String(star))">★</button>
      </div>
      <input
        v-else-if="column.type === 'tag' || column.type === 'smart_tag' || column.type === 'date' || column.type === 'boolean'"
        class="field-input"
        :value="cell.value"
        :readonly="!column.editable"
        @focus="editing = true"
        @blur="editing = false"
        @change="emit('update', ($event.target as HTMLInputElement).value)"
      />
      <SmartMarkdownCell
        v-else
        ref="markdownEditor"
        class="markdown-field"
        :value="cell.value"
        :path="markdownPath"
        :editable="column.editable"
        :inline-markdown-preview="column.id === 'figures' || column.id === 'formulas'"
        :upload-image="rejectInlineImage"
        @update="emit('update', $event)"
      />
    </div>
  </section>
</template>

<style scoped>
.literature-field {
  min-width: 0;
  overflow: visible;
  border: 0;
  background: transparent;
}

.field-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
  padding: 0;
  color: var(--color-text-muted);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  font-weight: 400;
}

.field-heading > span:first-child {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  padding: 0 var(--space-8);
  border-radius: 999px;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.field-actions { display: inline-flex; align-items: center; gap: 2px; margin-left: auto; }
.field-actions button { display: grid; width: 24px; height: 24px; place-items: center; padding: 0; border: 0; border-radius: 4px; background: transparent; color: var(--color-text-muted); }.field-actions button:hover:not(:disabled) { background: color-mix(in srgb, var(--color-primary) 10%, transparent); color: var(--color-primary); }

.field-body { min-width: 0; min-height: 36px; overflow: hidden; border: 1px solid transparent; border-radius: var(--radius-md); background: transparent; transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease; }
.field-body:focus-within,.literature-field.editing .field-body { border-color: var(--color-primary); background: var(--color-canvas); box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 14%, transparent); }

.markdown-field {
  min-height: 36px;
}

.field-input {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.file-link {
  width: 100%;
  padding: 9px 10px;
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font: inherit;
  text-align: left;
  text-decoration: underline;
  cursor: pointer;
}

.star-editor {
  display: flex;
  padding: 6px 8px;
}

.pixel-loader { display: grid; grid-template-columns: repeat(5, 5px); align-items: end; gap: 3px; height: 13px; margin: 0 4px; }.pixel-loader i { display: block; width: 5px; height: 5px; background: var(--color-primary); image-rendering: pixelated; animation: literature-pixel-loader 800ms steps(2,end) infinite; }.pixel-loader i:nth-child(2),.pixel-loader i:nth-child(4) { animation-delay: 120ms; }.pixel-loader i:nth-child(3) { animation-delay: 240ms; }
@keyframes literature-pixel-loader { 0%,100% { height: 5px; opacity: .38; } 50% { height: 13px; opacity: 1; } }

.star-editor button {
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 18px;
}

.star-editor button.active {
  color: #f3bd21;
}
</style>
