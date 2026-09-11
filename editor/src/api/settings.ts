/*
 * Editor settings API.
 *
 * Usage:
 * User entry and future knowledge-root settings call these helpers instead of
 * hard-coding settings endpoint paths inside components or stores.
 */

import { apiDelete, apiGet, apiPost, apiPut, buildApiUrl, streamLines } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

export interface SettingsProfileResponse {
  user_id: string
  knowledge_dir: string
  active_library_id?: string
  active_knowledge_library?: SettingsKnowledgeLibraryResponse | null
  knowledge_libraries?: SettingsKnowledgeLibraryResponse[]
  auto_ingest_on_upload?: boolean
  ocr_enabled?: boolean
  vlm_enabled?: boolean
  vision_understanding_enabled?: boolean
  model_auto_download_enabled?: boolean
  dsh_coding_agent_enabled?: boolean
  knowledge_ignore_patterns?: string
  knowledge_supported_suffixes?: string[]
  terminal_sandbox?: TerminalSandboxConfig
  ui_font_families?: string[]
  text_font_families?: string[]
  ui_font_size_percent?: number
  text_font_size_percent?: number
  /** Legacy shared size returned by older backends. */
  font_size_percent?: number
  theme_primary_color?: string
  theme_soft_color?: string
  tag_colors?: string[]
  tag_colors_translucent?: boolean
  background_cover_url?: string
  show_backlinks?: boolean
  graph_node_limit?: number
  floating_launch_enabled?: boolean
  editor_image_assets_dir?: string
  created_at: string
  updated_at: string
}

export type TerminalShellKey = 'cmd' | 'powershell' | 'bash'

export interface TerminalSegmentInfo {
  type: string
  program: string
  usage: string
}

export interface TerminalSandboxConfig {
  enabled: boolean
  workspace_root: string
  enabled_shells: TerminalShellKey[]
  allowed_programs: Record<TerminalShellKey, string[]>
  blocked_programs: string[]
  default_timeout_seconds: number
  max_timeout_seconds: number
  max_output_chars: number
  max_segments_per_call: number
}

export interface TerminalSandboxConfigResponse {
  user_id: string
  config: TerminalSandboxConfig
  segment_catalog: Record<TerminalShellKey, TerminalSegmentInfo[]>
}

