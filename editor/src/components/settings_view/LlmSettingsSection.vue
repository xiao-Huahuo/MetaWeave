<!--
  LLM settings section.

  Usage:
  Presents large and small model credentials. SettingsView owns loading,
  saving, and cancel behavior so model state remains centralized.
-->
<script setup lang="ts">
import { computed } from 'vue'

import { DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS, type SavedLLMConfig } from '@/api/settings'
import SavedModelConfigRow from '@/components/settings_view/SavedModelConfigRow.vue'

const largeModelName = defineModel<string>('largeModelName', { required: true })
const largeBaseUrl = defineModel<string>('largeBaseUrl', { required: true })
const largeApiKey = defineModel<string>('largeApiKey', { required: true })
const largeContextWindowTokens = defineModel<number>('largeContextWindowTokens', { required: true })
const largeMaxOutputTokens = defineModel<number>('largeMaxOutputTokens', { required: true })
const smallModelName = defineModel<string>('smallModelName', { required: true })
const smallBaseUrl = defineModel<string>('smallBaseUrl', { required: true })
const smallApiKey = defineModel<string>('smallApiKey', { required: true })
const smallContextWindowTokens = defineModel<number>('smallContextWindowTokens', { required: true })
const smallMaxOutputTokens = defineModel<number>('smallMaxOutputTokens', { required: true })
const showLargeKey = defineModel<boolean>('showLargeKey', { required: true })
const showSmallKey = defineModel<boolean>('showSmallKey', { required: true })
const modelEditing = defineModel<boolean>('modelEditing', { required: true })

const props = defineProps<{
  modelConfigSaved: boolean
  modelConfigLoaded: boolean
  modelSaving: boolean
  modelMsg: string
  savedConfigs: SavedLLMConfig[]
  effectiveLargeModelName: string
  effectiveLargeModelSource: 'remote' | 'local' | ''
  effectiveSmallModelName: string
  effectiveSmallModelSource: 'remote' | 'local' | ''
  savedSmallModelConfigured: boolean
}>()

defineEmits<{
  save: []
  cancel: []
  savePreset: [target: 'large' | 'small']
  importSavedConfig: [config: SavedLLMConfig, target: 'large' | 'small']
  deleteSavedConfig: [configId: string]
}>()

/** Describe the backend-resolved route without presenting editable drafts as active state. */
const effectiveLargeSourceLabel = computed(() => (
  props.effectiveLargeModelSource === 'local'
    ? '本地回退'
    : props.effectiveLargeModelSource === 'remote' ? '远程配置' : '状态未知'
))

/** Distinguish an explicit small model from reuse of the configured large model. */
const effectiveSmallSourceLabel = computed(() => {
  if (props.effectiveSmallModelSource === 'local') return '本地回退'
  if (props.effectiveSmallModelSource === 'remote') {
    return props.savedSmallModelConfigured ? '独立配置' : '复用大模型'
  }
  return '状态未知'
})

/** Clear one saved-model draft and enter edit mode; persistence still requires Save. */
function clearModelDraft(target: 'large' | 'small') {
  if (target === 'large') {
    largeModelName.value = ''
    largeBaseUrl.value = ''
    largeApiKey.value = ''
    largeContextWindowTokens.value = DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
    largeMaxOutputTokens.value = 0
  } else {
    smallModelName.value = ''
    smallBaseUrl.value = ''
    smallApiKey.value = ''
    smallContextWindowTokens.value = DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
    smallMaxOutputTokens.value = 0
  }
  modelEditing.value = true
}
</script>

