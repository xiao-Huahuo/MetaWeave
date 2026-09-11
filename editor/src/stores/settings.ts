/*
 * Global settings store.
 *
 * Usage:
 * This is the only place that reads/writes theme and editor profile values.
 * Components call actions here instead of touching localStorage or DOM theme
 * attributes directly.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { ensureSettingsProfile, fetchWebSearchConfig, rebuildKnowledgeRoot, saveAppearanceConfig, saveEditorPasteConfig, saveFloatingConfig, saveFontConfig, saveGraphConfig, saveKnowledgeIngestionConfig, saveWebSearchConfig, updateSettingsKnowledgeDir } from '@/api/settings'
import type { AgentAccessMode, AgentLoopMode } from '@/api/agent'
import type { SettingsKnowledgeLibraryResponse, SettingsProfileResponse } from '@/api/settings'
import type { KnowledgeLibraryProfile } from '@/types/settings'
import type { SidebarDisplayMode, ThemeMode, UserSettingsProfile } from '@/types/settings'

const THEME_KEY = 'agent_editor_theme_mode'
const PROFILE_KEY = 'agent_editor_profile'
const CHAT_MODE_KEY = 'agent_editor_chat_mode'
const AGENT_LOOP_MODE_KEY = 'agent_editor_loop_mode'
const AGENT_ACCESS_MODE_KEY = 'agent_editor_access_mode'
const SHOW_INDEX_COLUMN_KEY = 'agent_editor_show_index_column'
const SHOW_GRAPH_COLUMN_KEY = 'agent_editor_show_graph_column'
const SHOW_FAVORITE_COLUMN_KEY = 'agent_editor_show_favorite_column'
const SHOW_PRIVACY_COLUMN_KEY = 'agent_editor_show_privacy_column'
const SIDEBAR_DISPLAY_MODE_KEY = 'agent_editor_sidebar_display_mode'
const FLOATING_PIN_MODE_KEY = 'agent_editor_floating_pin_mode'

const DEFAULT_UI_FONT_STACK = 'var(--font-ui-default)'
const DEFAULT_TEXT_FONT_STACK = 'var(--font-text-default)'
const DEFAULT_THEME_PRIMARY_COLOR = '#476bf7'
const DEFAULT_THEME_SOFT_COLOR = '#476bf7'
export const DEFAULT_TAG_COLORS = ['#7c5cfc', '#eb2463', '#26a269', '#2f88d5', '#e2a72e', '#0ea5b6'] as const
const APPEARANCE_PREVIEW_EVENT = 'metaweave:appearance-preview'

const DEFAULT_PROFILE: UserSettingsProfile = {
  userId: '',
  knowledgeDir: 'D:/Knowledge',
  activeLibraryId: '',
  knowledgeLibraries: [],
  knowledgeWatchEnabled: true,
  proxyUrl: '',
  webSearchEnabled: false,
  webSearchMaxResults: 10,
  autoIngestOnUpload: false,
  ocrEnabled: false,
  vlmEnabled: false,
  visionUnderstandingEnabled: false,
  modelAutoDownloadEnabled: false,
  dshCodingAgentEnabled: false,
  knowledgeIgnorePatterns: '',
  knowledgeSupportedSuffixes: [],
  uiFontFamilies: [],
  textFontFamilies: [],
  uiFontSizePercent: 100,
  textFontSizePercent: 100,
  themePrimaryColor: '',
  themeSoftColor: '',
  tagColors: [...DEFAULT_TAG_COLORS],
  tagColorsTranslucent: true,
  backgroundCoverUrl: '',
  showBacklinks: false,
  graphNodeLimit: 2000,
  floatingLaunchEnabled: false,
  editorImageAssetsDir: './assets/',
}

function normalizeThemeColor(value: string | undefined): string {
  const color = (value ?? '').trim()
  if (!color) return ''
  if (/^#[0-9a-fA-F]{3}$/u.test(color)) {
    return `#${color.slice(1).split('').map((item) => item + item).join('')}`.toLowerCase()
  }
  if (/^#[0-9a-fA-F]{6}$/u.test(color)) {
    return color.toLowerCase()
  }
  return ''
}

function normalizeTagColors(values: string[] | undefined): string[] {
  if (!Array.isArray(values) || values.length !== DEFAULT_TAG_COLORS.length) {
    return [...DEFAULT_TAG_COLORS]
  }
  const colors = values.map((value) => normalizeThemeColor(value))
  return colors.every(Boolean) ? colors : [...DEFAULT_TAG_COLORS]
}

function hexToRgb(value: string): { r: number; g: number; b: number } {
  const color = normalizeThemeColor(value) || DEFAULT_THEME_PRIMARY_COLOR
  return {
    r: Number.parseInt(color.slice(1, 3), 16),
    g: Number.parseInt(color.slice(3, 5), 16),
    b: Number.parseInt(color.slice(5, 7), 16),
  }
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b].map((item) => Math.round(Math.max(0, Math.min(255, item))).toString(16).padStart(2, '0')).join('')}`
}

function mixWithWhite(value: string, amount: number): string {
  const color = hexToRgb(value)
  return rgbToHex(
    color.r + (255 - color.r) * amount,
    color.g + (255 - color.g) * amount,
    color.b + (255 - color.b) * amount,
  )
}

function rgbaFromHex(value: string, alpha: number): string {
  const color = hexToRgb(value)
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`
}

function normalizeFontFamily(value: string | undefined): string {
  return (value ?? '').replace(/[;{}]/g, '').trim()
}

function normalizeFontFamilies(values: string[] | string | undefined): string[] {
  const sourceValues = Array.isArray(values) ? values : (values ? [values] : [])
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const value of sourceValues) {
    const family = normalizeFontFamily(value)
    if (!family) continue
    const key = family.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    normalized.push(family)
  }
  return normalized
}

function normalizeFontSizePercent(value: number | string | undefined): number {
  const parsed = Number(value ?? 100)
  if (!Number.isFinite(parsed)) return 100
  return Math.max(50, Math.min(150, Math.round(parsed)))
}

function normalizeEditorImageAssetsDir(value: string | undefined): string {
  const rawValue = (value ?? './assets/').trim().replace(/\\/g, '/')
  if (!rawValue) return './assets/'
  const parts = rawValue.split('/').filter((part) => part && part !== '.' && part !== '..')
  const normalized = parts.join('/') || 'assets'
  return `./${normalized}/`
}

/** Accept only backend-managed library assets before interpolating a CSS URL. */
function normalizeBackgroundCoverUrl(value: string | undefined): string {
  const normalized = (value ?? '').trim()
  if (!normalized) return ''
  if (!normalized.startsWith('/library/assets/') || /["'()\\\r\n]/u.test(normalized) || normalized.includes('..')) return ''
  return normalized
}

function quoteFontFamily(value: string): string {
  if (value.startsWith('var(') || /^[-_a-zA-Z][-_a-zA-Z0-9]*$/u.test(value)) {
    return value
  }
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

function buildFontStack(values: string[] | undefined, fallback: string): string {
  const normalized = normalizeFontFamilies(values)
  return normalized.length > 0
    ? `${normalized.map(quoteFontFamily).join(', ')}, ${fallback}`
    : fallback
}

function normalizeProfile(profile: UserSettingsProfile): UserSettingsProfile {
  const nextProfile = {
    ...DEFAULT_PROFILE,
    ...profile,
    userId: profile.userId.trim(),
    knowledgeLibraries: profile.knowledgeLibraries ?? [],
    uiFontFamilies: normalizeFontFamilies(profile.uiFontFamilies ?? profile.uiFontFamily),
    textFontFamilies: normalizeFontFamilies(profile.textFontFamilies ?? profile.textFontFamily),
    uiFontSizePercent: normalizeFontSizePercent(profile.uiFontSizePercent ?? profile.fontSizePercent),
    textFontSizePercent: normalizeFontSizePercent(profile.textFontSizePercent ?? profile.fontSizePercent),
    themePrimaryColor: normalizeThemeColor(profile.themePrimaryColor),
    themeSoftColor: normalizeThemeColor(profile.themeSoftColor),
    tagColors: normalizeTagColors(profile.tagColors),
    tagColorsTranslucent: profile.tagColorsTranslucent !== false,
    backgroundCoverUrl: normalizeBackgroundCoverUrl(profile.backgroundCoverUrl),
    editorImageAssetsDir: normalizeEditorImageAssetsDir(profile.editorImageAssetsDir),
    knowledgeSupportedSuffixes: [...new Set(profile.knowledgeSupportedSuffixes ?? [])],
  }
  if (nextProfile.userId === 'local-user') {
    nextProfile.userId = ''
  }
  return nextProfile
}

function mapKnowledgeLibrary(library: SettingsKnowledgeLibraryResponse): KnowledgeLibraryProfile {
  return {
    libraryId: library.library_id,
    name: library.name,
    knowledgeDir: library.knowledge_dir,
    libraryStorageDir: library.library_storage_dir ?? '.mw/library',
    isActive: library.is_active,
  }
}

function mapBackendProfile(profileResponse: SettingsProfileResponse): Partial<UserSettingsProfile> {
  return {
    userId: profileResponse.user_id,
    knowledgeDir: profileResponse.knowledge_dir,
    activeLibraryId: profileResponse.active_library_id ?? '',
    knowledgeLibraries: (profileResponse.knowledge_libraries ?? []).map(mapKnowledgeLibrary),
    autoIngestOnUpload: Boolean(profileResponse.auto_ingest_on_upload),
    ocrEnabled: Boolean(profileResponse.ocr_enabled),
    vlmEnabled: Boolean(profileResponse.vlm_enabled),
    visionUnderstandingEnabled: Boolean(profileResponse.vision_understanding_enabled),
    modelAutoDownloadEnabled: Boolean(profileResponse.model_auto_download_enabled),
    dshCodingAgentEnabled: Boolean(profileResponse.dsh_coding_agent_enabled),
    knowledgeIgnorePatterns: profileResponse.knowledge_ignore_patterns ?? '',
    knowledgeSupportedSuffixes: profileResponse.knowledge_supported_suffixes ?? [],
    uiFontFamilies: profileResponse.ui_font_families ?? [],
    textFontFamilies: profileResponse.text_font_families ?? [],
    uiFontSizePercent: normalizeFontSizePercent(
      profileResponse.ui_font_size_percent ?? profileResponse.font_size_percent,
    ),
    textFontSizePercent: normalizeFontSizePercent(
      profileResponse.text_font_size_percent ?? profileResponse.font_size_percent,
    ),
    themePrimaryColor: profileResponse.theme_primary_color ?? '',
    themeSoftColor: profileResponse.theme_soft_color ?? '',
    tagColors: normalizeTagColors(profileResponse.tag_colors),
    tagColorsTranslucent: profileResponse.tag_colors_translucent !== false,
    backgroundCoverUrl: profileResponse.background_cover_url ?? '',
    showBacklinks: Boolean(profileResponse.show_backlinks),
    graphNodeLimit: profileResponse.graph_node_limit ?? 2000,
    floatingLaunchEnabled: Boolean(profileResponse.floating_launch_enabled),
    editorImageAssetsDir: profileResponse.editor_image_assets_dir ?? './assets/',
  }
}

function mapBackendWebSearchConfig(config: { proxy_url: string; web_search_enabled: boolean; web_search_max_results?: number }): Partial<UserSettingsProfile> {
  return {
    proxyUrl: config.proxy_url,
    webSearchEnabled: config.web_search_enabled,
    webSearchMaxResults: config.web_search_max_results ?? 10,
  }
}

function normalizeAgentLoopMode(mode: string | null): AgentLoopMode {
  if (mode === 'simple' || mode === 'react' || mode === 'plan') {
    return mode
  }
  if (mode === 'deep') {
    return 'plan'
  }
  return 'auto'
}

function normalizeAgentAccessMode(mode: string | null): AgentAccessMode {
  if (mode === 'readonly' || mode === 'full_access') {
    return mode
  }
  return 'sandbox'
}

function normalizeSidebarDisplayMode(mode: string | null): SidebarDisplayMode {
  return mode === 'management' ? 'management' : 'icons'
}

function normalizeFloatingPinMode(mode: string | null): 'off' | 'normal' | 'global' {
  return mode === 'off' || mode === 'global' ? mode : 'normal'
}

function loadProfile(): UserSettingsProfile {
  const raw = localStorage.getItem(PROFILE_KEY)
  if (!raw) {
    return normalizeProfile(DEFAULT_PROFILE)
  }
  try {
    return normalizeProfile({ ...DEFAULT_PROFILE, ...JSON.parse(raw) } as UserSettingsProfile)
  } catch {
    return normalizeProfile(DEFAULT_PROFILE)
  }
}

export const useSettingsStore = defineStore('settings', () => {
  /** Active theme mode persisted for the editor app. */
  const themeMode = ref<ThemeMode>((localStorage.getItem(THEME_KEY) as ThemeMode | null) ?? 'dark')

  /** Global color scheme token for CSS variable selection. */
  const colorScheme = ref('editor-default')

  /** User profile settings shared by future backend settings endpoints. */
  const profile = ref<UserSettingsProfile>(loadProfile())

  /** Chat bubble rendering mode shared by the editor Agent panel. */
  const chatMode = ref<'chat' | 'tool'>((localStorage.getItem(CHAT_MODE_KEY) as 'chat' | 'tool' | null) ?? 'tool')

  /** Agent execution loop mode shared by Agent panel and Obs graph. */
  const agentLoopMode = ref<AgentLoopMode>(normalizeAgentLoopMode(localStorage.getItem(AGENT_LOOP_MODE_KEY)))

  /** Agent filesystem and terminal permission mode for the next turn. */
  const agentAccessMode = ref<AgentAccessMode>(normalizeAgentAccessMode(localStorage.getItem(AGENT_ACCESS_MODE_KEY)))

  /** Whether to show index status column/icons in file tree and file resource manager. */
  const showIndexColumn = ref(localStorage.getItem(SHOW_INDEX_COLUMN_KEY) !== 'false')

  /** Whether to show semantic graph status column/icons in file tree and file resource manager. */
  const showGraphColumn = ref(localStorage.getItem(SHOW_GRAPH_COLUMN_KEY) !== 'false')

  /** Whether to show favorite status buttons in the file tree. */
  const showFavoriteColumn = ref(localStorage.getItem(SHOW_FAVORITE_COLUMN_KEY) !== 'false')

  /** Whether to show privacy controls in file-tree and resource-manager status columns. */
  const showPrivacyColumn = ref(localStorage.getItem(SHOW_PRIVACY_COLUMN_KEY) !== 'false')

  /** Left workspace sidebar mode: icon-only rail or wider management rail. */
  const sidebarDisplayMode = ref<SidebarDisplayMode>(normalizeSidebarDisplayMode(localStorage.getItem(SIDEBAR_DISPLAY_MODE_KEY)))

  /** Floating Agent window pin mode: off / normal (above normal apps) / global (above all). */
  const floatingPinMode = ref<'off' | 'normal' | 'global'>(normalizeFloatingPinMode(localStorage.getItem(FLOATING_PIN_MODE_KEY)))

  /** Whether the editor shell can enter workspace routes. */
  const hasUserId = computed(() => profile.value.userId.trim().length > 0)

  /** Active backend knowledge library config for the current root. */
  const activeKnowledgeLibrary = computed(() => {
    return profile.value.knowledgeLibraries.find((library) => library.libraryId === profile.value.activeLibraryId)
      ?? profile.value.knowledgeLibraries.find((library) => library.isActive)
      ?? null
  })

  const isDark = computed(() => {
    if (themeMode.value === 'system') {
      return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
    }
    return themeMode.value === 'dark'
  })

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
    document.documentElement.setAttribute('data-color-scheme', colorScheme.value)
    window.dispatchEvent(new CustomEvent(APPEARANCE_PREVIEW_EVENT))
  }

  function applyFonts() {
    document.documentElement.style.setProperty(
      '--font-scale',
      String((normalizeFontSizePercent(profile.value.uiFontSizePercent) / 100) * 1.2),
    )
    document.documentElement.style.setProperty(
      '--text-font-scale',
      String((normalizeFontSizePercent(profile.value.textFontSizePercent) / 100) * 1.56),
    )
    document.documentElement.style.setProperty(
      '--font-ui',
      buildFontStack(profile.value.uiFontFamilies, DEFAULT_UI_FONT_STACK),
    )
    document.documentElement.style.setProperty(
      '--font-text',
      buildFontStack(profile.value.textFontFamilies, DEFAULT_TEXT_FONT_STACK),
    )
  }

  function applyAppearanceColorValues(themePrimaryColor?: string, themeSoftColor?: string, tagColors?: string[], tagColorsTranslucent?: boolean) {
    const rootStyle = document.documentElement.style
    const primaryColor = normalizeThemeColor(themePrimaryColor)
    const softColor = normalizeThemeColor(themeSoftColor)
    if (primaryColor) {
      rootStyle.setProperty('--color-primary', primaryColor)
      rootStyle.setProperty('--color-primary-hover', mixWithWhite(primaryColor, 0.12))
      rootStyle.setProperty('--color-selection-blue', primaryColor)
      rootStyle.setProperty('--color-blue', primaryColor)
    } else {
      rootStyle.removeProperty('--color-primary')
      rootStyle.removeProperty('--color-primary-hover')
      rootStyle.removeProperty('--color-selection-blue')
      rootStyle.removeProperty('--color-blue')
    }
    if (softColor) {
      rootStyle.setProperty('--color-primary-soft', rgbaFromHex(softColor, 0.16))
      rootStyle.setProperty('--color-primary-softer', rgbaFromHex(softColor, 0.1))
      rootStyle.setProperty('--color-selection-blue-soft', rgbaFromHex(softColor, 0.16))
      rootStyle.setProperty('--color-user-bubble', rgbaFromHex(softColor, 0.16))
      rootStyle.setProperty('--color-user-bubble-border', rgbaFromHex(softColor, 0.46))
      rootStyle.setProperty('--color-user-bubble-glow', rgbaFromHex(softColor, 0.18))
      rootStyle.setProperty('--color-agent-bubble', rgbaFromHex(softColor, 0.12))
      rootStyle.setProperty('--color-agent-bubble-border', rgbaFromHex(softColor, 0.38))
      rootStyle.setProperty('--color-agent-bubble-glow', rgbaFromHex(softColor, 0.14))
    } else {
      rootStyle.removeProperty('--color-primary-soft')
      rootStyle.removeProperty('--color-primary-softer')
      rootStyle.removeProperty('--color-selection-blue-soft')
      rootStyle.removeProperty('--color-user-bubble')
      rootStyle.removeProperty('--color-user-bubble-border')
      rootStyle.removeProperty('--color-user-bubble-glow')
      rootStyle.removeProperty('--color-agent-bubble')
      rootStyle.removeProperty('--color-agent-bubble-border')
      rootStyle.removeProperty('--color-agent-bubble-glow')
    }
    normalizeTagColors(tagColors ?? profile.value.tagColors).forEach((color, index) => {
      rootStyle.setProperty(`--color-tag-${index + 1}`, color)
    })
    const translucent = tagColorsTranslucent ?? profile.value.tagColorsTranslucent !== false
    rootStyle.setProperty('--tag-color-library-strength', translucent ? '30%' : '100%')
    rootStyle.setProperty('--tag-color-smart-strength', translucent ? '16%' : '100%')
  }

  function applyAppearanceColors() {
    applyAppearanceColorValues(
      profile.value.themePrimaryColor,
      profile.value.themeSoftColor,
      profile.value.tagColors,
      profile.value.tagColorsTranslucent,
    )
    window.dispatchEvent(new CustomEvent(APPEARANCE_PREVIEW_EVENT))
  }

  /** Apply one persisted cover behind the application shell without local persistence. */
  function applyAppearanceBackground() {
    const url = normalizeBackgroundCoverUrl(profile.value.backgroundCoverUrl)
    if (url) {
      document.documentElement.style.setProperty('--app-background-image', `url("${url}")`)
      document.documentElement.setAttribute('data-app-background-cover', 'true')
    } else {
      document.documentElement.style.removeProperty('--app-background-image')
      document.documentElement.removeAttribute('data-app-background-cover')
    }
  }

  function previewAppearanceColors(params: { themePrimaryColor?: string; themeSoftColor?: string; tagColors?: string[]; tagColorsTranslucent?: boolean }) {
    applyAppearanceColorValues(
      params.themePrimaryColor ?? profile.value.themePrimaryColor,
      params.themeSoftColor ?? profile.value.themeSoftColor,
      params.tagColors ?? profile.value.tagColors,
      params.tagColorsTranslucent ?? profile.value.tagColorsTranslucent,
    )
    window.dispatchEvent(new CustomEvent(APPEARANCE_PREVIEW_EVENT))
  }

  function persistProfile() {
    localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...profile.value, backgroundCoverUrl: '' }))
  }

  /** Restore persisted theme and attach system color-scheme listener. */
  function initTheme() {
    applyTheme()
    applyFonts()
    applyAppearanceColors()
    applyAppearanceBackground()
    window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', applyTheme)
  }

  /** Set explicit theme mode and immediately apply CSS variables. */
  function setThemeMode(mode: ThemeMode, broadcast = true) {
    themeMode.value = mode
    localStorage.setItem(THEME_KEY, mode)
    applyTheme()
    // Keep the floating Agent window's theme in sync.
    if (broadcast) window.agentEditorDesktop?.windowSync?.('theme', mode)
  }

  /** Toggle between dark and light for the toolbar button. */
  function toggleTheme() {
    setThemeMode(isDark.value ? 'light' : 'dark')
  }

  /** Toggle between compact chat bubbles and tool-node-aware rendering. */
  /** Set the shared Agent renderer mode without creating cross-window echoes. */
  function setChatMode(mode: 'chat' | 'tool', broadcast = true) {
    chatMode.value = mode
    localStorage.setItem(CHAT_MODE_KEY, chatMode.value)
    if (broadcast) window.agentEditorDesktop?.windowSync?.('chat-mode', mode)
  }

  function toggleChatMode() {
    setChatMode(chatMode.value === 'chat' ? 'tool' : 'chat')
  }

  function setShowIndexColumn(value: boolean) {
    showIndexColumn.value = value
    localStorage.setItem(SHOW_INDEX_COLUMN_KEY, String(value))
  }

  function setShowGraphColumn(value: boolean) {
    showGraphColumn.value = value
    localStorage.setItem(SHOW_GRAPH_COLUMN_KEY, String(value))
  }

  function setShowFavoriteColumn(value: boolean) {
    showFavoriteColumn.value = value
    localStorage.setItem(SHOW_FAVORITE_COLUMN_KEY, String(value))
  }

  function setShowPrivacyColumn(value: boolean) {
    showPrivacyColumn.value = value
    localStorage.setItem(SHOW_PRIVACY_COLUMN_KEY, String(value))
  }

  function setSidebarDisplayMode(mode: SidebarDisplayMode) {
    sidebarDisplayMode.value = normalizeSidebarDisplayMode(mode)
    localStorage.setItem(SIDEBAR_DISPLAY_MODE_KEY, sidebarDisplayMode.value)
  }

  function setFloatingPinMode(mode: 'off' | 'normal' | 'global') {
    floatingPinMode.value = normalizeFloatingPinMode(mode)
    localStorage.setItem(FLOATING_PIN_MODE_KEY, floatingPinMode.value)
  }

  function setAgentLoopMode(mode: AgentLoopMode, broadcast = true) {
    agentLoopMode.value = mode
    localStorage.setItem(AGENT_LOOP_MODE_KEY, mode)
    if (broadcast) window.agentEditorDesktop?.windowSync?.('agent-loop-mode', mode)
  }

  function setAgentAccessMode(mode: AgentAccessMode, broadcast = true) {
    agentAccessMode.value = normalizeAgentAccessMode(mode)
    localStorage.setItem(AGENT_ACCESS_MODE_KEY, agentAccessMode.value)
    if (broadcast) window.agentEditorDesktop?.windowSync?.('agent-access-mode', agentAccessMode.value)
  }

  /** Update local profile values until backend settings are connected. */
  function updateProfile(nextProfile: Partial<UserSettingsProfile>) {
    profile.value = normalizeProfile({ ...profile.value, ...nextProfile })
    persistProfile()
    applyFonts()
    applyAppearanceColors()
    applyAppearanceBackground()
  }

  function setUiFontFamilies(fontFamilies: string[]) {
    updateProfile({ uiFontFamilies: fontFamilies })
  }

  function setTextFontFamilies(fontFamilies: string[]) {
    updateProfile({ textFontFamilies: fontFamilies })
  }

  function setUiFontSizePercent(value: number) {
    updateProfile({ uiFontSizePercent: normalizeFontSizePercent(value) })
  }

  function setTextFontSizePercent(value: number) {
    updateProfile({ textFontSizePercent: normalizeFontSizePercent(value) })
  }

  async function saveFontSettings(
    params: {
      uiFontFamilies?: string[]
      textFontFamilies?: string[]
      uiFontSizePercent?: number
      textFontSizePercent?: number
    },
  ) {
    const nextUiFontFamilies = params.uiFontFamilies ?? profile.value.uiFontFamilies
    const nextTextFontFamilies = params.textFontFamilies ?? profile.value.textFontFamilies
    const nextUiFontSizePercent = normalizeFontSizePercent(
      params.uiFontSizePercent ?? profile.value.uiFontSizePercent,
    )
    const nextTextFontSizePercent = normalizeFontSizePercent(
      params.textFontSizePercent ?? profile.value.textFontSizePercent,
    )
    updateProfile({
      uiFontFamilies: nextUiFontFamilies,
      textFontFamilies: nextTextFontFamilies,
      uiFontSizePercent: nextUiFontSizePercent,
      textFontSizePercent: nextTextFontSizePercent,
    })
    if (!hasUserId.value) {
      return null
    }
    try {
      const result = await saveFontConfig(profile.value.userId, {
        uiFontFamilies: nextUiFontFamilies,
        textFontFamilies: nextTextFontFamilies,
        uiFontSizePercent: nextUiFontSizePercent,
        textFontSizePercent: nextTextFontSizePercent,
      })
      updateProfile({
        uiFontFamilies: result.ui_font_families,
        textFontFamilies: result.text_font_families,
        uiFontSizePercent: result.ui_font_size_percent,
        textFontSizePercent: result.text_font_size_percent,
      })
      return result
    } catch (error) {
      if (error instanceof ApiError && error.status === 405) {
        throw new Error('保存字体设置失败: 后端尚未加载字体配置接口,请重启后端服务')
      }
      throw new Error('保存字体设置失败')
    }
  }

  async function saveAppearanceSettings(params: {
    themePrimaryColor?: string
    themeSoftColor?: string
    tagColors?: string[]
    tagColorsTranslucent?: boolean | null
    backgroundCoverUrl?: string
    showBacklinks?: boolean
  }) {
    const nextThemePrimaryColor = normalizeThemeColor(params.themePrimaryColor ?? profile.value.themePrimaryColor)
    const nextThemeSoftColor = normalizeThemeColor(params.themeSoftColor ?? profile.value.themeSoftColor)
    const resetTagColors = params.tagColors?.length === 0
    const nextTagColors = normalizeTagColors(resetTagColors ? undefined : (params.tagColors ?? profile.value.tagColors))
    const nextTagColorsTranslucent = params.tagColorsTranslucent === null
      ? true
      : (params.tagColorsTranslucent ?? profile.value.tagColorsTranslucent !== false)
    updateProfile({
      themePrimaryColor: nextThemePrimaryColor,
      themeSoftColor: nextThemeSoftColor,
      tagColors: nextTagColors,
      tagColorsTranslucent: nextTagColorsTranslucent,
      backgroundCoverUrl: params.backgroundCoverUrl ?? profile.value.backgroundCoverUrl,
      showBacklinks: params.showBacklinks ?? profile.value.showBacklinks,
    })
    if (!hasUserId.value) {
      return null
    }
    try {
      const result = await saveAppearanceConfig(profile.value.userId, {
        themePrimaryColor: nextThemePrimaryColor,
        themeSoftColor: nextThemeSoftColor,
        tagColors: params.tagColors === undefined ? undefined : (resetTagColors ? [] : nextTagColors),
        tagColorsTranslucent: params.tagColorsTranslucent,
        backgroundCoverUrl: params.backgroundCoverUrl,
        showBacklinks: params.showBacklinks,
      })
      updateProfile({
        themePrimaryColor: result.theme_primary_color,
        themeSoftColor: result.theme_soft_color,
        tagColors: result.tag_colors,
        tagColorsTranslucent: result.tag_colors_translucent,
        backgroundCoverUrl: result.background_cover_url,
        showBacklinks: result.show_backlinks,
      })
      return result
    } catch (error) {
      if (error instanceof ApiError && error.status === 405) {
        throw new Error('保存外观设置失败: 后端尚未加载外观配置接口,请重启后端服务')
      }
      throw new Error('保存外观设置失败')
    }
  }

  async function setShowBacklinks(value: boolean) {
    const previous = Boolean(profile.value.showBacklinks)
    updateProfile({ showBacklinks: value })
    try {
      return await saveAppearanceSettings({ showBacklinks: value })
    } catch (error) {
      updateProfile({ showBacklinks: previous })
      throw error
    }
  }

  /** Replace local profile fields with a backend settings response. */
  function applyBackendProfile(profileResponse: SettingsProfileResponse) {
    updateProfile(mapBackendProfile(profileResponse))
  }

  /** Set the local user id required before entering the editor shell. */
  function setUserId(userId: string) {
    updateProfile({ userId })
  }

  /** Clear the local user id and return the app to the entry gate. */
  function clearUserId() {
    updateProfile({ userId: '' })
  }

  /** Refresh the cached user profile from the backend before entering the app. */
  async function refreshUserProfile() {
    if (!hasUserId.value) {
      return null
    }
    const nextProfile = await ensureSettingsProfile(profile.value.userId)
    applyBackendProfile(nextProfile)
    return nextProfile
  }

  /** Set the active local knowledge root path shown by the editor shell. */
  function setKnowledgeDir(knowledgeDir: string) {
    updateProfile({ knowledgeDir })
  }

  /** Persist and rebuild the active backend knowledge root. */
  async function switchKnowledgeRoot(knowledgeDir: string) {
    const normalizedDir = knowledgeDir.trim()
    if (!hasUserId.value || !normalizedDir) {
      return null
    }
    const nextProfile = await updateSettingsKnowledgeDir(profile.value.userId, normalizedDir)
    applyBackendProfile(nextProfile)
    const rebuildResult = await rebuildKnowledgeRoot(profile.value.userId)
    return rebuildResult
  }

  /** Persist a display name for the active backend knowledge library. */
  async function renameActiveKnowledgeLibrary(name: string) {
    const normalizedName = name.trim()
    if (!hasUserId.value || !profile.value.knowledgeDir || !normalizedName) {
      return null
    }
    const nextProfile = await updateSettingsKnowledgeDir(
      profile.value.userId,
      profile.value.knowledgeDir,
      normalizedName,
    )
    applyBackendProfile(nextProfile)
    return nextProfile
  }

  async function fetchWebSearchSettings() {
    if (!hasUserId.value) return
    try {
      const result = await fetchWebSearchConfig(profile.value.userId)
      updateProfile(mapBackendWebSearchConfig(result))
    } catch { /* not critical */ }
  }

  async function toggleWebSearch(enabled: boolean) {
    if (!hasUserId.value) return
    const prev = { proxyUrl: profile.value.proxyUrl, webSearchEnabled: profile.value.webSearchEnabled }
    updateProfile({ webSearchEnabled: enabled })
    try {
      await saveWebSearchConfig(profile.value.userId, { webSearchEnabled: enabled })
    } catch {
      updateProfile(prev)
    }
  }

  async function saveKnowledgeIngestionSettings(params: { autoIngestOnUpload?: boolean; ocrEnabled?: boolean; visionUnderstandingEnabled?: boolean; dshCodingAgentEnabled?: boolean; knowledgeIgnorePatterns?: string }) {
    if (!hasUserId.value) {
      updateProfile({
        autoIngestOnUpload: params.autoIngestOnUpload ?? profile.value.autoIngestOnUpload,
        ocrEnabled: params.ocrEnabled ?? profile.value.ocrEnabled,
        visionUnderstandingEnabled: params.visionUnderstandingEnabled ?? profile.value.visionUnderstandingEnabled,
        dshCodingAgentEnabled: params.dshCodingAgentEnabled ?? profile.value.dshCodingAgentEnabled,
        knowledgeIgnorePatterns: params.knowledgeIgnorePatterns ?? profile.value.knowledgeIgnorePatterns,
      })
      return
    }
    const prev = {
      autoIngestOnUpload: profile.value.autoIngestOnUpload,
      ocrEnabled: profile.value.ocrEnabled,
      visionUnderstandingEnabled: profile.value.visionUnderstandingEnabled,
      dshCodingAgentEnabled: profile.value.dshCodingAgentEnabled,
      knowledgeIgnorePatterns: profile.value.knowledgeIgnorePatterns,
    }
    updateProfile({
      autoIngestOnUpload: params.autoIngestOnUpload ?? profile.value.autoIngestOnUpload,
      ocrEnabled: params.ocrEnabled ?? profile.value.ocrEnabled,
      visionUnderstandingEnabled: params.visionUnderstandingEnabled ?? profile.value.visionUnderstandingEnabled,
      dshCodingAgentEnabled: params.dshCodingAgentEnabled ?? profile.value.dshCodingAgentEnabled,
      knowledgeIgnorePatterns: params.knowledgeIgnorePatterns ?? profile.value.knowledgeIgnorePatterns,
    })
    try {
      const result = await saveKnowledgeIngestionConfig(profile.value.userId, params)
      updateProfile({
        autoIngestOnUpload: result.auto_ingest_on_upload,
        ocrEnabled: result.ocr_enabled,
        visionUnderstandingEnabled: result.vision_understanding_enabled,
        dshCodingAgentEnabled: result.dsh_coding_agent_enabled,
        knowledgeIgnorePatterns: result.knowledge_ignore_patterns,
      })
      return result
    } catch {
      updateProfile(prev)
      throw new Error('保存灌库设置失败')
    }
  }

  async function setAutoIngestOnUpload(enabled: boolean) {
    await saveKnowledgeIngestionSettings({ autoIngestOnUpload: enabled })
  }

  async function saveGraphSettings(params: { graphNodeLimit?: number }) {
    if (!hasUserId.value) {
      updateProfile({
        graphNodeLimit: params.graphNodeLimit ?? profile.value.graphNodeLimit,
      })
      return
    }
    const prev = { graphNodeLimit: profile.value.graphNodeLimit }
    updateProfile({
      graphNodeLimit: params.graphNodeLimit ?? profile.value.graphNodeLimit,
    })
    try {
      const result = await saveGraphConfig(profile.value.userId, params)
      updateProfile({ graphNodeLimit: result.graph_node_limit })
      return result
    } catch {
      updateProfile(prev)
      throw new Error('保存图谱设置失败')
    }
  }

  async function saveFloatingSettings(params: { floatingLaunchEnabled?: boolean }) {
    const nextFloatingLaunchEnabled = params.floatingLaunchEnabled ?? Boolean(profile.value.floatingLaunchEnabled)
    if (!hasUserId.value) {
      updateProfile({ floatingLaunchEnabled: nextFloatingLaunchEnabled })
      return null
    }
    const prev = { floatingLaunchEnabled: Boolean(profile.value.floatingLaunchEnabled) }
    updateProfile({ floatingLaunchEnabled: nextFloatingLaunchEnabled })
    try {
      const result = await saveFloatingConfig(profile.value.userId, {
        floatingLaunchEnabled: nextFloatingLaunchEnabled,
      })
      updateProfile({ floatingLaunchEnabled: result.floating_launch_enabled })
      return result
    } catch {
      updateProfile(prev)
      throw new Error('保存悬浮窗设置失败')
    }
  }

  async function saveEditorPasteSettings(params: { editorImageAssetsDir?: string }) {
    const nextEditorImageAssetsDir = normalizeEditorImageAssetsDir(params.editorImageAssetsDir ?? profile.value.editorImageAssetsDir)
    if (!hasUserId.value) {
      updateProfile({ editorImageAssetsDir: nextEditorImageAssetsDir })
      return null
    }
    const prev = { editorImageAssetsDir: profile.value.editorImageAssetsDir }
    updateProfile({ editorImageAssetsDir: nextEditorImageAssetsDir })
    try {
      const result = await saveEditorPasteConfig(profile.value.userId, {
        editorImageAssetsDir: nextEditorImageAssetsDir,
      })
      updateProfile({ editorImageAssetsDir: result.editor_image_assets_dir })
      return result
    } catch {
      updateProfile(prev)
      throw new Error('保存粘贴设置失败')
    }
  }

  return {
    themeMode,
    colorScheme,
    chatMode,
    agentLoopMode,
    agentAccessMode,
    sidebarDisplayMode,
    profile,
    hasUserId,
    activeKnowledgeLibrary,
    isDark,
    initTheme,
    applyFonts,
    setThemeMode,
    toggleTheme,
    toggleChatMode,
    setChatMode,
    setAgentLoopMode,
    setAgentAccessMode,
    setSidebarDisplayMode,
    floatingPinMode,
    setFloatingPinMode,
    updateProfile,
    setUiFontFamilies,
    setTextFontFamilies,
    setUiFontSizePercent,
    setTextFontSizePercent,
    saveFontSettings,
    previewAppearanceColors,
    saveAppearanceSettings,
    setShowBacklinks,
    applyBackendProfile,
    setUserId,
    clearUserId,
    refreshUserProfile,
    setKnowledgeDir,
    switchKnowledgeRoot,
    renameActiveKnowledgeLibrary,
    fetchWebSearchSettings,
    toggleWebSearch,
    saveKnowledgeIngestionSettings,
    saveGraphSettings,
    saveFloatingSettings,
    saveEditorPasteSettings,
    setAutoIngestOnUpload,
    showIndexColumn,
    setShowIndexColumn,
    showGraphColumn,
    setShowGraphColumn,
    showFavoriteColumn,
    setShowFavoriteColumn,
    showPrivacyColumn,
    setShowPrivacyColumn,
  }
})
