/*
 * Shared streaming client scheduling tests.
 *
 * Verifies that a buffered SSE burst cannot monopolize the renderer task queue.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiGet, streamLines } from '../client'

describe('streamLines scheduling', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('yields to renderer tasks while consuming one buffered SSE burst', async () => {
    const events = Array.from({ length: 18 }, (_, index) => `data: {"index":${index}}\n\n`).join('')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(events, { status: 200 })))
    const order: string[] = []
    setTimeout(() => order.push('timer'), 0)

    for await (const event of streamLines('/agent/stream')) {
      order.push(String(event.index))
    }

    expect(order.indexOf('timer')).toBeGreaterThan(0)
    expect(order.indexOf('timer')).toBeLessThan(18)
    expect(order.filter((item) => item !== 'timer')).toEqual(Array.from({ length: 18 }, (_, index) => String(index)))
  })

  it('honors cancellation while a buffered SSE burst is yielding', async () => {
    const events = Array.from({ length: 18 }, (_, index) => `data: {"index":${index}}\n\n`).join('')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(events, { status: 200 })))
    const controller = new AbortController()
    const received: number[] = []
    setTimeout(() => controller.abort(), 0)

    for await (const event of streamLines('/agent/stream', { signal: controller.signal })) {
      received.push(Number(event.index))
    }

    expect(received.length).toBeGreaterThan(0)
    expect(received.length).toBeLessThan(18)
  })

  it('releases the abort listener when the server finishes the stream', async () => {
    const controller = new AbortController()
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('data: [DONE]\n\n')))
    const stream = streamLines('/agent/stream', { signal: controller.signal })
    await expect(stream.next()).resolves.toMatchObject({ done: true })
    expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function))
  })

  it('settles cancellation when fetch has already errored its readable body', async () => {
    const abortController = new AbortController()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"content":"保留前缀"}\n\n'))
        abortController.signal.addEventListener('abort', () => {
          controller.error(new DOMException('Aborted', 'AbortError'))
        }, { once: true })
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)))
    const stream = streamLines('/agent/stream', { signal: abortController.signal })
    await expect(stream.next()).resolves.toMatchObject({ value: { content: '保留前缀' } })
    abortController.abort()
    await expect(stream.next()).resolves.toMatchObject({ done: true })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(body.locked).toBe(false)
  })

  it('uses an independent timeout signal for each management request', async () => {
    const signals: AbortSignal[] = []
    let resolveSecond: ((response: Response) => void) | undefined
    vi.stubGlobal('fetch', vi.fn((path: string, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal)
      if (path === '/slow') {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        })
      }
      return new Promise<Response>((resolve) => { resolveSecond = resolve })
    }))

    const slow = apiGet('/slow', undefined, { timeoutMs: 5 })
    const independent = apiGet('/independent', undefined, { timeoutMs: 1000 })
    await expect(slow).rejects.toEqual(expect.objectContaining<ApiError>({ status: 408 }))
    expect(signals[0]?.aborted).toBe(true)
    expect(signals[1]?.aborted).toBe(false)
    resolveSecond?.(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await expect(independent).resolves.toEqual({})
  })
})
