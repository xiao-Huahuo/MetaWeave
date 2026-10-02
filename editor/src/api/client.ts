/*
 * HTTP client helper for planned editor API calls.
 *
 * Usage:
 * Stores should import apiGet/apiPost/apiPut/apiPatch/apiDelete once the
 * backend endpoints are connected. The current mock UI does not call them yet.
 */

type QueryValue = string | number | boolean | undefined | null

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function getApiOrigin(): string {
  if (import.meta.env.VITE_AGENT_API_BASE) {
    return import.meta.env.VITE_AGENT_API_BASE
  }
  if (window.agentEditorDesktop?.isDesktop) {
    return 'http://127.0.0.1:8002'
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
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), init?.timeoutMs ?? REQUEST_TIMEOUT)
  const isFormData = init?.body instanceof FormData
  const { timeoutMs: _timeoutMs, ...fetchInit } = init ?? {}
  try {
    const response = await fetch(path, {
      ...fetchInit,
      headers: isFormData
        ? fetchInit.headers
        : {
            'Content-Type': 'application/json',
            ...fetchInit.headers,
          },
      signal: controller.signal,
    })
    if (!response.ok) {
      const detail = await readErrorDetail(response)
      throw new ApiError(response.status, `Request failed: ${response.status} ${detail || response.statusText}`)
    }
    return await readJsonResponse<T>(response, path)
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
  const response = await fetch(path, options)
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
        if (signal?.aborted) {
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
    reader.releaseLock()
  }
}
