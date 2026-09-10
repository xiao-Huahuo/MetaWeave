<!--
  Component library preview card.

  Usage:
  Shows one real sandboxed component preview, its single fixed tag, intrinsic
  preview height, a source-copy action, and a dedicated detail-page trigger.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

import FavoriteButton from '@/components/common/FavoriteButton.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import ComponentNameEditor from '@/components/component_library/ComponentNameEditor.vue'
import ComponentPreview from '@/components/component_library/ComponentPreview.vue'
import DrawingScriptCover from '@/components/component_library/DrawingScriptCover.vue'
import type { ComponentLibraryItem } from '@/types/componentLibrary'

defineOptions({ name: 'ComponentLibraryCard' })

const props = withDefaults(defineProps<{
  item: ComponentLibraryItem
  renaming?: boolean
  deleting?: boolean
  readonly?: boolean
}>(), {
  renaming: false,
  deleting: false,
  readonly: false,
})
const emit = defineEmits<{
  open: [item: ComponentLibraryItem]
  rename: [item: ComponentLibraryItem, name: string]
  delete: [item: ComponentLibraryItem]
}>()
const copied = ref(false)
const previewHeight = ref(216)
const isDrawingScript = computed(() => props.item.source_format === 'script')

/** Add only the sandbox canvas vertical padding; no artificial minimum or maximum. */
const previewStyle = computed(() => ({
  '--component-preview-height': `${previewHeight.value + 64}px`,
}))

/** Resize only for a real height change so preview interaction never resets the iframe. */
function handlePreviewResize(size: { width: number; height: number }): void {
  if (previewHeight.value === size.height) return
  previewHeight.value = size.height
}

/** Copy the exact uploaded or bundled source and briefly acknowledge success. */
async function copySource(): Promise<void> {
  await navigator.clipboard.writeText(props.item.source)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1400)
}
</script>

<template>
  <article class="component-card">
    <div class="preview-surface" :style="previewStyle">
      <div class="card-actions">
        <FavoriteButton
          class="component-favorite"
          target-type="component"
          :target-id="item.component_id"
          :size="17"
          variant="v1"
        />
        <button class="copy-button" type="button" :title="copied ? '已复制' : '复制代码'" :aria-label="copied ? '已复制' : '复制代码'" @click="copySource">
          <IcIcon :name="copied ? 'check' : 'copy'" :size="15" morph />
        </button>
        <button class="detail-button" type="button" title="查看详情" aria-label="查看详情" @click="emit('open', item)">
          <IcIcon name="open-in-full" :size="16" />
        </button>
      </div>
      <DrawingScriptCover v-if="isDrawingScript" :item="item" />
      <ComponentPreview
        v-else
        :source="item.source"
        :source-format="item.source_format"
        :label="item.title"
        @resize="handlePreviewResize"
      />
    </div>
    <footer class="component-meta">
      <div class="component-identity">
        <ComponentNameEditor
          v-if="!readonly"
          :name="item.title"
          :compact="true"
          :saving="renaming"
          @rename="emit('rename', item, $event)"
        />
        <strong v-else class="readonly-title">{{ item.title }}</strong>
        <div class="component-capsules">
          <span class="tag-pill">{{ isDrawingScript ? '绘图脚本' : item.tag }}</span>
          <span v-if="isDrawingScript" class="language-pill">{{ item.script_language }}</span>
        </div>
      </div>
      <button
        v-if="!readonly"
        class="delete-button"
        type="button"
        title="删除组件"
        aria-label="删除组件"
        :disabled="deleting"
        @click="emit('delete', item)"
      >
        <IcIcon name="trash" :size="15" />
      </button>
    </footer>
  </article>
</template>

<style scoped>
.component-card {
  position: relative;
  display: inline-flex;
  width: 100%;
  min-width: 0;
  margin-bottom: var(--space-16);
  flex-direction: column;
  overflow: hidden;
  border: 0;
  border-radius: 20px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  animation: component-card-enter 200ms cubic-bezier(0.23, 1, 0.32, 1) both;
  transition:
    box-shadow 160ms ease,
    background-color 160ms ease;
  break-inside: avoid;
  page-break-inside: avoid;
  vertical-align: top;
}

.preview-surface {
  position: relative;
  height: var(--component-preview-height, 280px);
  background: var(--color-surface-raised);
  transition: height 180ms ease;
}

.card-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  opacity: 0.58;
  transition: opacity 140ms ease;
}

.detail-button,
.copy-button,
.delete-button {
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    color 140ms ease,
    transform 140ms cubic-bezier(0.23, 1, 0.32, 1);
}

.detail-button:hover,
.copy-button:hover {
  background: color-mix(in srgb, var(--color-canvas) 72%, transparent);
  color: var(--color-primary);
}

.delete-button {
  flex: 0 0 auto;
  align-self: flex-end;
}

.delete-button:hover:not(:disabled) {
  color: var(--color-danger);
}

.delete-button:disabled {
  cursor: wait;
  opacity: 0.45;
}

.component-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-10);
  min-height: 56px;
  padding: var(--space-10) var(--space-12);
}

.component-identity {
  display: grid;
  min-width: 0;
  gap: var(--space-6);
}

.component-capsules {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: var(--space-6);
}

.readonly-title {
  overflow: hidden;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  min-height: 23px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 30%, transparent);
  color: var(--color-tag-pill-text);
  padding: 0 8px;
  font-size: calc(11px * var(--font-scale));
}

.language-pill {
  display: inline-flex;
  align-items: center;
  min-height: 23px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  padding: 0 8px;
  font-size: calc(11px * var(--font-scale));
}

@media (hover: hover) and (pointer: fine) {
  .component-card:hover {
    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.14);
  }

  .component-card:hover .card-actions {
    opacity: 1;
  }

  .detail-button:hover,
  .copy-button:hover,
  .delete-button:hover:not(:disabled) {
    transform: scale(1.08);
  }
}

@keyframes component-card-enter {
  from { opacity: 0; transform: translateY(6px) scale(0.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .component-card {
    animation: none;
  }

  .detail-button,
  .copy-button,
  .delete-button {
    transform: none;
  }
}

</style>
