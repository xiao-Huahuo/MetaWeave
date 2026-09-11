<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import { DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS, fetchSystemPrompts, addSystemPromptEntry, deleteSystemPromptEntry, fetchMemories, addMemory, deleteMemory, fetchMemoryConfig, saveMemoryConfig, fetchLLMConfig, saveLLMConfig, fetchSavedLLMConfigs, saveLLMConfigPreset, deleteLLMConfigPreset, fetchWebSearchConfig, saveWebSearchConfig, fetchTerminalSandboxConfig, saveTerminalSandboxConfig } from '@/api/settings'
import type { LLMConfigResponse, SystemPromptEntry, MemoryEntry, SavedLLMConfig, TerminalSandboxConfig, TerminalSandboxConfigResponse, TerminalSegmentInfo, TerminalShellKey } from '@/api/settings'
import AppearanceSettingsSection from '@/components/settings_view/AppearanceSettingsSection.vue'
import BasicSettingsSection from '@/components/settings_view/BasicSettingsSection.vue'
import BrowserSettingsSection from '@/components/settings_view/BrowserSettingsSection.vue'
import LlmSettingsSection from '@/components/settings_view/LlmSettingsSection.vue'
import VlmSettingsSection from '@/components/settings_view/VlmSettingsSection.vue'
import MemorySettingsSection from '@/components/settings_view/MemorySettingsSection.vue'
import McpSettingsSection from '@/components/settings_view/McpSettingsSection.vue'
import SettingsSidebar from '@/components/settings_view/SettingsSidebar.vue'
import type { SettingsTabKey } from '@/components/settings_view/SettingsSidebar.vue'
import TerminalSandboxSettingsSection from '@/components/settings_view/TerminalSandboxSettingsSection.vue'

