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
import markdownIcon from 'material-icon-theme/icons/markdown.svg?url'
import pythonIcon from 'material-icon-theme/icons/python.svg?url'
import vueIcon from 'material-icon-theme/icons/vue.svg?url'
import pdfIcon from 'material-icon-theme/icons/pdf.svg?url'
import imageIcon from 'material-icon-theme/icons/image.svg?url'

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
    expect(sourceLink.get('.markdown-link-icon img').attributes('src')).toBe(markdownIcon)
  })

  it('uses target file types for relative, absolute, encoded, and attachment Markdown links', async () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: [
        '[AgentCore](D:/Projects/agent_core.py:203)',
        '[组件](./src/View.vue)',
        '[文档](file:///D:/Knowledge/%E8%B5%84%E6%96%99.pdf)',
        '[附件](session-upload://u1/library/s1/image.png)',
        '[Windows](D:%5C资料%5Cmain.py)',
      ].join(' · ') },
    })
    const links = wrapper.findAll('a')
    expect(links.map((link) => link.text())).toEqual(['AgentCore', '组件', '文档', '附件', 'Windows'])
    expect(links.map((link) => link.get('.markdown-link-icon img').attributes('src'))).toEqual([
      pythonIcon, vueIcon, pdfIcon, imageIcon, pythonIcon,
    ])
    expect(links[0]?.attributes('href')).toBe('D:/Projects/agent_core.py:203')
  })

  it('requests only the website origin and keeps a fallback on favicon failure', async () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: '[网站](https://github.com/private/path?token=secret#part)' },
    })
    const image = wrapper.get('.markdown-link-icon img')
    const iconUrl = new URL(image.attributes('src'))
    expect(iconUrl.origin).toBe('https://t0.gstatic.com')
    expect(iconUrl.searchParams.get('url')).toBe('https://github.com')
    expect(image.attributes('referrerpolicy')).toBe('no-referrer')
    await image.trigger('error')
    expect(wrapper.find('.markdown-link-icon img').exists()).toBe(false)
    expect(wrapper.find('.markdown-link-icon__fallback').exists()).toBe(true)
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [{ name: 'added.md', path: 'added.md', isDir: false }]
    await nextTick()
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(wrapper.findAll('.markdown-link-icon')).toHaveLength(1)
  })

  it('keeps icon clicks out of image preview and excludes icons from its gallery', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [{ name: 'source.md', path: 'source.md', isDir: false }]
    const onNavigateSource = vi.fn<(uri: string) => void>()
    const wrapper = mount(MarkdownContent, {
      props: { content: 'source.md\n\n![插图](https://example.com/diagram.png)', onNavigateSource },
    })
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    await wrapper.get('.source-file-link img').trigger('click')
    expect(onNavigateSource).toHaveBeenCalledWith('source.md')
    expect(openImagePreview).not.toHaveBeenCalled()
    await wrapper.get('p > img').trigger('click')
    expect(openImagePreview).toHaveBeenCalledWith([{ src: 'https://example.com/diagram.png', alt: '插图' }], 0)
  })

  it('keeps dangerous links sanitized and leaves fragment, mail, image, and code links undecorated', () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: '[锚点](#part) [邮件](mailto:hello@example.com) [![图](https://example.com/p.png)](https://example.com)\n\n`[代码](https://github.com)`\n\n<a href="javascript:alert(1)">危险</a>' },
    })
    expect(wrapper.find('.markdown-link-icon').exists()).toBe(false)
    expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
    expect(wrapper.findAll('img')).toHaveLength(1)
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

  it.each([
    ['prose', '长段落正文'.repeat(2000), '继续输出', 'p'],
    ['code', '```python\n' + 'print("长代码块")\n'.repeat(200), 'print("后续")', 'pre code'],
    ['list', '- 已生成条目\n- 当前条目', '\n- 后续条目', 'li'],
    ['table', '| 列名 |\n| --- |\n| 已生成行 |', '\n| 后续行 |', 'tbody tr'],
  ])('preserves the active %s prefix DOM while more text streams', async (_name, prefix, delta, selector) => {
    const wrapper = mount(MarkdownContent, {
      props: { content: prefix, isStreaming: true },
    })
    const prefixNode = wrapper.get(selector).element
    const prefixText = prefixNode.firstChild
    await wrapper.setProps({ content: prefix + delta })
    expect(wrapper.get(selector).element === prefixNode).toBe(true)
    expect(wrapper.get(selector).element.firstChild === prefixText).toBe(true)
    expect(wrapper.text()).toContain(delta.replace(/^\s*- /, '').replace(/\|/g, '').trim())
    wrapper.unmount()
  })

  it('decorates streaming links without duplicating icons or replacing completed blocks', async () => {
    const prefix = '[网站](https://github.com)\n\n'
    const wrapper = mount(MarkdownContent, {
      props: { content: prefix + '[脚本](./main.py)', isStreaming: true },
    })
    const stableLink = wrapper.get('a[href="https://github.com"]').element
    expect(wrapper.findAll('.markdown-link-icon')).toHaveLength(2)
    await wrapper.setProps({ content: prefix + '[脚本](./main.py) 后续内容' })
    expect(wrapper.get('a[href="https://github.com"]').element).toBe(stableLink)
    expect(wrapper.findAll('.markdown-link-icon')).toHaveLength(2)
    await wrapper.setProps({ isStreaming: false })
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(wrapper.findAll('.markdown-link-icon')).toHaveLength(2)
  })

  it('keeps the active link icon loaded while following text grows', async () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: '[脚本](./main.py)', isStreaming: true },
    })
    const icon = wrapper.get('.markdown-link-icon').element
    await wrapper.get('.markdown-link-icon img').trigger('load')
    await wrapper.setProps({ content: '[脚本](./main.py) 继续输出' })
    expect(wrapper.get('.markdown-link-icon').element === icon).toBe(true)
    expect(wrapper.get('.markdown-link-icon').classes()).toContain('is-loaded')
    await wrapper.setProps({ content: '[脚本](./next.vue) 继续输出' })
    await wrapper.get('.markdown-link-icon img').trigger('load')
    expect(wrapper.get('.markdown-link-icon').classes()).toContain('is-loaded')
    wrapper.unmount()
  })

  it('keeps a failed link icon fallback instead of retrying on each body batch', async () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: '[网站](https://example.com)', isStreaming: true },
    })
    const icon = wrapper.get('.markdown-link-icon').element
    await wrapper.get('.markdown-link-icon img').trigger('error')
    await wrapper.setProps({ content: '[网站](https://example.com) 继续输出' })
    expect(wrapper.get('.markdown-link-icon').element === icon).toBe(true)
    expect(wrapper.find('.markdown-link-icon img').exists()).toBe(false)
    expect(wrapper.find('.markdown-link-icon__fallback').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps long text laid out while still repairing newly completed inline markup', async () => {
    const prefix = '长段落正文'.repeat(400)
    const wrapper = mount(MarkdownContent, {
      props: { content: prefix, isStreaming: true },
    })
    const firstText = wrapper.get('p').element.firstChild
    await wrapper.setProps({ content: prefix + '后续正文' })
    expect(firstText?.nodeValue).toBe(prefix)
    await wrapper.setProps({ content: prefix + '后续正文 **强调内容** [链接](https://example.com)' })
    expect(wrapper.get('strong').text()).toBe('强调内容')
    expect(wrapper.get('a').text()).toBe('链接')
    await wrapper.setProps({ content: prefix + '后续正文 **强调内容** [链接](https://example.com) <img src="x" onerror="alert(1)">', isStreaming: false })
    expect(wrapper.text()).toContain(prefix + '后续正文 强调内容')
    expect(wrapper.get('img[src="x"]').attributes('onerror')).toBeUndefined()
    wrapper.unmount()
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
