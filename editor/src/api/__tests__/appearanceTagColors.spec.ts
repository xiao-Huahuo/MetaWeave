/** Appearance tag-color API request tests. */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveAppearanceConfig } from '@/api/settings'

describe('appearance tag-color API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends complete palettes and empty reset overrides', async () => {
    const colors = ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666']
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({
      user_id: 'u1', theme_primary_color: '', theme_soft_color: '', tag_colors: colors,
      tag_colors_translucent: false, background_cover_url: '', show_backlinks: false, updated_at: '',
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await saveAppearanceConfig('u1', { tagColors: colors, tagColorsTranslucent: false })
    await saveAppearanceConfig('u1', { tagColors: [], tagColorsTranslucent: null })

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({ user_id: 'u1', tag_colors: colors, tag_colors_translucent: false })
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toMatchObject({ user_id: 'u1', tag_colors: [], tag_colors_translucent: null })
  })
})
