/**
 * Top-bar search interaction tests.
 *
 * Usage:
 * Verifies that the compact toolbar variant keeps its searchable icon and
 * keyboard submission while the page variant retains its full submit button.
 */

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import SearchPalette from '@/components/editor_workspace/SearchPalette.vue'
import { useWorkspaceStore } from '@/stores/workspace'

describe('SearchPalette toolbar variant', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
    setActivePinia(createPinia())
  })

  it('expands the compact search button without submitting', async () => {
    const workspaceStore = useWorkspaceStore()
    const initialView = workspaceStore.mainView
    const wrapper = mount(SearchPalette, {
      global: { stubs: { Teleport: true, Transition: false } },
    })

    await wrapper.get('.toolbar-search-btn').trigger('click')

    expect(wrapper.get('.search-wrapper').classes()).toContain('focused')
    expect(workspaceStore.mainView).toBe(initialView)
  })

  it('expands on focus and submits the existing query with Enter', async () => {
    const workspaceStore = useWorkspaceStore()
    const wrapper = mount(SearchPalette, {
      global: { stubs: { Teleport: true, Transition: false } },
    })

    workspaceStore.searchQuery = 'heatmap'
    await wrapper.get('.search-input').trigger('focus')
    expect(wrapper.get('.search-wrapper').classes()).toContain('focused')
    expect(wrapper.findAll('.toolbar-search-btn')).toHaveLength(1)
    expect(wrapper.find('.search-submit-btn').exists()).toBe(false)
    expect(wrapper.get('.search-input').attributes('placeholder')).toBe('')
    expect(wrapper.get('.search-input').attributes('aria-label')).toBe('搜索文件')

    await wrapper.get('.search-input').trigger('blur', { relatedTarget: document.body })
    expect(wrapper.get('.search-wrapper').classes()).not.toContain('focused')

    await wrapper.get('.search-input').trigger('focus')
    await wrapper.get('.search-input').trigger('keydown.enter')
    expect(workspaceStore.mainView).toBe('search')
    expect(wrapper.get('.search-wrapper').classes()).not.toContain('focused')
  })

  it('keeps the full submit button on the search page variant', () => {
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      global: { stubs: { Teleport: true, Transition: false } },
    })

    expect(wrapper.find('.toolbar-search-btn').exists()).toBe(false)
    expect(wrapper.findAll('.search-submit-btn')).toHaveLength(1)
    expect(wrapper.get('.search-input').attributes('placeholder')).toBe('搜索文件...')
  })

  it('adds four multi-select library filters beside the existing content and semantic toggles', async () => {
    const workspaceStore = useWorkspaceStore()
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      global: { stubs: { Teleport: true, Transition: false } },
    })

    await wrapper.get('.search-input').trigger('focus')

    expect(wrapper.findAll('.toggle-btn')).toHaveLength(2)
    expect(wrapper.findAll('.source-toggle-btn')).toHaveLength(4)
    expect(wrapper.text()).toContain('文件库')
    expect(wrapper.text()).toContain('图书馆')
    expect(wrapper.text()).toContain('组件库')
    expect(wrapper.text()).toContain('文献库')

    await wrapper.findAll('.source-toggle-btn')[2]!.trigger('mousedown')
    expect(workspaceStore.searchSources).toEqual(['files', 'library', 'literature'])
  })

  it('keeps a teleported dropdown open when a source filter is clicked', async () => {
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      attachTo: document.body,
      global: { stubs: { Transition: false } },
    })
    await wrapper.get('.search-input').trigger('focus')
    const sourceButton = document.body.querySelector<HTMLButtonElement>('.source-toggle-btn')!

    sourceButton.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    await nextTick()

    expect(document.body.querySelector('.page-search-dropdown')).not.toBeNull()
    wrapper.unmount()
  })

  it('shows source icons without source text in the toolbar dropdown', async () => {
    const wrapper = mount(SearchPalette, {
      global: { stubs: { Teleport: true, Transition: false } },
    })
    await wrapper.get('.search-input').trigger('focus')

    expect(wrapper.findAll('.source-toggle-icon')).toHaveLength(4)
    expect(wrapper.findAll('.source-toggle-label')).toHaveLength(0)
  })

  it('uses the smart-table PixelLoader while searching', () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.searching = true
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      global: { stubs: { Teleport: true, Transition: false } },
    })

    expect(wrapper.find('.search-pixel-loader.pixel-loader').exists()).toBe(true)
    expect(wrapper.find('.spinner').exists()).toBe(false)
  })

  it('passes the selected libraries and search modes to the Agent search request', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.searchQuery = '多模态检索'
    workspaceStore.searchSources = ['files', 'literature']
    workspaceStore.fulltextEnabled = false
    workspaceStore.semanticEnabled = true
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      global: { stubs: { Teleport: true, Transition: false } },
    })

    await wrapper.get('.search-input').trigger('focus')
    await wrapper.get('.ai-search-btn').trigger('mousedown')

    expect(workspaceStore.agentSidebarOpen).toBe(true)
    expect(workspaceStore.pendingAgentPrompt).toContain('四库联合搜索')
    expect(workspaceStore.pendingAgentPrompt).toContain('文件库、文献库')
    expect(workspaceStore.pendingAgentPrompt).toContain('全文搜索：关闭')
    expect(workspaceStore.pendingAgentPrompt).toContain('语义搜索：开启')
  })

  it('tracks a moving toolbar anchor while the dropdown remains open', async () => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0))
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
    const wrapper = mount(SearchPalette, {
      attachTo: document.body,
      global: { stubs: { Transition: false } },
    })
    const searchWrapper = wrapper.get('.search-wrapper').element
    let left = 120
    vi.spyOn(searchWrapper, 'getBoundingClientRect').mockImplementation(() => ({
      top: 20, bottom: 48, left, right: left + 250, width: 250, height: 28,
      x: left, y: 20, toJSON: () => ({}),
    } as DOMRect))
    await wrapper.get('.search-input').trigger('focus')
    await new Promise((resolve) => window.setTimeout(resolve, 5))
    left = 72
    await new Promise((resolve) => window.setTimeout(resolve, 5))

    expect((document.body.querySelector('.search-dropdown') as HTMLElement).style.left).toBe('72px')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('reopens the dropdown on the first click after Enter submits a focused input', async () => {
    const workspaceStore = useWorkspaceStore()
    const wrapper = mount(SearchPalette, {
      props: { variant: 'page' },
      attachTo: document.body,
      global: { stubs: { Teleport: true, Transition: false } },
    })
    const input = wrapper.get('.search-input')
    workspaceStore.searchQuery = 'alpha'
    ;(input.element as HTMLInputElement).focus()
    await input.trigger('focus')
    await input.trigger('keydown.enter')
    expect(wrapper.get('.search-wrapper').classes()).not.toContain('focused')

    await input.trigger('click')

    expect(wrapper.get('.search-wrapper').classes()).toContain('focused')
    expect(wrapper.find('.page-search-dropdown').exists()).toBe(true)
    wrapper.unmount()
  })
})
