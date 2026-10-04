/** Real onboarding settings requests, shared by per-section Save and page Confirm. */
import { ensureSettingsProfile, fetchLLMConfig, fetchMemoryConfig, fetchOnboardingDefaults, fetchSafetyConfig, fetchVlmConfig, fetchWebSearchConfig, saveAppearanceConfig, saveKnowledgeIngestionConfig, saveLLMConfig, saveMemoryConfig, saveSafetyConfig, saveVlmConfig, saveWebSearchConfig, updateSettingsKnowledgeDir } from '@/api/settings'
import type { AuthDraft } from './authTypes'
import type { ThemeMode } from '@/types/settings'
import { useSettingsStore } from '@/stores/settings'
import { getApiSessionToken } from '@/api/client'

export type ModelSection = 'large' | 'small' | 'vision' | 'mineru'

/** Restore backend configuration before resuming an incomplete five-page initialization. */
export async function loadOnboardingDraft(userId: string, draft: AuthDraft): Promise<void> {
  const token = getApiSessionToken()
  const [profile, models, mineru, web, memory, safety, defaults] = await Promise.all([
    ensureSettingsProfile(userId), fetchLLMConfig(userId), fetchVlmConfig(userId),
    fetchWebSearchConfig(userId), fetchMemoryConfig(userId), fetchSafetyConfig(userId), fetchOnboardingDefaults(),
  ])
  if (getApiSessionToken() !== token || useSettingsStore().profile.userId !== userId) return
  useSettingsStore().applyBackendProfile(profile)
  const active = profile.active_knowledge_library
  draft.knowledgeDir = profile.knowledge_dir || defaults.knowledge_dir
  draft.libraryName = active?.name || draft.libraryName
  draft.large = { modelName: models.model_name, baseUrl: models.base_url, apiKey: models.api_key }
  draft.small = { modelName: models.small_model_name, baseUrl: models.small_base_url, apiKey: models.small_api_key }
  draft.vision = { modelName: models.vision_model_name, baseUrl: models.vision_base_url, apiKey: models.vision_api_key }
  draft.mineruKey = mineru.api_key
  draft.mineruModel = mineru.model
  draft.vlmEnabled = mineru.enabled
  draft.ocrEnabled = profile.ocr_enabled === true
  draft.visionEnabled = profile.vision_understanding_enabled === true
  draft.proxyUrl = web.proxy_url
  draft.webSearchEnabled = web.web_search_enabled
  draft.memoryEnabled = memory.long_term_memory_enabled
  draft.sensitiveWordsEnabled = safety.sensitive_words_enabled
  draft.safetyEnabled = safety.safety_enabled
  draft.dshEnabled = profile.dsh_coding_agent_enabled === true
  draft.primaryColor = profile.theme_primary_color || '#476bf7'
  draft.softColor = profile.theme_soft_color || '#476bf7'
}

/** Save exactly the selected model group, preserving all other backend overrides. */
export async function saveOnboardingModel(userId: string, draft: AuthDraft, section: ModelSection): Promise<void> {
  if (section === 'mineru') {
    await saveVlmConfig(userId, { enabled: draft.vlmEnabled, api_key: draft.mineruKey, model: draft.mineruModel as 'pipeline' | 'vlm' })
    await saveKnowledgeIngestionConfig(userId, { ocrEnabled: draft.ocrEnabled, visionUnderstandingEnabled: draft.visionEnabled })
    return
  }
  const model = draft[section]
  if (section === 'large') await saveLLMConfig(userId, { modelName: model.modelName, baseUrl: model.baseUrl, apiKey: model.apiKey })
  if (section === 'small') await saveLLMConfig(userId, { smallModelName: model.modelName, smallBaseUrl: model.baseUrl, smallApiKey: model.apiKey })
  if (section === 'vision') await saveLLMConfig(userId, { visionModelName: model.modelName, visionBaseUrl: model.baseUrl, visionApiKey: model.apiKey })
}

/** Persist all controls on a page before the caller advances the account's saved progress. */
export async function saveOnboardingPage(userId: string, draft: AuthDraft, page: number, themeMode: ThemeMode): Promise<void> {
  if (page === 1) {
    if (!draft.libraryName.trim()) throw new Error('请输入知识库名称')
    if (!/^(?:[A-Za-z]:[\\/]|\\\\|\/)/u.test(draft.knowledgeDir.trim())) throw new Error('请选择绝对知识目录')
    const profile = await updateSettingsKnowledgeDir(userId, draft.knowledgeDir.trim(), draft.libraryName.trim())
    if (useSettingsStore().profile.userId === userId) useSettingsStore().applyBackendProfile(profile)
  } else if (page === 2) {
    // Serial saves avoid racing updates to the same user-settings row.
    for (const section of ['large', 'small', 'vision', 'mineru'] as const) await saveOnboardingModel(userId, draft, section)
  } else if (page === 3) {
    await saveAppearanceConfig(userId, { themeMode, themePrimaryColor: draft.primaryColor, themeSoftColor: draft.softColor })
    await saveWebSearchConfig(userId, { webSearchEnabled: draft.webSearchEnabled, proxyUrl: draft.proxyUrl })
    await saveMemoryConfig(userId, draft.memoryEnabled)
    await saveSafetyConfig(userId, { sensitive_words_enabled: draft.sensitiveWordsEnabled, safety_enabled: draft.safetyEnabled })
    await saveKnowledgeIngestionConfig(userId, { dshCodingAgentEnabled: draft.dshEnabled })
    await useSettingsStore().refreshUserProfile()
  }
}
