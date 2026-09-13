<!--
  Component upload form.

  Usage:
  Presents a centered library-style dialog with code on the left and either a
  live component preview or optional drawing-script cover upload on the right.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import CompactCodeInput from '@/components/common/CompactCodeInput.vue'
import ComponentPreview from '@/components/component_library/ComponentPreview.vue'
import {
  buildComponentPreviewDocument,
  canBuildComponentPreview,
} from '@/components/component_library/componentPreview'
import LibraryCoverUploader from '@/components/library_view/LibraryCoverUploader.vue'
import LibraryTagPicker from '@/components/library_view/LibraryTagPicker.vue'
import { createComponentLibraryItem } from '@/api/componentLibrary'
import { COMPONENT_TAGS, type ComponentLibraryItem, type ComponentSourceFormat } from '@/types/componentLibrary'
import type { LibraryAsset } from '@/types/knowledge'

defineOptions({ name: 'ComponentUploadForm' })

const props = defineProps<{ userId: string }>()
const emit = defineEmits<{
  cancel: []
  created: [component: ComponentLibraryItem]
}>()

interface SelectedComponentFile {
  /** Original basename persisted by the backend. */
  name: string
  /** UTF-8 browser-decoded component source. */
  source: string
}

/** Built-in language suggestions are offered through the shared tag picker. */
const SCRIPT_LANGUAGE_OPTIONS = ['Python', 'R', 'MATLAB', 'JavaScript', 'Julia', 'Gnuplot']
const DRAWING_SCRIPT_TAG = 'drawing scripts' as const
const DRAWING_SCRIPT_LABEL = '绘图脚本'
const COMPONENT_TAG_OPTIONS = COMPONENT_TAGS.map((tag) => (
  tag === DRAWING_SCRIPT_TAG ? DRAWING_SCRIPT_LABEL : tag
))

