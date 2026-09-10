<!--
  Shared editor view-mode switch.

  Usage:
  Bind an EditorViewMode with v-model. Set preview-only when the current file
  cannot expose text, or edit-only for source files that are rendered directly
  in the editable surface.
-->
<script setup lang="ts">
import { computed } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import type { EditorWorkspaceMode } from '@/types/knowledge'

defineOptions({ name: 'EditorModeSwitch' })

const props = withDefaults(defineProps<{
  modelValue: EditorWorkspaceMode
  options?: Array<{ mode: EditorWorkspaceMode; label: string; icon: string }>
  previewOnly?: boolean
  editOnly?: boolean
}>(), {
  previewOnly: false,
  editOnly: false,
})

const emit = defineEmits<{
  'update:modelValue': [mode: EditorWorkspaceMode]
}>()

/** Stable mode definitions shared by the formal editor and readonly preview. */
const defaultModeButtons: Array<{ mode: EditorWorkspaceMode; label: string; icon: string }> = [
  { mode: 'edit', label: '编辑', icon: 'edit' },
  { mode: 'preview', label: '预览', icon: 'visibility' },
  { mode: 'split', label: '分栏', icon: 'view-column' },
]
const modeButtons = computed(() => props.options ?? defaultModeButtons)
const switchStyle = computed(() => ({
  '--mode-count': modeButtons.value.length,
  '--mode-index': Math.max(0, modeButtons.value.findIndex((button) => button.mode === props.modelValue)),
}))

/** Selects an available view mode without changing the editor's write policy. */
function selectMode(mode: EditorWorkspaceMode) {
  if (props.previewOnly && mode !== 'preview') return
  if (props.editOnly && mode !== 'edit') return
  emit('update:modelValue', mode)
}
</script>

<template>
  <div
    class="editor-mode-switch"
    :data-mode="modelValue"
    :style="switchStyle"
    role="group"
    aria-label="Editor view mode"
  >
    <span class="editor-mode-indicator"></span>
    <button
      v-for="button in modeButtons"
      :key="button.mode"
      :class="{ active: modelValue === button.mode }"
      :disabled="(previewOnly && button.mode !== 'preview') || (editOnly && button.mode !== 'edit')"
      :aria-pressed="modelValue === button.mode"
      type="button"
      @click="selectMode(button.mode)"
    >
      <IcIcon :name="button.icon" :size="14" />
      <span>{{ button.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.editor-mode-switch {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--mode-count), minmax(0, 1fr));
  padding: 2px;
  border: 0;
  border-radius: var(--radius-md);
  background: var(--color-canvas-soft);
}

.editor-mode-indicator {
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 2px;
  width: calc((100% - 4px) / var(--mode-count));
  pointer-events: none;
  border-radius: 999px;
  background: var(--color-primary);
  transform: translateX(calc(var(--mode-index) * 100%));
  transition: transform 180ms ease;
}

.editor-mode-switch button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  min-width: 68px;
  height: 22px;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: 0 var(--space-6);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), transform 140ms ease;
}

.editor-mode-switch button:not(.active):not(:disabled):hover {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.editor-mode-switch button:not(:disabled):active {
  transform: scale(.96);
}

.editor-mode-switch button.active {
  color: white;
}

.editor-mode-switch button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.editor-mode-switch button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .editor-mode-indicator {
    transition: none;
  }

  .editor-mode-switch button {
    transition: none;
  }
}
</style>
