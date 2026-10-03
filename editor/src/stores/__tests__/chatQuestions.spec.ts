/* Synchronous question store contracts: wait timers, same-run answer transport, cancellation and history recovery. */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import type { AgentQuestionRequest } from '@/api/agent'

const request: AgentQuestionRequest = {
  request_id: 'question1', user_id: 'u1', session_id: 's1', run_id: 'r1', status: 'pending',
  questions: [{ id: 'q1', type: 'select', question: '选择处理方式', options: ['阅读', '编辑'], multi_select: false, allow_text: false }],
}
const mocks = vi.hoisted(() => ({
  stream: vi.fn(), answer: vi.fn(), cancel: vi.fn(), questions: vi.fn(), history: vi.fn(),
  session: { currentSessionId: 's1', setSessionStreaming: vi.fn(), load: vi.fn(), settleFreshSession: vi.fn() },
}))
vi.mock('@/api/agent', async importOriginal => ({ ...await importOriginal<typeof import('@/api/agent')>(),
  streamPrompt: mocks.stream, answerAgentQuestion: mocks.answer, cancelAgentSession: mocks.cancel,
  fetchAgentQuestions: mocks.questions, fetchTaskSuggestions: vi.fn().mockResolvedValue({ suggestions: [] }),
}))
vi.mock('@/api/session', async importOriginal => ({ ...await importOriginal<typeof import('@/api/session')>(), fetchMessages: mocks.history }))
vi.mock('@/stores/session', () => ({ useSessionStore: () => mocks.session }))
vi.mock('@/stores/taskList', () => ({ useTaskListStore: () => ({ load: vi.fn(), clear: vi.fn() }) }))

beforeEach(() => {
  setActivePinia(createPinia())
  mocks.answer.mockReset()
  mocks.questions.mockResolvedValue({ requests: [request] })
  mocks.history.mockResolvedValue([])
  mocks.cancel.mockResolvedValue({ ok: true })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 16))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('pauses the sliding stream timeout and returns answers without another model turn', async () => {
  let release!: () => void
  const held = new Promise<void>(resolve => { release = resolve })
  mocks.stream.mockImplementation(() => (async function* () {
    yield { type: 'user_question', node: 'user_question', question_request: request }
    await held
    yield { type: 'user_question_resolved', node: 'user_question', question_request: { ...request, status: 'answered' } }
    yield { node: 'agent', content: '已收到回答' }
  })())
  const store = useChatStore()
  const running = store.send('u1', 's1', '请先询问我')
  await vi.waitFor(() => expect(store.pendingQuestion?.request_id).toBe('question1'))
  expect(store.isStreaming).toBe(true)
  expect(store.canSend).toBe(false)
  vi.useFakeTimers()
  await vi.advanceTimersByTimeAsync(11 * 60 * 1000)
  expect(store.isStreaming).toBe(true)
  expect(store.pendingQuestion).toEqual(request)
  mocks.answer.mockImplementation(async () => { release(); return { request: { ...request, status: 'answered' } } })
  const answers = { q1: { selected_options: ['阅读'], text: '' } }
  await store.submitQuestionAnswers(answers)
  await running
  expect(mocks.answer).toHaveBeenCalledWith(request, answers)
  expect(mocks.stream).toHaveBeenCalledOnce()
  expect(store.messages.filter(message => message.role === 'user')).toHaveLength(1)
  expect(store.pendingQuestion).toBeNull()
  expect(store.isStreaming).toBe(false)
  store.clear()
})

it('restores an active question and explicitly cancels its backend waiter', async () => {
  const store = useChatStore()
  await store.loadHistory('s1', 'u1')
  await vi.waitFor(() => expect(store.pendingQuestion).toEqual(request))
  expect(store.isStreaming).toBe(false)
  store.cancelStream()
  expect(mocks.cancel).toHaveBeenCalledWith('s1')
  expect(store.pendingQuestion).toBeNull()
  store.clear()
})

it('keeps a rejected request visible and accepts a later successful retry', async () => {
  const store = useChatStore()
  store.pendingQuestions = [request]
  mocks.answer.mockRejectedValueOnce(new Error('暂时失败')).mockResolvedValueOnce({ request: { ...request, status: 'answered' } })
  const answers = { q1: { selected_options: ['编辑'], text: '' } }
  await store.submitQuestionAnswers(answers)
  expect(store.pendingQuestion).toEqual(request)
  expect(store.questionError).toBe('暂时失败')
  expect(store.questionSubmitting).toBe(false)
  await store.submitQuestionAnswers(answers)
  expect(store.pendingQuestion).toBeNull()
  expect(store.questionError).toBe('')
  store.clear()
})