export interface SettingsKnowledgeLibraryResponse {
  library_id: string
  user_id: string
  name: string
  knowledge_dir: string
  library_storage_dir?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface KnowledgeRebuildResponse {
  user_id: string
  library_id: string
  knowledge_dir: string
  frontmatter_dir: string
  frontmatter_files_seen: number
  frontmatter_files_written: number
  frontmatter_files_skipped: number
  files_seen: number
  files_ingested: number
  files_skipped: number
  chunks_created: number
  chunks_deleted: number
  uploaded_path: string
  skip_reason?: string
  status_message?: string
}

export function ensureSettingsProfile(userId: string): Promise<SettingsProfileResponse> {
  return apiPost<SettingsProfileResponse>(API_ROUTES.SETTINGS_PROFILE, { user_id: userId })
}

export function updateSettingsKnowledgeDir(
  userId: string,
  knowledgeDir: string,
  name?: string,
): Promise<SettingsProfileResponse> {
  const body: { user_id: string; knowledge_dir: string; name?: string } = {
    user_id: userId,
    knowledge_dir: knowledgeDir,
  }
  if (name !== undefined) {
    body.name = name
  }
  return apiPut<SettingsProfileResponse>(API_ROUTES.SETTINGS_KNOWLEDGE_DIR, body)
}

export interface FontConfigResponse {
  user_id: string
  ui_font_families: string[]
  text_font_families: string[]
  ui_font_size_percent: number
  text_font_size_percent: number
  /** Legacy shared size retained for older clients. */
  font_size_percent: number
  updated_at: string
}

export function saveFontConfig(
  userId: string,
  params: {
    uiFontFamilies?: string[]
    textFontFamilies?: string[]
    uiFontSizePercent?: number
    textFontSizePercent?: number
  },
): Promise<FontConfigResponse> {
  const body: {
    user_id: string
    ui_font_families?: string[]
    text_font_families?: string[]
    ui_font_size_percent?: number
    text_font_size_percent?: number
  } = {
    user_id: userId,
  }
  if (params.uiFontFamilies !== undefined) body.ui_font_families = params.uiFontFamilies
  if (params.textFontFamilies !== undefined) body.text_font_families = params.textFontFamilies
  if (params.uiFontSizePercent !== undefined) body.ui_font_size_percent = params.uiFontSizePercent
  if (params.textFontSizePercent !== undefined) body.text_font_size_percent = params.textFontSizePercent
  return apiPut<FontConfigResponse>(API_ROUTES.SETTINGS_FONT_CONFIG, body)
}

export interface AppearanceConfigResponse {
  user_id: string
  theme_primary_color: string
  theme_soft_color: string
  tag_colors: string[]
  tag_colors_translucent: boolean
  background_cover_url: string
  show_backlinks: boolean
  updated_at: string
}

export function saveAppearanceConfig(
  userId: string,
  params: { themePrimaryColor?: string; themeSoftColor?: string; tagColors?: string[]; tagColorsTranslucent?: boolean | null; backgroundCoverUrl?: string; showBacklinks?: boolean },
): Promise<AppearanceConfigResponse> {
  const body: {
    user_id: string
    theme_primary_color?: string
    theme_soft_color?: string
    tag_colors?: string[]
    tag_colors_translucent?: boolean | null
    background_cover_url?: string
    show_backlinks?: boolean
  } = {
    user_id: userId,
  }
  if (params.themePrimaryColor !== undefined) body.theme_primary_color = params.themePrimaryColor
  if (params.themeSoftColor !== undefined) body.theme_soft_color = params.themeSoftColor
  if (params.tagColors !== undefined) body.tag_colors = params.tagColors
  if (params.tagColorsTranslucent !== undefined) body.tag_colors_translucent = params.tagColorsTranslucent
  if (params.backgroundCoverUrl !== undefined) body.background_cover_url = params.backgroundCoverUrl
  if (params.showBacklinks !== undefined) body.show_backlinks = params.showBacklinks
  return apiPut<AppearanceConfigResponse>(API_ROUTES.SETTINGS_APPEARANCE_CONFIG, body)
}

export interface EditorPasteConfigResponse {
  user_id: string
  editor_image_assets_dir: string
  updated_at: string
}

export function saveEditorPasteConfig(
  userId: string,
  params: { editorImageAssetsDir?: string },
): Promise<EditorPasteConfigResponse> {
  const body: { user_id: string; editor_image_assets_dir?: string } = { user_id: userId }
  if (params.editorImageAssetsDir !== undefined) body.editor_image_assets_dir = params.editorImageAssetsDir
  return apiPut<EditorPasteConfigResponse>(API_ROUTES.SETTINGS_EDITOR_PASTE_CONFIG, body)
}

export interface KnowledgeIngestionConfigResponse {
  auto_ingest_on_upload: boolean
  ocr_enabled: boolean
  vision_understanding_enabled: boolean
  dsh_coding_agent_enabled: boolean
  knowledge_ignore_patterns: string
  restart_required?: boolean
  ignore_cleanup?: {
    files_seen: number
    chunks_deleted: number
  }
}

/** Effective MinerU precision configuration after service defaults and user overrides are merged. */
export interface VlmConfigResponse {
  user_id: string
  enabled: boolean
  api_key: string
  configured: boolean
  base_url: string
  model: 'pipeline' | 'vlm'
  max_concurrency: number
  max_file_bytes: number
  max_pages: number
  submit_rate_per_minute: number
  result_rate_per_minute: number
  batch_max_files: number
  poll_interval_seconds: number
  timeout_seconds: number
  ocr_enabled: boolean
}

/** User-owned reusable MinerU model and limit configuration. */
export interface SavedVlmConfig {
  config_id: string
  user_id: string
  label: string
  api_key: string
  model: 'pipeline' | 'vlm'
  max_concurrency: number
  max_file_bytes: number
  max_pages: number
  submit_rate_per_minute: number
  result_rate_per_minute: number
  created_at: string
  updated_at: string
}

export function fetchVlmConfig(userId: string): Promise<VlmConfigResponse> {
  return apiGet<VlmConfigResponse>(API_ROUTES.SETTINGS_VLM_CONFIG, { user_id: userId })
}

export function saveVlmConfig(userId: string, config: Partial<Omit<VlmConfigResponse, 'user_id' | 'configured' | 'base_url' | 'batch_max_files' | 'poll_interval_seconds' | 'timeout_seconds'>>): Promise<VlmConfigResponse> {
  return apiPut<VlmConfigResponse>(API_ROUTES.SETTINGS_VLM_CONFIG, { user_id: userId, ...config })
}

export function checkVlmConnection(userId: string, apiKey?: string): Promise<{ online: boolean; authorized: boolean; message: string }> {
  return apiPost(API_ROUTES.SETTINGS_VLM_CHECK, { user_id: userId, ...(apiKey === undefined ? {} : { api_key: apiKey }) })
}

export function ensureLocalOcr(userId: string): Promise<{ ready: boolean }> {
  return apiPost(API_ROUTES.SETTINGS_VLM_LOCAL_OCR_ENSURE, { user_id: userId })
}

export function fetchSavedVlmConfigs(userId: string): Promise<{ configs: SavedVlmConfig[] }> {
  return apiGet(API_ROUTES.SETTINGS_VLM_CONFIG_SAVED, { user_id: userId })
}

export function saveVlmConfigPreset(userId: string, config: Omit<SavedVlmConfig, 'config_id' | 'user_id' | 'created_at' | 'updated_at'>): Promise<SavedVlmConfig> {
  return apiPost(API_ROUTES.SETTINGS_VLM_CONFIG_SAVED, { user_id: userId, ...config })
}

export function deleteVlmConfigPreset(configId: string, userId: string): Promise<{ ok: boolean }> {
  return apiDelete(`${API_ROUTES.SETTINGS_VLM_CONFIG_SAVED}/${encodeURIComponent(configId)}`, { user_id: userId })
}

export function fetchKnowledgeIngestionConfig(userId: string): Promise<KnowledgeIngestionConfigResponse> {
  return apiGet<KnowledgeIngestionConfigResponse>(API_ROUTES.SETTINGS_KNOWLEDGE_INGESTION, { user_id: userId })
}

export function saveKnowledgeIngestionConfig(
  userId: string,
  params: { autoIngestOnUpload?: boolean; ocrEnabled?: boolean; visionUnderstandingEnabled?: boolean; dshCodingAgentEnabled?: boolean; knowledgeIgnorePatterns?: string },
): Promise<KnowledgeIngestionConfigResponse> {
  const body: Record<string, string | boolean> = { user_id: userId }
  if (params.autoIngestOnUpload !== undefined) body.auto_ingest_on_upload = params.autoIngestOnUpload
  if ('ocrEnabled' in params && params.ocrEnabled !== undefined) body.ocr_enabled = params.ocrEnabled
  if ('visionUnderstandingEnabled' in params && params.visionUnderstandingEnabled !== undefined) {
    body.vision_understanding_enabled = params.visionUnderstandingEnabled
  }
  if ('dshCodingAgentEnabled' in params && params.dshCodingAgentEnabled !== undefined) {
    body.dsh_coding_agent_enabled = params.dshCodingAgentEnabled
  }
  if (params.knowledgeIgnorePatterns !== undefined) body.knowledge_ignore_patterns = params.knowledgeIgnorePatterns
  return apiPut<KnowledgeIngestionConfigResponse>(API_ROUTES.SETTINGS_KNOWLEDGE_INGESTION, body)
}

export interface GraphConfigResponse {
  graph_node_limit: number
}

export function saveGraphConfig(
  userId: string,
  params: { graphNodeLimit?: number },
): Promise<GraphConfigResponse> {
  const body: Record<string, string | number> = { user_id: userId }
  if (params.graphNodeLimit !== undefined) body.graph_node_limit = params.graphNodeLimit
  return apiPut<GraphConfigResponse>(API_ROUTES.SETTINGS_GRAPH_CONFIG, body)
}

export interface FloatingConfigResponse {
  user_id: string
  floating_launch_enabled: boolean
  updated_at: string
}

export function saveFloatingConfig(
  userId: string,
  params: { floatingLaunchEnabled?: boolean },
): Promise<FloatingConfigResponse> {
  const body: Record<string, string | boolean> = { user_id: userId }
  if (params.floatingLaunchEnabled !== undefined) {
    body.floating_launch_enabled = params.floatingLaunchEnabled
  }
  return apiPut<FloatingConfigResponse>(API_ROUTES.SETTINGS_FLOATING_CONFIG, body)
}

export function rebuildKnowledgeRoot(
  userId: string,
  knowledgeDir?: string,
): Promise<KnowledgeRebuildResponse> {
  const body: { user_id: string; knowledge_dir?: string } = {
    user_id: userId,
  }
  if (knowledgeDir) {
    body.knowledge_dir = knowledgeDir
  }
  return apiPost<KnowledgeRebuildResponse>(API_ROUTES.KNOWLEDGE_REBUILD, body, {
    timeoutMs: 600_000,
  })
}

export interface KnowledgeIngestionProgressEvent {
  type?: string
  phase?: 'frontmatter' | 'ingestion' | 'cleanup' | 'graph'
  status?: string
  processed?: number
  total?: number
  path?: string
  name?: string
  files_written?: number
  files_ingested?: number
  files_skipped?: number
  chunks_created?: number
  chunks_deleted?: number
  file_chunks_created?: number
  sections?: number
  result?: KnowledgeRebuildResponse
  message?: string
}

export async function rebuildKnowledgeRootStream(
  userId: string,
  onProgress: (event: KnowledgeIngestionProgressEvent) => void,
  knowledgeDir?: string,
): Promise<KnowledgeRebuildResponse> {
  const body: { user_id: string; knowledge_dir?: string } = { user_id: userId }
  if (knowledgeDir) {
    body.knowledge_dir = knowledgeDir
  }
  let finalResult: KnowledgeRebuildResponse | null = null
  for await (const event of streamLines(buildApiUrl(API_ROUTES.KNOWLEDGE_REBUILD_STREAM), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })) {
    const typed = event as KnowledgeIngestionProgressEvent
    if (typed.type === 'error') {
      throw new Error(typed.message || 'Knowledge rebuild failed')
    }
    if (typed.type === 'done' && typed.result) {
      finalResult = typed.result
    }
    onProgress(typed)
  }
  if (!finalResult) {
    throw new Error('Knowledge rebuild stream finished without a result')
  }
  return finalResult
}

