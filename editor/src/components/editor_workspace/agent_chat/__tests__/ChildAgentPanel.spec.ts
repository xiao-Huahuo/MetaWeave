/*
 * 子 Agent 面板详情链接回归测试。
 *
 * 用途：验证普通子 Agent 名字打开完整对话、DSH 打开现有浏览器侧栏，
 * 并在主历史恢复时并发预载全部子 Session。
 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import ChildAgentPanel from '../ChildAgentPanel.vue'
import { useWorkspaceStore } from '@/stores/workspace'

enableAutoUnmount(afterEach)

const mocks = vi.hoisted(() => ({
  fetchChildAgents: vi.fn(),
  fetchChildAgentDshWeb: vi.fn(),
  preload: vi.fn(),
}))

vi.mock('@/api/agent', () => ({
  fetchChildAgents: mocks.fetchChildAgents,
  fetchChildAgentDshWeb: mocks.fetchChildAgentDshWeb,
  stopChildAgent: vi.fn(),
}))
vi.mock('@/components/editor_workspace/agent_chat/childAgentConversations', () => ({
  preloadChildAgentConversations: mocks.preload,
}))

describe('ChildAgentPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    mocks.fetchChildAgents.mockResolvedValue({
      children: [{
        run_id: 'child-1', conversation_session_id: 'child-session-1', parent_run_id: 'parent-1',
        goal: '检索资料', name: 'explore1', category: 'explore', mode: 'background', status: 'running',
        access_mode: 'readonly', allowed_tools: [],
      }],
    })
    mocks.fetchChildAgentDshWeb.mockResolvedValue({ run_id: 'child-1', url: 'http://127.0.0.1:3080/#readonly=1' })
  })

  it.each(['explore', 'coding'])('opens the complete conversation of a %s child', async (category) => {
    mocks.fetchChildAgents.mockResolvedValue({
      children: [{
        run_id: 'child-1', conversation_session_id: 'child-session-1', parent_run_id: 'parent-1',
        goal: '检索资料', name: 'explore1', category, mode: 'background', status: 'running',
        access_mode: 'readonly', allowed_tools: [],
      }],
    })
    const wrapper = mount(ChildAgentPanel, { props: { sessionId: 'parent-session', userId: 'u1' } })
    await flushPromises()

    const link = wrapper.get('.child-agent-name-link')
    expect(link.text()).toBe('explore1')
    await link.trigger('click')
    expect(wrapper.emitted('open-conversation')?.[0]?.[0]).toMatchObject({ run_id: 'child-1' })
    expect(wrapper.emitted('open-dsh-web')).toBeUndefined()
    expect(useWorkspaceStore().browserSidebarOpen).toBe(false)
    expect(mocks.preload).toHaveBeenCalledWith(
      [expect.objectContaining({ conversation_session_id: 'child-session-1' })],
      'u1',
    )
  })

  it('opens DSH names and run names in the existing browser sidebar', async () => {
    const openExternal = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window, 'agentEditorDesktop', {
      configurable: true,
      value: { openExternal },
    })
    mocks.fetchChildAgents.mockResolvedValue({
      children: [{
        run_id: 'child-dsh', conversation_session_id: 'child-session-dsh', parent_run_id: 'parent-1',
        goal: '修改代码', name: 'dsh1', category: 'dsh', provider: 'dsh', mode: 'background', status: 'running',
        access_mode: 'sandbox', allowed_tools: ['dsh.edit'],
      }],
    })
    const webUrl = 'http://127.0.0.1:3080/#mw_token=test-session-token&session=child-session-dsh&readonly=1'
    mocks.fetchChildAgentDshWeb.mockResolvedValue({ run_id: 'child-dsh', url: webUrl })

    const wrapper = mount(ChildAgentPanel, { props: { sessionId: 'parent-session', userId: 'u1' } })
    await flushPromises()
    await wrapper.get('.child-agent-name-link').trigger('click')
    await flushPromises()

    expect(mocks.fetchChildAgentDshWeb).toHaveBeenCalledWith('child-dsh', 'u1', 'parent-session')
    const workspace = useWorkspaceStore()
    expect(workspace.browserSidebarOpen).toBe(true)
    expect(workspace.browserSidebarUrl).toBe(webUrl)
    expect(workspace.browserSidebarNavigationId).toBe(1)
    expect(openExternal).not.toHaveBeenCalled()
    expect(wrapper.emitted('open-conversation')).toBeUndefined()
    expect(wrapper.emitted('open-dsh-web')).toHaveLength(1)

    workspace.closeBrowserSidebar()
    await wrapper.get('.child-agent-name-link.run').trigger('click')
    await flushPromises()
    expect(workspace.browserSidebarOpen).toBe(true)
    expect(workspace.browserSidebarNavigationId).toBe(2)
    expect(wrapper.emitted('open-dsh-web')).toHaveLength(2)
    expect(openExternal).not.toHaveBeenCalled()
  })

  it('reports DSH Web failures without opening a conversation or browser sidebar', async () => {
    mocks.fetchChildAgents.mockResolvedValue({
      children: [{
        run_id: 'child-dsh', conversation_session_id: 'child-session-dsh', parent_run_id: 'parent-1',
        goal: '修改代码', name: 'dsh1', category: 'dsh', provider: 'dsh', mode: 'background', status: 'running',
        access_mode: 'sandbox', allowed_tools: ['dsh.edit'],
      }],
    })
    mocks.fetchChildAgentDshWeb.mockRejectedValue(new Error('DSH Web unavailable'))
    const wrapper = mount(ChildAgentPanel, { props: { sessionId: 'parent-session', userId: 'u1' } })
    await flushPromises()
    await wrapper.get('.child-agent-name-link').trigger('click')
    await flushPromises()

    expect(wrapper.get('.child-agent-error').text()).toBe('DSH Web unavailable')
    expect(useWorkspaceStore().browserSidebarOpen).toBe(false)
    expect(wrapper.emitted('open-conversation')).toBeUndefined()
    expect(wrapper.emitted('open-dsh-web')).toBeUndefined()
  })
})
