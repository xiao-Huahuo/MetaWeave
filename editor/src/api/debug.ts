/*
 * Runtime debug API client.
 *
 * Usage:
 * Debug pages call these endpoints to render backend-reported runtime state
 * without duplicating service addresses in front-end components.
 */

import { apiFetch, ApiError, apiGet } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

export type RuntimeApiKind = 'rest' | 'grpc'
export type RuntimeApiStatus = 'running' | 'stopped' | 'unknown'

export interface RuntimeApiInfo {
  kind: RuntimeApiKind
  name: string
  protocol: string
  service: string
  method: string
  path: string
  operation_id?: string
  tags?: string[]
  request: string
  response: string
  base_url: string
  summary: string
  description?: string
  status: RuntimeApiStatus
  parameters?: RuntimeRestParameter[]
  request_body?: RuntimeRestRequestBody
  responses?: Record<string, RuntimeRestResponse>
  request_schema_tree?: RuntimeSchemaNode | null
  response_schema_tree?: RuntimeSchemaNode[]
  call?: Record<string, string>
  client_streaming?: boolean
  server_streaming?: boolean
  input_type?: string
  output_type?: string
  input_fields?: RuntimeGrpcField[]
  output_fields?: RuntimeGrpcField[]
  input_schema_tree?: RuntimeSchemaNode
  output_schema_tree?: RuntimeSchemaNode
}

export interface RuntimeRestParameter {
  name: string
  in: string
  required?: boolean
  description?: string
  schema?: Record<string, unknown>
  schema_tree?: RuntimeSchemaNode | null
}

export interface RuntimeRestRequestBody {
  required?: boolean
  content?: Record<string, { schema?: Record<string, unknown>; schema_tree?: RuntimeSchemaNode | null }>
}

export interface RuntimeRestResponse {
  description?: string
  content?: Record<string, { schema?: Record<string, unknown>; schema_tree?: RuntimeSchemaNode | null }>
}

export interface RuntimeGrpcField {
  name: string
  number: number
  type: string
  label: string
  repeated: boolean
  message_type: string
}

export interface RuntimeSchemaNode {
  name: string
  type: string
  required: boolean
  description: string
  default?: unknown
  enum?: unknown[]
  number?: number | string
  label?: string
  children?: RuntimeSchemaNode[]
}

export interface RuntimeApiGroup {
  kind: RuntimeApiKind
  name: string
  base_url: string
}

export interface RuntimeApisResponse {
  api_count: number
  apis: RuntimeApiInfo[]
  groups: RuntimeApiGroup[]
}

export interface GlobalConstantInfo {
  name: string
  description: string
  type: string
  value: unknown
}

export interface GlobalConfigInfo {
  key: string
  name: string
  description: string
  constants: GlobalConstantInfo[]
}

export interface GlobalConstantsResponse {
  config_count: number
  constant_count: number
  configs: GlobalConfigInfo[]
}

export interface MultimodalSemanticChunk {
  index: number
  section_id: string
  heading: string
  title_path: string[]
  start_char: number
  end_char: number
  char_count: number
  content: string
}

export interface MultimodalOverlapChunk {
  index: number
  section_index: number
  section_id: string
  section_heading: string
  local_chunk_index: number
  chunk_start_char: number
  chunk_end_char: number
  char_count: number
  overlap_chars: number
  overlap_preview: string
  content: string
  ingestion_content: string
  source_range: Record<string, unknown>
}

export interface MultimodalIngestionObservation {
  path: string
  name: string
  source_size: number
  chunk_size: number
  chunk_overlap: number
  json_result: Record<string, unknown>
  markdown_result: string
  schema_version: number
  projection_hash: string
  assets: Record<string, unknown>[]
  source_map: Record<string, unknown>[]
  semantic_chunks: MultimodalSemanticChunk[]
  overlap_chunks: MultimodalOverlapChunk[]
  stats: {
    section_count: number
    overlap_chunk_count: number
    ocr_enabled: boolean
  }
}

