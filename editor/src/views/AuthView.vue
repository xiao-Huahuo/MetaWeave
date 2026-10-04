<!-- Global login/onboarding UI framework. Drafts are unsaved and never grant access without backend authentication. -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fetchOnboardingDefaults } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'
import LineWaves from '@/components/common/LineWaves.vue'
import AuthFormShell from '@/components/auth_view/AuthFormShell.vue'
import CredentialsStep from '@/components/auth_view/CredentialsStep.vue'
import KnowledgeLibraryStep from '@/components/auth_view/KnowledgeLibraryStep.vue'
import ModelConfigStep from '@/components/auth_view/ModelConfigStep.vue'
import PreferencesStep from '@/components/auth_view/PreferencesStep.vue'
import CompletionStep from '@/components/auth_view/CompletionStep.vue'
import type { AuthDraft } from '@/components/auth_view/authTypes'
const settings = useSettingsStore()
const page = ref(0)
const mode = ref<'login' | 'register'>('login')
const message = ref('')
/** Unsaved page drafts live only for this entry view; credentials never enter browser storage. */
const draft = ref<AuthDraft>({
  username: '',
  password: '',
  confirmation: '',
  libraryName: 'knowledge',
  knowledgeDir: '',
  large: { modelName: '', baseUrl: '', apiKey: '' },
  small: { modelName: '', baseUrl: '', apiKey: '' },
  vision: { modelName: '', baseUrl: '', apiKey: '' },
  mineruKey: '',
  mineruModel: 'vlm',
  vlmEnabled: false,
  ocrEnabled: false,
  visionEnabled: false,
  proxyUrl: '',
  webSearchEnabled: false,
  memoryEnabled: true,
  sensitiveWordsEnabled: true,
  safetyEnabled: true,
  dshEnabled: false,
  primaryColor: settings.profile.themePrimaryColor || '#476bf7',
  softColor: settings.profile.themeSoftColor || '#476bf7',
})
onMounted(async () => {
  try {
    const defaults = await fetchOnboardingDefaults()
    if (!draft.value.knowledgeDir) draft.value.knowledgeDir = defaults.knowledge_dir
  } catch {
    message.value = '无法读取默认知识目录，请使用目录选择按钮。'
  }
})
/** Mirror the existing DSH model rule on drafts, without pretending they are saved configuration. */
const dshAvailable = computed(() =>
  Boolean(
    draft.value.large.apiKey.trim() &&
    draft.value.large.baseUrl.trim() &&
    draft.value.large.modelName
      .trim()
      .toLowerCase()
      .replaceAll(':', '/')
      .split('/')
      .some((part) => part.startsWith('deepseek')),
  ),
)
watch(dshAvailable, (available) => {
  if (!available) draft.value.dshEnabled = false
})
watch(mode, () => {
  message.value = ''
  draft.value.password = ''
  draft.value.confirmation = ''
})
/** Header navigation previews the five pages and preserves unsent input. */
function navigate(offset: number) {
  page.value = Math.min(4, Math.max(0, page.value + offset))
  message.value = ''
}
/** Do not create a fake authenticated identity or report configuration saved. */
function pending(action: string) {
  message.value = action + '尚未接入全局账号服务，当前输入未提交。'
}
function confirm() {
  if (page.value === 0) {
    if (mode.value === 'register' && draft.value.password !== draft.value.confirmation) {
      message.value = '两次密码不一致'
      return
    }
    pending(mode.value === 'login' ? '登录' : '注册')
    return
  }
  pending('配置保存')
}
/** Theme previews use the application's centralized CSS-variable mechanism. */
function previewColors() {
  settings.previewAppearanceColors({
    themePrimaryColor: draft.value.primaryColor,
    themeSoftColor: draft.value.softColor,
  })
}
function resetColors() {
  draft.value.primaryColor = '#476bf7'
  draft.value.softColor = '#476bf7'
  previewColors()
}
onBeforeUnmount(() => {
  draft.value.password = ''
  draft.value.confirmation = ''
  settings.previewAppearanceColors({
    themePrimaryColor: settings.profile.themePrimaryColor,
    themeSoftColor: settings.profile.themeSoftColor,
  })
})
</script>
<template>
  <main class="auth-entry">
    <LineWaves :speed="0.15" class="auth-wave-background" :color1="settings.profile.themePrimaryColor || '#476bf7'" :color2="settings.profile.themeSoftColor || '#476bf7'" :color3="settings.profile.themePrimaryColor || '#476bf7'" :light-mode="!settings.isDark" />
    <AuthFormShell
      :page="page"
      :registering="mode === 'register'"
      :message="message"
      @navigate="navigate"
      @confirm="confirm"
    >
      <template #step-0><CredentialsStep v-model:draft="draft" v-model:mode="mode" /></template>
      <template #step-1><KnowledgeLibraryStep v-model:draft="draft" /></template>
      <template #step-2><ModelConfigStep v-model:draft="draft" @save="pending" /></template>
      <template #step-3
        ><PreferencesStep
          v-model:draft="draft"
          :theme-mode="settings.themeMode"
          :dsh-available="dshAvailable"
          @theme="settings.setThemeMode"
          @colors="previewColors"
          @reset-colors="resetColors"
          @save-colors="pending('主题色保存')"
      /></template>
      <template #step-4
        ><CompletionStep :active="page === 4" @enter="pending('进入主页')"
      /></template>
    </AuthFormShell>
  </main>
</template>
<style src="../components/auth_view/auth-view.css"></style>