/* ---- System prompts ---- */

export interface SystemPromptEntry {
  prompt_id: string
  user_id: string
  content: string
}

export function fetchSystemPrompts(userId: string): Promise<{ entries: SystemPromptEntry[] }> {
  return apiGet<{ entries: SystemPromptEntry[] }>(API_ROUTES.SETTINGS_SYSTEM_PROMPT, { user_id: userId })
}

export function addSystemPromptEntry(userId: string, content: string): Promise<SystemPromptEntry> {
  return apiPost<SystemPromptEntry>(API_ROUTES.SETTINGS_SYSTEM_PROMPT_ENTRIES, { user_id: userId, content })
}

export function deleteSystemPromptEntry(promptId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`${API_ROUTES.SETTINGS_SYSTEM_PROMPT_ENTRIES}/${promptId}`)
}

/* ---- Web search config ---- */

export interface WebSearchConfigResponse {
  user_id: string
  proxy_url: string
  browser_proxy_url: string
  browser_home_url: string
  web_search_enabled: boolean
  web_search_max_results: number
}

export function fetchWebSearchConfig(userId: string): Promise<WebSearchConfigResponse> {
  return apiGet<WebSearchConfigResponse>(API_ROUTES.SETTINGS_WEB_SEARCH, { user_id: userId })
}

