<!-- Optional model groups reuse the existing measured settings-disclosure component. -->
<script setup lang="ts">
import SettingsDisclosure from '@/components/common/SettingsDisclosure.vue'
import AuthField from './AuthField.vue'
import AuthToggle from './AuthToggle.vue'
import type { AuthDraft } from './authTypes'
const draft = defineModel<AuthDraft>('draft', { required: true })
const emit = defineEmits<{ save: [section: string] }>()
const models = [
  { key: 'large', label: '大模型 · 建议 DeepSeek', open: true },
  { key: 'small', label: '小模型', open: false },
  { key: 'vision', label: '视觉模型', open: false },
] as const
</script>
<template>
  <section class="auth-step">
    <h1>API Key 配置</h1>
    <SettingsDisclosure
      v-for="model in models"
      :key="model.key"
      :label="model.label + '（选填）'"
      :default-open="model.open"
    >
      <div class="auth-config-block auth-fields">
        <AuthField v-model="draft[model.key].modelName" label="模型名" placeholder="模型名称" />
        <AuthField v-model="draft[model.key].baseUrl" label="URL" placeholder="API Base URL" />
        <AuthField
          v-model="draft[model.key].apiKey"
          label="API Key"
          type="password"
          placeholder="API Key"
        />
        <div class="auth-block-actions">
          <button class="auth-button" type="button" @click="emit('save', model.label)">
            保存配置
          </button>
        </div>
      </div>
    </SettingsDisclosure>
    <SettingsDisclosure label="MinerU Key（选填）" default-open>
      <div class="auth-config-block auth-fields">
        <AuthToggle v-model="draft.vlmEnabled" label="开启 VLM" />
        <AuthToggle v-model="draft.ocrEnabled" label="OCR" />
        <AuthToggle v-model="draft.visionEnabled" label="识图" />
        <AuthField
          v-model="draft.mineruKey"
          label="API Key"
          type="password"
          placeholder="MinerU API Key"
        />
        <label class="auth-select-field"
          >模型<select v-model="draft.mineruModel">
            <option value="vlm">vlm</option>
            <option value="pipeline">pipeline</option>
          </select></label
        >
        <div class="auth-block-actions">
          <button class="auth-button" type="button" @click="emit('save', 'MinerU')">
            保存配置
          </button>
        </div>
      </div>
    </SettingsDisclosure>
  </section>
</template>
