/**
 * Four-library search page presentation and interaction tests.
 *
 * Usage:
 * Verifies unified source labels, shared pagination, split native sections,
 * and the existing file preview/open workflow without running a browser server.
 */

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SearchPage from '@/views/SearchPage.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type { SearchSource, UnifiedSearchResponse, UnifiedSearchResult } from '@/types/unifiedSearch'

const searchAllLibraries = vi.fn()

vi.mock('@/api/unifiedSearch', () => ({
  searchAllLibraries: (...args: unknown[]) => searchAllLibraries(...args),
}))
vi.mock('@/api/agent', () => ({ updateCurrentDocumentContext: vi.fn().mockResolvedValue(undefined) }))
vi.mock('@/api/settings', () => ({ rebuildKnowledgeRootStream: vi.fn() }))
vi.mock('@/api/knowledge', () => ({
  buildKnowledgeEventsUrl: vi.fn(() => '/events'),
  getKnowledgeGraphStatus: vi.fn(),
  readKnowledgeFile: vi.fn().mockResolvedValue({ path: 'docs/notes.md', content: 'alpha', mtime: '', size: 5 }),
  previewKnowledgeFile: vi.fn(),
}))

const emptyGroups = (): Record<SearchSource, UnifiedSearchResult[]> => ({ files: [], library: [], components: [], literature: [] })

function response(results: UnifiedSearchResult[]): UnifiedSearchResponse {
  const groups = emptyGroups()
  for (const result of results) groups[result.source].push(result)
  return {
    query: 'alpha',
    selected_sources: ['files', 'library', 'components', 'literature'],
    fulltext: true,
    semantic: false,
    results,
    groups,
    counts: {
      files: groups.files.length,
      library: groups.library.length,
      components: groups.components.length,
      literature: groups.literature.length,
    },
    total: results.length,
  }
}

function fileResult(index = 1): UnifiedSearchResult {
  const path = `docs/note-${index}.md`
  return {
    id: path,
    source: 'files',
    title: `note-${index}.md`,
    snippet: 'alpha beta',
    locator: path,
    updated_at: '',
    score: 0.9,
    matched_modes: ['title', 'fulltext'],
    item: { name: `note-${index}.md`, path, isDir: false, size: 10 },
  }
}

function mountPage() {
  return mount(SearchPage, {
    global: {
      stubs: {
        SplitText: true,
        ComponentLibraryCard: { props: ['item'], template: '<article class="component-native">{{ item.title }}</article>' },
        LibraryCard: { props: ['item'], template: '<article class="library-native">{{ item.display_title }}</article>' },
        LiteratureEntryCard: { name: 'LiteratureEntryCard', props: ['entry', 'expandable'], template: '<article class="literature-native">{{ entry.title }}</article>' },
        SearchFileMediumTile: { props: ['node'], template: '<button class="file-native">{{ node.name }}</button>' },
      },
    },
  })
}

