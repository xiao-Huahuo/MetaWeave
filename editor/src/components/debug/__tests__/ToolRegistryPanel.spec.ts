/*
 * Debug 工具注册表组件测试。
 *
 * 使用说明:
 * 验证面板以 Agent 最终运行时注册表为准,即使设置分组尚未登记新增工具也不会隐藏。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ToolRegistryPanel from '@/components/dashboard/ToolRegistryPanel.vue'
import { fetchAgentTools } from '@/api/tools'
import { fetchAvailableTools, saveDisabledTools } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/api/tools', () => ({
  fetchAgentTools: vi.fn().mockResolvedValue({
    tool_count: 2,
    tools: [
      {
        name: 'known_tool',
        display_name: '已分组工具',
        description: '已有设置分组。',
        args_schema: { properties: {}, required: [] },
        argument_count: 0,
      },
      {
        name: 'new_runtime_tool',
        display_name: '新增运行时工具',
        description: '尚未登记到设置分组。',
        args_schema: { properties: {}, required: [] },
        argument_count: 0,
      },
      {
        name: 'write_long_term_memory',
        display_name: '写入记忆',
        description: '写入长期记忆。',
        args_schema: { properties: {}, required: [] },
        argument_count: 1,
      },
    ],
  }),
}))

vi.mock('@/api/settings', () => ({
  fetchAvailableTools: vi.fn().mockResolvedValue({
    groups: [
      {
        category: 'UTILITY',
        display_name: '通用工具',
        tools: [
          {
            name: 'known_tool',
            display_name: '已分组工具',
            description: '已有设置分组。',
            enabled: true,
          },
        ],
      },
      {
        category: 'MEMORY',
        display_name: '记忆工具',
        tools: [{
          name: 'write_long_term_memory',
          display_name: '写入记忆',
          description: '写入长期记忆。',
          enabled: true,
        }],
      },
    ],
  }),
  fetchDisabledTools: vi.fn().mockResolvedValue({ disabled_tools: [] }),
  saveDisabledTools: vi.fn().mockResolvedValue({ disabled_tools: [] }),
}))

describe('ToolRegistryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('keeps tools that only exist in the final runtime registry visible', async () => {
    const wrapper = mount(ToolRegistryPanel, {
      global: {
        stubs: {
          IcIcon: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('已分组工具')
    expect(wrapper.text()).toContain('新增运行时工具')
    expect(wrapper.text()).toContain('运行时工具')
    wrapper.unmount()
  })

  it('delegates memory tool switches to the long-term memory master setting', async () => {
    const wrapper = mount(ToolRegistryPanel, {
      global: { stubs: { IcIcon: true } },
    })
    await flushPromises()

    const memoryRow = wrapper.findAll('.tool-list-item')
      .find((row) => row.text().includes('写入记忆'))

    expect(memoryRow).toBeDefined()
    expect(memoryRow!.get('input').attributes('disabled')).toBeDefined()
    expect(memoryRow!.get('.tool-toggle-label').attributes('title')).toBe('由长期记忆总开关控制')
    wrapper.unmount()
  })

  it('refreshes the final catalog on focus and releases its listener on unmount', async () => {
    const wrapper = mount(ToolRegistryPanel, { global: { stubs: { IcIcon: true } } })
    await flushPromises()
    vi.mocked(fetchAgentTools).mockResolvedValueOnce({ tool_count: 1, tools: [{
      name: 'get_knowledge_url', display_name: '获取知识URL', description: '统一知识链接',
      args_schema: { properties: {}, required: [] }, argument_count: 0,
    }] })
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(wrapper.text()).toContain('获取知识URL')
    expect(wrapper.text()).not.toContain('已分组工具')
    expect(fetchAgentTools).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    window.dispatchEvent(new Event('focus'))
    expect(fetchAgentTools).toHaveBeenCalledTimes(2)
  })

  it('discards an older user load that finishes after the new user catalog', async () => {
    const settings = useSettingsStore()
    settings.profile.userId = 'first-user'
    let finish!: (result: Awaited<ReturnType<typeof fetchAgentTools>>) => void
    vi.mocked(fetchAgentTools).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const wrapper = mount(ToolRegistryPanel, { global: { stubs: { IcIcon: true } } })
    settings.profile.userId = 'next-user'
    await flushPromises()
    finish({ tool_count: 1, tools: [{ name: 'retired', display_name: '过期目录', description: '', args_schema: {}, argument_count: 0 }] })
    await flushPromises()
    expect(fetchAvailableTools).toHaveBeenCalledWith('next-user')
    expect(wrapper.text()).toContain('新增运行时工具')
    expect(wrapper.text()).not.toContain('过期目录')
    wrapper.unmount()
  })

  it('does not persist retired settings-group tools when toggling the current catalog', async () => {
    useSettingsStore().profile.userId = 'user-1'
    vi.mocked(fetchAvailableTools).mockResolvedValueOnce({ groups: [{
      category: 'UTILITY', display_name: '通用工具', tools: [
        { name: 'retired', display_name: '已移除工具', description: '', enabled: false },
        { name: 'known_tool', display_name: '已分组工具', description: '', enabled: true },
      ],
    }] })
    const wrapper = mount(ToolRegistryPanel, { global: { stubs: { IcIcon: true } } })
    await flushPromises()
    const row = wrapper.findAll('.tool-list-item').find(item => item.text().includes('已分组工具'))!
    await row.get('input').setValue(false)
    expect(saveDisabledTools).toHaveBeenCalledWith('user-1', ['known_tool'])
    wrapper.unmount()
  })
})
