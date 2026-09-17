/*
 * Chat store reference persistence tests.
 *
 * Verifies that references saved in message metadata survive history reloads.
 */
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createPinia, setActivePinia } from 'pinia'

import { useChatStore, useSessionChatStore } from '../chat'

const apiMocks = vi.hoisted(() => ({
  fetchMessages: vi.fn(),
  streamPrompt: vi.fn(),
  fetchTaskSuggestions: vi.fn(),
  fetchChildAgents: vi.fn(),
  claimChildAgentWakeup: vi.fn(),
  deleteAgentAttachment: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  updateSessionName: vi.fn(),
  clearAllSessions: vi.fn(),
}))

vi.mock('@/api/session', () => ({
  fetchMessages: apiMocks.fetchMessages,
  listSessions: apiMocks.listSessions,
  createSession: apiMocks.createSession,
  deleteSession: apiMocks.deleteSession,
  updateSessionName: apiMocks.updateSessionName,
  clearAllSessions: apiMocks.clearAllSessions,
}))
vi.mock('@/api/agent', () => ({
  streamPrompt: apiMocks.streamPrompt,
  fetchTaskSuggestions: apiMocks.fetchTaskSuggestions,
  fetchChildAgents: apiMocks.fetchChildAgents,
  claimChildAgentWakeup: apiMocks.claimChildAgentWakeup,
  deleteAgentAttachment: apiMocks.deleteAgentAttachment,
}))

