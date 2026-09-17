/*
 * 会话导出子 Agent 事件回归测试。
 *
 * 用途：验证导出 YAML 的结构化消息中保留 `child_agent_event`，
 * 这样导出的会话再导入后能恢复子 Agent 事件条。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { exportSession } from '@/utils/sessionExport'

const mocks = vi.hoisted(() => ({
  fetchMessages: vi.fn(),
  fetchSessionState: vi.fn(),
  fetchSessionTaskList: vi.fn(),
  fetchChildAgents: vi.fn(),
  toYaml: vi.fn(),
}))

vi.mock('@/api/session', () => ({
  fetchMessages: mocks.fetchMessages,
  fetchSessionState: mocks.fetchSessionState,
}))

vi.mock('@/api/agent', () => ({
  fetchChildAgents: mocks.fetchChildAgents,
}))

vi.mock('@/api/taskList', () => ({
  fetchSessionTaskList: mocks.fetchSessionTaskList,
}))

vi.mock('@/utils/yamlExport', () => ({
  toYaml: mocks.toYaml,
}))

describe('sessionExport child agent events', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.fetchSessionTaskList.mockResolvedValue({ task_list: null })
    mocks.fetchSessionState.mockResolvedValue({ session_state: null })
    mocks.fetchChildAgents.mockResolvedValue({ children: [] })
    mocks.toYaml.mockReturnValue('session: test')
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  it('keeps child_agent_event in exported messages', async () => {
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
    mocks.fetchMessages.mockResolvedValue([
      {
        message_id: 'message-child',
        session_id: 'session-1',
        role: 'assistant',
        content: '子 Agent child_run_1 完成任务: 整理资料',
        created_at: '2026-08-01T00:00:00Z',
        metadata: { node: 'child_agent', child_agent_event: childAgentEvent },
        tool_calls: [],
      },
    ])

    await exportSession({
      session_id: 'session-1',
      user_id: 'user-1',
      session_name: '子 Agent 会话',
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:01:00Z',
    }, 'user-1')

    expect(mocks.toYaml).toHaveBeenCalledOnce()
    expect(mocks.toYaml.mock.calls[0]?.[0].messages[0].child_agent_event).toEqual(childAgentEvent)
  })

  it('preserves full metadata and tool lifecycle fields for round-trip import', async () => {
    mocks.fetchMessages.mockResolvedValue([{
      message_id: 'message-tool', session_id: 'session-1', role: 'assistant', content: '', created_at: '2026-08-01T00:00:00Z',
      tool_call_id: 'call_1',
      tool_calls: [{ id: 'call_1', name: 'patch_knowledge_file', args: { path: 'a.md' } }],
      metadata: { node: 'action', trace: [{ event: 'tool_call_start', tool_call_id: 'call_1', patch: { path: 'a.md' } }] },
    }])

    await exportSession({ session_id: 'session-1', user_id: 'user-1', session_name: '测试', created_at: '', updated_at: '' }, 'user-1')

    const message = mocks.toYaml.mock.calls[0]?.[0].messages[0]
    expect(message.tool_calls[0].id).toBe('call_1')
    expect(message.tool_call_id).toBe('call_1')
    expect(message.metadata.trace[0].patch.path).toBe('a.md')
  })

  it('exports user attachment metadata with the original message time', async () => {
    const attachment = {
      attachment_id: 'att-1', user_id: 'user-1', session_id: 'session-1',
      library_id: 'default', library_name: '默认知识库', filename: '报告.pdf', stored_name: '报告.pdf',
      uri: 'session-upload://user-1/default/session-1/报告.pdf', mime_type: 'application/pdf',
      size: 42, source_type: 'document', created_at: '2026-08-30T08:00:00Z',
    }
    mocks.fetchMessages.mockResolvedValue([{
      message_id: 'message-user', session_id: 'session-1', role: 'user', content: '分析附件',
      created_at: '2026-08-30T08:01:00Z', metadata: { attachments: [attachment] }, tool_calls: [],
    }])

    await exportSession({ session_id: 'session-1', user_id: 'user-1', session_name: '测试', created_at: '', updated_at: '' }, 'user-1')

    const message = mocks.toYaml.mock.calls[0]?.[0].messages[0]
    expect(message.created_at).toBe('2026-08-30T08:01:00Z')
    expect(message.attachments).toEqual([attachment])
  })

  it('exports the recoverable environment, task list, and child-agent snapshots', async () => {
    mocks.fetchMessages
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{
        message_id: 'child-message', session_id: 'child-session-1', role: 'assistant', content: '完整子对话',
        created_at: '2026-08-30T08:02:00Z', metadata: { node: 'agent' }, tool_calls: [],
      }])
    mocks.fetchSessionTaskList.mockResolvedValue({ task_list: { task_list_id: 'tasks-1', items: [] } })
    mocks.fetchSessionState.mockResolvedValue({
      session_state: {
        environment: { branch: 'main', commit: 'abc', commit_time: '2026-08-13T00:00:00Z' },
        change_snapshot: { snapshot_id: 'change-1', additions: 3, deletions: 1, files: [], edits: [] },
      },
    })
    mocks.fetchChildAgents.mockResolvedValue({
      children: [{ run_id: 'child-1', conversation_session_id: 'child-session-1', status: 'completed' }],
    })

    await exportSession({ session_id: 'session-1', user_id: 'user-1', session_name: '测试', created_at: '', updated_at: '' }, 'user-1')

    const exported = mocks.toYaml.mock.calls[0]?.[0]
    expect(exported.task_list.task_list_id).toBe('tasks-1')
    expect(exported.session_state.environment.branch).toBe('main')
    expect(exported.session_state.change_snapshot.snapshot_id).toBe('change-1')
    expect(exported.child_agents[0].run_id).toBe('child-1')
    expect(exported.child_agents[0].messages[0].content).toBe('完整子对话')
    expect(mocks.fetchMessages).toHaveBeenNthCalledWith(2, 'child-session-1', 'user-1', undefined)
  })

  it('keeps reasoning_content in exported messages for round-trip import', async () => {
    mocks.fetchMessages.mockResolvedValue([{
      message_id: 'message-think', session_id: 'session-1', role: 'assistant', content: '回答',
      created_at: '2026-08-30T08:00:00Z',
      metadata: { node: 'agent', reasoning_content: '导出的思考全文' },
      tool_calls: [],
    }])

    await exportSession({ session_id: 'session-1', user_id: 'user-1', session_name: '测试', created_at: '', updated_at: '' }, 'user-1')

    const message = mocks.toYaml.mock.calls[0]?.[0].messages[0]
    expect(message.metadata.reasoning_content).toBe('导出的思考全文')
  })
})