describe('SearchPage four-library results', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    searchAllLibraries.mockReset().mockResolvedValue(response([]))
  })

  it('keeps the unified row style and identifies every result source at top right', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    store.searchResults = response([
      fileResult(),
      { id: 'lib-1', source: 'library', title: 'Alpha Book', snippet: 'book', locator: 'library/a.pdf', updated_at: '', score: 0.8, matched_modes: ['title'], item: { item_id: 'lib-1', parent_id: '', display_title: 'Alpha Book' } },
      { id: 'cards/a.vue', source: 'components', title: 'AlphaCard', snippet: '<article>', locator: 'cards/a.vue', updated_at: '', score: 0.7, matched_modes: ['fulltext'], item: { component_id: 'cards/a.vue', title: 'AlphaCard' } },
      { id: 'form:row', source: 'literature', title: 'Alpha Paper', snippet: 'paper', locator: 'paper.pdf', updated_at: '', score: 0.6, matched_modes: ['semantic'], item: { form_id: 'form', row_id: 'row', title: 'Alpha Paper' } },
    ])

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('.unified-result-row')).toHaveLength(4)
    expect(wrapper.text()).not.toContain('来自')
    expect(wrapper.text()).toContain('文件库')
    expect(wrapper.text()).toContain('图书馆')
    expect(wrapper.text()).toContain('组件库')
    expect(wrapper.text()).toContain('文献库')
    expect(wrapper.findAll('.result-source .source-result-icon')).toHaveLength(4)
  })

  it('paginates the shared ranked sequence at twenty rows', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    store.searchResults = response(Array.from({ length: 25 }, (_, index) => fileResult(index + 1)))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('.unified-result-row')).toHaveLength(20)
    await wrapper.get('.pagination button:last-child').trigger('click')
    expect(wrapper.findAll('.unified-result-row')).toHaveLength(5)
  })

  it('switches to four vertical native sections without issuing another search', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    store.searchResults = response([
      fileResult(),
      { id: 'lib-1', source: 'library', title: 'Book', snippet: '', locator: '', updated_at: '', score: 1, matched_modes: ['title'], item: { item_id: 'lib-1', display_title: 'Book' } },
      { id: 'c.vue', source: 'components', title: 'Card', snippet: '', locator: '', updated_at: '', score: 1, matched_modes: ['title'], item: { component_id: 'c.vue', title: 'Card' } },
      { id: 'f:r', source: 'literature', title: 'Paper', snippet: '', locator: '', updated_at: '', score: 1, matched_modes: ['title'], item: { form_id: 'f', row_id: 'r', title: 'Paper' } },
    ])
    const wrapper = mountPage()
    await flushPromises()
    searchAllLibraries.mockClear()

    await wrapper.findAll('.presentation-switch button')[1]!.trigger('click')

    expect(wrapper.findAll('.split-section')).toHaveLength(4)
    expect(wrapper.find('.file-native').exists()).toBe(true)
    expect(wrapper.find('.library-native').exists()).toBe(true)
    expect(wrapper.find('.component-native').exists()).toBe(true)
    expect(wrapper.find('.literature-native').exists()).toBe(true)
    expect(wrapper.getComponent({ name: 'LiteratureEntryCard' }).props('expandable')).toBe(false)
    expect(searchAllLibraries).not.toHaveBeenCalled()
    expect(wrapper.find('.presentation-indicator.split').exists()).toBe(true)
  })

  it('keeps single-click file preview inside search', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    store.searchResults = response([fileResult()])
    store.tree = [{ name: 'docs', path: 'docs', isDir: true, children: [{ name: 'note-1.md', path: 'docs/note-1.md', isDir: false }] }]
    const preview = vi.spyOn(store, 'openEditorSidebar').mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.get('.unified-result-row').trigger('click')

    expect(store.mainView).toBe('search')
    expect(preview).toHaveBeenCalledOnce()
  })

  it('opens non-file results in the shared editor sidebar without leaving search', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    const libraryResult: UnifiedSearchResult = {
      id: 'lib-1', source: 'library', title: 'Book', snippet: '', locator: '', updated_at: '', score: 1,
      matched_modes: ['title'], item: { item_id: 'lib-1', display_title: 'Book' },
    }
    store.searchResults = response([libraryResult])
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.get('.unified-result-row').trigger('click')

    expect(store.mainView).toBe('search')
    expect(store.editorSidebarOpen).toBe(true)
    expect(store.searchSidebarResult?.id).toBe('lib-1')
  })

  it('reuses the smart-table PixelLoader for active search work', async () => {
    const store = useWorkspaceStore()
    store.mainView = 'search'
    store.searchQuery = 'alpha'
    store.searchResults = response([fileResult()])
    store.searching = true
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('.search-status .pixel-loader').exists()).toBe(true)
    expect(wrapper.find('.search-status .spinner').exists()).toBe(false)
  })
})
