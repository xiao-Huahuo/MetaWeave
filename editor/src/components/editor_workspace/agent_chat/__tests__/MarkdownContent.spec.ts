/*
 * Markdown source-link regression tests.
 *
 * Verifies that local document names in assistant answers remain clickable even
 * when the final message does not carry a local citation_map entry.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import MarkdownContent from '../MarkdownContent.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type { SearchSource, UnifiedSearchResult } from '@/types/unifiedSearch'

const { openImagePreview } = vi.hoisted(() => ({ openImagePreview: vi.fn() }))

vi.mock('@/components/common/useImagePreviewer', () => ({
  useImagePreviewer: () => ({ open: openImagePreview }),
}))

describe('MarkdownContent source links', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    openImagePreview.mockClear()
  })

  it('links a unique workspace filename even without citation metadata', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [
      {
        name: '01_climate_change_nasa.md',
        path: '1/3/01_climate_change_nasa.md',
        isDir: false,
      },
    ]
    const onNavigateSource = vi.fn<(uri: string) => void>()

    const wrapper = mount(MarkdownContent, {
      props: {
        content: '气候变化资料主要来自 01_climate_change_nasa.md。',
        citationMap: {},
        onNavigateSource,
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    const sourceLink = wrapper.get('.source-file-link')
    expect(sourceLink.text()).toBe('01_climate_change_nasa.md')
    await sourceLink.trigger('click')
    expect(onNavigateSource).toHaveBeenCalledWith('1/3/01_climate_change_nasa.md')
  })

  it('opens every four-library K citation through the shared result sidebar', async () => {
    const workspaceStore = useWorkspaceStore()
    const openSearchResultSidebar = vi.spyOn(workspaceStore, 'openSearchResultSidebar').mockResolvedValue()
    const sources: SearchSource[] = ['files', 'library', 'components', 'literature']
    const citationMap = Object.fromEntries(sources.map((source, index) => {
      const searchResult: UnifiedSearchResult = {
        id: `${source}-1`, source, title: source, snippet: '',
        locator: source === 'library' ? 'https://example.com/library-1' : `${source}/1`, updated_at: '',
        score: 1, matched_modes: ['title'], item: {},
      }
      return [`K${index + 1}`, {
        source_uri: searchResult.locator,
        content: source,
        search_result: searchResult,
      }]
    }))
    const wrapper = mount(MarkdownContent, {
      props: {
        content: sources.map((_, index) => `[K${index + 1}]`).join(' '),
        citationMap,
      },
    })

    for (const anchor of wrapper.findAll('.citation-anchor')) await anchor.trigger('click')

    expect(openSearchResultSidebar.mock.calls.map(([result]) => result.source)).toEqual(sources)
  })

  it('renders inline and display math after DOMPurify', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '行内 $a^2+b^2$ 与块级\n\n$$\\sum_{i=1}^{n} i$$\n\n结束',
        citationMap: {},
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(wrapper.find('.katex').exists()).toBe(true)
    expect(wrapper.find('.katex-display').exists()).toBe(true)
    // KaTeX 依赖的 style 定位属性经 DOMPurify 后保留(非空 style)
    const styles = wrapper.findAll('.katex [style]')
    expect(styles.length).toBeGreaterThan(0)
  })

  it('does not render math inside code fences', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '代码: ```js\nconst price = "$5 and $10";\n```',
        citationMap: {},
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(wrapper.find('.katex').exists()).toBe(false)
    expect(wrapper.text()).toContain('$5 and $10')
  })

  it('links filenames after the workspace tree loads later', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = []
    const onNavigateSource = vi.fn<(uri: string) => void>()

    const wrapper = mount(MarkdownContent, {
      props: {
        content: '海洋酸化资料主要来自 09_ocean_acidification_noaa 2.md。',
        citationMap: {},
        onNavigateSource,
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(wrapper.find('.source-file-link').exists()).toBe(false)

    workspaceStore.tree = [
      {
        name: '09_ocean_acidification_noaa 2.md',
        path: '1/3/special/09_ocean_acidification_noaa 2.md',
        isDir: false,
      },
    ]
    await nextTick()
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    const sourceLink = wrapper.get('.source-file-link')
    expect(sourceLink.text()).toBe('09_ocean_acidification_noaa 2.md')
    await sourceLink.trigger('click')
    expect(onNavigateSource).toHaveBeenCalledWith('1/3/special/09_ocean_acidification_noaa 2.md')
  })

  it('opens the exact session attachment even when the workspace has the same filename', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [{ name: 'image11.png', path: 'old/image11.png', isDir: false }]
    const onNavigateSource = vi.fn<(uri: string) => void>()
    const uri = 'session-upload://u1/library/s1/image11.png'
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '1. image11.png — Vue.js 介绍',
        citationMap: { A1: { source_uri: uri, content: 'OCR', title: 'image11.png' } },
        onNavigateSource,
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    await wrapper.get('.source-file-link').trigger('click')

    expect(onNavigateSource).not.toHaveBeenCalled()
    expect(openImagePreview).toHaveBeenCalledWith([{
      src: `/agent/attachments/raw?uri=${encodeURIComponent(uri)}`,
      alt: 'image11.png',
    }], 0)
  })

  it('does not auto-link duplicate attachment filenames ambiguously', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: 'image11.png',
        citationMap: {
          A1: { source_uri: 'session-upload://u1/library/s1/image11.png', content: '', title: 'image11.png' },
          A2: { source_uri: 'session-upload://u1/library/s2/image11.png', content: '', title: 'image11.png' },
        },
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(wrapper.find('.source-file-link').exists()).toBe(false)
  })

  it('mounts an encoded knowledge file link as a clickable standalone file block', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [
      {
        name: '简单word.docx',
        path: '文档/简单word.docx',
        isDir: false,
        size: 2048,
        createdAt: '2026-08-21 09:30',
        indexStatus: 'indexed',
        graphStatus: 'graphed',
      },
    ]
    const onNavigateSource = vi.fn<(uri: string) => void>()

    const wrapper = mount(MarkdownContent, {
      props: {
        content: '📄 [打开《简单word.docx》](/knowledge/files/raw?user_id=1&path=%E6%96%87%E6%A1%A3%2F%E7%AE%80%E5%8D%95word.docx)',
        citationMap: {},
        onNavigateSource,
      },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    const fileBlock = wrapper.get('.agent-mounted-file')
    expect(fileBlock.element.tagName).toBe('BUTTON')
    expect(fileBlock.text()).toContain('简单word.docx')
    expect(fileBlock.text()).toContain('文档/简单word.docx')
    expect(fileBlock.text()).toContain('2026-08-21 09:30')
    expect(fileBlock.text()).toContain('2.0 KB')
    expect(fileBlock.findAll('.agent-mounted-file__status')).toHaveLength(4)
    expect(wrapper.find('a[href*="/knowledge/files/raw"]').exists()).toBe(false)

    await fileBlock.trigger('click')
    expect(onNavigateSource).toHaveBeenCalledWith('文档/简单word.docx')
  })
})

describe('MarkdownContent streaming code highlight', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('highlights code blocks while still streaming (does not wait for finish)', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '```python\nprint("hi")\n```',
        isStreaming: true,
        citationMap: {},
      },
    })
    await nextTick()
    const code = wrapper.find('.markdown-body pre code')
    expect(code.exists()).toBe(true)
    expect(code.classes()).toContain('hljs')
    expect(code.element.innerHTML).toContain('<span')
  })

  it('falls back to plain text for unknown languages without dropping tags', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '```not-a-real-lang\n<b>x</b>\n```',
        citationMap: {},
      },
    })
    await nextTick()
    const code = wrapper.find('.markdown-body pre code')
    expect(code.exists()).toBe(true)
    expect(code.element.textContent).toContain('<b>x</b>')
    expect(code.element.innerHTML).not.toContain('<span')
  })

  it('renders growing lists, tables, and code without transient DOM wrappers', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '- 第一项',
        isStreaming: true,
        citationMap: {},
      },
    })
    await nextTick()

    expect(wrapper.findAll('li')).toHaveLength(1)

    await wrapper.setProps({ content: '- 第一项\n- 第二项\n\n| 名称 | 状态 |\n| --- | --- |\n| 图谱 | 抽取中 |' })
    await nextTick()

    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)

    await wrapper.setProps({ content: '- 第一项\n- 第二项\n\n| 名称 | 状态 |\n| --- | --- |\n| 图谱 | 抽取中 |\n\n```ts\nconst live = true' })
    await nextTick()

    expect(wrapper.get('pre code').text()).toContain('const live = true')
    expect(wrapper.find('.stream-reveal-word').exists()).toBe(false)
    expect(wrapper.find('.stream-cursor').exists()).toBe(false)
  })

  it('keeps completed Markdown block DOM stable while only the active tail grows', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '已完成段落\n\n正在生成',
        isStreaming: true,
        citationMap: {},
      },
    })
    await nextTick()
    const stableParagraph = wrapper.findAll('.markdown-body p')[0]?.element
    expect(stableParagraph).toBeDefined()

    await wrapper.setProps({ content: '已完成段落\n\n正在生成更多内容' })
    await nextTick()

    expect(wrapper.findAll('.markdown-body p')[0]?.element).toBe(stableParagraph)
    expect(wrapper.findAll('.markdown-body p')[1]?.text()).toContain('正在生成更多内容')
  })

  it('removes the stream cursor without altering the final markdown content', async () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: '**完成内容**',
        isStreaming: true,
        citationMap: {},
      },
    })
    await nextTick()

    await wrapper.setProps({ isStreaming: false })
    await nextTick()

    expect(wrapper.find('.stream-cursor').exists()).toBe(false)
    expect(wrapper.get('strong').text()).toBe('完成内容')
  })
})
