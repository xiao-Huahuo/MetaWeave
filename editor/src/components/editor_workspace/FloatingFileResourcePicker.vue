<!--
  Floating file resource picker.

  Usage:
  Wraps the existing FileResourceManager in a modal card so pages can choose a
  knowledge-base file without switching to the full resource-manager page.
-->
<script setup lang="ts">
import { computed } from 'vue'

import FileResourceManager from '@/components/editor_workspace/FileResourceManager.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const workspaceStore = useWorkspaceStore()

const emit = defineEmits<{
  close: []
}>()

const selectedFile = computed(() => {
  const node = workspaceStore.flatNodes.find((item) => item.path === workspaceStore.selectedTreePath)
  return node && !node.isDir ? node : null
})

const selectedPath = computed(() => selectedFile.value?.path ?? '')

async function confirmSelection() {
  if (!selectedFile.value) {
    workspaceStore.showToast('请选择一个文件')
    return
  }
  await workspaceStore.selectMarkdownHtmlVisualizationDocument(selectedFile.value)
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="floating-picker-backdrop" role="presentation" @click.self="emit('close')">
      <section
        class="floating-picker-card library-form-surface"
        role="dialog"
        aria-modal="true"
        aria-labelledby="md-html-file-picker-title"
      >
        <header class="floating-picker-header">
          <h2 id="md-html-file-picker-title">选择文件</h2>
        </header>
        <FileResourceManager class="floating-picker-manager" embedded-picker />
        <footer class="floating-picker-footer">
          <label class="path-field" for="md-html-selected-path">
            <span>文件路径</span>
            <input
              id="md-html-selected-path"
              :value="selectedPath"
              type="text"
              readonly
              placeholder="请选择一个文件"
            />
          </label>
          <div class="footer-actions">
            <button type="button" class="primary" :disabled="!selectedFile" @click="confirmSelection">
              选择文件
            </button>
            <button type="button" @click="emit('close')">取消</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.floating-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: var(--space-24);
  background: rgba(0, 0, 0, 0.42);
  animation: picker-fade-in 160ms ease;
}

.floating-picker-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(1120px, calc(100vw - 48px));
  height: min(760px, calc(100vh - 48px));
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.34);
}

.floating-picker-card.library-form-surface {
  border-radius: 28px;
  box-shadow:
    0 0 0 2px var(--library-form-ring),
    0 24px 60px rgba(0, 0, 0, 0.34);
  animation: library-form-scan-in 420ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

.floating-picker-header,
.floating-picker-footer {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  min-width: 0;
  border-color: var(--color-border);
  background: var(--color-canvas);
}

.floating-picker-header {
  justify-content: space-between;
  min-height: 44px;
  padding: 0 var(--space-16);
  border-bottom: 1px solid var(--color-border);
}

.floating-picker-header h2 {
  margin: 0 0 0 var(--space-4);
  color: var(--color-text);
  font-size: calc(14px * var(--font-scale));
  font-weight: 650;
}

.footer-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.floating-picker-manager {
  min-width: 0;
  min-height: 0;
  border: 0;
  border-radius: 0;
}

.floating-picker-footer {
  justify-content: center;
  min-height: 56px;
  padding: var(--space-10) var(--space-14);
  border-top: 1px solid var(--color-border);
}

.path-field {
  display: grid;
  grid-template-columns: auto minmax(220px, 520px);
  align-items: center;
  gap: var(--space-8);
  min-width: 0;
  flex: 1 1 auto;
  max-width: 660px;
}

.path-field span {
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.path-field input {
  min-width: 0;
  height: 32px;
  padding: 0 var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas-soft);
  color: var(--color-text);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  text-overflow: ellipsis;
}

.footer-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  flex: 0 0 auto;
}

.footer-actions button {
  min-width: 74px;
  padding: 0 var(--space-12);
  font-size: calc(12px * var(--font-scale));
}

.footer-actions button.primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.footer-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.footer-actions button:hover:not(:disabled) {
  border-color: var(--color-primary);
}

@keyframes picker-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (max-width: 760px) {
  .floating-picker-backdrop {
    padding: var(--space-12);
  }

  .floating-picker-card {
    width: calc(100vw - 24px);
    height: calc(100vh - 24px);
  }

  .floating-picker-footer,
  .path-field {
    align-items: stretch;
    grid-template-columns: 1fr;
  }

  .floating-picker-footer {
    flex-direction: column;
  }

  .footer-actions {
    width: 100%;
  }

  .footer-actions button {
    flex: 1 1 0;
  }
}
</style>
