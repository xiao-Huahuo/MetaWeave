/** New native tools share complete names and category icons in both Agent trace renderers. */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ToolCallInline from '../ToolCallInline.vue'
import ThinkingInline from '../ThinkingInline.vue'
import { TOOL_DISPLAY_NAMES } from '../toolDisplayNames'

describe('Agent native tool presentation', () => {
  it.each([
    ['get_knowledge_url', 'manage-search'],
    ['read_tool_result', 'build'],
    ['understand_image', 'document'],
    ['request_user_input', 'group'],
    ['continue_child_agent', 'group'],
    ['patch_knowledge_file', 'document'],
  ])('shows %s with its shared name and semantic icon without trace metadata', (toolName, icon) => {
    const trace = { event: 'tool_call_end', tool_name: toolName, human_readable: '工具已完成', raw_content: '完成' }
    const tool = mount(ToolCallInline, { props: { traces: [{ ...trace, event: 'tool_call_start' }] }, global: { stubs: { IcIcon: true } } })
    const thinking = mount(ThinkingInline, { props: { traces: [trace], defaultExpanded: true } })
    expect(tool.text()).toContain(TOOL_DISPLAY_NAMES[toolName]!)
    expect(thinking.text()).toContain(TOOL_DISPLAY_NAMES[toolName]!)
    expect(tool.get('.tool-category-icon').attributes('data-tool-icon')).toBe(icon)
    tool.unmount()
    thinking.unmount()
  })

  it('keeps the running backend display name authoritative for native and extension tools', () => {
    const trace = { event: 'tool_call_end', tool_name: 'request_user_input', display_name: '运行时名称', human_readable: '完成' }
    const tool = mount(ToolCallInline, { props: { traces: [trace] }, global: { stubs: { IcIcon: true } } })
    expect(tool.text()).toContain('运行时名称')
    tool.unmount()
  })
})
