/*
 * Tool call inline summary tests.
 *
 * Usage:
 * Verifies per-tool toolbar summary text without changing the existing trace
 * grouping or streaming lifecycle behavior.
 */
import { describe, expect, it } from 'vitest'

import { mount } from '@vue/test-utils'

import ToolCallInline from '../ToolCallInline.vue'

describe('ToolCallInline summaries', () => {
  it('keeps the category icon visible from a tool preview through its result', async () => {
    const start = {
      event: 'tool_call_start',
      tool_call_id: 'call_web_1',
      tool_name: 'web_search',
      display_name: '联网搜索',
    }
    const wrapper = mount(ToolCallInline, {
      global: {
        stubs: {
          IcIcon: {
            props: ['name'],
            template: '<i class="stub-icon" :data-icon="name"></i>',
          },
        },
      },
      props: { traces: [start] },
    })
    const originalRow = wrapper.get('.tool-call-box').element

    expect(wrapper.get('.tool-leading-icon .stub-icon').attributes('data-icon')).toBe('language')
    expect(wrapper.find('.tool-expand-btn').exists()).toBe(false)

    await wrapper.setProps({
      traces: [start, {
        event: 'tool_call_end',
        tool_call_id: 'call_web_1',
        tool_name: 'web_search',
        display_name: '联网搜索',
        result_count: 1,
        raw_content: '搜索结果',
      }],
    })

    expect(wrapper.get('.tool-call-box').element).toBe(originalRow)
    expect(wrapper.findAll('.tool-expand-btn .stub-icon').map((icon) => icon.attributes('data-icon'))).toEqual([
      'language',
      'chevron-down',
    ])
  })

  it('shows count-based knowledge and file summaries', () => {
    const wrapper = mount(ToolCallInline, {
      props: {
        traces: [
          {
            event: 'tool_call_end',
            tool_name: 'get_knowledge_context',
            display_name: '检索知识',
            result_count: 4,
            raw_content: '1. [K1] 来源: a.md\n内容: A',
          },
          {
            event: 'tool_call_end',
            tool_name: 'search_knowledge',
            display_name: '四库联合搜索',
            tool_args_summary: 'query=原神',
            result_count: 2,
            raw_content: '=== 文件名匹配 ===\n  [K1] 原神.md',
          },
          {
            event: 'tool_call_end',
            tool_name: 'list_knowledge_files',
            display_name: '列出文件',
            raw_content: '[DIR] docs\n[FILE] docs/a.md\n[FILE] b.txt',
          },
        ],
      },
    })

    const text = wrapper.text()
    expect(text).toContain('检索到 4 条知识')
    expect(text).toContain('四库联合搜索：2 条结果 | 原神')
    expect(text).toContain('列出 2 个文件 / 1 个文件夹')
  })

  it('shows the unified read_file tool as one document-reading toolbar entry', async () => {
    const wrapper = mount(ToolCallInline, {
      global: {
        stubs: {
          IcIcon: {
            props: ['name'],
            template: '<i class="stub-icon" :data-icon="name"></i>',
          },
        },
      },
      props: {
        traces: [{
          event: 'tool_call_end',
          tool_name: 'read_file',
          display_name: '阅读文件',
          tool_args_summary: 'path=attachment://att_1',
          raw_content: JSON.stringify({ filename: 'report.pdf', content: '正文' }),
        }],
      },
    })

    expect(wrapper.text()).toContain('阅读文件：report.pdf')
    expect(wrapper.get('.tool-leading-icon .stub-icon').attributes('data-icon')).toBe('document')
    await wrapper.find('.tool-expand-btn').trigger('click')
    expect(wrapper.get('.tool-result-code').text()).toContain('report.pdf')
  })

  it('shows current status and content labels', () => {
    const wrapper = mount(ToolCallInline, {
      props: {
        traces: [
          {
            event: 'tool_call_end',
            tool_name: 'get_current_time',
            display_name: '获取当前时间',
            raw_content: '2026-07-28T13:42:00+08:00',
          },
          {
            event: 'tool_call_end',
            tool_name: 'get_current_viewing_document',
            display_name: '获取当前文档',
            raw_content: JSON.stringify({ name: '计划.md', path: 'docs/计划.md' }),
          },
          {
            event: 'tool_call_end',
            tool_name: 'use_skill',
            display_name: '使用技能',
            tool_args_summary: 'skill_ref=pdf',
            raw_content: 'Skill loaded: pdf',
          },
          {
            event: 'tool_call_end',
            tool_name: 'add_todo',
            display_name: '新增待办',
            tool_args_summary: 'text=整理测试报告',
            raw_content: '已创建待办 [todo_1]: 整理测试报告',
          },
        ],
      },
    })

    const text = wrapper.text()
    expect(text).toContain('获取当前时间：2026-07-28 13:42')
    expect(text).toContain('获取当前文档：计划.md')
    expect(text).toContain('使用技能：pdf')
    expect(text).toContain('新增待办：整理测试报告')
  })

  it('replaces a running patch preview in place and renders the shared diff', async () => {
    const start = {
      event: 'tool_call_start',
      tool_call_id: 'call_patch_1',
      tool_name: 'patch_knowledge_file',
    }
    const wrapper = mount(ToolCallInline, { props: { traces: [start] } })
    expect(wrapper.text()).toContain('正在局部修改文件')
    expect(wrapper.find('.tool-expand-btn').exists()).toBe(false)
    expect(wrapper.get('.tool-text').classes()).toContain('pending')
    expect(wrapper.get('.tool-text').classes()).toContain('thinking-shimmer-text')
    const originalRow = wrapper.get('.tool-call-box').element

    await wrapper.setProps({
      traces: [{
        ...start,
      }, {
        event: 'tool_call_end',
        tool_call_id: 'call_patch_1',
        tool_name: 'patch_knowledge_file',
        raw_content: '已局部修改文件 notes/a.md',
        patch: { path: 'notes/a.md', before: '旧内容', after: '新内容', complete: true },
      }],
    })

    expect(wrapper.get('.tool-call-box').element).toBe(originalRow)
    await wrapper.find('.tool-expand-btn').trigger('click')
    expect(wrapper.find('.removed .line-text').text()).toBe('旧内容')
    expect(wrapper.find('.added .line-text').text()).toBe('新内容')
  })

  it('prefers the finalized snapshot over a transient patch preview', async () => {
    const wrapper = mount(ToolCallInline, {
      props: {
        traces: [{
          event: 'tool_call_end', tool_call_id: 'call_patch_2', tool_name: 'patch_knowledge_file', raw_content: 'done',
          patch: { path: 'notes/a.md', before: 'old', after: 'new', complete: false },
        }],
        changeSnapshot: {
          snapshot_id: 'snap_1', session_id: 's1', run_id: 'run_1', created_at: '', additions: 1, deletions: 1, is_undone: false,
          files: [{ path: 'notes/a.md', additions: 1, deletions: 1, edits: [{ path: 'notes/a.md', before: 'one\ntwo\nold', after: 'one\ntwo\nnew', additions: 1, deletions: 1 }] }],
          edits: [],
        },
      },
    })

    await wrapper.find('.tool-expand-btn').trigger('click')
    expect(wrapper.find('.removed .line-number').text()).toBe('3')
    expect(wrapper.find('.removed .line-text').text()).toBe('old')
    expect(wrapper.find('.added .line-text').text()).toBe('new')
  })
})