import WebSearchSettingsSection from '@/components/settings_view/WebSearchSettingsSection.vue'
import GraphSettingsSection from '@/components/settings_view/GraphSettingsSection.vue'
import SafetySettingsSection from '@/components/settings_view/SafetySettingsSection.vue'
import StorageSettingsSection from '@/components/settings_view/StorageSettingsSection.vue'
import FloatingSettingsSection from '@/components/settings_view/FloatingSettingsSection.vue'
import SkillView from '@/views/SkillView.vue'
import { DEFAULT_TAG_COLORS, useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { ThemeMode } from '@/types/settings'

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()

const SETTINGS_ACTIVE_TAB_KEY = 'agent_editor_settings_active_tab'
const persistedSettingsTab = localStorage.getItem(SETTINGS_ACTIVE_TAB_KEY)
const activeTab = ref<SettingsTabKey>(
  persistedSettingsTab === 'browser'
    ? 'web'
    : (persistedSettingsTab as SettingsTabKey | null) ?? 'basic',
)

const tabs = [
  { key: 'basic' as const, label: '基础设置' },
  { key: 'appearance' as const, label: '外观' },
  { key: 'llm' as const, label: 'LLM 配置' },
  { key: 'vlm' as const, label: 'OCR/VLM 设置' },
  { key: 'terminal' as const, label: '终端沙盒' },
  { key: 'web' as const, label: '联网配置' },
  { key: 'memory' as const, label: '记忆与指令' },
  { key: 'graph' as const, label: '图谱' },
  { key: 'safety' as const, label: '密码与安全' },
  { key: 'storage' as const, label: '存储管理' },
  { key: 'floating' as const, label: '悬浮窗' },
  { key: 'skills' as const, label: 'Skills' },
  { key: 'mcp' as const, label: 'MCP' },
]

watch(activeTab, (tab) => {
  localStorage.setItem(SETTINGS_ACTIVE_TAB_KEY, tab)
})

function handleExternalSettingsTab(event: Event) {
  const requestedTab = (event as CustomEvent<string>).detail
  const tab = requestedTab === 'browser' ? 'web' : requestedTab
  if (tabs.some((item) => item.key === tab)) {
    activeTab.value = tab as SettingsTabKey
  }
}
/* ---- Basic settings ---- */

const libraryNameDraft = ref(settingsStore.activeKnowledgeLibrary?.name ?? '')
const knowledgeDirDraft = ref(settingsStore.profile.knowledgeDir)
const watchEnabledDraft = ref(settingsStore.profile.knowledgeWatchEnabled)
const autoIngestOnUploadDraft = ref(Boolean(settingsStore.profile.autoIngestOnUpload))
const visionUnderstandingEnabledDraft = ref(Boolean(settingsStore.profile.visionUnderstandingEnabled))
const dshCodingAgentEnabledDraft = ref(Boolean(settingsStore.profile.dshCodingAgentEnabled))
const knowledgeIgnorePatternsDraft = ref(settingsStore.profile.knowledgeIgnorePatterns ?? '')
const editorImageAssetsDirDraft = ref(settingsStore.profile.editorImageAssetsDir ?? './assets/')
const uiFontFamiliesDraft = ref<string[]>([...(settingsStore.profile.uiFontFamilies ?? [])])
const textFontFamiliesDraft = ref<string[]>([...(settingsStore.profile.textFontFamilies ?? [])])
const uiFontSizePercentDraft = ref(settingsStore.profile.uiFontSizePercent ?? 100)
const textFontSizePercentDraft = ref(settingsStore.profile.textFontSizePercent ?? 100)
const themePrimaryColorDraft = ref(settingsStore.profile.themePrimaryColor || '#476bf7')
const themeSoftColorDraft = ref(settingsStore.profile.themeSoftColor || '#476bf7')
const tagColorsDraft = ref<string[]>([...(settingsStore.profile.tagColors ?? DEFAULT_TAG_COLORS)])
const tagColorsTranslucentDraft = ref(settingsStore.profile.tagColorsTranslucent !== false)
const graphNodeLimitDraft = ref(settingsStore.profile.graphNodeLimit ?? 2000)
const availableFontFamilies = ref<string[]>([])
const fontsLoading = ref(false)
const saving = ref(false)
const switchingKnowledgeRoot = ref(false)
const saveError = ref('')
const saveMessage = ref('')
const fontSizeSaveTimers: Record<'ui' | 'text', number | null> = { ui: null, text: null }

const hasChanges = computed(() => {
  return (
    knowledgeDirDraft.value !== settingsStore.profile.knowledgeDir ||
    libraryNameDraft.value !== (settingsStore.activeKnowledgeLibrary?.name ?? '') ||
    watchEnabledDraft.value !== settingsStore.profile.knowledgeWatchEnabled ||
    autoIngestOnUploadDraft.value !== Boolean(settingsStore.profile.autoIngestOnUpload) ||
    visionUnderstandingEnabledDraft.value !== Boolean(settingsStore.profile.visionUnderstandingEnabled) ||
    dshCodingAgentEnabledDraft.value !== Boolean(settingsStore.profile.dshCodingAgentEnabled) ||
    knowledgeIgnorePatternsDraft.value !== (settingsStore.profile.knowledgeIgnorePatterns ?? '') ||
    editorImageAssetsDirDraft.value !== (settingsStore.profile.editorImageAssetsDir ?? './assets/')
  )
})

watch(
  () => settingsStore.activeKnowledgeLibrary?.name ?? '',
  (value) => { libraryNameDraft.value = value },
)

watch(
  () => settingsStore.profile.knowledgeDir,
  (value) => { knowledgeDirDraft.value = value },
)

watch(
  () => settingsStore.profile.autoIngestOnUpload,
  (value) => { autoIngestOnUploadDraft.value = Boolean(value) },
)


watch(
  () => settingsStore.profile.visionUnderstandingEnabled,
  (value) => { visionUnderstandingEnabledDraft.value = Boolean(value) },
)

watch(
  () => settingsStore.profile.dshCodingAgentEnabled,
  (value) => { dshCodingAgentEnabledDraft.value = Boolean(value) },
)

watch(
  () => settingsStore.profile.knowledgeIgnorePatterns,
  (value) => { knowledgeIgnorePatternsDraft.value = value ?? '' },
)

watch(
  () => settingsStore.profile.editorImageAssetsDir,
  (value) => { editorImageAssetsDirDraft.value = value ?? './assets/' },
)

watch(
  () => settingsStore.profile.uiFontFamilies,
  (value) => { uiFontFamiliesDraft.value = [...(value ?? [])] },
)

watch(
  () => settingsStore.profile.textFontFamilies,
  (value) => { textFontFamiliesDraft.value = [...(value ?? [])] },
)

watch(
  () => settingsStore.profile.uiFontSizePercent,
  (value) => { uiFontSizePercentDraft.value = value ?? 100 },
)

watch(
  () => settingsStore.profile.textFontSizePercent,
  (value) => { textFontSizePercentDraft.value = value ?? 100 },
)

watch(
  () => settingsStore.profile.themePrimaryColor,
  (value) => { themePrimaryColorDraft.value = value || '#476bf7' },
)

watch(
  () => settingsStore.profile.themeSoftColor,
  (value) => { themeSoftColorDraft.value = value || '#476bf7' },
)

watch(
  () => settingsStore.profile.tagColors,
  (value) => { tagColorsDraft.value = [...(value ?? DEFAULT_TAG_COLORS)] },
)

watch(
  () => settingsStore.profile.tagColorsTranslucent,
  (value) => { tagColorsTranslucentDraft.value = value !== false },
)

async function loadAvailableFonts() {
  fontsLoading.value = true
  const fallbackFonts = [
    'Google Sans',
    'Noto Sans SC',
    'Microsoft YaHei UI',
    'Microsoft YaHei',
    'PingFang SC',
    'JetBrains Mono',
    'Hack',
    'Cascadia Code',
    'Arial',
    'Segoe UI',
    'system-ui',
  ]
  try {
    const desktopFonts = await window.agentEditorDesktop?.listFontFamilies?.()
    const fonts = desktopFonts?.length ? desktopFonts : fallbackFonts
    availableFontFamilies.value = [...new Set(fonts.map((item) => item.trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b))
  } catch {
    availableFontFamilies.value = fallbackFonts
  } finally {
    fontsLoading.value = false
  }
}

async function handleSaveFontFamilies(payload: { target: 'ui' | 'text'; families: string[] }) {
  const nextUiFontFamilies = payload.target === 'ui' ? payload.families : uiFontFamiliesDraft.value
  const nextTextFontFamilies = payload.target === 'text' ? payload.families : textFontFamiliesDraft.value
  uiFontFamiliesDraft.value = [...nextUiFontFamilies]
  textFontFamiliesDraft.value = [...nextTextFontFamilies]
  try {
    await settingsStore.saveFontSettings({
      uiFontFamilies: nextUiFontFamilies,
      textFontFamilies: nextTextFontFamilies,
      uiFontSizePercent: uiFontSizePercentDraft.value,
      textFontSizePercent: textFontSizePercentDraft.value,
    })
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存字体设置失败'
  }
}

async function persistFontSize(target: 'ui' | 'text', percent: number) {
  try {
    await settingsStore.saveFontSettings({
      [target === 'ui' ? 'uiFontSizePercent' : 'textFontSizePercent']: percent,
    })
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存字体大小失败'
  }
}

function handleSaveFontSize(payload: { target: 'ui' | 'text'; percent: number }) {
  const { target, percent } = payload
  if (target === 'ui') {
    uiFontSizePercentDraft.value = percent
    settingsStore.setUiFontSizePercent(percent)
  } else {
    textFontSizePercentDraft.value = percent
    settingsStore.setTextFontSizePercent(percent)
  }
  if (fontSizeSaveTimers[target]) {
    window.clearTimeout(fontSizeSaveTimers[target])
  }
  fontSizeSaveTimers[target] = window.setTimeout(() => {
    fontSizeSaveTimers[target] = null
    void persistFontSize(target, percent)
  }, 350)
}

async function handleSaveThemeColors() {
  try {
    await settingsStore.saveAppearanceSettings({
      themePrimaryColor: themePrimaryColorDraft.value,
      themeSoftColor: themeSoftColorDraft.value,
    })
    saveError.value = ''
    saveMessage.value = '外观设置已保存'
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存外观设置失败'
  }
}

async function handleSetShowBacklinks(value: boolean) {
  try {
    await settingsStore.setShowBacklinks(value)
    saveError.value = ''
    saveMessage.value = '反向链接设置已保存'
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存反向链接设置失败'
  }
}

/** Persist an uploaded library asset as the application background. */
async function handleSetBackgroundCover(url: string) {
  try {
    await settingsStore.saveAppearanceSettings({ backgroundCoverUrl: url })
    saveError.value = ''
    saveMessage.value = '背景封面已应用'
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存背景封面失败'
  }
}

/** Clear the persistent background and restore the default application shell. */
async function handleResetBackgroundCover() {
  await handleSetBackgroundCover('')
}

function handlePreviewThemeColors() {
  settingsStore.previewAppearanceColors({
    themePrimaryColor: themePrimaryColorDraft.value,
    themeSoftColor: themeSoftColorDraft.value,
  })
}

async function handleResetThemeColors() {
  themePrimaryColorDraft.value = ''
  themeSoftColorDraft.value = ''
  handlePreviewThemeColors()
  await handleSaveThemeColors()
  themePrimaryColorDraft.value = '#476bf7'
  themeSoftColorDraft.value = '#476bf7'
}

function handlePreviewTagColors() {
  settingsStore.previewAppearanceColors({
    tagColors: tagColorsDraft.value,
    tagColorsTranslucent: tagColorsTranslucentDraft.value,
  })
}

async function handleSaveTagColors() {
  try {
    await settingsStore.saveAppearanceSettings({
      tagColors: tagColorsDraft.value,
      tagColorsTranslucent: tagColorsTranslucentDraft.value,
    })
    saveError.value = ''
    saveMessage.value = '标签色已保存'
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存标签色失败'
  }
}

async function handleResetTagColors() {
  tagColorsDraft.value = [...DEFAULT_TAG_COLORS]
  tagColorsTranslucentDraft.value = true
  handlePreviewTagColors()
  try {
    await settingsStore.saveAppearanceSettings({ tagColors: [], tagColorsTranslucent: null })
    saveError.value = ''
    saveMessage.value = '标签色已重置'
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '重置标签色失败'
  }
}

async function saveProfile() {
  if (saving.value || !hasChanges.value) return
  saving.value = true
  saveError.value = ''
  saveMessage.value = ''
  const nextKnowledgeDir = knowledgeDirDraft.value.trim() || settingsStore.profile.knowledgeDir
  const nextLibraryName = libraryNameDraft.value.trim()
  const ignorePatternsChanged = knowledgeIgnorePatternsDraft.value !== (settingsStore.profile.knowledgeIgnorePatterns ?? '')
  const visionUnderstandingChanged = visionUnderstandingEnabledDraft.value !== Boolean(settingsStore.profile.visionUnderstandingEnabled)
  const dshCodingAgentEnabledChanged = dshCodingAgentEnabledDraft.value !== Boolean(settingsStore.profile.dshCodingAgentEnabled)
  const editorImageAssetsDirChanged = editorImageAssetsDirDraft.value !== (settingsStore.profile.editorImageAssetsDir ?? './assets/')
  try {
    settingsStore.updateProfile({ knowledgeWatchEnabled: watchEnabledDraft.value })
    if (nextKnowledgeDir !== settingsStore.profile.knowledgeDir) {
      await settingsStore.switchKnowledgeRoot(nextKnowledgeDir)
    }
    if (nextLibraryName && nextLibraryName !== (settingsStore.activeKnowledgeLibrary?.name ?? '')) {
      await settingsStore.renameActiveKnowledgeLibrary(nextLibraryName)
    }
    if (
      autoIngestOnUploadDraft.value !== Boolean(settingsStore.profile.autoIngestOnUpload) ||
      visionUnderstandingChanged ||
      dshCodingAgentEnabledChanged ||
      ignorePatternsChanged
    ) {
      const result = await settingsStore.saveKnowledgeIngestionSettings({
        autoIngestOnUpload: autoIngestOnUploadDraft.value,
        visionUnderstandingEnabled: visionUnderstandingEnabledDraft.value,
        dshCodingAgentEnabled: dshCodingAgentEnabledDraft.value,
        knowledgeIgnorePatterns: knowledgeIgnorePatternsDraft.value,
      })
    }
    if (ignorePatternsChanged) {
      await workspaceStore.loadKnowledgeTree()
    }
    if (editorImageAssetsDirChanged) {
      await settingsStore.saveEditorPasteSettings({ editorImageAssetsDir: editorImageAssetsDirDraft.value })
    }
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

/** Selects and activates a knowledge root from the basic-settings directory row. */
async function selectKnowledgeDirectory(): Promise<void> {
  const selectedDir = await window.agentEditorDesktop?.selectDirectory?.()
  if (!selectedDir) return
  switchingKnowledgeRoot.value = true
  saveError.value = ''
  try {
    await settingsStore.switchKnowledgeRoot(selectedDir)
    knowledgeDirDraft.value = settingsStore.profile.knowledgeDir
    await workspaceStore.loadKnowledgeTree()
    workspaceStore.restartFileWatcher()
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : '切换知识库失败'
  } finally {
    switchingKnowledgeRoot.value = false
  }
}

function handleLogout() {
  workspaceStore.setMainView('editor')
  settingsStore.clearUserId()
}

const themeOptions: Array<{ value: ThemeMode; label: string }> = [
  { value: 'dark', label: '深色' },
  { value: 'light', label: '浅色' },
  { value: 'system', label: '跟随系统' },
]

/* ---- System prompts ---- */

const promptEntries = ref<SystemPromptEntry[]>([])
const newPromptContent = ref('')
const addingPrompt = ref(false)
const promptMsg = ref('')

/* ---- Long-term memories ---- */

const memories = ref<MemoryEntry[]>([])
const newMemoryContent = ref('')
const addingMemory = ref(false)
const memoryMsg = ref('')
const longTermMemoryEnabled = ref(true)

function showMessage(refObj: ReturnType<typeof ref<string>>, text: string, duration = 2000) {
  refObj.value = text
  setTimeout(() => { refObj.value = '' }, duration)
}

async function loadAgentSettings() {
  const userId = settingsStore.profile.userId
  if (!userId) return

  const [promptResult, memoryResult, configResult] = await Promise.allSettled([
    fetchSystemPrompts(userId),
    fetchMemories(userId),
    fetchMemoryConfig(userId),
  ])

  if (promptResult.status === 'fulfilled') {
    promptEntries.value = promptResult.value.entries ?? []
  }
  if (memoryResult.status === 'fulfilled') {
    memories.value = memoryResult.value ?? []
  }
  if (configResult.status === 'fulfilled') {
    longTermMemoryEnabled.value = configResult.value.long_term_memory_enabled
  }
}

async function handleSaveMemoryConfig() {
  if (!settingsStore.profile.userId) return
  try {
    const result = await saveMemoryConfig(settingsStore.profile.userId, longTermMemoryEnabled.value)
    longTermMemoryEnabled.value = result.long_term_memory_enabled
    showMessage(memoryMsg, result.long_term_memory_enabled ? '长期记忆已开启' : '长期记忆已关闭')
  } catch {
    longTermMemoryEnabled.value = !longTermMemoryEnabled.value
    showMessage(memoryMsg, '保存长期记忆设置失败')
  }
}

async function handleAddPrompt() {
  const content = newPromptContent.value.trim()
  if (!content || !settingsStore.profile.userId) return
  addingPrompt.value = true
  try {
    await addSystemPromptEntry(settingsStore.profile.userId, content)
    newPromptContent.value = ''
    await loadAgentSettings()
    showMessage(promptMsg, '已添加')
  } catch {
    showMessage(promptMsg, '添加失败')
  } finally {
    addingPrompt.value = false
  }
}

async function handleDeletePrompt(promptId: string) {
  try {
    await deleteSystemPromptEntry(promptId)
    await loadAgentSettings()
    showMessage(promptMsg, '已删除')
  } catch {
    showMessage(promptMsg, '删除失败')
  }
}

async function handleAddMemory() {
  const content = newMemoryContent.value.trim()
  if (!content || !settingsStore.profile.userId) return
  addingMemory.value = true
  try {
    await addMemory(settingsStore.profile.userId, content)
    newMemoryContent.value = ''
    await loadAgentSettings()
    showMessage(memoryMsg, '已添加')
  } catch {
    showMessage(memoryMsg, '添加失败')
  } finally {
    addingMemory.value = false
  }
}

async function handleDeleteMemory(memoryId: string) {
  try {
    await deleteMemory(memoryId)
    await loadAgentSettings()
    showMessage(memoryMsg, '已删除')
  } catch {
    showMessage(memoryMsg, '删除失败')
  }
}

/* ---- Web search config ---- */

const proxyUrlDraft = ref('')
const webSearchEnabledDraft = ref(false)
const webSearchMaxResultsDraft = ref(10)
const webSearchSaving = ref(false)
const webSearchMsg = ref('')
const browserProxyUrlDraft = ref('')
const browserHomeUrlDraft = ref('https://www.google.com')
const browserSaving = ref(false)
const browserMsg = ref('')

async function loadWebSearchConfig() {
  if (!settingsStore.profile.userId) return
  try {
    const cfg = await fetchWebSearchConfig(settingsStore.profile.userId)
    proxyUrlDraft.value = cfg.proxy_url || ''
    webSearchEnabledDraft.value = cfg.web_search_enabled
    webSearchMaxResultsDraft.value = cfg.web_search_max_results ?? 10
    browserProxyUrlDraft.value = cfg.browser_proxy_url || ''
    browserHomeUrlDraft.value = cfg.browser_home_url || 'https://www.google.com'
  } catch { /* ignore */ }
}

/** Persist browser-only networking settings and update a live browser view. */
async function handleSaveBrowser() {
  if (!settingsStore.profile.userId || browserSaving.value) return
  browserSaving.value = true
  browserMsg.value = ''
  try {
    const cfg = await saveWebSearchConfig(settingsStore.profile.userId, {
      browserProxyUrl: browserProxyUrlDraft.value,
      browserHomeUrl: browserHomeUrlDraft.value || 'https://www.google.com',
    })
    await window.agentEditorDesktop?.browserConfigure({
      proxyUrl: cfg.browser_proxy_url || cfg.proxy_url || '',
      homeUrl: cfg.browser_home_url || 'https://www.google.com',
      themeMode: settingsStore.themeMode,
    })
    showMessage(browserMsg, '已保存')
  } catch {
    showMessage(browserMsg, '保存失败')
  } finally {
    browserSaving.value = false
  }
}

async function handleSaveWebSearch() {
  if (!settingsStore.profile.userId || webSearchSaving.value) return
  webSearchSaving.value = true
  webSearchMsg.value = ''
  try {
    await saveWebSearchConfig(settingsStore.profile.userId, {
      proxyUrl: proxyUrlDraft.value || undefined,
      webSearchEnabled: webSearchEnabledDraft.value,
      webSearchMaxResults: webSearchMaxResultsDraft.value || undefined,
    })
    settingsStore.updateProfile({
      proxyUrl: proxyUrlDraft.value,
      webSearchEnabled: webSearchEnabledDraft.value,
    })
    showMessage(webSearchMsg, '已保存')
  } catch {
    showMessage(webSearchMsg, '保存失败')
  } finally {
    webSearchSaving.value = false
  }
}

/* ---- LLM model config ---- */

const largeModelName = ref('')
const largeBaseUrl = ref('')
const largeApiKey = ref('')
const smallModelName = ref('')
const smallBaseUrl = ref('')
const smallApiKey = ref('')
const largeContextWindowTokens = ref(DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS)
const largeMaxOutputTokens = ref(0)
const smallContextWindowTokens = ref(DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS)
const smallMaxOutputTokens = ref(0)
const showLargeKey = ref(false)
const showSmallKey = ref(false)
const modelSaving = ref(false)
const modelMsg = ref('')
const modelEditing = ref(false)
const modelConfigLoaded = ref(false)
const effectiveLargeModelName = ref('')
const effectiveLargeModelSource = ref<'remote' | 'local' | ''>('')
const effectiveSmallModelName = ref('')
const effectiveSmallModelSource = ref<'remote' | 'local' | ''>('')
const savedSmallModelConfigured = ref(false)
const modelConfigSaved = computed(() => !!(largeModelName.value || largeBaseUrl.value || largeApiKey.value))
const savedModelConfigs = ref<SavedLLMConfig[]>([])

/** Store only backend-resolved values so unsaved drafts are never shown as active models. */
function applyEffectiveModelConfig(config: LLMConfigResponse) {
  effectiveLargeModelName.value = config.effective_model_name || ''
  effectiveLargeModelSource.value = config.effective_model_source || ''
  effectiveSmallModelName.value = config.effective_small_model_name || ''
  effectiveSmallModelSource.value = config.effective_small_model_source || ''
  savedSmallModelConfigured.value = Boolean(config.small_model_name?.trim())
}

async function loadModelConfig() {
  if (!settingsStore.profile.userId) return
  modelConfigLoaded.value = false
  try {
    const cfg = await fetchLLMConfig(settingsStore.profile.userId)
    if (!cfg || !cfg.user_id) return
    largeModelName.value = cfg.model_name || ''
    largeBaseUrl.value = cfg.base_url || ''
    largeApiKey.value = cfg.api_key || ''
    smallModelName.value = cfg.small_model_name || ''
    smallBaseUrl.value = cfg.small_base_url || ''
    smallApiKey.value = cfg.small_api_key || ''
    largeContextWindowTokens.value = cfg.model_context_window_tokens || DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
    largeMaxOutputTokens.value = cfg.model_max_output_tokens || 0
    smallContextWindowTokens.value = cfg.small_model_context_window_tokens || DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
    smallMaxOutputTokens.value = cfg.small_model_max_output_tokens || 0
    applyEffectiveModelConfig(cfg)
  } catch { /* ignore */ }
  finally { modelConfigLoaded.value = true }
}

async function loadSavedModelConfigs() {
  if (!settingsStore.profile.userId) return
  try {
    const response = await fetchSavedLLMConfigs(settingsStore.profile.userId)
    savedModelConfigs.value = response.configs ?? []
  } catch {
    savedModelConfigs.value = []
  }
}

async function handleSaveModel() {
  if (!settingsStore.profile.userId) return
  modelSaving.value = true
  modelMsg.value = ''
  try {
    const saved = await saveLLMConfig(settingsStore.profile.userId, {
      apiKey: largeApiKey.value,
      baseUrl: largeBaseUrl.value,
      modelName: largeModelName.value,
      smallApiKey: smallApiKey.value,
      smallBaseUrl: smallBaseUrl.value,
      smallModelName: smallModelName.value,
      modelContextWindowTokens: largeContextWindowTokens.value,
      modelMaxOutputTokens: largeMaxOutputTokens.value,
      smallModelContextWindowTokens: smallContextWindowTokens.value,
      smallModelMaxOutputTokens: smallMaxOutputTokens.value,
    })
    modelEditing.value = false
    applyEffectiveModelConfig(saved)
    await loadSavedModelConfigs()
    window.dispatchEvent(new CustomEvent('agent-model-config-updated', {
      detail: { modelName: saved.effective_model_name || saved.model_name },
    }))
    showMessage(modelMsg, '已保存')
  } catch {
    showMessage(modelMsg, '保存失败')
  } finally {
    modelSaving.value = false
  }
}

async function handleSaveModelPreset(target: 'large' | 'small') {
  if (!settingsStore.profile.userId) return
  const source = target === 'large'
    ? { modelName: largeModelName.value, baseUrl: largeBaseUrl.value, apiKey: largeApiKey.value, label: '大模型配置' }
    : { modelName: smallModelName.value, baseUrl: smallBaseUrl.value, apiKey: smallApiKey.value, label: '小模型配置' }
  try {
    await saveLLMConfigPreset(settingsStore.profile.userId, {
      label: source.modelName || source.baseUrl || source.label,
      modelName: source.modelName || undefined,
      baseUrl: source.baseUrl || undefined,
      apiKey: source.apiKey || undefined,
    })
    await loadSavedModelConfigs()
    showMessage(modelMsg, '已保存配置')
  } catch {
    showMessage(modelMsg, '保存配置失败')
  }
}

function importSavedModelConfig(config: SavedLLMConfig, target: 'large' | 'small') {
  if (target === 'large') {
    largeModelName.value = config.model_name || ''
    largeBaseUrl.value = config.base_url || ''
    largeApiKey.value = config.api_key || ''
  } else {
    smallModelName.value = config.model_name || ''
    smallBaseUrl.value = config.base_url || ''
    smallApiKey.value = config.api_key || ''
  }
  modelEditing.value = true
}

async function handleDeleteSavedModelConfig(configId: string) {
  try {
    await deleteLLMConfigPreset(configId)
    savedModelConfigs.value = savedModelConfigs.value.filter(config => config.config_id !== configId)
    showMessage(modelMsg, '已删除配置')
  } catch {
    showMessage(modelMsg, '删除配置失败')
  }
}


/* ---- Terminal sandbox ---- */

const terminalSandboxConfig = ref<TerminalSandboxConfig | null>(null)
const terminalSegmentCatalog = ref<Record<TerminalShellKey, TerminalSegmentInfo[]>>({
  cmd: [],
  powershell: [],
  bash: [],
})
const terminalSandboxSaving = ref(false)
const terminalSandboxMsg = ref('')

function applyTerminalSandboxResponse(response: TerminalSandboxConfigResponse) {
  terminalSandboxConfig.value = response.config
  terminalSegmentCatalog.value = response.segment_catalog
}

async function loadTerminalSandboxConfig() {
  if (!settingsStore.profile.userId) return
  try {
    applyTerminalSandboxResponse(await fetchTerminalSandboxConfig(settingsStore.profile.userId))
  } catch {
    terminalSandboxMsg.value = '加载失败'
  }
}

async function handleSaveTerminalSandbox(config: TerminalSandboxConfig) {
  if (!settingsStore.profile.userId || terminalSandboxSaving.value) return
  terminalSandboxSaving.value = true
  terminalSandboxMsg.value = ''
  try {
    applyTerminalSandboxResponse(await saveTerminalSandboxConfig(settingsStore.profile.userId, config))
    showMessage(terminalSandboxMsg, '已保存')
  } catch {
    showMessage(terminalSandboxMsg, '保存失败')
  } finally {
    terminalSandboxSaving.value = false
  }
}

onMounted(() => {
  window.addEventListener('agent-settings-tab', handleExternalSettingsTab as EventListener)
  loadAvailableFonts()
  loadAgentSettings()
  loadModelConfig()
  loadSavedModelConfigs()
  loadWebSearchConfig()
  loadTerminalSandboxConfig()
})

onBeforeUnmount(() => {
  window.removeEventListener('agent-settings-tab', handleExternalSettingsTab as EventListener)
  for (const target of ['ui', 'text'] as const) {
    if (!fontSizeSaveTimers[target]) continue
    window.clearTimeout(fontSizeSaveTimers[target])
    fontSizeSaveTimers[target] = null
    const percent = target === 'ui' ? uiFontSizePercentDraft.value : textFontSizePercentDraft.value
    void persistFontSize(target, percent)
  }
})
</script>

<template>
  <div class="settings-page">
    <SettingsSidebar
      :active-tab="activeTab"
      :tabs="tabs"
      @select="activeTab = $event"
    />

    <div class="settings-body" :class="{ 'settings-body-skills': activeTab === 'skills' }">
      <FormHeightTransition :watch-key="activeTab">
        <div class="settings-body-content">
          <BasicSettingsSection
        v-if="activeTab === 'basic'"
        v-model:auto-ingest-on-upload-draft="autoIngestOnUploadDraft"
        v-model:editor-image-assets-dir-draft="editorImageAssetsDirDraft"
        v-model:knowledge-dir-draft="knowledgeDirDraft"
        v-model:knowledge-ignore-patterns-draft="knowledgeIgnorePatternsDraft"
        v-model:library-name-draft="libraryNameDraft"
        v-model:vision-understanding-enabled-draft="visionUnderstandingEnabledDraft"
        v-model:dsh-coding-agent-enabled-draft="dshCodingAgentEnabledDraft"
        v-model:watch-enabled-draft="watchEnabledDraft"
        :supported-file-types="settingsStore.profile.knowledgeSupportedSuffixes ?? []"
        :has-changes="hasChanges"
        :save-error="saveError"
        :save-message="saveMessage"
        :saving="saving"
        :switching-knowledge-root="switchingKnowledgeRoot"
        @logout="handleLogout"
        @save="saveProfile"
        @select-knowledge-directory="selectKnowledgeDirectory"
      />

      <AppearanceSettingsSection
        v-if="activeTab === 'appearance'"
        v-model:text-font-size-percent-draft="textFontSizePercentDraft"
        v-model:text-font-families-draft="textFontFamiliesDraft"
        v-model:theme-primary-color-draft="themePrimaryColorDraft"
        v-model:theme-soft-color-draft="themeSoftColorDraft"
        v-model:tag-colors-draft="tagColorsDraft"
        v-model:tag-colors-translucent-draft="tagColorsTranslucentDraft"
        v-model:ui-font-families-draft="uiFontFamiliesDraft"
        v-model:ui-font-size-percent-draft="uiFontSizePercentDraft"
        :available-font-families="availableFontFamilies"
        :background-cover-url="settingsStore.profile.backgroundCoverUrl ?? ''"
        :fonts-loading="fontsLoading"
        :sidebar-display-mode="settingsStore.sidebarDisplayMode"
        :show-backlinks="Boolean(settingsStore.profile.showBacklinks)"
        :theme-mode="settingsStore.themeMode"
        :theme-options="themeOptions"
        :user-id="settingsStore.profile.userId"
        @preview-theme-colors="handlePreviewThemeColors"
        @preview-tag-colors="handlePreviewTagColors"
        @reset-tag-colors="handleResetTagColors"
        @reset-theme-colors="handleResetThemeColors"
        @save-font-families="handleSaveFontFamilies"
        @save-font-size="handleSaveFontSize"
        @save-theme-colors="handleSaveThemeColors"
        @save-tag-colors="handleSaveTagColors"
        @set-sidebar-display-mode="settingsStore.setSidebarDisplayMode"
        @set-background-cover="handleSetBackgroundCover"
        @set-show-backlinks="handleSetShowBacklinks"
        @set-theme-mode="settingsStore.setThemeMode"
        @reset-background-cover="handleResetBackgroundCover"
      />

      <LlmSettingsSection
        v-if="activeTab === 'llm'"
        v-model:large-api-key="largeApiKey"
        v-model:large-base-url="largeBaseUrl"
        v-model:large-model-name="largeModelName"
        v-model:large-context-window-tokens="largeContextWindowTokens"
        v-model:large-max-output-tokens="largeMaxOutputTokens"
        v-model:model-editing="modelEditing"
        v-model:show-large-key="showLargeKey"
        v-model:show-small-key="showSmallKey"
        v-model:small-api-key="smallApiKey"
        v-model:small-base-url="smallBaseUrl"
        v-model:small-model-name="smallModelName"
        v-model:small-context-window-tokens="smallContextWindowTokens"
        v-model:small-max-output-tokens="smallMaxOutputTokens"
        :model-config-saved="modelConfigSaved"
        :model-config-loaded="modelConfigLoaded"
        :model-msg="modelMsg"
        :model-saving="modelSaving"
        :saved-configs="savedModelConfigs"
        :effective-large-model-name="effectiveLargeModelName"
        :effective-large-model-source="effectiveLargeModelSource"
        :effective-small-model-name="effectiveSmallModelName"
        :effective-small-model-source="effectiveSmallModelSource"
        :saved-small-model-configured="savedSmallModelConfigured"
        @cancel="modelEditing = false; loadModelConfig()"
        @delete-saved-config="handleDeleteSavedModelConfig"
        @import-saved-config="importSavedModelConfig"
        @save="handleSaveModel"
        @save-preset="handleSaveModelPreset"
      />

      <VlmSettingsSection v-if="activeTab === 'vlm'" />

      <TerminalSandboxSettingsSection
        v-if="activeTab === 'terminal' && terminalSandboxConfig"
        :config="terminalSandboxConfig"
        :saving="terminalSandboxSaving"
        :segment-catalog="terminalSegmentCatalog"
        :status-message="terminalSandboxMsg"
        @save="handleSaveTerminalSandbox"
      />

      <div v-if="activeTab === 'web'" class="web-settings-sections">
        <WebSearchSettingsSection
          v-model:proxy-url-draft="proxyUrlDraft"
          v-model:web-search-enabled-draft="webSearchEnabledDraft"
          v-model:web-search-max-results-draft="webSearchMaxResultsDraft"
          :web-search-msg="webSearchMsg"
          :web-search-saving="webSearchSaving"
          @save="handleSaveWebSearch"
        />

        <BrowserSettingsSection
          v-model:browser-home-url-draft="browserHomeUrlDraft"
          v-model:browser-proxy-url-draft="browserProxyUrlDraft"
          :inherited-proxy-url="proxyUrlDraft"
          :saving="browserSaving"
          :status-message="browserMsg"
          @save="handleSaveBrowser"
        />
      </div>

      <MemorySettingsSection
        v-if="activeTab === 'memory'"
        v-model:new-memory-content="newMemoryContent"
        v-model:new-prompt-content="newPromptContent"
        v-model:long-term-memory-enabled="longTermMemoryEnabled"
        :adding-memory="addingMemory"
        :adding-prompt="addingPrompt"
        :memories="memories"
        :memory-msg="memoryMsg"
        :prompt-entries="promptEntries"
        :prompt-msg="promptMsg"
        :show-favorite-column="settingsStore.showFavoriteColumn"
        :show-graph-column="settingsStore.showGraphColumn"
        :show-index-column="settingsStore.showIndexColumn"
        @add-memory="handleAddMemory"
        @add-prompt="handleAddPrompt"
        @delete-memory="handleDeleteMemory"
        @delete-prompt="handleDeletePrompt"
        @save-memory-config="handleSaveMemoryConfig"
        @set-show-favorite-column="settingsStore.setShowFavoriteColumn"
        @set-show-graph-column="settingsStore.setShowGraphColumn"
        @set-show-index-column="settingsStore.setShowIndexColumn"
      />

      <GraphSettingsSection
        v-if="activeTab === 'graph'"
        v-model:graph-node-limit-draft="graphNodeLimitDraft"
      />

      <SafetySettingsSection
        v-if="activeTab === 'safety'"
      />
      <StorageSettingsSection
        v-if="activeTab === 'storage'"
      />
          <FloatingSettingsSection
            v-if="activeTab === 'floating'"
          />
          <SkillView v-if="activeTab === 'skills'" />
          <McpSettingsSection v-if="activeTab === 'mcp'" />
        </div>
      </FormHeightTransition>
    </div>
  </div>
</template>

<style>
.settings-page {
  display: flex;
  height: 100%;
  overflow: hidden;
  background:
    linear-gradient(180deg, var(--color-chrome-bg-top), var(--color-chrome-bg-bottom)),
    var(--color-chrome-bg-solid);
}

.settings-sidebar {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 136px;
  flex-shrink: 0;
  padding: var(--space-12) var(--space-8);
  border-right: 0;
  overflow-y: auto;
}

.sidebar-tab {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  padding: var(--space-8) var(--space-10);
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  text-align: left;
  cursor: pointer;
  transition: background 150ms, color 150ms;
}

.settings-sidebar .sidebar-tab-icon {
  flex: 0 0 16px;
}

.sidebar-tab:hover {
  background: var(--color-primary-softer);
  color: var(--color-text-primary);
}

.sidebar-tab.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.settings-body {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-16) var(--space-20);
  font-size: calc(13px * var(--font-scale));
}

.settings-body > .form-height-transition {
  overflow: visible;
}

.settings-body.settings-body-skills {
  padding: 0;
}

.web-settings-sections {
  display: grid;
  gap: var(--space-24);
  min-width: 0;
}

.web-settings-sections > .setting-section,
.web-settings-sections .setting-row > input {
  min-width: 0;
}

@media (max-width: 600px) {
  .settings-page {
    flex-direction: column;
  }

  .settings-sidebar {
    width: 100%;
    flex-direction: row;
    gap: 2px;
    padding: var(--space-6) var(--space-8);
    overflow-x: auto;
    overflow-y: hidden;
  }

  .settings-sidebar::after {
    content: '';
    flex: 0 0 var(--space-12);
  }

  .sidebar-tab {
    width: auto;
    flex: 0 0 auto;
    padding: var(--space-6) var(--space-10);
    white-space: nowrap;
  }

  .settings-body {
    padding: var(--space-10) var(--space-12);
  }
}

.setting-section h3 {
  margin: 0 0 var(--space-10);
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.setting-row {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  margin-bottom: var(--space-8);
}

.setting-row label {
  flex-shrink: 0;
  width: 72px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.setting-row > input {
  flex: 1;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
}

.setting-row > input:focus {
  border-color: var(--color-primary);
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: var(--space-10);
}

.toggle-row label {
  width: 72px;
}

.toggle-row input[type="checkbox"] {
  position: relative;
  width: 32px;
  height: 20px;
  margin: 0;
  flex: none;
  appearance: none;
  -webkit-appearance: none;
  outline: none;
  cursor: pointer;
  flex-shrink: 0;
  background: transparent;
  border: none;
  z-index: 0;
  padding: 0;
}

/* Track */
.toggle-row input[type="checkbox"]::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 2px;
  right: 2px;
  height: 6px;
  transform: translateY(-50%);
  border-radius: 999px;
  background: var(--color-text-muted);
  opacity: 0.3;
  transition: opacity 0.3s, background 0.3s;
  pointer-events: none;
}

/* Thumb with inner dot */
.toggle-row input[type="checkbox"]::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
  box-shadow: inset 0 0 0 3px var(--color-canvas);
  transition: left 0.3s, background 0.3s, box-shadow 0.2s;
  pointer-events: none;
}

.toggle-row input[type="checkbox"]:checked::before {
  opacity: 1;
  background: var(--color-primary);
}

.toggle-row input[type="checkbox"]:checked::after {
  left: 14px;
  background: var(--color-primary);
  box-shadow: none;
}

.ignore-row {
  align-items: flex-start;
}

.ignore-row textarea {
  flex: 1;
  min-height: 86px;
  padding: var(--space-8) var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.5;
  outline: none;
  resize: vertical;
}

.ignore-row textarea:focus {
  border-color: var(--color-primary);
}

.terminal-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-8) var(--space-12);
  margin-bottom: var(--space-8);
}

.terminal-grid .compact-row {
  margin-bottom: 0;
}

.terminal-grid .compact-row label {
  width: 72px;
}

.terminal-pages {
  display: flex;
  gap: var(--space-4);
  margin: var(--space-12) 0 var(--space-8);
  border-bottom: 1px solid var(--color-border);
}

.terminal-page-tab {
  height: 30px;
  padding: 0 var(--space-12);
  border: 1px solid transparent;
  border-bottom: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.terminal-page-tab:hover,
.terminal-page-tab.active {
  border-color: var(--color-border);
  color: var(--color-primary);
}

.terminal-page-body {
  padding-top: var(--space-4);
}

.segment-list {
  display: grid;
  gap: var(--space-6);
  margin: var(--space-8) 0 var(--space-12) 82px;
}

.segment-row {
  display: grid;
  grid-template-columns: 132px 96px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-8);
  min-height: 30px;
  padding: 0 var(--space-8);
  border: 1px solid var(--color-border);
  background: var(--color-canvas);
}

.segment-row code {
  color: var(--color-text-muted);
  font-family: var(--font-code);
  font-size: calc(11px * var(--font-scale));
}

.segment-row strong {
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
}

.segment-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-family: var(--font-code);
  font-size: calc(11px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.setting-hint {
  margin: -2px 0 var(--space-8) 82px;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.45;
}

.font-family-control {
  position: relative;
  margin-bottom: var(--space-10);
  padding-left: 82px;
}

.font-family-header {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  margin-bottom: var(--space-6);
}

.font-family-header label {
  width: 72px;
  margin-left: -82px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.font-family-header span {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.font-size-control {
  margin-bottom: var(--space-16);
}

.font-size-row {
  display: grid;
  grid-template-columns: 140px 72px;
  align-items: center;
  gap: var(--space-10);
}

.font-size-row input[type='range'] {
  width: 140px;
  accent-color: var(--color-primary);
}

.font-size-number {
  width: 72px;
  height: 30px;
  padding: 0 var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  text-align: center;
  box-sizing: border-box;
}

.font-size-number:focus {
  border-color: var(--color-primary);
}

.font-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
  min-width: 0;
}

.font-chip,
.font-add-button {
  min-height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.font-chip:hover,
.font-add-button:hover {
  border-color: var(--color-primary);
  color: var(--color-text);
}

.font-picker-popover {
  position: absolute;
  top: calc(100% + 4px);
  left: 82px;
  z-index: 30;
  width: min(360px, calc(100vw - 180px));
  padding: var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-window);
}

.font-picker-popover input {
  width: 100%;
  height: 30px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--color-surface-raised);
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
}

.font-picker-popover input:focus {
  border-color: var(--color-primary);
}

.font-option-list {
  display: grid;
  gap: 2px;
  max-height: 260px;
  margin-top: var(--space-6);
  overflow: auto;
}

.font-option-list button {
  min-height: 28px;
  padding: 0 var(--space-8);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  text-align: left;
}

.font-option-list button:hover {
  background: var(--color-primary-softer);
  color: var(--color-text);
}

.font-empty {
  margin: var(--space-8);
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

/* Theme */
.theme-row {
  display: flex;
  gap: var(--space-6);
}

.theme-row button {
  height: 28px;
  padding: 0 var(--space-16);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.theme-row button.active {
  background: transparent;
  font-weight: 600;
}

.theme-row button.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.color-control {
  margin-top: var(--space-10);
  padding-left: 82px;
}

.color-control-header {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  margin-bottom: var(--space-6);
}

.color-control-header label {
  width: 72px;
  margin-left: -82px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.color-control-header span {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.color-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}

.color-picker {
  width: 34px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  cursor: pointer;
}

.page-display-control {
  margin: var(--space-10) 0 var(--space-16);
  padding-left: 82px;
}

.page-display-header {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  margin-bottom: var(--space-6);
}

.page-display-header label {
  width: 72px;
  margin-left: -82px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.page-display-header span {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.page-display-row {
  display: inline-flex;
  gap: var(--space-6);
}

.page-display-row button {
  height: 28px;
  padding: 0 var(--space-16);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast),
    background var(--transition-fast);
}

.page-display-row button:hover,
.page-display-row button.active {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.color-text {
  width: 110px;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
}

.color-text:focus {
  border-color: var(--color-primary);
}

.appearance-actions {
  margin-top: var(--space-10);
  padding-left: 82px;
}

/* Model */
.model-block {
  margin-bottom: var(--space-10);
}

.model-block > input {
  display: block;
  width: 100%;
  height: 28px;
  margin-bottom: var(--space-6);
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
  box-sizing: border-box;
}

.model-block > input:focus {
  border-color: var(--color-primary);
}

.model-block > input.readonly {
  border-color: transparent;
  background: transparent;
  cursor: default;
}

.key-row {
  display: flex;
  gap: var(--space-4);
}

.key-row input {
  flex: 1;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
  box-sizing: border-box;
}

.key-row input:focus {
  border-color: var(--color-primary);
}

.key-row input.readonly {
  border-color: transparent;
  background: transparent;
  cursor: default;
}

.toggle-key {
  flex-shrink: 0;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
}

.toggle-key:hover {
  color: var(--color-text);
  border-color: var(--color-primary);
}

.model-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.saved-model-section {
  margin-top: var(--space-16);
}

.saved-model-grid {
  display: grid;
  gap: var(--space-8);
}

.saved-model-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
}

.saved-model-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.saved-model-main strong,
.saved-model-main span,
.saved-model-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.saved-model-main strong {
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.saved-model-main span,
.saved-model-main small {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.saved-model-actions {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.saved-model-actions button {
  height: 26px;
  padding: 0 var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
}

.saved-model-actions button:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.saved-model-actions button.danger:hover {
  border-color: rgba(255, 95, 95, 0.5);
  color: var(--color-danger);
}

.hint-text {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.4;
}

.feedback.error {
  color: var(--color-danger);
}

.save-model-btn {
  height: 28px;
  padding: 0 var(--space-16);
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary-softer);
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.save-model-btn:hover:not(:disabled) {
  background: var(--color-primary);
  color: #fff;
}

.save-model-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.edit-model-btn {
  height: 28px;
  padding: 0 var(--space-16);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.edit-model-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.cancel-model-btn {
  height: 28px;
  padding: 0 var(--space-14);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.cancel-model-btn:hover {
  border-color: var(--color-danger);
  color: var(--color-danger);
}

/* ---- 动画删除按钮 ---- */
.delete-btn {
  width: 25px;
  height: 25px;
  border-radius: 50%;
  background-color: var(--color-canvas);
  border: 1px solid var(--color-border);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: none;
  cursor: pointer;
  transition-duration: .3s;
  overflow: hidden;
  position: relative;
  flex-shrink: 0;
  padding: 0;
}

.delete-btn .svgIcon {
  width: 12px;
  transition-duration: .3s;
}

.delete-btn .svgIcon path {
  fill: rgb(255, 69, 69);
}

.delete-btn:hover {
  width: 70px;
  border-radius: 50px;
  transition-duration: .3s;
  background-color: rgb(255, 69, 69);
  border-color: rgb(255, 69, 69);
}

.delete-btn:hover .svgIcon {
  width: 25px;
  transition-duration: .3s;
  transform: translateY(60%);
}

.delete-btn:hover .svgIcon path {
  fill: white;
}

/* Input row for add */
.input-row {
  display: flex;
  gap: var(--space-4);
}

.input-row input {
  flex: 1;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
}

.input-row input:focus {
  border-color: var(--color-primary);
}

.add-btn {
  flex-shrink: 0;
  height: 28px;
  padding: 0 var(--space-12);
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  white-space: nowrap;
}

.add-btn:hover:not(:disabled) {
  background: var(--color-primary);
  color: #fff;
}

.add-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.feedback {
  margin: var(--space-4) 0 0;
  color: var(--color-primary);
  font-size: calc(12px * var(--font-scale));
}

/* Entry list */
.entry-list {
  list-style: none;
  margin: var(--space-6) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.entry-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-4) var(--space-8);
  border: 0;
  border-radius: 999px;
  background: var(--color-canvas);
}

.memory-title {
  margin-top: var(--space-16) !important;
}

.memory-entry-row {
  border: 0;
}

.entry-text {
  flex: 1;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-del {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: calc(14px * var(--font-scale));
  cursor: pointer;
}

.entry-del:hover {
  color: var(--color-danger);
  border-color: rgba(255, 95, 95, 0.4);
  background: rgba(255, 95, 95, 0.08);
}

/* Tool management */
.tool-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.tool-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
  transition: opacity 150ms;
}

.tool-row.disabled {
  opacity: 0.55;
}

.tool-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tool-name {
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
  color: var(--color-text);
}

.tool-desc {
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row input[type="checkbox"] {
  position: relative;
  width: 28px;
  height: 16px;
  margin: 0;
  flex: none;
  appearance: none;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  cursor: pointer;
  transition: background 200ms, border-color 200ms;
  flex-shrink: 0;
}

.tool-row input[type="checkbox"]::before {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--color-text-muted);
  transition: transform 200ms, background 200ms;
}

.tool-row input[type="checkbox"]:checked {
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.tool-row input[type="checkbox"]:checked::before {
  transform: translateX(12px);
  background: #fff;
}

.toggle-hint {
  margin: -2px 0 var(--space-8) 0 !important;
}

.empty-hint {
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-muted);
  margin: var(--space-4) 0;
}
</style>

<style>
/* Normalize every editable settings field while preserving toggle controls. */
.settings-body input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']):not([type='file']):not([type='hidden']),
.settings-body select {
  border: 0 !important;
  border-radius: 999px !important;
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-text) 6%) !important;
  transition: box-shadow var(--transition-fast);
}

.settings-body textarea {
  border: 0 !important;
  border-radius: 28px !important;
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-text) 6%) !important;
  transition: box-shadow var(--transition-fast);
}

.settings-body .ignore-row textarea {
  min-height: 172px;
  border-radius: 18px !important;
  background: var(--color-code-bg) !important;
  font-family: var(--font-code);
  line-height: 1.6;
}

.settings-body {
  --settings-label-width: 112px;
  --settings-label-indent: 122px;
}

.settings-body .setting-row > label,
.settings-body .terminal-grid .compact-row label,
.settings-body .font-family-header label,
.settings-body .color-control-header label,
.settings-body .page-display-header label {
  width: var(--settings-label-width) !important;
}

.settings-body .font-family-control,
.settings-body .color-control,
.settings-body .page-display-control {
  padding-left: var(--settings-label-indent);
}

.settings-body .font-family-header label,
.settings-body .color-control-header label,
.settings-body .page-display-header label {
  margin-left: calc(-1 * var(--settings-label-indent));
}

.settings-body .blocked-file-types-row > label {
  flex: 0 0 var(--settings-label-width) !important;
}

.settings-body .terminal-page-card,
.settings-body .vault-debug-card,
.settings-body .safety-global-toggles,
.settings-body .safety-category-card,
.settings-body .stat-card {
  margin-inline: var(--space-8);
}

.settings-body input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']):not([type='file']):not([type='hidden']):focus,
.settings-body select:focus,
.settings-body textarea:focus {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-border-strong) 50%, transparent) !important;
}

/* LLM and OCR/VLM forms share one field rhythm, inset, and focus motion. */
.settings-model-form input:not([type='checkbox']),
.settings-model-form select {
  min-width: 0;
  box-sizing: border-box;
  padding-inline: var(--space-12) !important;
  font-size: calc(12px * var(--font-scale));
  line-height: 28px;
  transition: background-color 180ms ease, box-shadow 180ms ease, color 180ms ease, opacity 180ms ease, transform 140ms cubic-bezier(.16,1,.3,1);
}

.settings-model-form input:not([type='checkbox']):hover:not([readonly]),
.settings-model-form select:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-surface) 90%, var(--color-primary) 10%) !important;
}

.settings-model-form input:not([type='checkbox']):focus,
.settings-model-form select:focus {
  transform: translateY(-1px);
}

.settings-model-form input.readonly,
.settings-model-form select.readonly {
  box-shadow: none !important;
}

.settings-model-form .effective-model-summary { margin-bottom: var(--space-16); }
.settings-model-form .effective-model-summary h3 { margin: 0 0 var(--space-10); }
.settings-model-form .effective-model-summary dl { margin: 0; border-block: 1px solid var(--color-border); }
.settings-model-form .effective-model-summary dl > div { display:grid; grid-template-columns:84px minmax(0,1fr) auto; align-items:center; gap:var(--space-10); min-height:38px; }
.settings-model-form .effective-model-summary dl > div + div { border-top:1px solid var(--color-border); }
.settings-model-form .effective-model-summary dt,
.settings-model-form .effective-model-summary dd,
.settings-model-form .effective-model-summary span { margin:0; font-size:calc(12px * var(--font-scale)); }
.settings-model-form .effective-model-summary dt,
.settings-model-form .effective-model-summary span { color:var(--color-text-muted); }
.settings-model-form .effective-model-summary dd { min-width:0; overflow:hidden; color:var(--color-text); font-family:var(--font-mono); text-overflow:ellipsis; white-space:nowrap; }
.settings-model-form .model-heading { display:flex; align-items:center; min-height:28px; margin-bottom:var(--space-10); }

@media (prefers-reduced-motion: reduce) {
  .settings-model-form input:not([type='checkbox']),
  .settings-model-form select { transition:none; }
}
</style>
