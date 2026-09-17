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
  })
})