export async function fetchRuntimeApis(): Promise<RuntimeApisResponse> {
  try {
    return await apiGet<RuntimeApisResponse>(API_ROUTES.DEBUG_RUNTIME_APIS)
  } catch (error) {
    if (shouldRetryFromBackendOrigin(error)) {
      return fetchRuntimeApisFromBackendOrigin()
    }
    throw error
  }
}

/** 读取后端动态枚举的 AgentConfig 全量只读快照。 */
export async function fetchGlobalConstants(): Promise<GlobalConstantsResponse> {
  try {
    return await apiGet<GlobalConstantsResponse>(API_ROUTES.DEBUG_GLOBAL_CONSTANTS)
  } catch (error) {
    if (shouldRetryFromBackendOrigin(error)) {
      return fetchGlobalConstantsFromBackendOrigin()
    }
    throw error
  }
}

/** 开发代理不可用时直连本地后端,与其他 debug 页面保持相同恢复策略。 */
async function fetchGlobalConstantsFromBackendOrigin(): Promise<GlobalConstantsResponse> {
  const url = `http://127.0.0.1:8002${API_ROUTES.DEBUG_GLOBAL_CONSTANTS}`
  const response = await apiFetch(url)
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`)
  }
  return readDebugJson<GlobalConstantsResponse>(response, url)
}

async function fetchRuntimeApisFromBackendOrigin(): Promise<RuntimeApisResponse> {
  const response = await apiFetch(`http://127.0.0.1:8002${API_ROUTES.DEBUG_RUNTIME_APIS}`)
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`)
  }
  return readDebugJson<RuntimeApisResponse>(response, `http://127.0.0.1:8002${API_ROUTES.DEBUG_RUNTIME_APIS}`)
}

export async function fetchMultimodalIngestionObservation(
  userId: string,
  path: string,
  signal?: AbortSignal,
): Promise<MultimodalIngestionObservation> {
  try {
    return await apiGet<MultimodalIngestionObservation>(
      API_ROUTES.DEBUG_MULTIMODAL_INGESTION,
      { user_id: userId, path },
      { signal, timeoutMs: 600_000 },
    )
  } catch (error) {
    if (shouldRetryFromBackendOrigin(error)) {
      return fetchMultimodalIngestionObservationFromBackendOrigin(userId, path, signal)
    }
    throw error
  }
}

async function fetchMultimodalIngestionObservationFromBackendOrigin(
  userId: string,
  path: string,
  signal?: AbortSignal,
): Promise<MultimodalIngestionObservation> {
  const url = new URL(`http://127.0.0.1:8002${API_ROUTES.DEBUG_MULTIMODAL_INGESTION}`)
  url.searchParams.set('user_id', userId)
  url.searchParams.set('path', path)

  const response = await apiFetch(url, { signal })
  if (!response.ok) {
    throw new Error(await readDebugError(response, `Request failed: ${response.status} ${response.statusText}`))
  }
  return readDebugJson<MultimodalIngestionObservation>(response, url.toString())
}

function shouldRetryFromBackendOrigin(error: unknown): boolean {
  /** Dev server fallback can return index.html when the API proxy is unavailable. */

  return error instanceof SyntaxError
    || (error instanceof ApiError && error.message.includes('非 JSON 响应'))
}

async function readDebugJson<T>(response: Response, url: string): Promise<T> {
  /** Parse debug fallback responses with a clear message for HTML/plain-text bodies. */

  const contentType = response.headers.get('content-type') || 'unknown'
  const body = await response.text()
  try {
    return JSON.parse(body) as T
  } catch {
    throw new Error(`接口 ${url} 返回了非 JSON 响应（Content-Type: ${contentType}）`)
  }
}

async function readDebugError(response: Response, fallback: string): Promise<string> {
  /** Extract FastAPI JSON error details from debug fallback requests. */

  try {
    const payload = await readDebugJson<{ detail?: unknown }>(response.clone(), response.url)
    if (typeof payload.detail === 'string') {
      return payload.detail
    }
  } catch {
    return fallback
  }
  return fallback
}