export function saveWebSearchConfig(
  userId: string,
  params: {
    proxyUrl?: string
    browserProxyUrl?: string
    browserHomeUrl?: string
    webSearchEnabled?: boolean
    webSearchMaxResults?: number
  },
): Promise<WebSearchConfigResponse> {
  const body: Record<string, string | boolean | number> = { user_id: userId }
  if (params.proxyUrl !== undefined) body.proxy_url = params.proxyUrl
  if (params.browserProxyUrl !== undefined) body.browser_proxy_url = params.browserProxyUrl
  if (params.browserHomeUrl !== undefined) body.browser_home_url = params.browserHomeUrl
  if (params.webSearchEnabled !== undefined) body.web_search_enabled = params.webSearchEnabled
  if (params.webSearchMaxResults !== undefined) body.web_search_max_results = params.webSearchMaxResults
  return apiPut<WebSearchConfigResponse>(API_ROUTES.SETTINGS_WEB_SEARCH, body)
}

/* ---- Custom long-term memories ---- */

export interface MemoryEntry {
  memory_id: string
  content: string
}

export function fetchMemories(userId: string): Promise<MemoryEntry[]> {
  return apiGet<MemoryEntry[]>(API_ROUTES.SETTINGS_MEMORIES, { user_id: userId })
}