<template>
  <div class="setting-section settings-model-form">
    <section class="effective-model-summary" aria-labelledby="effective-model-title">
      <h3 id="effective-model-title">当前生效</h3>
      <dl>
        <div data-effective-model="large">
          <dt>大模型</dt>
          <dd>{{ modelConfigLoaded ? (effectiveLargeModelName || '未配置') : '正在读取...' }}</dd>
          <span v-if="modelConfigLoaded">{{ effectiveLargeSourceLabel }}</span>
        </div>
        <div data-effective-model="small">
          <dt>小模型</dt>
          <dd>{{ modelConfigLoaded ? (effectiveSmallModelName || '未配置') : '正在读取...' }}</dd>
          <span v-if="modelConfigLoaded">{{ effectiveSmallSourceLabel }}</span>
        </div>
      </dl>
    </section>
    <div class="model-heading">
      <h3>大模型</h3>
      <button class="delete-btn" type="button" title="清空大模型配置" aria-label="清空大模型配置" @click="clearModelDraft('large')">
        <svg viewBox="0 0 448 512" class="svgIcon" aria-hidden="true"><path d="M135.2 17.7L128 32H32C14.3 32 0 46.3 0 64S14.3 96 32 96H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H320l-7.2-14.3C307.4 6.8 296.3 0 284.2 0H163.8c-12.1 0-23.2 6.8-28.6 17.7zM416 128H32L53.2 467c1.6 25.3 22.6 45 47.9 45H346.9c25.3 0 46.3-19.7 47.9-45L416 128z"></path></svg>
      </button>
    </div>
    <div class="model-block">
      <input v-model="largeModelName" placeholder="模型名称" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      <input v-model="largeBaseUrl" placeholder="Base URL" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      <div class="capacity-row">
        <input v-model.number="largeContextWindowTokens" type="number" min="0" placeholder="上下文窗口 token（默认 1000000）" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
        <input v-model.number="largeMaxOutputTokens" type="number" min="0" placeholder="最大输出 token（0=继承）" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      </div>
      <div class="key-row">
        <input v-model="largeApiKey" :type="showLargeKey ? 'text' : 'password'" placeholder="API Key" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
        <button class="toggle-key" @click="showLargeKey = !showLargeKey">{{ showLargeKey ? '隐藏' : '显示' }}</button>
      </div>
    </div>
    <div class="model-heading">
      <h3>小模型</h3>
      <button class="delete-btn" type="button" title="清空小模型配置" aria-label="清空小模型配置" @click="clearModelDraft('small')">
        <svg viewBox="0 0 448 512" class="svgIcon" aria-hidden="true"><path d="M135.2 17.7L128 32H32C14.3 32 0 46.3 0 64S14.3 96 32 96H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H320l-7.2-14.3C307.4 6.8 296.3 0 284.2 0H163.8c-12.1 0-23.2 6.8-28.6 17.7zM416 128H32L53.2 467c1.6 25.3 22.6 45 47.9 45H346.9c25.3 0 46.3-19.7 47.9-45L416 128z"></path></svg>
      </button>
    </div>
    <div class="model-block">
      <input v-model="smallModelName" placeholder="模型名称（留空继承大模型）" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      <input v-model="smallBaseUrl" placeholder="Base URL（留空继承大模型）" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      <div class="capacity-row">
        <input v-model.number="smallContextWindowTokens" type="number" min="0" placeholder="上下文窗口 token（默认 1000000）" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
        <input v-model.number="smallMaxOutputTokens" type="number" min="0" placeholder="最大输出 token（0=继承）" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
      </div>
      <div class="key-row">
        <input v-model="smallApiKey" :type="showSmallKey ? 'text' : 'password'" placeholder="API Key" spellcheck="false" :readonly="!modelEditing" :class="{ readonly: !modelEditing }" />
        <button class="toggle-key" @click="showSmallKey = !showSmallKey">{{ showSmallKey ? '隐藏' : '显示' }}</button>
      </div>
    </div>
    <div class="model-actions">
      <button v-if="!modelEditing" class="edit-model-btn" type="button" @click="modelEditing = true">{{ modelConfigSaved ? '编辑' : '配置' }}</button>
      <button v-if="modelEditing" class="save-model-btn" :disabled="modelSaving" @click="$emit('save')">
        {{ modelSaving ? '保存中...' : '保存' }}
      </button>
      <button v-if="modelEditing" class="edit-model-btn" type="button" @click="$emit('savePreset', 'large')">保存大模型配置</button>
      <button v-if="modelEditing" class="edit-model-btn" type="button" @click="$emit('savePreset', 'small')">保存小模型配置</button>
      <button v-if="modelEditing" class="cancel-model-btn" type="button" @click="$emit('cancel')">取消</button>
      <span v-if="modelMsg" class="feedback">{{ modelMsg }}</span>
    </div>
    <section class="saved-model-section">
      <h3>已保存的配置</h3>
      <p v-if="!savedConfigs.length" class="empty-hint">暂无已保存的模型配置。</p>
      <div v-else class="saved-model-grid">
        <SavedModelConfigRow
          v-for="config in savedConfigs"
          :key="config.config_id"
          :title="config.label || config.model_name || '未命名配置'"
          :model="config.model_name"
          :endpoint="config.base_url"
          icon="psychology"
        >
          <template #actions>
            <button type="button" @click="$emit('importSavedConfig', config, 'large')">导入大模型</button>
            <button type="button" @click="$emit('importSavedConfig', config, 'small')">导入小模型</button>
            <button class="danger" type="button" @click="$emit('deleteSavedConfig', config.config_id)">删除</button>
          </template>
        </SavedModelConfigRow>
      </div>
    </section>
  </div>
</template>

<style scoped>
.effective-model-summary {
  margin-bottom: var(--space-16);
}

.effective-model-summary dl {
  margin: 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.effective-model-summary dl > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-10);
  min-height: 38px;
}

.effective-model-summary dl > div + div {
  border-top: 1px solid var(--color-border);
}

.effective-model-summary dt,
.effective-model-summary dd,
.effective-model-summary span {
  margin: 0;
  font-size: calc(12px * var(--font-scale));
}

.effective-model-summary dt,
.effective-model-summary span {
  color: var(--color-text-muted);
}

.effective-model-summary dd {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text);
  font-family: var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.effective-model-summary span {
  white-space: nowrap;
}

.model-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 28px;
  margin-bottom: var(--space-10);
}

.capacity-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-6);
  margin-bottom: var(--space-6);
}

.capacity-row input {
  min-width: 0;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-mono);
}

@media (max-width: 480px) {
  .capacity-row {
    grid-template-columns: 1fr;
  }
}

.model-heading h3 {
  margin: 0;
}
</style>
