<!-- TodoSidebar's exact animated checkbox, shared with settings; native input retains keyboard and change semantics. -->
<script setup lang="ts">
const props = withDefaults(defineProps<{ modelValue: boolean; label: string; inputId?: string; disabled?: boolean; title?: string; inputType?: 'checkbox' | 'radio'; name?: string }>(), { disabled: false, title: '', inputType: 'checkbox' })
const emit = defineEmits<{ 'update:modelValue': [checked: boolean] }>()
</script>
<template>
  <label class="creative-checkbox" :title="title || label" :class="{ 'is-disabled': disabled }">
    <input :id="inputId" :type="inputType" :name="name" :checked="props.modelValue" :disabled="disabled" :aria-label="label" @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)" />
    <div class="checkbox-box"><svg viewBox="0 0 44 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path class="box-path" d="M12,4 H32 A8,8 0 0 1 40,12 V32 A8,8 0 0 1 32,40 H12 A8,8 0 0 1 4,32 V12 A8,8 0 0 1 12,4 Z" />
      <path class="check-path" d="M14,23 L19,28 L30,15" />
    </svg></div>
  </label>
</template>
<style src="./creative-checkbox.css" scoped></style>
