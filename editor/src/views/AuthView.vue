<!-- Global account entry and resumable five-page onboarding; every Confirm persists real backend state. -->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { saveAppearanceConfig } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import LineWaves from '@/components/common/LineWaves.vue'
import AuthFormShell from '@/components/auth_view/AuthFormShell.vue'
import CredentialsStep from '@/components/auth_view/CredentialsStep.vue'
import KnowledgeLibraryStep from '@/components/auth_view/KnowledgeLibraryStep.vue'
import ModelConfigStep from '@/components/auth_view/ModelConfigStep.vue'
import PreferencesStep from '@/components/auth_view/PreferencesStep.vue'
import CompletionStep from '@/components/auth_view/CompletionStep.vue'
import type { AuthDraft } from '@/components/auth_view/authTypes'
import { loadOnboardingDraft, saveOnboardingModel, saveOnboardingPage, type ModelSection } from '@/components/auth_view/onboarding'
const props = defineProps<{ backendReady?: boolean }>()
const settings = useSettingsStore()
const auth = useAuthStore()
const page = ref(0)
const mode = ref<'login' | 'register'>('login')
const message = ref('')
const saving = ref(false)
const busy = computed(() => auth.busy || saving.value)
/** Unchanged authenticated credentials may revisit initialization without issuing another device credential. */
const credentialsChanged = computed(() => !auth.session || draft.value.username !== auth.session.username || Boolean(draft.value.password || draft.value.confirmation))
let disposed = false
let restoreStarted = false
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
/** Render the login page first, then make one restore attempt after the backend is reachable. */
watch(() => props.backendReady, async (ready) => {
  if (!ready || restoreStarted) return
  restoreStarted = true
  if (!disposed) await auth.restore()
}, { immediate: true })
watch(() => auth.rememberedUsername, (username) => { if (username) draft.value.username = username })
watch(() => auth.notice, (notice) => { if (notice) message.value = notice }, { immediate: true })
/** Incomplete accounts resume saved progress; completed accounts immediately leave this entry surface. */
watch(() => auth.session?.token, async (token) => {
  const session = auth.session
  if (!token || !session || session.onboarding_completed) return
  saving.value = true
  try {
    await loadOnboardingDraft(session.user_id, draft.value)
    if (!disposed && auth.session?.token === token) page.value = Math.min(4, Math.max(1, session.onboarding_step - 1))
  } catch (error) {
    message.value = error instanceof Error ? error.message : '读取配置失败，请重试。'
    if (!disposed && auth.session?.token === token) page.value = Math.min(4, Math.max(1, session.onboarding_step - 1))
  } finally { if (!disposed) saving.value = false }
}, { immediate: true })
/** Mirror the existing DSH model rule on drafts, without pretending they are saved configuration. */
const dshAvailable = computed(() =>
  Boolean(
    draft.value.large.apiKey.trim() &&
    draft.value.large.baseUrl.trim() &&
    draft.value.large.modelName
      .trim()
      .toLowerCase()
      .replace(/:/gu, '/')
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
/** Forward arrows save the current stage; back arrows can only revisit this authenticated initialization. */
async function navigate(offset: number) {
  if (busy.value || !auth.authenticated) return
  if (offset > 0) {
    if (page.value === 0) {
      if (!credentialsChanged.value) page.value = 1
      return
    }
    await confirm()
    return
  }
  page.value = Math.max(0, page.value - 1)
  if (page.value === 0 && auth.session) {
    mode.value = 'login'
    draft.value.username = auth.session.username
    draft.value.password = ''
    draft.value.confirmation = ''
  }
  message.value = ''
}
/** Submit passwords explicitly, or persist every control on the current configuration page. */
async function confirm() {
  if (busy.value) return
  message.value = ''
  if (page.value === 0) {
    if (mode.value === 'register' && draft.value.password !== draft.value.confirmation) {
      message.value = '两次密码不一致'
      return
    }
    try {
      await auth.authenticate({ username: draft.value.username.trim(), password: draft.value.password }, mode.value === 'register')
    } catch (error) {
      message.value = error instanceof Error ? error.message : '账号验证失败'
    } finally { draft.value.password = ''; draft.value.confirmation = '' }
    return
  }
  const session = auth.session
  if (!session) return
  saving.value = true
  try {
    await saveOnboardingPage(session.user_id, draft.value, page.value, settings.themeMode)
    if (disposed || auth.session?.token !== session.token) return
    const nextStep = page.value + 2
    if (nextStep > session.onboarding_step) await auth.advance(nextStep)
    if (!disposed && auth.session?.token === session.token) page.value = Math.min(4, page.value + 1)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '配置保存失败，请重试。'
  } finally { if (!disposed) saving.value = false }
}
/** Model blocks save independently without silently advancing initialization. */
async function saveModel(section: ModelSection) {
  if (busy.value || !auth.session) return
  saving.value = true
  message.value = ''
  try { await saveOnboardingModel(auth.session.user_id, draft.value, section); message.value = '配置已保存' }
  catch (error) { message.value = error instanceof Error ? error.message : '配置保存失败' }
  finally { if (!disposed) saving.value = false }
}
/** Theme Save uses the same persisted appearance API as normal account settings. */
async function saveColors() {
  if (busy.value || !auth.session) return
  const session = auth.session
  saving.value = true
  try {
    const result = await saveAppearanceConfig(session.user_id, { themeMode: settings.themeMode, themePrimaryColor: draft.value.primaryColor, themeSoftColor: draft.value.softColor })
    if (disposed || auth.session?.token !== session.token) return
    settings.updateProfile({ themePrimaryColor: result.theme_primary_color, themeSoftColor: result.theme_soft_color })
    message.value = '主题色已保存'
  } catch (error) { message.value = error instanceof Error ? error.message : '主题色保存失败' }
  finally { if (!disposed) saving.value = false }
}
/** Only the completion button can set stage 6 and grant workspace access. */
async function enter() {
  if (busy.value) return
  saving.value = true
  try { await auth.advance(6) }
  catch (error) { message.value = error instanceof Error ? error.message : '完成初始化失败' }
  finally { if (!disposed) saving.value = false }
}
/** Theme previews use the application's centralized CSS-variable mechanism. */
function previewColors() {
  settings.previewAppearanceColors({
    themePrimaryColor: draft.value.primaryColor,
    themeSoftColor: draft.value.softColor,
  })
}
/** Match the settings theme group's reset behavior: clear persisted overrides, then display the default colors. */
async function resetColors() {
  if (busy.value || !auth.session) return
  const session = auth.session
  saving.value = true
  try {
    const result = await saveAppearanceConfig(session.user_id, { themePrimaryColor: '', themeSoftColor: '' })
    if (disposed || auth.session?.token !== session.token) return
    settings.updateProfile({ themePrimaryColor: result.theme_primary_color, themeSoftColor: result.theme_soft_color })
    draft.value.primaryColor = result.theme_primary_color || '#476bf7'
    draft.value.softColor = result.theme_soft_color || '#476bf7'
    previewColors()
    message.value = '主题色已重置'
  } catch (error) { message.value = error instanceof Error ? error.message : '重置主题色失败' }
  finally { if (!disposed) saving.value = false }
}
onBeforeUnmount(() => {
  disposed = true
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
      :busy="busy"
      :onboarding="auth.authenticated && !auth.canEnter"
      :credentials-changed="credentialsChanged"
      @navigate="navigate"
      @confirm="confirm"
    >
      <template #step-0><CredentialsStep v-model:draft="draft" v-model:mode="mode" /></template>
      <template #step-1><KnowledgeLibraryStep v-model:draft="draft" /></template>
      <template #step-2><ModelConfigStep v-model:draft="draft" @save="saveModel" /></template>
      <template #step-3
        ><PreferencesStep
          v-model:draft="draft"
          :theme-mode="settings.themeMode"
          :dsh-available="dshAvailable"
          @theme="settings.setThemeMode"
          @colors="previewColors"
          @reset-colors="resetColors"
          @save-colors="saveColors"
      /></template>
      <template #step-4
        ><CompletionStep :active="page === 4" :busy="busy" @enter="enter"
      /></template>
    </AuthFormShell>
  </main>
</template>
<style src="../components/auth_view/auth-view.css"></style>
