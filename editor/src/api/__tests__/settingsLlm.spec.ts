/** LLM text/vision model settings API request tests. */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveLLMConfig } from '@/api/settings'

describe('LLM settings API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('persists explicit text capacities and visual-model overrides', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ user_id: 'u1', updated_at: '2026-08-31T00:00:00Z' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await saveLLMConfig('u1', {
      modelContextWindowTokens: 1_000_000,
      modelMaxOutputTokens: 65_536,
      smallModelContextWindowTokens: 131_072,
      smallModelMaxOutputTokens: 8_192,
      visionModelName: 'deepseek-flash',
      visionBaseUrl: 'https://api.deepseek.com/v1',
      visionApiKey: 'vision-key',
    })

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/settings/llm/config')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
      user_id: 'u1',
      model_context_window_tokens: 1_000_000,
      model_max_output_tokens: 65_536,
      small_model_context_window_tokens: 131_072,
      small_model_max_output_tokens: 8_192,
      vision_model_name: 'deepseek-flash',
      vision_base_url: 'https://api.deepseek.com/v1',
      vision_api_key: 'vision-key',
    })
  })
})
