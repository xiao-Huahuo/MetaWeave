<!--
  Basic settings section.

  Usage:
  Edits knowledge library metadata and ingestion switches. The parent owns
  persistence and side effects.
-->
<script setup lang="ts">
import { nextTick } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'

const libraryNameDraft = defineModel<string>('libraryNameDraft', { required: true })
const knowledgeDirDraft = defineModel<string>('knowledgeDirDraft', { required: true })
const editorImageAssetsDirDraft = defineModel<string>('editorImageAssetsDirDraft', { required: true })
const watchEnabledDraft = defineModel<boolean>('watchEnabledDraft', { required: true })
const autoIngestOnUploadDraft = defineModel<boolean>('autoIngestOnUploadDraft', { required: true })
const visionUnderstandingEnabledDraft = defineModel<boolean>('visionUnderstandingEnabledDraft', { required: true })
const dshCodingAgentEnabledDraft = defineModel<boolean>('dshCodingAgentEnabledDraft', { required: true })
const knowledgeIgnorePatternsDraft = defineModel<string>('knowledgeIgnorePatternsDraft', { required: true })

const props = defineProps<{
  supportedFileTypes: string[]
  hasChanges: boolean
  saving: boolean
  saveMessage: string
  saveError: string
  switchingKnowledgeRoot: boolean
}>()

const emit = defineEmits<{
  save: []
  logout: []
  selectKnowledgeDirectory: []
}>()


/** Converts one backend-supported suffix into the existing gitignore-style rule. */
function fileTypeRule(suffix: string): string {
  const normalizedSuffix = suffix.trim().toLowerCase()
  return `*${normalizedSuffix.startsWith('.') ? normalizedSuffix : `.${normalizedSuffix}`}`
}

/** Reports whether the exact file-type rule already exists, ignoring case and surrounding spaces. */
function isFileTypeBlocked(suffix: string): boolean {
  const rule = fileTypeRule(suffix)
  return knowledgeIgnorePatternsDraft.value
    .split(/\r?\n/u)
    .some((pattern) => pattern.trim().toLowerCase() === rule)
}

/** Appends one unique rule and persists it through the section's existing save flow. */
async function appendBlockedFileType(suffix: string): Promise<void> {
  if (isFileTypeBlocked(suffix)) return
  const currentPatterns = knowledgeIgnorePatternsDraft.value.trimEnd()
  knowledgeIgnorePatternsDraft.value = currentPatterns
    ? `${currentPatterns}\n${fileTypeRule(suffix)}`
    : fileTypeRule(suffix)
  await nextTick()
  emit('save')
}
</script>