export function addMemory(userId: string, content: string, importance?: number): Promise<MemoryEntry> {
  return apiPost<MemoryEntry>(API_ROUTES.SETTINGS_MEMORIES, { user_id: userId, content, importance: importance ?? 0.5 })
}

export function deleteMemory(memoryId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`${API_ROUTES.SETTINGS_MEMORIES}/${memoryId}`)
}

export interface MemoryConfigResponse {
  long_term_memory_enabled: boolean
}

export function fetchMemoryConfig(userId: string): Promise<MemoryConfigResponse> {
  return apiGet<MemoryConfigResponse>(API_ROUTES.SETTINGS_MEMORY_CONFIG, { user_id: userId })
}

export function saveMemoryConfig(userId: string, enabled: boolean): Promise<MemoryConfigResponse> {
  return apiPut<MemoryConfigResponse>(API_ROUTES.SETTINGS_MEMORY_CONFIG, {
    user_id: userId,
    long_term_memory_enabled: enabled,
  })
}

/* ---- LLM model config ---- */

export const DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS = 1_000_000

export interface LLMConfigResponse {
  user_id: string
  api_key: string
  base_url: string
  model_name: string
  small_api_key: string
  small_base_url: string
  small_model_name: string
  model_context_window_tokens: number
  model_max_output_tokens: number
  small_model_context_window_tokens: number
  small_model_max_output_tokens: number
  effective_api_key?: string
  effective_base_url?: string
  effective_model_name?: string
  effective_model_source?: 'remote' | 'local'
  effective_small_api_key?: string
  effective_small_base_url?: string
  effective_small_model_name?: string
  effective_small_model_source?: 'remote' | 'local'
  context_window_tokens?: number
  updated_at: string
}

export function fetchLLMConfig(userId: string): Promise<LLMConfigResponse> {
  return apiGet<LLMConfigResponse>(API_ROUTES.SETTINGS_MODEL_CONFIG, { user_id: userId })
}

