/** Persistent single-file knowledge ingestion job API tests. */

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelKnowledgeIngestionJob,
  createKnowledgeIngestionJobs,
  listKnowledgeIngestionJobs,
} from '@/api/knowledge'

describe('knowledge ingestion job API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('submits every selected file as one persistent batch', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{"jobs":[]}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await createKnowledgeIngestionJobs('user/1', ['notes/a.md', 'papers/b.pdf'])

    const [url, request] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/knowledge/ingestion/jobs')
    expect(JSON.parse(String(request.body))).toEqual({
      user_id: 'user/1',
      paths: ['notes/a.md', 'papers/b.pdf'],
    })
  })

  it('lists active state and encodes the cancellation job id', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{"jobs":[]}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await listKnowledgeIngestionJobs('user/1', true)
    await cancelKnowledgeIngestionJob('user/1', 'ingest/a b')

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/knowledge/ingestion/jobs?user_id=user%2F1&active_only=true')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/knowledge/ingestion/jobs/ingest%2Fa%20b/cancel')
    expect(JSON.parse(String((fetchMock.mock.calls[1]?.[1] as RequestInit).body))).toEqual({ user_id: 'user/1' })
  })

  it('preserves the submitted library and cancels by job identity after switching libraries', async () => {
    const job = { job_id: 'ingest_A', library_id: 'library_A', path: 'note.md', status: 'queued' }
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ jobs: [job] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ jobs: [
        job, { ...job, job_id: 'ingest_B', library_id: 'library_B' },
      ] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...job, status: 'cancelled' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const submitted = await createKnowledgeIngestionJobs('user/1', ['note.md'])
    const listed = await listKnowledgeIngestionJobs('user/1', true)
    expect(submitted.jobs[0]?.library_id).toBe('library_A')
    expect(listed.jobs.map((item) => item.library_id)).toEqual(['library_A', 'library_B'])
    await cancelKnowledgeIngestionJob('user/1', submitted.jobs[0]!.job_id)

    expect(fetchMock.mock.calls[2]?.[0]).toBe('/knowledge/ingestion/jobs/ingest_A/cancel')
    expect(JSON.parse(String((fetchMock.mock.calls[2]?.[1] as RequestInit).body))).toEqual({ user_id: 'user/1' })
  })
})