<template>
  <div class="setting-section">
    <h3>知识库</h3>
    <div class="setting-row">
      <label>库名称</label>
      <input v-model="libraryNameDraft" spellcheck="false" @blur="$emit('save')" />
    </div>
    <div class="setting-row">
      <label>知识目录</label>
      <div class="knowledge-dir-control">
        <input v-model="knowledgeDirDraft" spellcheck="false" @blur="$emit('save')" />
        <button
          class="knowledge-dir-picker"
          type="button"
          title="选择知识库"
          aria-label="选择知识库"
          :disabled="props.switchingKnowledgeRoot"
          @click="$emit('selectKnowledgeDirectory')"
        >
          <IcIcon name="folder-open" :size="16" />
        </button>
      </div>
    </div>
    <div class="setting-row">
      <label>Markdown 粘贴图片目录</label>
      <input v-model="editorImageAssetsDirDraft" spellcheck="false" placeholder="./assets/" @blur="$emit('save')" />
    </div>

    <div class="setting-row toggle-row">
      <label>文件监听</label>
      <input v-model="watchEnabledDraft" type="checkbox" @change="$emit('save')" />
    </div>
    <div class="setting-row toggle-row">
      <label>自动灌库</label>
      <input v-model="autoIngestOnUploadDraft" type="checkbox" @change="$emit('save')" />
      <span class="hint-text">关闭时上传只进入文件树,点击 header 刷新或文件按钮才灌库</span>
    </div>
    <div class="setting-row toggle-row">
      <label>识图</label>
      <input v-model="visionUnderstandingEnabledDraft" type="checkbox" @change="$emit('save')" />
      <span class="hint-text">开启后才会调用本地 Qwen 补充图片语义；关闭时仅保留 OCR</span>
    </div>
    <div class="setting-row toggle-row">
      <label>启用 DSH coding agent</label>
      <input
        v-model="dshCodingAgentEnabledDraft"
        type="checkbox"
        aria-label="启用 DSH（deepseek-harness）作为 coding agent"
        @change="$emit('save')"
      />
      <span class="hint-text">使用 deepseek-harness 作为 coding agent；开启后在应用启动完成时后台加载</span>
    </div>
    <div class="setting-row ignore-row">
      <label>屏蔽区</label>
      <textarea
        v-model="knowledgeIgnorePatternsDraft"
        spellcheck="false"
        placeholder="# gitignore-like&#10;private/&#10;*.tmp&#10;!private/keep.md"
        @blur="$emit('save')"
      ></textarea>
    </div>
    <div class="blocked-file-types-row">
      <label>屏蔽的文件类型</label>
      <div class="file-type-chip-list" aria-label="屏蔽的文件类型">
        <button
          v-for="suffix in props.supportedFileTypes"
          :key="suffix"
          class="file-type-chip"
          :class="{ active: isFileTypeBlocked(suffix) }"
          type="button"
          :disabled="isFileTypeBlocked(suffix)"
          :aria-pressed="isFileTypeBlocked(suffix)"
          @mousedown.prevent
          @click="appendBlockedFileType(suffix)"
        >{{ suffix }}</button>
      </div>
    </div>
    <p class="setting-hint">被屏蔽的文件不会入库;已入库文件会在下次 Ingest 或单文件灌库时出库。</p>
    <div class="model-actions">
      <span v-if="saving" class="feedback">保存中...</span>
      <span v-if="saveMessage" class="feedback">{{ saveMessage }}</span>
      <span v-if="saveError" class="feedback error">{{ saveError }}</span>
    </div>
    <section class="logout-section">
      <div>
        <h3>当前身份</h3>
        <p class="setting-hint">退出后会回到 user_id 输入入口,本地知识库和用户配置不会被删除。</p>
      </div>
      <button class="logout-btn" type="button" @click="$emit('logout')">
        <div class="logout-sign">
          <svg viewBox="0 0 512 512"><path d="M377.9 105.9L500.7 228.7c7.2 7.2 11.3 17.1 11.3 27.3s-4.1 20.1-11.3 27.3L377.9 406.1c-6.4 6.4-15 9.9-24 9.9c-18.7 0-33.9-15.2-33.9-33.9l0-62.1-128 0c-17.7 0-32-14.3-32-32l0-64c0-17.7 14.3-32 32-32l128 0 0-62.1c0-18.7 15.2-33.9 33.9-33.9c9 0 17.6 3.6 24 9.9zM160 96L96 96c-17.7 0-32 14.3-32 32l0 256c0 17.7 14.3 32 32 32l64 0c17.7 0 32 14.3 32 32s-14.3 32-32 32l-64 0c-53 0-96-43-96-96L0 128C0 75 43 32 96 32l64 0c17.7 0 32 14.3 32 32s-14.3 32-32 32z" /></svg>
        </div>
        <div class="logout-text">退出登录</div>
      </button>
    </section>
    <div class="github-section">
      <a
        href="https://github.com/xiao-Huahuo/MetaWeave.git"
        target="_blank"
        rel="noopener noreferrer"
        class="github-btn"
      >
        <span class="github-shine"></span>
        <div class="github-content">
          <svg class="github-icon" viewBox="0 0 438.549 438.549">
            <path d="M409.132 114.573c-19.608-33.596-46.205-60.194-79.798-79.8-33.598-19.607-70.277-29.408-110.063-29.408-39.781 0-76.472 9.804-110.063 29.408-33.596 19.605-60.192 46.204-79.8 79.8C9.803 148.168 0 184.854 0 224.63c0 47.78 13.94 90.745 41.827 128.906 27.884 38.164 63.906 64.572 108.063 79.227 5.14.954 8.945.283 11.419-1.996 2.475-2.282 3.711-5.14 3.711-8.562 0-.571-.049-5.708-.144-15.417a2549.81 2549.81 0 01-.144-25.406l-6.567 1.136c-4.187.767-9.469 1.092-15.846 1-6.374-.089-12.991-.757-19.842-1.999-6.854-1.231-13.229-4.086-19.13-8.559-5.898-4.473-10.085-10.328-12.56-17.556l-2.855-6.57c-1.903-4.374-4.899-9.233-8.992-14.559-4.093-5.331-8.232-8.945-12.419-10.848l-1.999-1.431c-1.332-.951-2.568-2.098-3.711-3.429-1.142-1.331-1.997-2.663-2.568-3.997-.572-1.335-.098-2.43 1.427-3.289 1.525-.859 4.281-1.276 8.28-1.276l5.708.853c3.807.763 8.516 3.042 14.133 6.851 5.614 3.806 10.229 8.754 13.846 14.842 4.38 7.806 9.657 13.754 15.846 17.847 6.184 4.093 12.419 6.136 18.699 6.136 6.28 0 11.704-.476 16.274-1.423 4.565-.952 8.848-2.383 12.847-4.285 1.713-12.758 6.377-22.559 13.988-29.41-10.848-1.14-20.601-2.857-29.264-5.14-8.658-2.286-17.605-5.996-26.835-11.14-9.235-5.137-16.896-11.516-22.985-19.126-6.09-7.614-11.088-17.61-14.987-29.979-3.901-12.374-5.852-26.648-5.852-42.826 0-23.035 7.52-42.637 22.557-58.817-7.044-17.318-6.379-36.732 1.997-58.24 5.52-1.715 13.706-.428 24.554 3.853 10.85 4.283 18.794 7.952 23.84 10.994 5.046 3.041 9.089 5.618 12.135 7.708 17.705-4.947 35.976-7.421 54.818-7.421s37.117 2.474 54.823 7.421l10.849-6.849c7.419-4.57 16.18-8.758 26.262-12.565 10.088-3.805 17.802-4.853 23.134-3.138 8.562 21.509 9.325 40.922 2.279 58.24 15.036 16.18 22.559 35.787 22.559 58.817 0 16.178-1.958 30.497-5.853 42.966-3.9 12.471-8.941 22.457-15.125 29.979-6.191 7.521-13.901 13.85-23.131 18.986-9.232 5.14-18.182 8.85-26.84 11.136-8.662 2.286-18.415 4.004-29.263 5.146 9.894 8.562 14.842 22.077 14.842 40.539v60.237c0 3.422 1.19 6.279 3.572 8.562 2.379 2.279 6.136 2.95 11.276 1.995 44.163-14.653 80.185-41.062 108.068-79.226 27.88-38.161 41.825-81.126 41.825-128.906-.01-39.771-9.818-76.454-29.414-110.049z" />
          </svg>
          <span class="github-label">Star on GitHub</span>
        </div>
        <div class="github-stars">
          <svg class="star-icon" viewBox="0 0 24 24" fill="currentColor">
            <path clip-rule="evenodd" fill-rule="evenodd" d="M10.788 3.21c.448-1.077 1.976-1.077 2.424 0l2.082 5.006 5.404.434c1.164.093 1.636 1.545.749 2.305l-4.117 3.527 1.257 5.273c.271 1.136-.964 2.033-1.96 1.425L12 18.354 7.373 21.18c-.996.608-2.231-.29-1.96-1.425l1.257-5.273-4.117-3.527c-.887-.76-.415-2.212.749-2.305l5.404-.434 2.082-5.005Z" />
          </svg>
          <span class="star-count">6</span>
        </div>
      </a>
    </div>
  </div>

