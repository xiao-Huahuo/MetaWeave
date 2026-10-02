<!-- Editable env/header rows; null preserves encrypted stored values, deleting a row removes the key. -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
const props = defineProps<{ modelValue: Record<string, string | null>; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string | null>] }>()
const rows = ref<Array<{ key: string; value: string | null; reveal: boolean }>>([])
watch(() => props.modelValue, value => {
  if (JSON.stringify(value) === JSON.stringify(Object.fromEntries(rows.value.map(r => [r.key, r.value])))) return
  rows.value = Object.entries(value).map(([key, val]) => ({ key, value: val, reveal: false }))
}, { immediate: true })
/** Publish edits without turning untouched stored secrets into empty replacements. */
function publish() { emit('update:modelValue', Object.fromEntries(rows.value.map(r => [r.key, r.value]))) }
function add() { rows.value.push({ key: '', value: '', reveal: false }) }
function remove(index: number) { rows.value.splice(index, 1); publish() }
</script>
<template>
  <div class="mcp-key-values">
    <div class="mcp-toolbar"><h4>{{ label }}</h4><button class="mcp-text-button" type="button" @click="add"><IcIcon name="add" :size="16" /><span>添加{{ label }}</span></button></div>
    <div v-for="(row, index) in rows" :key="index" class="mcp-key-row">
      <input v-model="row.key" :aria-label="`${label}名称 ${index + 1}`" placeholder="名称" spellcheck="false" @input="publish" />
      <input :value="row.value ?? ''" :type="row.reveal ? 'text' : 'password'" :aria-label="`${label}值 ${index + 1}`"
        :placeholder="row.value === null ? '已保存，留空保留' : '值'" autocomplete="off" spellcheck="false"
        @input="row.value = ($event.target as HTMLInputElement).value; publish()" />
      <button class="mcp-icon-button" type="button" :disabled="row.value === null" :title="row.value === null ? '已保存值不回传，填写新值替换' : ''" :aria-label="row.reveal ? '隐藏值' : '显示值'" @click="row.reveal = !row.reveal"><IcIcon :name="row.reveal ? 'visibility-off' : 'visibility'" :size="16" /></button>
      <button class="mcp-icon-button danger" type="button" :aria-label="`删除${label} ${index + 1}`" @click="remove(index)"><IcIcon name="trash" :size="16" /></button>
    </div>
  </div>
</template>
