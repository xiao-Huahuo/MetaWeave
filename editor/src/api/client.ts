/*
 * Shared authenticated HTTP client for editor API calls.
 *
 * Usage:
 * Stores import the request helpers; bearer state stays in memory and every
 * request owns its timeout/cancellation while streams own their reader lifetime.
 */

type QueryValue = string | number | boolean | undefined | null

/** App session exists only in this renderer's memory; desktop persistence belongs to safeStorage. */
let sessionToken = ''
export function setApiSessionToken(token: string): void { sessionToken = token }
export function getApiSessionToken(): string { return sessionToken }

/** Attach the current application session to JSON, binary, upload and streaming requests. */
export function applyApiAuthHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers)
  if (sessionToken && !result.has('Authorization')) result.set('Authorization', `Bearer ${sessionToken}`)
  return result
}

/** Shared fetch boundary for endpoints that return binary data or streaming bodies. */
export async function apiFetch(path: string | URL, init: RequestInit = {}): Promise<Response> {
  const apiOrigin = new URL(getApiOrigin()).origin
  const trusted = new URL(path, getApiOrigin()).origin === apiOrigin
  const headers = trusted ? applyApiAuthHeaders(init.headers) : new Headers(init.headers)
  const requestedToken = headers.get('Authorization')?.replace(/^Bearer\s+/iu, '') ?? ''
  const response = await fetch(path, { credentials: trusted ? 'include' : 'same-origin', ...init, headers })
  if (requestedToken && requestedToken !== sessionToken) throw new DOMException('Account session changed', 'AbortError')
  if (response.status === 401 && requestedToken && requestedToken === sessionToken) {
    window.dispatchEvent(new CustomEvent('metaweave:session-expired'))
  }
  return response
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function getApiOrigin(): string {
  if (window.agentEditorDesktop?.isDesktop) {
    return window.agentEditorDesktop.backendOrigin || 'http://127.0.0.1:8002'
  }
  if (import.meta.env.VITE_AGENT_API_BASE) {
    return import.meta.env.VITE_AGENT_API_BASE
  }
  if (window.location.protocol === 'file:') {
    return 'http://127.0.0.1:8002'
  }
  return window.location.origin
}

export function buildApiUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(path, getApiOrigin())
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value))
    }
  })
  return url.origin === window.location.origin ? `${url.pathname}${url.search}` : url.toString()
}

const REQUEST_TIMEOUT = 30_000

export type ApiRequestInit = RequestInit & {
  timeoutMs?: number
}

async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const requestedToken = sessionToken
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), init?.timeoutMs ?? REQUEST_TIMEOUT)
  const isFormData = init?.body instanceof FormData
  const { timeoutMs: _timeoutMs, ...fetchInit } = init ?? {}
  const signal = fetchInit.signal ? AbortSignal.any([controller.signal, fetchInit.signal]) : controller.signal
  try {
    const headers = new Headers(fetchInit.headers)
    if (!isFormData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const response = await apiFetch(path, {
      ...fetchInit,
      headers,
      signal,
    })
    if (!response.ok) {
      const detail = await readErrorDetail(response)
      throw new ApiError(response.status, `Request failed: ${response.status} ${detail || response.statusText}`)
    }
    const payload = await readJsonResponse<T>(response, path)
    if (requestedToken && requestedToken !== sessionToken) throw new DOMException('Account session changed', 'AbortError')
    return payload
  } catch (error: unknown) {
    if (controller.signal.aborted) {
      throw new ApiError(408, `接口 ${path} 请求超时`)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
}

async function readJsonResponse<T>(response: Response, path: string): Promise<T> {
  /**
   * Parse one successful API response and convert malformed/non-JSON bodies
   * into an actionable ApiError instead of leaking the browser SyntaxError.
   */

  if (response.status === 204) {
    return undefined as T
  }
  const contentType = response.headers.get('content-type') || 'unknown'
  const body = await response.text()
  try {
    return JSON.parse(body) as T
  } catch {
    throw new ApiError(
      response.status,
      `接口 ${path} 返回了非 JSON 响应（Content-Type: ${contentType}）`,
    )
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.clone().json()) as { detail?: unknown }
    if (typeof payload.detail === 'string') {
      return payload.detail
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => JSON.stringify(item)).join('; ')
    }
  } catch {
    return ''
  }
  return ''
}

