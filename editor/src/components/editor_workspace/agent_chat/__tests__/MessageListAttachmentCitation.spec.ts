/* Streaming body isolation, bottom-follow behavior, and historical attachment citation tests. */
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { defineComponent, h, nextTick, onUpdated, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import MessageList from '../MessageList.vue'

describe('MessageList attachment citation recovery', () => {
  it('leaves completed bubbles untouched while only the last body grows', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    const updatedMessages: string[] = []
    const messages = reactive([
      { message_id: 'old-user', role: 'user' as const, content: 'Earlier prompt' },
      { message_id: 'old-answer', role: 'assistant' as const, node: 'agent', content: 'Completed answer' },
      { message_id: 'new-user', role: 'user' as const, content: 'Current prompt' },
      { message_id: 'new-answer', role: 'assistant' as const, node: 'agent', content: 'First word' },
    ])
    const wrapper = mount(MessageList, {
      props: { messages, isStreaming: true },
      global: {
        plugins: [createPinia()],
        stubs: {
          MessageBubble: defineComponent({
            props: ['message', 'isStreaming', 'isThinkingActive', 'userAvatar', 'agentAvatar', 'showAvatar', 'showActions', 'knowledgeSources', 'citationMap', 'changeSnapshot'],
            setup(props) {
              onUpdated(() => updatedMessages.push(props.message.message_id))
              return () => h('div', props.message.content)
            },
          }),
          FinalTurnSummary: true, LoadingState: true, LoaderCube: true,
        },
      },
    })
    updatedMessages.length = 0
    messages[3]!.content += ' continues'
    await nextTick()

    expect(updatedMessages).toEqual(['new-answer'])
    wrapper.unmount()
  })

  it('coalesces body follow into a frame and yields to upward scrolling', async () => {
    const scrollTo = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: scrollTo, configurable: true })
    const callbacks: FrameRequestCallback[] = []
    const frameSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback)
      return callbacks.length
    })
    const messages = reactive([{ role: 'assistant' as const, content: 'First word', node: 'agent' }])
    const wrapper = mount(MessageList, {
      props: { messages, isStreaming: true },
      global: {
        plugins: [createPinia()],
        stubs: { MessageBubble: true, FinalTurnSummary: true, LoadingState: true, LoaderCube: true },
      },
    })
    const list = wrapper.get('.message-list')
    const readHeight = vi.fn(() => 1000)
    Object.defineProperties(list.element, {
      scrollHeight: { get: readHeight },
      clientHeight: { value: 300 },
      scrollTop: { value: 700, writable: true },
    })
    scrollTo.mockClear()
    messages[0]!.content += ' grows'
    await nextTick()
    await nextTick()
    messages[0]!.content += ' again'
    await nextTick()
    await nextTick()

    expect(scrollTo).not.toHaveBeenCalled()
    expect(readHeight).not.toHaveBeenCalled()
    expect(callbacks).toHaveLength(1)
    callbacks[0]?.(performance.now())
    expect(scrollTo).toHaveBeenCalledOnce()
    expect(readHeight).toHaveBeenCalledOnce()

    scrollTo.mockClear()
    messages[0]!.content += ' while user scrolls'
    await nextTick()
    await nextTick()
    await list.trigger('wheel')
    list.element.scrollTop = 400
    await list.trigger('scroll')
    callbacks[1]?.(performance.now())
    callbacks[2]?.(performance.now())
    expect(scrollTo).not.toHaveBeenCalled()

    messages[0]!.content += ' in history view'
    await nextTick()
    await nextTick()
    expect(callbacks).toHaveLength(3)
    expect(scrollTo).not.toHaveBeenCalled()

    list.element.scrollTop = 700
    await list.trigger('scroll')
    callbacks[3]?.(performance.now())
    messages[0]!.content += ' back at bottom'
    await nextTick()
    await nextTick()
    callbacks[4]?.(performance.now())
    expect(scrollTo).toHaveBeenCalledOnce()
    wrapper.unmount()
    frameSpy.mockRestore()
  })

  it('coalesces repeated scroll events into one animation-frame layout read', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    const callbacks: FrameRequestCallback[] = []
    const frameSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback)
      return callbacks.length
    })
    const wrapper = mount(MessageList, {
      props: { messages: [] },
      global: {
        plugins: [createPinia()],
        stubs: { MessageBubble: true, FinalTurnSummary: true, LoadingState: true, LoaderCube: true },
      },
    })

    await wrapper.get('.message-list').trigger('scroll')
    await wrapper.get('.message-list').trigger('scroll')
    await wrapper.get('.message-list').trigger('scroll')

    expect(callbacks).toHaveLength(1)
    callbacks[0]?.(performance.now())
    wrapper.unmount()
    frameSpy.mockRestore()
  })

  it('recovers exact session-upload URIs for old assistant messages', () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    const uri = 'session-upload://u1/library/s1/image11.png'
    const wrapper = mount(MessageList, {
      props: {
        messages: [
          {
            role: 'user',
            content: '这些图片有啥',
            attachments: [{
              attachment_id: 'att-1', user_id: 'u1', session_id: 's1', library_id: 'library', library_name: '',
              filename: 'image11.png', stored_name: 'image11.png', uri, mime_type: 'image/png', size: 12,
              source_type: 'image', created_at: '', metadata: {},
            }],
          },
          { role: 'assistant', content: '1. image11.png — Vue.js', node: 'agent', metadata: {} },
        ],
      },
      global: {
        plugins: [createPinia()],
        stubs: {
          MessageBubble: {
            props: ['message', 'citationMap'],
            template: '<div class="citation-map">{{ JSON.stringify(citationMap) }}</div>',
          },
          FinalTurnSummary: true,
          LoadingState: true,
          LoaderCube: true,
        },
      },
    })

    expect(wrapper.findAll('.citation-map')[1]?.text()).toContain(uri)
    expect(wrapper.findAll('.citation-map')[1]?.text()).toContain('image11.png')
  })

  it('mounts only four-library results cited by the final Agent answer', () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    const wrapper = mount(MessageList, {
      props: {
        messages: [{
          role: 'assistant',
          content: '建议使用这个组件 [K2]',
          node: 'agent',
          metadata: {
            citation_map: {
              K1: {
                source_uri: 'docs/a.md', content: '文件', source: 'tool',
                search_result: { id: 'docs/a.md', source: 'files', title: 'a.md', snippet: '', locator: 'docs/a.md', updated_at: '', score: 1, matched_modes: ['title'], item: {} },
              },
              K2: {
                source_uri: 'cards/a.vue', content: '组件', source: 'tool',
                search_result: { id: 'cards/a.vue', source: 'components', title: 'Card', snippet: '', locator: 'cards/a.vue', updated_at: '', score: 1, matched_modes: ['title'], item: {} },
              },
            },
          },
        }],
      },
      global: {
        plugins: [createPinia()],
        stubs: {
          MessageBubble: true,
          FinalTurnSummary: true,
          AgentSearchResultBlocks: {
            props: ['results'],
            template: '<div class="mounted-results">{{ results.map((item) => item.id).join(",") }}</div>',
          },
          LoadingState: true,
          LoaderCube: true,
        },
      },
    })

    expect(wrapper.get('.mounted-results').text()).toBe('cards/a.vue')
  })
})
