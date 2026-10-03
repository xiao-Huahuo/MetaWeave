/** Explicit link mounting, native component reuse, and stale-result lifecycle regressions. */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MarkdownContent from '../MarkdownContent.vue'
import SearchNativeResultCard from '@/components/search_page/SearchNativeResultCard.vue'
import { resolveKnowledgeLink } from '@/api/knowledgeLinks'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { UnifiedSearchResult } from '@/types/unifiedSearch'

vi.mock('@/api/knowledgeLinks', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/knowledgeLinks')>(),
  resolveKnowledgeLink: vi.fn(),
}))

/** Keep real card dispatch while isolating each native card's unrelated data loads. */
const nativeStubs = {
  LibraryCard: { props: ['item'], template: '<button class="book-native" @click="$emit(\'select\')">{{ item.display_title }}</button>' },
  ComponentLibraryCard: { props: ['item'], template: '<button class="component-native" @click="$emit(\'open\')">{{ item.title }}</button>' },
  LiteratureEntryCard: { props: ['entry'], template: '<button class="literature-native" @click="$emit(\'select\')">{{ entry.title }}</button>' },
}

describe('explicit knowledge links', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useSettingsStore().profile.userId = 'current-user'
    vi.mocked(resolveKnowledgeLink).mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it.each([
    ['library', 'book-native', { display_title: '知识手册' }],
    ['components', 'component-native', { title: '搜索组件' }],
    ['literature', 'literature-native', { title: '检索研究' }],
  ] as const)('mounts a %s link in place through the actual search card dispatcher', async (source, selector, item) => {
    const result: UnifiedSearchResult = {
      id: 'selected-1', source, title: 'selected', locator: '', snippet: '', updated_at: '',
      score: 0, matched_modes: [], item,
    }
    vi.mocked(resolveKnowledgeLink).mockResolvedValue(result)
    const workspaceStore = useWorkspaceStore()
    const open = vi.spyOn(workspaceStore, 'openAgentSearchResult').mockResolvedValue()
    workspaceStore.mainView = 'agent'
    const wrapper = mount(MarkdownContent, {
      props: { content: `上文\n\n[选择的知识](/knowledge/resolve?source=${source}&id=selected-1&library_id=origin)\n\n下文` },
      global: { stubs: nativeStubs },
    })
    await flushPromises()
    expect(resolveKnowledgeLink).toHaveBeenCalledWith('current-user', { source, id: 'selected-1', libraryId: 'origin' })
    expect(wrapper.findComponent(SearchNativeResultCard).props('result')).toEqual(result)
    const body = wrapper.get('.markdown-body')
    expect(body.element.children[1]?.className).toBe('agent-knowledge-block')
    expect(body.findAll('.agent-knowledge-block')).toHaveLength(1)
    await body.get(`.${selector}`).trigger('click')
    expect(open).toHaveBeenCalledWith(result, false)
    wrapper.unmount()
  })

  it('does not fetch or mount bare citations, ordinary links, images, or links inside code', async () => {
    const wrapper = mount(MarkdownContent, { props: { content: '[K1] [网站](https://example.com)\n\n![图](https://example.com/a.png)\n\n`[知识](/knowledge/resolve?source=library&id=1)`' } })
    await flushPromises()
    expect(resolveKnowledgeLink).not.toHaveBeenCalled()
    expect(wrapper.find('.agent-knowledge-block').exists()).toBe(false)
    wrapper.unmount()
  })

  it('discards a delayed resolution after the answer changes and retains unavailable links', async () => {
    let finish!: (result: UnifiedSearchResult) => void
    vi.mocked(resolveKnowledgeLink).mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const wrapper = mount(MarkdownContent, { props: { content: '[旧知识](/knowledge/resolve?source=library&id=old)' }, global: { stubs: nativeStubs } })
    await flushPromises()
    await wrapper.setProps({ content: '修改后的回答' })
    finish({ id: 'old', source: 'library', title: 'old', locator: '', snippet: '', updated_at: '', score: 0, matched_modes: [], item: {} })
    await flushPromises()
    expect(wrapper.find('.agent-knowledge-block').exists()).toBe(false)
    vi.mocked(resolveKnowledgeLink).mockRejectedValueOnce(new Error('404'))
    await wrapper.setProps({ content: '[已删除知识](/knowledge/resolve?source=library&id=gone)' })
    await flushPromises()
    expect(wrapper.get('a').attributes('data-knowledge-error')).toBe('true')
    expect(wrapper.get('a').text()).toBe('已删除知识')
    wrapper.unmount()
  })

  it('waits for completed Markdown and replaces mounted card instances when the answer changes', async () => {
    const result = (id: string): UnifiedSearchResult => ({ id, source: 'components', title: id, locator: '', snippet: '', updated_at: '', score: 0, matched_modes: [], item: { title: id } })
    vi.mocked(resolveKnowledgeLink).mockResolvedValueOnce(result('first')).mockResolvedValueOnce(result('second'))
    const wrapper = mount(MarkdownContent, {
      props: { content: '[知识](/knowledge/resolve?source=components&id=first)', isStreaming: true },
      global: { stubs: nativeStubs },
    })
    await flushPromises()
    expect(resolveKnowledgeLink).not.toHaveBeenCalled()
    await wrapper.setProps({ isStreaming: false })
    await flushPromises()
    expect(wrapper.get('.component-native').text()).toBe('first')
    await wrapper.setProps({ content: '[知识](/knowledge/resolve?source=components&id=second)' })
    await flushPromises()
    expect(wrapper.findAll('.agent-knowledge-block')).toHaveLength(1)
    expect(wrapper.get('.component-native').text()).toBe('second')
    wrapper.unmount()
  })
})