describe('chat reference history', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMocks.listSessions.mockResolvedValue([])
    apiMocks.fetchTaskSuggestions.mockResolvedValue({ suggestions: [] })
    apiMocks.claimChildAgentWakeup.mockResolvedValue({ run_id: 'child-1', claimed: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('restores a persisted user reference from message metadata', async () => {
    apiMocks.fetchMessages.mockResolvedValue([
      {
        message_id: 'message-1',
        role: 'user',
        content: '请解释这段话',
        metadata: { reference: '被引用的文档内容' },
        created_at: '2026-07-10T00:00:00Z',
      },
    ])
    const store = useChatStore()

    await store.loadHistory('session-1', 'user-1')

    expect(store.messages).toHaveLength(1)
    expect(store.messages[0]?.reference).toBe('被引用的文档内容')
  })

  it('restores persisted user attachments and their original timestamp', async () => {
    const attachment = {
      attachment_id: 'att-history', user_id: 'user-1', session_id: 'session-1',
      library_id: 'default', library_name: '默认知识库', filename: '报告.pdf', stored_name: '报告.pdf',
      uri: 'session-upload://user-1/default/session-1/报告.pdf', mime_type: 'application/pdf',
      size: 42, source_type: 'document', created_at: '2026-08-30T08:00:00Z',
    }
    apiMocks.fetchMessages.mockResolvedValue([{
      message_id: 'message-attachment', role: 'user', content: '分析附件',
      metadata: { attachments: [attachment] }, created_at: '2026-08-30T08:01:00Z',
    }])
    const store = useChatStore()

    await store.loadHistory('session-1', 'user-1')

    expect(store.messages[0]?.created_at).toBe('2026-08-30T08:01:00Z')
    expect(store.messages[0]?.attachments).toEqual([attachment])
  })

  it('sends the displayed attachment list for backend message persistence', async () => {
    const attachment = {
      attachment_id: 'att-live', user_id: 'user-1', session_id: 'session-1',
      library_id: 'default', library_name: '默认知识库', filename: '数据.csv', stored_name: '数据.csv',
      uri: 'session-upload://user-1/default/session-1/数据.csv', mime_type: 'text/csv',
      size: 12, source_type: 'document', created_at: '2026-08-30T08:00:00Z',
    }
    apiMocks.streamPrompt.mockImplementation(async function* () {})
    const store = useChatStore()
    store.addPendingAttachment(attachment)

    await store.send('user-1', 'session-1', '分析附件')

    expect(apiMocks.streamPrompt).toHaveBeenCalledWith(
      'user-1', 'session-1', '分析附件',
      expect.objectContaining({ attachments: [attachment] }),
    )
  })

  it('creates a missing session only after appending the first user bubble', async () => {
    const store = useChatStore()
    apiMocks.createSession.mockImplementation(async () => {
      expect(store.messages).toMatchObject([{ role: 'user', content: '第一条消息' }])
      return {
        session_id: 'session-first-bubble',
        user_id: 'user-1',
        session_name: '新对话',
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
      }
    })
    apiMocks.streamPrompt.mockImplementation(async function* () {})

    await store.send('user-1', null, '第一条消息')

    expect(apiMocks.createSession).toHaveBeenCalledTimes(1)
    expect(apiMocks.streamPrompt).toHaveBeenCalledWith(
      'user-1',
      'session-first-bubble',
      '第一条消息',
      expect.anything(),
    )
  })

  it('restores persisted child agent event messages with empty content', async () => {
    const childAgentEvent = {
      event_name: 'child_agent.completed',
      child: {
        run_id: 'child_run_1',
        goal: '整理资料',
        mode: 'background',
        status: 'completed',
        access_mode: 'readonly',
        allowed_tools: ['read_file'],
        summary: '完成',
      },
    }
    apiMocks.fetchMessages.mockResolvedValue([
      {
        message_id: 'message-child-agent',
        role: 'assistant',
        content: '',
        metadata: { node: 'child_agent', child_agent_event: childAgentEvent },
        created_at: '2026-08-01T00:00:00Z',
      },
    ])
    const store = useChatStore()

    await store.loadHistory('session-1', 'user-1')

    expect(store.messages).toHaveLength(1)
    expect(store.messages[0]?.node).toBe('child_agent')
    expect(store.messages[0]?.metadata?.child_agent_event).toEqual(childAgentEvent)
  })

  it('sends wakeup metadata with the automatic child completion prompt', async () => {
    const childAgentEvent = {
      event_name: 'child_agent.completed',
      child: { run_id: 'child-1', status: 'completed' },
    }
    apiMocks.streamPrompt.mockImplementation(async function* () {})
    const store = useChatStore()

    await store.send('user-1', 'session-1', '继续主任务', '', 'auto', 'sandbox', {
      wakeup: true,
      childAgentEvent,
    })

    expect(apiMocks.streamPrompt).toHaveBeenCalledWith(
      'user-1',
      'session-1',
      '继续主任务',
      expect.objectContaining({
        messageMetadata: { wakeup: true, child_agent_event: childAgentEvent },
      }),
    )
  })

  it('claims a terminal child event already rendered by the active SSE stream', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        type: 'child_agent_event',
        node: 'child_agent',
        metadata: {
          child_agent_event: {
            event_name: 'child_agent.completed',
            child: { run_id: 'child-sse-1', status: 'completed' },
          },
        },
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '并行调查')

    expect(apiMocks.claimChildAgentWakeup).toHaveBeenCalledWith('child-sse-1', 'user-1', 'session-1')
    expect(store.messages.filter((message) => message.node === 'child_agent')).toHaveLength(1)
  })

  it('loads the complete session request without dropping the first user message', async () => {
    apiMocks.fetchMessages.mockResolvedValue([
      { message_id: 'first', role: 'user', content: '第一条', metadata: {}, created_at: '2026-08-01T00:00:00Z' },
      { message_id: 'last', role: 'assistant', content: '最后一条', metadata: { node: 'agent' }, created_at: '2026-08-01T00:01:00Z' },
    ])
    const store = useChatStore()

    await store.loadHistory('session-1', 'user-1')

    expect(apiMocks.fetchMessages).toHaveBeenCalledWith('session-1', 'user-1', undefined, expect.anything())
    expect(store.messages.map((message) => message.content)).toEqual(['第一条', '最后一条'])
  })

  it('silently syncs a mounted session while preserving existing message objects', async () => {
    apiMocks.fetchMessages
      .mockResolvedValueOnce([
        { message_id: 'first', role: 'assistant', content: '处理中', metadata: { node: 'agent' }, created_at: '2026-08-01T00:00:00Z' },
      ])
      .mockResolvedValueOnce([
        { message_id: 'first', role: 'assistant', content: '处理完成', metadata: { node: 'agent' }, created_at: '2026-08-01T00:00:00Z' },
        { message_id: 'second', role: 'assistant', content: '最终回答', metadata: { node: 'agent' }, created_at: '2026-08-01T00:01:00Z' },
      ])
    const store = useChatStore()
    await store.loadHistory('session-1', 'user-1')
    const firstMessage = store.messages[0]

    await store.syncHistory('session-1', 'user-1')

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]).toBe(firstMessage)
    expect(store.messages.map((message) => message.content)).toEqual(['处理完成', '最终回答'])
  })

  it('records thinking seconds from user bubble append to first final assistant content', async () => {
    const nowSpy = vi.spyOn(performance, 'now')
    nowSpy.mockReturnValueOnce(1000).mockReturnValueOnce(2234)
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        type: 'delta',
        node: 'agent',
        content: '你好',
        metadata: {
          latency: {
            first_agent_delta_ms: 1234,
          },
        },
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '你好')

    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.thinking_seconds).toBe(1.2)
    expect(assistant?.metadata?.backend_first_delta_seconds).toBe(1.2)
    nowSpy.mockRestore()
  })

  it('does not persist changing per-token latency metadata from thinking chunks', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        type: 'thinking',
        node: 'agent',
        content: '先分析',
        metadata: { latency: { backend_elapsed_ms: 10 } },
      }
      yield {
        type: 'thinking',
        node: 'agent',
        content: '再回答',
        metadata: { latency: { backend_elapsed_ms: 20 } },
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '请思考')

    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.thinking).toBe('先分析再回答')
    expect(assistant?.metadata?.latency).toBeUndefined()
  })

  it('records how many final characters reconciled a streamed prefix', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'delta', node: 'agent', content: '开头' }
      yield {
        node: 'agent',
        content: '开头和完整结尾',
        metadata: { stream_diagnostics: { reconciled_content_chars: 0 } },
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '继续')

    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.content).toBe('开头和完整结尾')
    expect(assistant?.metadata?.frontend_stream_reconciled_chars).toBe(5)
  })

  it('commits streamed text on the next animation frame instead of a 50ms block', async () => {
    let releaseStream: (() => void) | undefined
    const streamGate = new Promise<void>((resolve) => { releaseStream = resolve })
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'delta', node: 'agent', content: '逐帧内容' }
      await streamGate
    })
    let frameCallback: FrameRequestCallback | undefined
    const frameSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frameCallback = callback
      return 1
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '继续')
    for (let index = 0; index < 12; index += 1) await Promise.resolve()
    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.content).toBe('')
    expect(frameCallback).toBeDefined()

    frameCallback?.(performance.now())
    expect(assistant?.content).toBe('逐帧内容')
    store.cancelStream()
    releaseStream?.()
    await sendPromise
    frameSpy.mockRestore()
  })

  it('accumulates streamed thinking deltas into the assistant message', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'thinking', node: 'agent', content: '先分析' }
      yield { type: 'thinking', node: 'agent', content: '调用链' }
      yield { type: 'delta', node: 'agent', content: '回答' }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '分析')

    // 流结束时 store 同步冲刷 thinking 缓冲,因此 send 返回后即可断言。
    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.thinking).toBe('先分析调用链')
    expect(assistant?.content).toBe('回答')
  })

  it('restores persisted reasoning_content into message thinking', async () => {
    apiMocks.fetchMessages.mockResolvedValue([
      {
        message_id: 'message-thinking',
        role: 'assistant',
        content: '回答',
        metadata: { node: 'agent', reasoning_content: '持久化的思考全文' },
        created_at: '2026-08-01T00:00:00Z',
      },
    ])
    const store = useChatStore()

    await store.loadHistory('session-1', 'user-1')

    expect(store.messages[0]?.thinking).toBe('持久化的思考全文')
  })

  it('tracks backend context usage and the synchronous compression lifecycle', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        type: 'compression_started',
        node: 'compress',
        metadata: {
          context_usage: { current_tokens: 160, max_context_tokens: 256, trigger_tokens: 128, target_tokens: 64 },
        },
      }
      yield {
        type: 'compression_applied',
        node: 'compress',
        metadata: {
          context_usage: { current_tokens: 60, max_context_tokens: 256, trigger_tokens: 128, target_tokens: 64 },
        },
      }
      yield { type: 'delta', node: 'agent', content: '继续回答' }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '继续')

    expect(store.compressionStatus).toBe('idle')
    expect(store.contextUsage).toEqual({
      current_tokens: 60,
      max_context_tokens: 256,
      trigger_tokens: 128,
      target_tokens: 64,
    })
  })

  it('keeps displaying the real message mirror from a backend using the legacy context protocol', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        type: 'context_mirror',
        node: 'agent',
        model_name: 'deepseek-v4-flash',
        context_messages: [
          { role: 'system', content: '最终系统提示' },
          { role: 'user', content: '你好' },
        ],
      }
      yield { type: 'delta', node: 'agent', content: '你好！' }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '你好')

    expect(store.contextSnapshots).toHaveLength(1)
    expect(store.contextSnapshots[0]?.messages).toEqual([
      { role: 'system', content: '最终系统提示' },
      { role: 'user', content: '你好' },
    ])
    expect(store.contextSnapshots[0]?.model_kwargs).toEqual({ protocol: 'legacy_context_messages' })
  })

  it('preserves the capacity source needed to retire stale 128K session meters', () => {
    const store = useChatStore()

    store.setContextUsage({
      current_tokens: 80_000,
      max_context_tokens: 120_258,
      trigger_tokens: 96_206,
      target_tokens: 54_116,
      capacity_source: 'conservative_fallback',
    })

    expect(store.contextUsage?.capacity_source).toBe('conservative_fallback')
  })

  it('refreshes follow-up suggestions after a streamed turn completes', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'delta', node: 'agent', content: '处理完成' }
    })
    apiMocks.fetchTaskSuggestions.mockResolvedValue({
      suggestions: ['检查结果', '继续优化', '解释改动'],
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '开始处理')
    await vi.waitFor(() => {
      expect(apiMocks.fetchTaskSuggestions).toHaveBeenCalledWith('user-1', 'session-1', expect.anything())
      expect(store.taskSuggestions).toEqual(['检查结果', '继续优化', '解释改动'])
    })
  })

  it('creates a running action trace from an empty model tool-calls update', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        content: '',
        tool_calls: [{ id: 'call_patch_1', name: 'patch_knowledge_file', args: { path: 'notes/a.md' } }],
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '修改文档')

    const action = store.messages.find((message) => message.node === 'action')
    expect(action?.trace).toMatchObject([{
      event: 'tool_call_start',
      tool_call_id: 'call_patch_1',
      tool_name: 'patch_knowledge_file',
    }])
  })

  it('keeps full agent content when the same event also announces tools', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        content: '我先读取目标文档。',
        tool_calls: [{ id: 'call_read_1', name: 'read_file', args: { path: 'notes/a.md' } }],
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '读取文档')

    expect(store.messages.find((message) => message.node === 'agent')?.content).toBe('我先读取目标文档。')
    expect(store.messages.find((message) => message.node === 'action')?.content).toBe('')
  })

  it('flushes streamed agent text to its owner before an action message is created', async () => {
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'delta', node: 'agent', content: '中间输出不会消失。' }
      yield {
        node: 'action',
        content: '',
        trace: [{
          event: 'tool_call_start',
          tool_call_id: 'call_fast_1',
          tool_name: 'get_current_time',
          display_name: '获取当前时间',
        }],
      }
    })
    const store = useChatStore()

    await store.send('user-1', 'session-1', '现在几点')

    expect(store.messages.find((message) => message.node === 'agent')?.content).toBe('中间输出不会消失。')
    expect(store.messages.find((message) => message.node === 'action')?.content).toBe('')
  })

  it('keeps a fast tool pending long enough to render before completing in place', async () => {
    vi.useFakeTimers()
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        content: '',
        tool_calls: [{ id: 'call_fast_2', name: 'get_current_time', args: {} }],
      }
      yield {
        node: 'action',
        content: '',
        trace: [{
          event: 'tool_call_start',
          tool_call_id: 'call_fast_2',
          tool_name: 'get_current_time',
          display_name: '获取当前时间',
        }],
      }
      yield {
        node: 'action',
        content: '',
        trace: [{
          event: 'tool_call_end',
          tool_call_id: 'call_fast_2',
          raw_content: '2026-08-15T12:00:00+08:00',
        }],
      }
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '现在几点')
    // Drain the immediately available SSE records without advancing the
    // perceptible-preview timer used by the fixed implementation.
    for (let index = 0; index < 12; index += 1) {
      await Promise.resolve()
    }

    const action = store.messages.find((message) => message.node === 'action')
    expect(action?.trace?.some((trace) => trace.event === 'tool_call_start')).toBe(true)
    expect(action?.trace?.some((trace) => trace.event === 'tool_call_end')).toBe(false)
    expect(store.isStreaming).toBe(true)

    await vi.advanceTimersByTimeAsync(500)
    expect(action?.trace?.some((trace) => trace.event === 'tool_call_end')).toBe(false)
    expect(store.isStreaming).toBe(true)

    await vi.advanceTimersByTimeAsync(350)
    await sendPromise

    expect(store.messages.find((message) => message.node === 'action')).toBe(action)
    expect(action?.trace?.some((trace) => trace.event === 'tool_call_end')).toBe(true)
    expect(action?.trace?.find((trace) => trace.event === 'tool_call_end')?.tool_name).toBe('get_current_time')
    expect(store.isStreaming).toBe(false)
  })

  it('deduplicates repeated aggregate action traces without bypassing the preview window', async () => {
    vi.useFakeTimers()
    const start = {
      event: 'tool_call_start',
      tool_call_id: 'call_aggregate',
      tool_name: 'list_knowledge_files',
      display_name: '列出文件',
    }
    const end = {
      event: 'tool_call_end',
      tool_call_id: 'call_aggregate',
      tool_name: 'list_knowledge_files',
      display_name: '列出文件',
      raw_content: '[FILE] a.md',
      result_count: 1,
    }
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        tool_calls: [{ id: 'call_aggregate', name: 'list_knowledge_files', args: {} }],
      }
      yield { node: 'action', trace: [start] }
      yield { node: 'action', trace: [end] }
      yield { node: 'action', trace: [start, end] }
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '列出文件')
    for (let index = 0; index < 16; index += 1) {
      await Promise.resolve()
    }
    const action = store.messages.find((message) => message.node === 'action')
    expect(action?.trace?.filter((trace) => trace.event === 'tool_call_end')).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(850)
    await sendPromise

    expect(action?.trace?.filter((trace) => trace.event === 'tool_call_end')).toHaveLength(1)
    expect(store.messages.filter((message) => message.node === 'action')).toHaveLength(1)
  })

  it('adopts an anonymous announcement when the provider supplies its id on start', async () => {
    vi.useFakeTimers()
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        tool_calls: [{ name: 'get_current_time', args: {} }],
      }
      yield {
        node: 'action',
        trace: [{
          event: 'tool_call_start',
          tool_call_id: 'call_late_id',
          tool_name: 'get_current_time',
          display_name: '获取当前时间',
        }],
      }
      yield {
        node: 'action',
        trace: [{
          event: 'tool_call_end',
          tool_call_id: 'call_late_id',
          tool_name: 'get_current_time',
          raw_content: '2026-08-15T12:00:00+08:00',
        }],
      }
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '现在几点')
    for (let index = 0; index < 12; index += 1) {
      await Promise.resolve()
    }
    await vi.advanceTimersByTimeAsync(850)
    await sendPromise

    const actions = store.messages.filter((message) => message.node === 'action')
    const toolTraces = actions.flatMap((message) => message.trace ?? [])
      .filter((trace) => trace.event === 'tool_call_start' || trace.event === 'tool_call_end')
    expect(actions).toHaveLength(1)
    expect(new Set(toolTraces.map((trace) => trace.tool_call_id))).toEqual(new Set(['anonymous:get_current_time:1']))
    expect(toolTraces.filter((trace) => trace.event === 'tool_call_end')).toHaveLength(1)
  })

  it('routes out-of-order tool results back to the original action message', async () => {
    vi.useFakeTimers()
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        content: '',
        tool_calls: [
          { id: 'call_a', name: 'read_file', args: { path: 'a.md' } },
          { id: 'call_b', name: 'read_file', args: { path: 'b.md' } },
        ],
      }
      yield {
        node: 'action',
        trace: [{ event: 'tool_call_end', tool_call_id: 'call_b', tool_name: 'read_file', raw_content: 'B' }],
      }
      yield { node: 'agent', content: '两个结果并发返回。' }
      yield {
        node: 'action',
        trace: [{ event: 'tool_call_end', tool_call_id: 'call_a', tool_name: 'read_file', raw_content: 'A' }],
      }
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '并发读取')
    await Promise.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(850)
    await sendPromise

    const actions = store.messages.filter((message) => message.node === 'action')
    expect(actions).toHaveLength(1)
    expect(actions[0]?.trace?.filter((trace) => trace.event === 'tool_call_end')).toMatchObject([
      { tool_call_id: 'call_b', raw_content: 'B' },
      { tool_call_id: 'call_a', raw_content: 'A' },
    ])
    expect(store.messages.find((message) => message.node === 'agent')?.content).toBe('两个结果并发返回。')
  })

  it('preserves the action toolbar and an already received result when cancelled', async () => {
    let releaseStream: (() => void) | undefined
    const streamGate = new Promise<void>((resolve) => { releaseStream = resolve })
    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield {
        node: 'agent',
        tool_calls: [{ id: 'call_cancel', name: 'get_current_time', args: {} }],
      }
      yield {
        node: 'action',
        trace: [{
          event: 'tool_call_end',
          tool_call_id: 'call_cancel',
          tool_name: 'get_current_time',
          raw_content: '2026-08-15T12:00:00+08:00',
        }],
      }
      await streamGate
    })
    const store = useChatStore()

    const sendPromise = store.send('user-1', 'session-1', '现在几点')
    for (let index = 0; index < 12; index += 1) {
      await Promise.resolve()
    }
    const action = store.messages.find((message) => message.node === 'action')
    expect(action).toBeDefined()

    store.cancelStream()
    releaseStream?.()
    await sendPromise

    expect(action?.node).toBe('action')
    expect(action?.trace?.some((trace) => trace.event === 'tool_call_end')).toBe(true)
  })

  it('mirrors live text as ordered deltas without serializing full history for every update', async () => {
    const sent: Array<{ type: string; value: unknown }> = []
    let receive: ((payload: { type: string; value: unknown }) => void) | undefined
    Object.defineProperty(window, 'agentEditorDesktop', {
      configurable: true,
      value: {
        windowSync: (type: string, value: unknown) => sent.push({ type, value }),
        onWindowSync: (callback: (payload: { type: string; value: unknown }) => void) => {
          receive = callback
          return () => undefined
        },
      } as Partial<AgentEditorDesktopApi>,
    })
    const store = useSessionChatStore('shared-session')
    const requestsBeforeMirrorProbe = sent.length
    receive?.({ type: 'chat-sync-request', value: { sessionId: 'shared-session' } })
    expect(sent).toHaveLength(requestsBeforeMirrorProbe)

    apiMocks.streamPrompt.mockImplementation(async function* () {
      yield { type: 'thinking', node: 'agent', content: '先分析' }
      yield { type: 'delta', node: 'agent', content: '最终回答' }
    })
    await store.send('user-1', 'shared-session', '开始长任务')

    const streamEvents = sent.filter((item) => item.type === 'chat-stream')
    expect(streamEvents.map((item) => item.value)).toEqual(expect.arrayContaining([
      expect.objectContaining({ sessionId: 'shared-session', field: 'thinking', delta: '先分析' }),
      expect.objectContaining({ sessionId: 'shared-session', field: 'content', delta: '最终回答' }),
    ]))
    expect(streamEvents.every((item) => (
      !('messages' in (item.value as Record<string, unknown>))
      && !('messagePatches' in (item.value as Record<string, unknown>))
    ))).toBe(true)

    const sequence = streamEvents.map((item) => Number((item.value as Record<string, unknown>).seq))
    expect(sequence).toEqual([...sequence].sort((left, right) => left - right))
    expect(new Set(sequence).size).toBe(sequence.length)

    store.$patch({ currentNode: 'planner' })
    await nextTick()
    const metaEvent = [...sent].reverse().find((item) => item.type === 'chat-meta')
    expect(metaEvent?.value).toMatchObject({ sessionId: 'shared-session', currentNode: 'planner' })
    expect('messages' in (metaEvent?.value as Record<string, unknown>)).toBe(false)

    const snapshot = [...sent].reverse().find((item) => item.type === 'chat-state')?.value as Record<string, unknown>
    receive?.({
      type: 'chat-state',
      value: {
        ...snapshot,
        sessionId: 'remote-session',
        seq: 1,
        messages: [{ role: 'assistant', content: '', node: 'agent' }],
        isStreaming: true,
      },
    })
    const remoteAppend = {
      sessionId: 'remote-session',
      seq: 2,
      index: 0,
      operation: 'append',
      field: 'content',
      delta: '只追加一次',
    }
    receive?.({ type: 'chat-stream', value: remoteAppend })
    receive?.({ type: 'chat-stream', value: remoteAppend })
    receive?.({ type: 'chat-stream', value: { ...remoteAppend, seq: 1, delta: '过期内容' } })
    expect(useSessionChatStore('remote-session').messages[0]?.content).toBe('只追加一次')

    sent.length = 0
    apiMocks.streamPrompt.mockImplementation(async function* () {
      for (let index = 0; index < 10_000; index += 1) yield { type: 'thinking', node: 'agent', content: '思' }
      for (let index = 0; index < 10_000; index += 1) yield { type: 'delta', node: 'agent', content: '答' }
    })
    const longStore = useSessionChatStore('long-session')
    await longStore.send('user-1', 'long-session', '长任务')

    const longAssistant = longStore.messages.find((message) => message.role === 'assistant')
    expect(longAssistant?.thinking).toHaveLength(10_000)
    expect(longAssistant?.content).toHaveLength(10_000)
    const longAppendEvents = sent.filter((item) => (
      item.type === 'chat-stream'
      && (item.value as Record<string, unknown>).operation === 'append'
    ))
    expect(longAppendEvents).toHaveLength(2)
    expect(JSON.stringify(longAppendEvents).length).toBeLessThan(25_000)
  })

})