const source = ref('')
const componentName = ref('')
const selectedTags = ref<string[]>([])
const selectedFiles = ref<SelectedComponentFile[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const error = ref('')
const saving = ref(false)
const selectedScriptLanguages = ref<string[]>([])
const coverAsset = ref<LibraryAsset | null>(null)
const drawingScriptMode = computed(() => selectedTags.value[0] === DRAWING_SCRIPT_LABEL)
const scriptLanguage = computed(() => selectedScriptLanguages.value[0]?.trim() || '')
const sourceFormat = computed<ComponentSourceFormat>(() => detectSourceFormat(source.value))
const filePickerTitle = computed(() => {
  if (!selectedFiles.value.length) return '选择 Vue / HTML 文件'
  if (selectedFiles.value.length === 1) return selectedFiles.value[0]?.name || '已选择 1 个文件'
  return `已选择 ${selectedFiles.value.length} 个文件`
})

/** Infer the existing preview compiler from source content. */
function detectSourceFormat(value: string): ComponentSourceFormat {
  return value.toLowerCase().includes('<template') ? 'vue' : 'html'
}

/** Clear incompatible file and cover state when the selected tag changes renderer. */
watch(drawingScriptMode, (active) => {
  selectedFiles.value = []
  if (!active) coverAsset.value = null
})

/** Retain the persistent cover asset selected through the shared library uploader. */
function handleCoverUploaded(asset: LibraryAsset): void {
  coverAsset.value = asset
}

/** Read every selected supported file and preview the first one. */
async function selectComponentFiles(event: Event): Promise<void> {
  error.value = ''
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const unsupported = files.find((file) => !/\.(vue|html?)$/iu.test(file.name))
  if (unsupported) {
    error.value = `不支持的文件格式：${unsupported.name}`
    input.value = ''
    return
  }
  selectedFiles.value = await Promise.all(files.map(async (file) => ({
    name: file.name,
    source: await file.text(),
  })))
  const first = selectedFiles.value[0]
  if (first) {
    source.value = first.source
    componentName.value = first.name.replace(/\.(vue|html?)$/iu, '')
  }
  input.value = ''
}

/** Build the persisted basename while retaining an imported file's extension. */
function namedFilename(name: string, value: string, originalFilename = ''): string {
  const stem = name.trim().replace(/\.(vue|html?)$/iu, '')
  const importedSuffix = originalFilename.match(/\.(vue|html?)$/iu)?.[0]
  const suffix = importedSuffix || (detectSourceFormat(value) === 'vue' ? '.vue' : '.html')
  return `${stem}${suffix}`
}

/** Compile once at submission so invalid source is never persisted. */
async function submit(): Promise<void> {
  error.value = ''
  const tag = drawingScriptMode.value ? DRAWING_SCRIPT_TAG : selectedTags.value[0]
  if (!componentName.value.trim().replace(/\.(vue|html?)$/iu, '')) {
    error.value = '请输入组件名'
    return
  }
  if (!source.value.trim() && !selectedFiles.value.length) {
    error.value = '请输入组件代码'
    return
  }
  if (!tag) {
    error.value = '请选择一个标签'
    return
  }
  if (drawingScriptMode.value && !scriptLanguage.value) {
    error.value = '请输入脚本语言'
    return
  }
  try {
    const uploads = !drawingScriptMode.value && selectedFiles.value.length
      ? selectedFiles.value.map((file, index) => ({
          source: index === 0 ? source.value : file.source,
          filename: index === 0
            ? namedFilename(componentName.value, source.value, file.name)
            : file.name,
        }))
      : [{
          source: source.value,
          filename: drawingScriptMode.value
            ? `${componentName.value.trim().replace(/\.script$/iu, '')}.script`
            : namedFilename(componentName.value, source.value),
        }]
    if (!drawingScriptMode.value) {
      uploads.forEach((upload) => {
        if (canBuildComponentPreview(upload.source)) {
          buildComponentPreviewDocument(upload.source, detectSourceFormat(upload.source))
        }
      })
    }
    saving.value = true
    const results = await Promise.all(uploads.map((upload) => createComponentLibraryItem({
      user_id: props.userId,
      source: upload.source,
      tag: tag as (typeof COMPONENT_TAGS)[number],
      ...(upload.filename ? { filename: upload.filename } : {}),
      ...(drawingScriptMode.value ? {
        script_language: scriptLanguage.value,
        cover_asset_id: coverAsset.value?.asset_id || '',
      } : {}),
    })))
    const firstResult = results[0]
    if (firstResult) emit('created', firstResult.component)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '组件上传失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="upload-backdrop" @click.self="emit('cancel')">
      <section
        class="upload-form library-form-surface"
        role="dialog"
        aria-modal="true"
        aria-labelledby="component-upload-title"
      >
    <header class="form-header">
      <h2 id="component-upload-title">上传组件</h2>
      <button class="icon-button" type="button" title="关闭" aria-label="关闭上传组件" @click="emit('cancel')">
        <IcIcon name="close" :size="16" />
      </button>
    </header>

    <div class="compiler-grid">
      <CompactCodeInput
        v-model="source"
        class="code-panel form-input-surface"
        :label="drawingScriptMode ? '绘图脚本' : '组件代码'"
        :placeholder="drawingScriptMode ? '粘贴绘图脚本代码' : '粘贴 Vue / HTML 代码'"
      />
      <section v-if="drawingScriptMode" class="script-cover-panel" aria-label="绘图脚本封面图片">
        <span class="panel-label">封面图片 · 可选</span>
        <LibraryCoverUploader
          :user-id="userId"
          :preview-url="coverAsset?.url"
          empty-label="点击或拖拽上传封面；留空时显示组件名"
          @uploaded="handleCoverUploaded"
        />
      </section>
      <section v-else class="preview-panel" aria-label="实时编译预览">
        <span class="panel-label">实时预览 · {{ sourceFormat.toUpperCase() }}</span>
        <ComponentPreview
          v-if="source.trim()"
          :source="source"
          :source-format="sourceFormat"
          label="待上传组件"
        />
        <div v-else class="preview-placeholder">
          <IcIcon name="code" :size="28" />
        </div>
      </section>
    </div>

    <div class="metadata-fields" :class="{ 'drawing-script-fields': drawingScriptMode }">
      <label class="name-field">
        <span>组件名</span>
        <input
          class="form-input-surface"
          v-model="componentName"
          name="component-name"
          type="text"
          maxlength="180"
          autocomplete="off"
        />
      </label>
      <div v-if="drawingScriptMode" key="script-language-field" class="script-language-field">
        <span>脚本语言</span>
        <LibraryTagPicker
          key="script-language-picker"
          v-model="selectedScriptLanguages"
          :available-tags="SCRIPT_LANGUAGE_OPTIONS"
          :single="true"
          :allow-custom="true"
          :dropdown-align-offset="24"
          :dropdown-z-index="1200"
          placeholder="输入或选择脚本语言"
        />
      </div>
      <div key="component-tag-field" class="tag-field">
        <span>标签</span>
        <LibraryTagPicker
          key="component-tag-picker"
          v-model="selectedTags"
          :available-tags="COMPONENT_TAG_OPTIONS"
          :single="true"
          :allow-custom="false"
          :dropdown-align-offset="24"
          :dropdown-z-index="1200"
          placeholder="选择一个标签"
        />
      </div>
    </div>

    <footer class="form-actions">
      <div class="form-leading">
        <input
          v-if="!drawingScriptMode"
          ref="fileInput"
          class="hidden-file-input"
          type="file"
          accept=".vue,.html,.htm,text/html"
          multiple
          @change="selectComponentFiles"
        />
        <button
          v-if="!drawingScriptMode"
          class="file-picker-button"
          type="button"
          :title="filePickerTitle"
          aria-label="选择 Vue / HTML 文件"
          @click="fileInput?.click()"
        >
          <IcIcon name="folder-open" :size="16" />
        </button>
        <span v-if="error" class="form-error" role="alert">{{ error }}</span>
      </div>
      <div class="submit-actions">
        <button class="secondary-button" type="button" @click="emit('cancel')">取消</button>
        <button class="primary-button" type="button" :disabled="saving" @click="submit">
          <IcIcon name="upload" :size="15" />
          {{ saving ? '上传中' : '上传组件' }}
        </button>
      </div>
    </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.upload-backdrop {
  position: fixed;
  z-index: 1100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: var(--space-24);
  background: rgba(0, 0, 0, 0.42);
}

.upload-form {
  width: min(1080px, 100%);
  max-height: calc(100vh - 48px);
  overflow-x: hidden;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.28);
}

.upload-form.library-form-surface {
  box-shadow:
    0 0 0 2px var(--library-form-ring),
    0 24px 70px rgba(0, 0, 0, 0.28);
}

.form-header,
.form-actions {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-12) var(--space-16);
}

.form-header {
  justify-content: space-between;
}

.form-header h2 {
  margin: 0;
}

.form-header h2 {
  color: var(--color-text);
  font-size: calc(15px * var(--font-scale));
}

.icon-button {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.icon-button:hover {
  background: var(--color-canvas-soft);
  color: var(--color-text);
}

.compiler-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  height: clamp(280px, calc(100vh - 320px), 480px);
  margin: 0 var(--space-16);
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 20px;
}

.code-panel,
.preview-panel,
.script-cover-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  background: var(--color-canvas);
}