export function saveLLMConfig(
  userId: string,
  params: {
    apiKey?: string
    baseUrl?: string
    modelName?: string
    smallApiKey?: string
    smallBaseUrl?: string
    smallModelName?: string
    modelContextWindowTokens?: number
    modelMaxOutputTokens?: number
    smallModelContextWindowTokens?: number
    smallModelMaxOutputTokens?: number
  },
): Promise<LLMConfigResponse> {
  const body: Record<string, string | number> = { user_id: userId }
  if (params.apiKey !== undefined) body.api_key = params.apiKey
  if (params.baseUrl !== undefined) body.base_url = params.baseUrl
  if (params.modelName !== undefined) body.model_name = params.modelName
  if (params.smallApiKey !== undefined) body.small_api_key = params.smallApiKey
  if (params.smallBaseUrl !== undefined) body.small_base_url = params.smallBaseUrl
  if (params.smallModelName !== undefined) body.small_model_name = params.smallModelName
  if (params.modelContextWindowTokens !== undefined) body.model_context_window_tokens = params.modelContextWindowTokens
  if (params.modelMaxOutputTokens !== undefined) body.model_max_output_tokens = params.modelMaxOutputTokens
  if (params.smallModelContextWindowTokens !== undefined) body.small_model_context_window_tokens = params.smallModelContextWindowTokens
  if (params.smallModelMaxOutputTokens !== undefined) body.small_model_max_output_tokens = params.smallModelMaxOutputTokens
  return apiPut<LLMConfigResponse>(API_ROUTES.SETTINGS_MODEL_CONFIG, body)
}

export interface SavedLLMConfig {
  config_id: string
  user_id: string
  label: string
  api_key: string
  base_url: string
  model_name: string
  created_at: string
  updated_at: string
}

export function fetchSavedLLMConfigs(userId: string): Promise<{ configs: SavedLLMConfig[] }> {
  return apiGet<{ configs: SavedLLMConfig[] }>(API_ROUTES.SETTINGS_MODEL_CONFIG_SAVED, { user_id: userId })
}

export function saveLLMConfigPreset(
  userId: string,
  params: { label?: string; apiKey?: string; baseUrl?: string; modelName?: string },
): Promise<SavedLLMConfig> {
  const body: Record<string, string> = { user_id: userId }
  if (params.label !== undefined) body.label = params.label
  if (params.apiKey !== undefined) body.api_key = params.apiKey
  if (params.baseUrl !== undefined) body.base_url = params.baseUrl
  if (params.modelName !== undefined) body.model_name = params.modelName
  return apiPost<SavedLLMConfig>(API_ROUTES.SETTINGS_MODEL_CONFIG_SAVED, body)
}

export function deleteLLMConfigPreset(configId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`${API_ROUTES.SETTINGS_MODEL_CONFIG_SAVED}/${encodeURIComponent(configId)}`)
}

/* ---- Tool management ---- */

export interface ToolEntry {
  name: string
  display_name: string
  description: string
  enabled: boolean
}

export interface ToolGroup {
  category: string
  display_name: string
  tools: ToolEntry[]
}

export interface AvailableToolsResponse {
  groups: ToolGroup[]
}

export function fetchAvailableTools(userId: string): Promise<AvailableToolsResponse> {
  return apiGet<AvailableToolsResponse>(API_ROUTES.SETTINGS_AVAILABLE_TOOLS, { user_id: userId })
}

export interface DisabledToolsResponse {
  disabled_tools: string[]
}

/** 读取当前用户关闭的工具,供运行时新增工具合并开关状态。 */
export function fetchDisabledTools(userId: string): Promise<DisabledToolsResponse> {
  return apiGet<DisabledToolsResponse>(API_ROUTES.SETTINGS_DISABLED_TOOLS, { user_id: userId })
}

export function saveDisabledTools(userId: string, toolNames: string[]): Promise<DisabledToolsResponse> {
  return apiPut<DisabledToolsResponse>(API_ROUTES.SETTINGS_DISABLED_TOOLS, {
    user_id: userId,
    tool_names: toolNames,
  })
}

export function fetchTerminalSandboxConfig(userId: string): Promise<TerminalSandboxConfigResponse> {
  return apiGet<TerminalSandboxConfigResponse>(API_ROUTES.SETTINGS_TERMINAL_SANDBOX, { user_id: userId })
}