</template>

<style scoped>
.knowledge-dir-control {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-4);
  min-width: 0;
}

.knowledge-dir-control input {
  flex: 1;
  min-width: 0;
  height: 28px;
  box-sizing: border-box;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  outline: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.knowledge-dir-picker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.knowledge-dir-picker:hover:not(:disabled) {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.knowledge-dir-picker:disabled {
  cursor: wait;
  opacity: 0.5;
}

.blocked-file-types-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-10);
  margin-bottom: var(--space-10);
}

.blocked-file-types-row > label {
  flex: 0 0 72px;
  padding-top: 5px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.file-type-chip-list {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: var(--space-6);
  min-width: 0;
}

.file-type-chip {
  min-height: 26px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-secondary);
  font-family: var(--font-code);
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
}

.file-type-chip:hover:not(:disabled) {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.file-type-chip.active {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
  cursor: default;
}

.logout-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-12);
  margin-top: var(--space-12);
  padding-top: var(--space-14);
  border-top: 1px solid var(--color-border);
}

.logout-section h3 {
  margin: 0 0 var(--space-4);
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: var(--color-danger);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition-duration: .3s;
  justify-self: end;
}

.logout-btn:hover {
  width: 125px;
  border-radius: 999px;
  background: var(--color-danger);
}

