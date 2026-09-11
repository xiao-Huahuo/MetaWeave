/* Scanner API construction tests. */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cancelScan, createFileScan, createUrlScan, fetchScanBatchExport, listScans, saveScanToKnowledge, updateScanDraft } from '@/api/scanner'

describe('scanner API', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('constructs file and URL scan requests with task-local OCR and online snapshots', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ scan_id: 'scan-1' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await createFileScan('u1', new File(['x'], 'sample.bin'), true, true)
    const fileInit = fetchMock.mock.calls[0]?.[1]
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/scanner/files')
    expect(fileInit?.body).toBeInstanceOf(FormData)
    expect((fileInit?.body as FormData).get('ocr_enabled')).toBe('true')
    expect((fileInit?.body as FormData).get('online_enabled')).toBe('true')

    await createUrlScan('u1', 'https://example.com', false, false)
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/scanner/urls')
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ user_id: 'u1', url: 'https://example.com', ocr_enabled: false, online_enabled: false })
  })

  it('constructs draft and knowledge-save requests with explicit variants', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ scan_id: 'scan-1' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await updateScanDraft('u1', 'scan-1', 'ocr', '# text')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/scanner/scan-1/draft')
    await saveScanToKnowledge('u1', 'scan-1', 'no_ocr', 'rename')
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ user_id: 'u1', variant: 'no_ocr', conflict_strategy: 'rename' })
  })

  it('posts cancellation for only the selected scan', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ scan_id: 'scan/a', status: 'cancelled' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await cancelScan('user/1', 'scan/a')

    expect(fetchMock.mock.calls[0]?.[0]).toContain('/scanner/scan%2Fa/cancel')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: 'user/1' })
  })

  it('reads scanner capacity from the persistent list response', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ scans: [], max_concurrency: 3 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    const response = await listScans('user/1')

    expect(response.max_concurrency).toBe(3)
  })

  it('posts every selected projection and reads the single ZIP response', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('zip', {
      status: 200,
      headers: { 'Content-Type': 'application/zip', 'Content-Disposition': "attachment; filename*=UTF-8''scanner-batch.zip" },
    }))

    const result = await fetchScanBatchExport('u1', [{ scan_id: 'scan-1', variant: 'ocr' }])

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: 'u1', items: [{ scan_id: 'scan-1', variant: 'ocr' }] })
    expect(result.filename).toBe('scanner-batch.zip')
  })
})
