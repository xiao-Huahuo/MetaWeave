/* Synchronous question API contract: exact identity, request path and typed answers are sent to the backend. */
import { afterEach, expect, it, vi } from 'vitest'
import { answerAgentQuestion, fetchAgentQuestions, type AgentQuestionRequest } from '@/api/agent'

afterEach(() => vi.unstubAllGlobals())

it('recovers questions and submits all answers to the existing run', async () => {
  const request: AgentQuestionRequest = { request_id: 'question/1', user_id: '用户一', session_id: 'session/1', run_id: 'run1', status: 'pending', questions: [
    { id: 'first', type: 'select', question: '选哪些输出', options: ['阅读', '整理'], multi_select: true, allow_text: false },
    { id: 'second', type: 'input', question: '请输入角色名', options: [], multi_select: false, allow_text: true },
  ] }
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ requests: [request], request }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  vi.stubGlobal('fetch', fetchMock)
  const restored = await fetchAgentQuestions('用户一', 'session/1')
  expect(restored.requests[0]?.questions.map(question => question.type)).toEqual(['select', 'input'])
  const url = new URL(fetchMock.mock.calls[0]![0] as string, 'http://localhost')
  expect(url.pathname).toBe('/agent/questions')
  expect(url.searchParams.get('user_id')).toBe('用户一')
  expect(url.searchParams.get('session_id')).toBe('session/1')
  const answers = { first: { selected_options: ['阅读', '整理'], text: '' }, second: { selected_options: [], text: '芙宁娜' } }
  await answerAgentQuestion(request, answers)
  const [answerUrl, init] = fetchMock.mock.calls[1] as [string, RequestInit]
  expect(answerUrl).toContain('/agent/questions/question%2F1/answer')
  expect(init.method).toBe('POST')
  expect(JSON.parse(String(init.body))).toEqual({ user_id: '用户一', session_id: 'session/1', answers })
})
