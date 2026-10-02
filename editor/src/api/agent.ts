/*
 * Agent streaming API.
 *
 * Usage:
 * The editor Agent panel calls streamPrompt() to consume the same backend SSE
 * chat endpoint as the console front-end.
 */

import { ApiError, apiDelete, apiGet, apiPost, apiPostForm, apiPut, buildApiUrl, streamLines } from '@/api/client'
import type { ApiRequestInit } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'
import type { MarkdownHtmlVisualizationPayload } from '@/types/knowledge'

export interface AgentStreamChunk {
  type?: string
  node?: string
  content?: string
  tool_calls?: unknown[]
  trace?: Array<Record<string, unknown>>
  metadata?: Record<string, unknown>
  context_messages?: unknown[]
  context_request?: AgentModelRequestSnapshot
  context_snapshots?: AgentModelRequestSnapshot[]
  visualization?: MarkdownHtmlVisualizationPayload
  question_request?: AgentQuestionRequest
}

/** Backend-owned synchronous question contract; the editor only holds unsent drafts. */
export interface AgentQuestion {
  id: string
  question: string
  options: string[]
  multi_select: boolean
  allow_text: boolean
}
export interface AgentQuestionAnswer {
  selected_options: string[]
  text: string
}
export interface AgentQuestionRequest {
  request_id: string
  user_id: string
  session_id: string
  run_id: string
  status: 'pending' | 'answered' | 'cancelled' | 'timed_out' | 'failed'
  questions: AgentQuestion[]
}

/** Restore active waiters after switching sessions or reopening a chat surface. */
export function fetchAgentQuestions(userId: string, sessionId: string): Promise<{ requests: AgentQuestionRequest[] }> {
  return apiGet(API_ROUTES.AGENT_QUESTIONS, { user_id: userId, session_id: sessionId })
}

/** Submit all answers in one request; success means the backend has persisted them. */
export function answerAgentQuestion(request: AgentQuestionRequest, answers: Record<string, AgentQuestionAnswer>): Promise<{ request: AgentQuestionRequest }> {
  return apiPost(`${API_ROUTES.AGENT_QUESTIONS}/${encodeURIComponent(request.request_id)}/answer`, {
    user_id: request.user_id, session_id: request.session_id, answers,
  })
}

/** Explicitly stop a waiting backend graph, including restored chats without an SSE reader. */
export function cancelAgentSession(sessionId: string): Promise<{ ok: boolean }> {
  return apiPost(API_ROUTES.AGENT_CANCEL, { session_id: sessionId })
}

/** Exact secret-free request submitted to one model call. */
export interface AgentModelRequestSnapshot {
  call_index: number
  node: string
  model_tier: string
  model: string
  temperature: number
  timeout_seconds: number
  model_kwargs: Record<string, unknown>
  messages: Array<Record<string, unknown>>
  tools: Array<Record<string, unknown>>
  context_budget?: {
    capacity_source: string
    effective_window_tokens: number
    input_budget_tokens: number
    final_input_tokens: number
    fixed_tokens: number
    remaining_tokens: number
    policy_version: string
    representations: Array<Record<string, unknown>>
  }
}

export type AgentLoopMode = 'auto' | 'simple' | 'react' | 'plan'
export type AgentAccessMode = 'readonly' | 'sandbox' | 'full_access'

export interface CurrentDocumentContextPayload {
  user_id: string
  path: string
  name: string
  knowledge_dir: string
  library_id: string
  library_name: string
  size?: number
  mtime?: string
  dirty: boolean
  open_tab_count: number
  selected_paths: string[]
}

