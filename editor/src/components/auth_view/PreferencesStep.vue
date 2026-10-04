<!-- Required preference controls operate on unsaved drafts; theme previews use the global store. -->
<script setup lang="ts">
import AuthField from './AuthField.vue'
import AuthToggle from './AuthToggle.vue'
import type { AuthDraft } from './authTypes'
import type { ThemeMode } from '@/types/settings'
const draft = defineModel<AuthDraft>('draft', { required: true })
defineProps<{ themeMode: ThemeMode; dshAvailable: boolean }>()
const emit = defineEmits<{
  theme: [mode: ThemeMode]
  colors: []
  resetColors: []
  saveColors: []
}>()
const themes = [
  { value: 'light', label: '明亮' },
  { value: 'dark', label: '暗色' },
  { value: 'system', label: '跟随系统' },
] as const
</script>
<template>
  <section class="auth-step">
    <h1>必要设置</h1>
    <div class="auth-preference-group">
      <h2>外观</h2>
      <div class="auth-theme-options">
        <button
          v-for="theme in themes"
          :key="theme.value"
          type="button"
          :aria-pressed="themeMode === theme.value"
          @click="emit('theme', theme.value)"
        >
          {{ theme.label }}
        </button>
      </div>
      <div class="auth-color-field">
        <label for="auth-primary-color">主主题色</label>
        <div>
          <input
            id="auth-primary-color"
            v-model="draft.primaryColor"
            type="color"
            @input="emit('colors')"
          /><input
            v-model="draft.primaryColor"
            aria-label="主主题色数值"
            @change="emit('colors')"
          />
        </div>
      </div>
      <div class="auth-color-field">
        <label for="auth-soft-color">柔和主题色</label>
        <div>
          <input
            id="auth-soft-color"
            v-model="draft.softColor"
            type="color"
            @input="emit('colors')"
          /><input v-model="draft.softColor" aria-label="柔和主题色数值" @change="emit('colors')" />
        </div>
      </div>
      <div class="auth-block-actions">
        <button class="auth-text-button" type="button" @click="emit('resetColors')">
          重置默认色</button
        ><button class="auth-button" type="button" @click="emit('saveColors')">保存主题色</button>
      </div>
    </div>
    <div class="auth-preference-group">
      <h2>代理</h2>
      <AuthToggle v-model="draft.webSearchEnabled" label="启用搜索" />
      <Transition name="auth-mode"
        ><AuthField
          v-if="draft.webSearchEnabled"
          v-model="draft.proxyUrl"
          label="代理地址"
          placeholder="http://127.0.0.1:7890"
      /></Transition>
    </div>
    <div class="auth-preference-group">
      <h2>记忆</h2>
      <AuthToggle v-model="draft.memoryEnabled" label="启用长期记忆" />
    </div>
    <div class="auth-preference-group">
      <h2>安全</h2>
      <AuthToggle v-model="draft.sensitiveWordsEnabled" label="敏感词库" /><AuthToggle
        v-model="draft.safetyEnabled"
        label="安全审核系统"
      />
    </div>
    <div class="auth-preference-group">
      <AuthToggle
        v-model="draft.dshEnabled"
        label="启用 DSH coding agent"
        :disabled="!dshAvailable"
      />
      <p v-if="!dshAvailable" class="auth-field-hint">需要配置 DeepSeek 大模型、URL 和 API Key</p>
    </div>
  </section>
</template>
