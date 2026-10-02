/*
 * Agent SSE 请求构造回归测试。
 *
 * 用途：确保后台子 Agent 完成唤醒所需的消息元数据会提交给后端落库，
 * 历史恢复时不会退化成普通用户气泡。
 */
import { describe, expect, it, vi } from 'vitest'

import { claimChildAgentWakeup, streamPrompt } from '@/api/agent'

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
  streamLines: vi.fn((_url: string, _init: RequestInit) => (async function* () {})()),
}))

vi.mock('@/api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/client')>(),
  apiPost: mocks.apiPost,
  buildApiUrl: (path: string) => path,
  streamLines: mocks.streamLines,
}))

describe('Agent stream API client', () => {
  it('keeps consecutive memory requests separate across conversations', () => {
    const firstCall = mocks.streamLines.mock.calls.length
    streamPrompt('memory-user', 'memory-session-1', '请记住：我偏好简洁回答。')
    streamPrompt('memory-user', 'memory-session-2', '请记住：我的研究方向是 Transformer。')

    const requests = mocks.streamLines.mock.calls.slice(firstCall)
    expect(requests.map(([url]) => url)).toEqual(['/agent/stream', '/agent/stream'])
    expect(requests.map(([, request]) => JSON.parse(String(request.body)))).toEqual([
      {
        user_id: 'memory-user', session_id: 'memory-session-1', prompt: '请记住：我偏好简洁回答。',
        agent_mode: 'auto', agent_access_mode: 'sandbox',
      },
      {
        user_id: 'memory-user', session_id: 'memory-session-2', prompt: '请记住：我的研究方向是 Transformer。',
        agent_mode: 'auto', agent_access_mode: 'sandbox',
      },
    ])
  })

  it('posts the complete investigation request to the backend tool loop', () => {
    streamPrompt('user-1', 'session-1', '调查知识库相关内容', {
      agentMode: 'plan', agentAccessMode: 'readonly',
    })

    const [url, request] = mocks.streamLines.mock.calls.at(-1)!
    expect(url).toBe('/agent/stream')
    expect(request.method).toBe('POST')
    expect(JSON.parse(String(request.body))).toEqual({
      user_id: 'user-1', session_id: 'session-1', prompt: '调查知识库相关内容',
      agent_mode: 'plan', agent_access_mode: 'readonly',
    })
  })

  it('posts child completion metadata for durable wakeup rendering', () => {
    const childAgentEvent = {
      event_name: 'child_agent.completed',
      child: { run_id: 'child-1', status: 'completed' },
    }

    streamPrompt('user-1', 'session-1', '继续主任务', {
      messageMetadata: { wakeup: true, child_agent_event: childAgentEvent },
    })

    const request = mocks.streamLines.mock.calls.at(-1)?.[1] as RequestInit
    expect(JSON.parse(String(request.body))).toMatchObject({
      message_metadata: { wakeup: true, child_agent_event: childAgentEvent },
    })
  })

  it('posts the child identity before issuing an automatic wakeup', () => {
    claimChildAgentWakeup('child/1', 'user-1', 'session-1')

    expect(mocks.apiPost).toHaveBeenCalledWith(
      '/agent/children/child%2F1/claim-wakeup',
      { user_id: 'user-1', session_id: 'session-1' },
    )
  })
})