export function saveTerminalSandboxConfig(
  userId: string,
  config: TerminalSandboxConfig,
): Promise<TerminalSandboxConfigResponse> {
  return apiPut<TerminalSandboxConfigResponse>(API_ROUTES.SETTINGS_TERMINAL_SANDBOX, {
    user_id: userId,
    config,
  })
}

export function fetchSensitiveWords(): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(API_ROUTES.SETTINGS_SAFETY_SENSITIVE_WORDS)
}

export function saveSensitiveWords(data: Record<string, unknown>): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(API_ROUTES.SETTINGS_SAFETY_SENSITIVE_WORDS, data)
}

/* ---- 模型状态 ---- */

export interface ModelStatusResponse {
  embedding: string
  rerank: string
  paddleocr: string
  local_qwen: string
}

export function fetchModelStatus(): Promise<ModelStatusResponse> {
  return apiGet<ModelStatusResponse>(API_ROUTES.SETTINGS_MODEL_STATUS)
}

/** 磁盘级检测模型状态，返回真实状态（非内存缓存） */
export function checkModelDisk(): Promise<ModelStatusResponse> {
  return apiPost<ModelStatusResponse>(API_ROUTES.SETTINGS_MODEL_CHECK, {})
}

/** Real byte/stage progress returned by backend download workers. */
export interface ModelDownloadProgress {
  status: 'idle' | 'downloading' | 'completed' | 'error' | string
  stage: string
  downloaded_bytes: number
  total_bytes: number | null
  percent: number | null
  indeterminate: boolean
  message: string
}

/** One model row with backend-owned runtime, disk and configuration details. */
export interface ManagedModelStatus {
  key: 'embedding' | 'rerank' | 'paddleocr' | 'local_qwen'
  label: string
  role: string
  name: string
  path: string
  base_path: string
  size_bytes: number
  file_count: number
  status: string
  enabled: boolean
  active: boolean
  downloaded: boolean
  progress: ModelDownloadProgress
  details: Record<string, string>
}

/** Fetch all data displayed by the model-management block. */
export function fetchModelManagement(userId: string): Promise<{ models: ManagedModelStatus[] }> {
  return apiGet(API_ROUTES.SETTINGS_MODEL_MANAGEMENT, { user_id: userId })
}

/** Start a backend-owned model download. */
export function downloadManagedModel(
  model: ManagedModelStatus['key'],
  userId: string,
): Promise<{ status: string; model: string }> {
  return apiPost(API_ROUTES.SETTINGS_MODEL_DOWNLOAD_CONFIRMED, { model, user_id: userId })
}

/** Load an already-downloaded Embedding or ReRank model into memory. */
export function loadManagedModel(model: 'embedding' | 'rerank' | 'local_qwen'): Promise<{ status: string; model: string }> {
  return apiPost(API_ROUTES.SETTINGS_MODEL_LOAD, { model })
}

/** Trigger all post-startup model policies after the application shell is visible. */
export function initializeManagedModels(userId: string): Promise<{ status: string }> {
  return apiPost(API_ROUTES.SETTINGS_MODEL_INITIALIZE, { user_id: userId })
}

/** Fetch the persisted opt-in automatic download preference. */
export function fetchModelPreferences(userId: string): Promise<{ user_id: string; auto_download_enabled: boolean }> {
  return apiGet(API_ROUTES.SETTINGS_MODEL_PREFERENCES, { user_id: userId })
}

/** Persist the user's explicit automatic download preference. */
export function saveModelPreferences(
  userId: string,
  autoDownloadEnabled: boolean,
): Promise<{ user_id: string; auto_download_enabled: boolean }> {
  return apiPut(API_ROUTES.SETTINGS_MODEL_PREFERENCES, {
    user_id: userId,
    auto_download_enabled: autoDownloadEnabled,
  })
}

/** Delete one managed model after explicit user confirmation. */
export function deleteManagedModel(
  model: ManagedModelStatus['key'],
  userId: string,
): Promise<{ model: string; deleted: boolean; path: string }> {
  return apiPost(API_ROUTES.SETTINGS_MODEL_DELETE, { model, user_id: userId })
}
