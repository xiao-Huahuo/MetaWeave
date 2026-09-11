/* Knowledge ingestion, OCR, and image-understanding API request tests. */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { checkVlmConnection, deleteVlmConfigPreset, ensureLocalOcr, fetchSavedVlmConfigs, saveKnowledgeIngestionConfig, saveVlmConfig, saveVlmConfigPreset } from '@/api/settings'

describe('knowledge ingestion settings API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('persists the explicit image-understanding switch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await saveKnowledgeIngestionConfig('u1', {
      visionUnderstandingEnabled: true,
      dshCodingAgentEnabled: true,
    })

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/settings/profile/ingestion')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      user_id: 'u1',
      vision_understanding_enabled: true,
      dsh_coding_agent_enabled: true,
    })
  })

  it('constructs persisted MinerU settings and readiness requests', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{"enabled":true}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await saveVlmConfig('u1', { enabled: true, model: 'vlm', max_pages: 600 })
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: 'u1', enabled: true, model: 'vlm', max_pages: 600 })
    await checkVlmConnection('u1')
    await ensureLocalOcr('u1')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/settings/vlm/check')
    expect(fetchMock.mock.calls[2]?.[0]).toBe('/settings/vlm/local-ocr/ensure')
  })

  it('constructs VLM preset list, save, and delete requests', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{"configs":[]}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchSavedVlmConfigs('u1')
    await saveVlmConfigPreset('u1', {
      label: 'MinerU 精准', api_key: 'secret', model: 'vlm', max_concurrency: 2,
      max_file_bytes: 209715200, max_pages: 600, submit_rate_per_minute: 300, result_rate_per_minute: 1000,
    })
    await deleteVlmConfigPreset('vlm-preset-1', 'u1')

    expect(fetchMock.mock.calls[0]?.[0]).toContain('/settings/vlm/config/saved')
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body)).label).toBe('MinerU 精准')
    expect(fetchMock.mock.calls[2]?.[0]).toContain('/settings/vlm/config/saved/vlm-preset-1')
  })
})