export function apiGet<T>(
  path: string,
  query?: Record<string, QueryValue>,
  init?: ApiRequestInit,
): Promise<T> {
  return request<T>(buildApiUrl(path, query), init)
}

export function apiPost<T>(path: string, body?: unknown, init?: ApiRequestInit): Promise<T> {
  return request<T>(buildApiUrl(path), {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
    ...init,
  })
}

export function apiPut<T>(path: string, body?: unknown, init?: ApiRequestInit): Promise<T> {
  return request<T>(buildApiUrl(path), {
    method: 'PUT',
    body: JSON.stringify(body ?? {}),
    ...init,
  })
}

export function apiPatch<T>(path: string, body?: unknown, init?: ApiRequestInit): Promise<T> {
  return request<T>(buildApiUrl(path), {
    method: 'PATCH',
    body: JSON.stringify(body ?? {}),
    ...init,
  })
}

export function apiDelete<T>(path: string, query?: Record<string, QueryValue>, init?: ApiRequestInit): Promise<T> {
  return request<T>(buildApiUrl(path, query), {
    method: 'DELETE',
    ...init,
  })
}

export function apiPostForm<T>(path: string, body: FormData, init?: ApiRequestInit): Promise<T> {
  return request<T>(buildApiUrl(path), {
    method: 'POST',
    headers: {},
    body,
    ...init,
  })
}

/** Maximum event burst processed before the stream cooperatively yields. */
const SSE_EVENTS_PER_RENDER_TASK = 16

/** Lets timers, input events, and Vue rendering run during a buffered SSE burst. */
function yieldToRenderer(): Promise<void> {
  const scheduler = (globalThis as typeof globalThis & { scheduler?: { yield?: () => Promise<void> } }).scheduler
  if (scheduler?.yield) {
    return scheduler.yield()
  }
  return new Promise((resolve) => globalThis.setTimeout(resolve, 0))
}

export async function* streamLines(
  path: string,
  options: RequestInit = {},
): AsyncGenerator<Record<string, unknown>> {
  const requestedToken = sessionToken
  const response = await apiFetch(path, options)
  if (!response.ok) {
    throw new ApiError(response.status, 'SSE stream connection failed')
  }
  if (!response.body) {
    throw new ApiError(0, 'SSE response body is null')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventsSinceYield = 0

  const signal = options.signal
  /** Fetch may error the body before its abort listener cancels the reader. */
  const cancelReader = () => reader.cancel().catch(() => {
    // Cancellation of an already errored body rejects; the read loop owns errors.
  })
  if (signal) {
    if (signal.aborted) {
      await cancelReader()
    } else {
      signal.addEventListener('abort', cancelReader, { once: true })
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        break
      }
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''

      for (const part of parts) {
        if (signal?.aborted || (requestedToken && requestedToken !== sessionToken)) {
          return
        }
        const trimmed = part.trim()
        if (!trimmed) {
          continue
        }
        for (const line of trimmed.split('\n')) {
          if (!line.startsWith('data: ')) {
            continue
          }
          const payload = line.slice(6)
          if (payload === '[DONE]') {
            return
          }
          try {
            yield JSON.parse(payload) as Record<string, unknown>
            eventsSinceYield += 1
            if (eventsSinceYield >= SSE_EVENTS_PER_RENDER_TASK) {
              eventsSinceYield = 0
              await yieldToRenderer()
            }
          } catch {
            // Ignore malformed stream chunks and continue reading.
          }
        }
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }
    throw error
  } finally {
    signal?.removeEventListener('abort', cancelReader)
    await cancelReader()
    reader.releaseLock()
  }
}