export function streamPrompt(
  userId: string,
  sessionId: string,
  prompt: string,
  options: {
    signal?: AbortSignal
    reference?: string
    agentMode?: AgentLoopMode
    agentAccessMode?: AgentAccessMode
    attachments?: AgentAttachmentUploadResponse['attachment'][]
    messageMetadata?: Record<string, unknown>
  } = {},
): AsyncGenerator<Record<string, unknown>> {
  const body = {
    user_id: userId,
    session_id: sessionId,
    prompt,
    reference: options.reference?.trim() || undefined,
    attachments: options.attachments?.length ? options.attachments : undefined,
    message_metadata: options.messageMetadata,
    agent_mode: options.agentMode || 'auto',
    agent_access_mode: options.agentAccessMode || 'sandbox',
  }
  return streamLines(
    buildApiUrl(API_ROUTES.AGENT_STREAM),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: options.signal,
    },
  )
}

export function updateCurrentDocumentContext(payload: CurrentDocumentContextPayload): Promise<unknown> {
  return apiPut(API_ROUTES.AGENT_CURRENT_DOCUMENT_CONTEXT, payload)
}

export interface AgentAttachmentUploadResponse {
  ok: boolean
  attachment: {
    attachment_id: string
    user_id: string
    session_id: string
    library_id: string
    library_name: string
    filename: string
    stored_name: string
    uri: string
    mime_type: string
    size: number
    source_type: string
    summary?: string
    metadata?: Record<string, unknown>
    created_at: string
  }
}

export function uploadAgentAttachment(
  userId: string,
  sessionId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<AgentAttachmentUploadResponse> {
  const form = new FormData()
  form.set('user_id', userId)
  form.set('session_id', sessionId)
  form.set('file', file)
  if (!onProgress) {
    return apiPostForm<AgentAttachmentUploadResponse>(API_ROUTES.AGENT_ATTACHMENTS_UPLOAD, form, {
      timeoutMs: 600_000,
    })
  }
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', buildApiUrl(API_ROUTES.AGENT_ATTACHMENTS_UPLOAD))
    request.timeout = 600_000
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.round(event.loaded / event.total * 100))
      }
    }
    request.onerror = () => reject(new ApiError(0, '附件上传网络失败'))
    request.ontimeout = () => reject(new ApiError(0, '附件上传超时'))
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new ApiError(request.status, `附件上传失败: ${request.status}`))
        return
      }
      try {
        resolve(JSON.parse(request.responseText) as AgentAttachmentUploadResponse)
      } catch {
        reject(new ApiError(request.status, '附件上传接口返回了无效数据'))
      }
    }
    request.send(form)
  })
}

/** Fetch one attachment's backend-owned parsing progress. */
export function fetchAgentAttachment(
  userId: string,
  sessionId: string,
  attachmentId: string,
): Promise<AgentAttachmentUploadResponse> {
  return apiGet(`${API_ROUTES.AGENT_ATTACHMENTS}/${encodeURIComponent(attachmentId)}`, {
    user_id: userId,
    session_id: sessionId,
  })
}

export function deleteAgentAttachment(
  userId: string,
  sessionId: string,
  attachmentId: string,
): Promise<{ ok: boolean; deleted: boolean; attachment_id: string }> {
  return apiDelete(`${API_ROUTES.AGENT_ATTACHMENTS}/${encodeURIComponent(attachmentId)}`, {
    user_id: userId,
    session_id: sessionId,
  })
}

export interface RecallDetailsResponse {
  session_id: string
  user_id: string
  created_at: string
  query: string
  rag_metrics: Record<string, unknown>
  memory_recall: Record<string, unknown>
  knowledge_recall: Record<string, unknown>
}

export function fetchRecallDetails(sessionId: string, userId: string): Promise<RecallDetailsResponse> {
  return apiGet<RecallDetailsResponse>(API_ROUTES.AGENT_RECALL_DETAILS, { session_id: sessionId, user_id: userId })
}

export interface TaskSuggestionsResponse {
  suggestions: string[]
}

