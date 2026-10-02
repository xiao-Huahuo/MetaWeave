/*
 * Chat input reference regression tests.
 *
 * Verifies that sending captures the visible reference before the input clears it.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { promptStarters } from '../promptStarters'

import ChatInput from '../ChatInput.vue'

describe('ChatInput references', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('emits a snapshot of the reference with the user prompt', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        reference: '  被引用的文档内容  ',
      },
    })

    await wrapper.get('textarea').setValue('引用内容是什么意思?')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('send')).toEqual([
      ['引用内容是什么意思?', '被引用的文档内容'],
    ])
    expect(wrapper.emitted('clear-reference')).toHaveLength(1)
  })

  it('emits the selected Agent access mode from the permission menu', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        agentAccessMode: 'sandbox',
      },
    })

    const details = wrapper.get('.access-mode-dropdown')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await nextTick()

    const fullAccessButton = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.access-mode-option'))
      .find((button) => button.textContent?.includes('完全访问'))

    expect(fullAccessButton).toBeTruthy()
    fullAccessButton?.click()
    await nextTick()

    expect(wrapper.emitted('set-agent-access-mode')).toEqual([['full_access']])
  })

  it('injects a starter prefix without sending the prompt', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        centered: true,
      },
    })

    const starter = wrapper
      .findAll('.prompt-starter-card')
      .at(0)

    expect(starter).toBeTruthy()
    await starter?.trigger('click')

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(promptStarters.find((entry) => entry.title === starter?.text())?.prefix)
    expect(wrapper.emitted('send')).toBeFalsy()
    expect(wrapper.findAll('.prompt-starter-card')).toHaveLength(0)
    expect(wrapper.findAll('.prompt-waterfall-item')).toHaveLength(4)
  })

  it('matches suggestions against the current input prefix', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        centered: true,
      },
    })

    await wrapper.get('textarea').setValue('撰写')
    const buildStarter = wrapper
      .findAll('.prompt-starter-card')
      .find((button) => button.text().includes('撰写文档'))

    await buildStarter?.trigger('click')
    const suggestion = wrapper
      .findAll('.prompt-waterfall-item')
      .find((button) => button.text().includes('撰写一份基于知识库资料的主题综述，并注明来源'))

    expect(suggestion).toBeTruthy()
    await suggestion?.trigger('click')

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('撰写一份基于知识库资料的主题综述，并注明来源')
    expect(wrapper.emitted('send')).toBeFalsy()
    expect(wrapper.findAll('.prompt-waterfall-item')).toHaveLength(1)
  })

  it('returns to starter cards when the prompt prefix is cleared', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        centered: true,
      },
    })

    const fixStarter = wrapper
      .findAll('.prompt-starter-card')
      .at(0)

    await fixStarter?.trigger('click')
    expect(wrapper.findAll('.prompt-waterfall-item')).toHaveLength(4)

    await wrapper.get('textarea').setValue('')

    expect(wrapper.findAll('.prompt-waterfall-item')).toHaveLength(0)
    expect(wrapper.findAll('.prompt-starter-card')).toHaveLength(4)
  })

  it('hides prompt starter blocks in compact sidebar mode', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        centered: true,
        compact: true,
      },
    })

    expect(wrapper.findAll('.prompt-starter-card')).toHaveLength(0)

    await wrapper.get('textarea').setValue('探索')

    expect(wrapper.findAll('.prompt-waterfall-item')).toHaveLength(0)
  })

  it('matches all eight functions even when their cards are outside the random draw', async () => {
    const wrapper = mount(ChatInput, { props: { centered: true } })
    expect(new Set(promptStarters.map((entry) => entry.icon)).size).toBe(8)
    expect(new Set(promptStarters.map((entry) => entry.color)).size).toBe(8)
    for (const entry of promptStarters) {
      await wrapper.get('textarea').setValue(entry.prefix)
      const rows = wrapper.findAll('.prompt-waterfall-item')
      expect(rows.map((row) => row.text())).toEqual(entry.suggestions)
      expect(rows[0]?.attributes('style')).toContain('--starter-color')
      await rows[0]?.trigger('click')
      expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(entry.suggestions[0])
    }
    expect(wrapper.emitted('send')).toBeFalsy()
    wrapper.unmount()
  })

  it('keeps the draw while editing and resets on repeated new draft requests', async () => {
    const wrapper = mount(ChatInput, { props: { centered: true, conversationKey: 'draft:0' } })
    const titles = wrapper.findAll('.prompt-starter-card').map((card) => card.text())
    expect(new Set(titles).size).toBe(4)
    await wrapper.get('textarea').setValue('检索')
    await wrapper.get('textarea').setValue('')
    expect(wrapper.findAll('.prompt-starter-card').map((card) => card.text())).toEqual(titles)
    await wrapper.get('textarea').setValue('阅读')
    await wrapper.setProps({ conversationKey: 'draft:1' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    expect(wrapper.findAll('.prompt-starter-card')).toHaveLength(4)
    wrapper.unmount()
  })

  it('preserves the next prompt when the first sent message receives a session ID', async () => {
    const wrapper = mount(ChatInput, { props: { centered: false, conversationKey: 'draft:0' } })
    await wrapper.get('textarea').setValue('接着分析这份资料')
    await wrapper.setProps({ conversationKey: 'saved-session:0' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('接着分析这份资料')
    wrapper.unmount()
  })

  it('shows starters on the full mobile Agent page while keeping compact sidebars quiet', () => {
    const wrapper = mount(ChatInput, { props: { centered: true, compact: true, page: true } })
    expect(wrapper.findAll('.prompt-starter-card')).toHaveLength(4)
    wrapper.unmount()
  })

  it('keeps the draft field editable while sending actions are unavailable', async () => {
    const wrapper = mount(ChatInput, {
      props: {
        disabled: true,
      },
    })

    const textarea = wrapper.get('textarea')
    expect(textarea.attributes('disabled')).toBeUndefined()
    await textarea.setValue('先写下这条消息')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect((textarea.element as HTMLTextAreaElement).value).toBe('先写下这条消息')
    expect(wrapper.emitted('send')).toBeFalsy()
  })
})
