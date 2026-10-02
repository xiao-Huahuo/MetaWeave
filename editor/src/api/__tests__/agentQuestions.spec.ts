/* Synchronous question API contract: exact identity, request path and typed answers are sent to the backend. */
import { afterEach, expect, it, vi } from 'vitest'
import { answerAgentQuestion, fetchAgentQuestions, type AgentQuestionRequest } from '@/api/agent'

afterEach(() => vi.unstubAllGlobals())

it('recovers questions and submits all answers to the existing run', async () => {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"requests":[],"request":{}}', { status: 200, headers: { 'Content-Type': 'application/json' } })))
  vi.stubGlobal('fetch', fetchMock)
  await fetchAgentQuestions('用户一', 'session/1')
  const url = new URL(fetchMock.mock.calls[0]![0] as string, 'http://localhost')
  expect(url.pathname).toBe('/agent/questions')
  expect(url.searchParams.get('user_id')).toBe('用户一')
  expect(url.searchParams.get('session_id')).toBe('session/1')
  const request: AgentQuestionRequest = { request_id: 'question/1', user_id: '用户一', session_id: 'session/1', run_id: 'run1', status: 'pending', questions: [] }
  const answers = { first: { selected_options: ['阅读', '整理'], text: '' }, second: { selected_options: [], text: '保持原文' } }
  await answerAgentQuestion(request, answers)
  const [answerUrl, init] = fetchMock.mock.calls[1] as [string, RequestInit]
  expect(answerUrl).toContain('/agent/questions/question%2F1/answer')
  expect(init.method).toBe('POST')
  expect(JSON.parse(String(init.body))).toEqual({ user_id: '用户一', session_id: 'session/1', answers })
})