.preview-panel {
  border-left: 1px solid var(--color-border-strong);
  background: var(--color-surface-raised);
}

.script-cover-panel {
  display: grid;
  grid-template-rows: 30px minmax(0, 1fr);
  padding: 0 var(--space-12) var(--space-12);
  border-left: 1px solid var(--color-border-strong);
  background: var(--color-surface-raised);
}

.script-cover-panel .panel-label {
  padding-right: 0;
  padding-left: 0;
}

.script-cover-panel :deep(.library-cover-uploader) {
  min-height: 0;
}

.script-cover-panel :deep(.cover-drop),
.script-cover-panel :deep(.cover-preview) {
  border-radius: 14px;
}

.panel-label {
  flex: 0 0 auto;
  min-height: 30px;
  padding: var(--space-8) var(--space-12);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.preview-placeholder {
  display: grid;
  flex: 1;
  place-content: center;
  justify-items: center;
  gap: var(--space-10);
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.metadata-fields {
  display: grid;
  box-sizing: border-box;
  width: calc(50% + var(--space-24));
  gap: var(--space-12);
  padding: var(--space-16) 0 0 var(--space-24);
}

.metadata-fields.drawing-script-fields {
  width: 100%;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  padding-right: var(--space-24);
}

.metadata-fields.drawing-script-fields .tag-field {
  grid-column: 1 / -1;
}

.name-field,
.script-language-field,
.tag-field {
  display: grid;
  gap: var(--space-8);
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.name-field input {
  box-sizing: border-box;
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  outline: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  padding: 0 var(--space-20);
  font-size: calc(13px * var(--font-scale));
}

.name-field input:focus {
  border-color: var(--color-primary);
}

.form-actions {
  justify-content: space-between;
  padding: var(--space-16) var(--space-24);
}

.form-leading,
.submit-actions,
.file-picker-button {
  display: inline-flex;
  align-items: center;
}

.form-leading {
  min-width: 0;
  gap: var(--space-10);
}

.submit-actions {
  flex: 0 0 auto;
  gap: var(--space-8);
}

.hidden-file-input {
  display: none;
}

.file-picker-button {
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0;
  cursor: pointer;
}

.file-picker-button:hover {
  background: var(--color-canvas-soft);
  color: var(--color-primary);
}

.form-error {
  color: var(--color-danger);
  font-size: calc(12px * var(--font-scale));
}

.secondary-button,
.primary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  min-height: 32px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0 var(--space-16);
  cursor: pointer;
  font-size: calc(13px * var(--font-scale));
}

.secondary-button {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.primary-button {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.primary-button:disabled {
  opacity: 0.55;
  cursor: default;
}

@media (max-width: 820px) {
  .compiler-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .preview-panel {
    min-height: 360px;
    border-top: 1px solid var(--color-border-strong);
    border-left: 0;
  }

  .script-cover-panel {
    min-height: 300px;
    border-top: 1px solid var(--color-border-strong);
    border-left: 0;
  }

  .form-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .form-leading,
  .submit-actions {
    justify-content: space-between;
  }

  .metadata-fields {
    width: 100%;
    padding-right: var(--space-24);
  }
}

@media (max-width: 480px) {
  .upload-backdrop {
    padding: var(--space-8);
  }

  .metadata-fields.drawing-script-fields {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-8);
    padding: var(--space-12);
  }

  .metadata-fields.drawing-script-fields .tag-field {
    grid-column: auto;
  }

  .compiler-grid {
    height: 340px;
    grid-template-rows: minmax(120px, 0.7fr) minmax(200px, 1.3fr);
    margin: 0 var(--space-8);
  }

  .script-cover-panel {
    min-height: 0;
  }

  .form-actions {
    gap: var(--space-8);
    padding: var(--space-12);
  }
}
</style>
