/**
 * Tool-settings API client regression tests.
 *
 * Verifies that the dashboard reads effective tool state and persists the
 * non-memory disabled-tool list through the registered settings routes.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchAvailableTools, fetchDisabledTools, saveDisabledTools } from '@/api/settings'

describe('tool settings API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the registered GET routes for effective and disabled tool state', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(
      JSON.stringify({ groups: [], disabled_tools: [] }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await fetchAvailableTools('user/1')
    await fetchDisabledTools('user/1')

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/settings/tools/available?user_id=user%2F1')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/settings/tools/disabled?user_id=user%2F1')
  })

  it('persists the exact disabled non-memory tool list', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      disabled_tools: ['web_search'],
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await saveDisabledTools('u1', ['web_search'])

    const request = fetchMock.mock.calls[0]
    expect(request?.[0]).toBe('/settings/tools/disabled')
    expect(JSON.parse(String((request?.[1] as RequestInit | undefined)?.body))).toEqual({
      user_id: 'u1',
      tool_names: ['web_search'],
    })
  })
})
