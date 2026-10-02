<!-- Shared tool policy rows with reusable todo checkboxes and animated sidebar-style parameter disclosure. -->
<script setup lang="ts">
import { useId } from 'vue'
import CreativeCheckbox from '@/components/common/CreativeCheckbox.vue'
import SettingsDisclosure from '@/components/common/SettingsDisclosure.vue'
import type { McpTool } from '@/api/mcp'
const props = withDefaults(defineProps<{ tools: McpTool[]; modelValue: string[]; label: string; disabled?: boolean; checkboxStyle?: 'native' | 'todo' }>(), { checkboxStyle: 'native' })
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const inputPrefix = useId()
/** Toggle one tool without changing unrelated grants. */
function toggle(name: string, checked: boolean) {
  emit('update:modelValue', checked ? [...new Set([...props.modelValue, name])] : props.modelValue.filter(n => n !== name))
}
</script>
<template>
  <div class="mcp-tool-list" :aria-label="label">
    <div v-for="(tool, index) in tools" :key="tool.name" class="mcp-tool-row">
      <div class="mcp-tool-select">
        <CreativeCheckbox v-if="checkboxStyle === 'todo'" :input-id="inputPrefix + '-' + index" :model-value="modelValue.includes(tool.name)" :label="tool.title || tool.name" :disabled="disabled" @update:model-value="toggle(tool.name, $event)" />
        <input v-else :id="inputPrefix + '-' + index" type="checkbox" :checked="modelValue.includes(tool.name)" :disabled="disabled" @change="toggle(tool.name, ($event.target as HTMLInputElement).checked)" />
        <label :for="inputPrefix + '-' + index">{{ tool.title || tool.name }}</label>
        <span class="mcp-access-kind">{{ tool.write || (tool.annotations && !tool.annotations.readOnlyHint) ? '写入' : '只读' }}</span>
      </div>
      <SettingsDisclosure label="参数与用途"><p>{{ tool.description }}</p><pre>{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></SettingsDisclosure>
    </div>
    <p v-if="!tools.length" class="mcp-empty">尚未发现工具，先测试连接。</p>
  </div>
</template>