export function fetchTaskSuggestions(
  userId: string,
  sessionId: string,
  init?: ApiRequestInit,
): Promise<TaskSuggestionsResponse> {
  return apiPost<TaskSuggestionsResponse>(API_ROUTES.AGENT_TASK_SUGGESTIONS, {
    user_id: userId,
    session_id: sessionId,
  }, init)
}

export type TokenUsageInterval =
  | '1m'
  | '3m'
  | '5m'
  | '10m'
  | '30m'
  | '1h'
  | '2h'
  | '3h'
  | '6h'
  | '12h'
  | '24h'
  | '3d'
  | '10d'
  | '15d'
  | 'month'

export interface TokenUsageCall {
  token_usage_id: string
  session_id: string
  message_id: string
  node: string
  event: string
  model_tier: 'large' | 'small'
  model_name: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  created_at: string
}

export interface TokenUsageBucket {
  bucket: string
  label: string
  start_at: string
  large_tokens: number
  small_tokens: number
  total_tokens: number
  call_count: number
}

export interface TokenUsageSessionTotal {
  session_id: string
  session_name: string
  large_tokens: number
  small_tokens: number
  total_tokens: number
  call_count: number
  updated_at: string
}

export interface TokenUsageStatsResponse {
  interval: TokenUsageInterval
  calls: TokenUsageCall[]
  buckets: TokenUsageBucket[]
  sessions: TokenUsageSessionTotal[]
}

export function fetchTokenUsageStats(
  userId: string,
  options: {
    sessionId?: string | null
    interval?: TokenUsageInterval
    limit?: number
    lookbackHours?: number
    sessionSort?: 'time' | 'tokens'
  } = {},
): Promise<TokenUsageStatsResponse> {
  return apiGet<TokenUsageStatsResponse>(API_ROUTES.AGENT_TOKEN_USAGE, {
    user_id: userId,
    session_id: options.sessionId || undefined,
    interval: options.interval || '5m',
    limit: options.limit || 120,
    lookback_hours: options.lookbackHours,
    session_sort: options.sessionSort || 'time',
  })
}

export interface ChildAgentRecord {
  run_id: string
  conversation_session_id: string
  parent_run_id: string
  goal: string
  mode: 'foreground' | 'background'
  status: 'created' | 'running' | 'completed' | 'failed' | 'stopped'
  access_mode: AgentAccessMode
  allowed_tools: string[]
  result?: unknown
  summary?: string
  error?: string | null
  category?: string
  name?: string
  provider?: 'native' | 'dsh'
  workspace_root?: string
}

export interface ChildAgentListResponse {
  session_id: string
  children: ChildAgentRecord[]
}

export function fetchChildAgents(sessionId: string): Promise<ChildAgentListResponse> {
  return apiGet<ChildAgentListResponse>(API_ROUTES.AGENT_CHILDREN, { session_id: sessionId })
}

export function claimChildAgentWakeup(
  runId: string,
  userId: string,
  sessionId: string,
): Promise<{ run_id: string; claimed: boolean }> {
  return apiPost(API_ROUTES.AGENT_CHILD_WAKEUP_CLAIM(runId), {
    user_id: userId,
    session_id: sessionId,
  })
}

export function stopChildAgent(runId: string): Promise<{ run_id: string; ok: boolean }> {
  return apiPost<{ run_id: string; ok: boolean }>(`${API_ROUTES.AGENT_CHILDREN}/${encodeURIComponent(runId)}/stop`, {})
}

export function fetchChildAgentDshWeb(runId: string, userId: string, sessionId: string): Promise<{ run_id: string; url: string }> {
  return apiGet(API_ROUTES.AGENT_CHILD_DSH_WEB(runId), { user_id: userId, session_id: sessionId })
}

export function updateChildAgent(runId: string, update: Record<string, unknown>): Promise<{ run_id: string; ok: boolean }> {
  return apiPost<{ run_id: string; ok: boolean }>(`${API_ROUTES.AGENT_CHILDREN}/${encodeURIComponent(runId)}/update`, update)
}