.logout-btn:active {
  transform: translate(1px, 1px);
}

.logout-sign {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition-duration: .3s;
}

.logout-sign svg {
  width: 16px;
  height: 16px;
}

.logout-sign svg path {
  fill: #fff;
}

.logout-text {
  position: absolute;
  right: 0;
  width: 0;
  opacity: 0;
  color: #fff;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
  transition-duration: .3s;
  white-space: nowrap;
}

.logout-btn:hover .logout-sign {
  width: 30%;
  padding-left: 16px;
}

.logout-btn:hover .logout-text {
  opacity: 1;
  width: 70%;
  padding-right: 12px;
}

@media (max-width: 560px) {
  .logout-section {
    grid-template-columns: 1fr;
  }

  .logout-btn {
    justify-self: start;
  }
}

.github-section {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-8);
}

.github-btn {
  display: flex;
  overflow: hidden;
  align-items: center;
  justify-content: center;
  gap: 6px;
  max-width: 200px;
  height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  background: #000;
  color: #fff;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  font-weight: 500;
  text-decoration: none;
  white-space: pre;
  position: relative;
  transition: all 0.3s ease-out;
}

.github-btn:hover {
  box-shadow: 0 0 0 2px #000, 0 0 0 4px var(--color-border);
}

.github-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--color-primary);
}

.github-shine {
  position: absolute;
  right: 0;
  top: -24px;
  width: 32px;
  height: 128px;
  background: rgba(255, 255, 255, 0.1);
  transition: all 1s ease-out;
  transform: translateX(48px) rotate(12deg);
}

.github-btn:hover .github-shine {
  transform: translateX(-160px) rotate(12deg);
}

.github-content {
  display: flex;
  align-items: center;
  gap: 4px;
}

.github-icon {
  width: 14px;
  height: 14px;
  fill: currentColor;
}

.github-label {
  color: #fff;
}

.github-stars {
  display: flex;
  align-items: center;
  gap: 3px;
}

.star-icon {
  width: 14px;
  height: 14px;
  color: #6b7280;
  transition: color 0.3s;
}

.github-btn:hover .star-icon {
  color: #facc15;
}

.star-count {
  display: inline-block;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  font-weight: 500;
  color: #fff;
  letter-spacing: 0.02em;
}

/* ---- 模型阻断模态框 ---- */
:global(.model-modal-overlay) {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
}

:global(.model-modal) {
  width: 380px;
  max-width: 90vw;
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35);
}

:global(.model-modal-message) {
  margin: 0 0 12px;
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  line-height: 1.5;
}

:global(.model-modal-link) {
  margin: 0 0 16px;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

:global(.model-modal-link a) {
  color: var(--color-primary);
  text-decoration: underline;
  cursor: pointer;
}

:global(.model-modal-link a:hover) {
  color: var(--color-primary-active);
}

:global(.model-modal-actions) {
  display: flex;
  gap: var(--space-8);
  justify-content: flex-end;
}

:global(.model-modal-btn) {
  padding: 6px 18px;
  border: 0;
  border-radius: var(--radius-sm);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

:global(.close-btn) {
  background: var(--color-border);
  color: var(--color-text);
}

:global(.close-btn:hover) {
  opacity: 0.8;
}
</style>

<style scoped>
.hint-text,
.setting-hint {
  display: none;
}

.ignore-row textarea {
  min-height: 172px;
  border-radius: 18px;
  background: var(--color-code-bg) !important;
  font-family: var(--font-code);
  line-height: 1.6;
}

.logout-section {
  display: flex;
  justify-content: flex-end;
}

.logout-section > div {
  display: none;
}

.file-type-chip {
  border: 0;
  background: color-mix(in srgb, var(--color-primary) 30%, transparent);
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.file-type-chip:hover:not(:disabled),
.file-type-chip.active {
  border: 0;
  background: color-mix(in srgb, var(--color-primary) 42%, transparent);
  color: var(--color-primary);
}
</style>
