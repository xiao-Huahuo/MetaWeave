/**
 * Verifies complete semantic coverage and the DSH/morphicons rendering split.
 *
 * These tests deliberately exercise the shared icon boundary instead of every
 * page caller, because all small icons route through IcIcon.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import IcIcon from '@/components/common/IcIcon.vue'
import { DSH_ICON_FILES, FEATURE_ICON_FILES, MORPH_ICONS } from '@/components/common/iconRegistry'

const DSH_ASSETS = import.meta.glob('@/assets/icons/svg/dsh/*.svg', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const EXPECTED_ICON_NAMES = [
  'home', 'search', 'filter', 'sort', 'unfold', 'star', 'refresh', 'history',
  'new-folder', 'new-file', 'back', 'arrow-left', 'check', 'close', 'arrow-up',
  'arrow-down', 'folder-open', 'git', 'todo', 'graph', 'ingest', 'arrow-right',
  'multi-select', 'trash', 'document', 'folder', 'book', 'code', 'auto-awesome',
  'dashboard', 'feedback', 'bug', 'settings', 'dns', 'upload', 'cloud-upload',
  'chevron-right', 'chevron-down', 'unfold-less', 'add', 'replay', 'warning',
  'image', 'link', 'cancel', 'add-photo', 'language', 'save', 'label',
  'view-stream', 'grid-view', 'event', 'info', 'psychology', 'radio-unchecked',
  'spinner', 'layers', 'view-list', 'tune', 'center-focus', 'play', 'pause',
  'text-fields', 'block', 'error-outline', 'check-circle', 'download', 'edit',
  'visibility', 'visibility-off', 'view-column', 'group', 'add-comment', 'forum',
  'open-in-full', 'schedule', 'copy', 'thumb-up', 'thumb-down', 'open-in-new',
  'more-horiz', 'view-sidebar', 'shield', 'stop', 'send', 'build', 'fact-check',
  'file', 'archive', 'edit-note', 'table-chart', 'title', 'manage-search', 'hub',
  'checklist', 'calendar', 'cut', 'paste', 'remove',
] as const

describe('IcIcon', () => {
  it.each(['skills', 'mcp', 'ocr', 'llm', 'memory', 'floating-window', 'scanner', 'appearance', 'terminal'])(
    'renders downloaded %s artwork instead of a fallback tool icon', (name) => {
      const wrapper = mount(IcIcon, { props: { name, size: 16 } })
      const svg = wrapper.get('svg')
      expect(FEATURE_ICON_FILES[name]).toBeDefined()
      expect(svg.attributes('data-icon-source')).toBe('feature')
      expect(svg.attributes('data-icon-name')).toBe(name)
      expect(svg.findAll('path, rect, circle, polygon').length).toBeGreaterThan(0)
      expect(svg.get('g').attributes('fill')).toBe('none')
      expect(svg.html()).not.toMatch(/<(script|image|foreignObject)\b|https?:\/\/(?!www.w3.org)/u)
      wrapper.unmount()
    },
  )

  it('covers all 99 existing semantic icon names with local morph data', () => {
    expect(Object.keys(MORPH_ICONS).sort()).toEqual([...EXPECTED_ICON_NAMES].sort())
  })

  it('uses the 52 strict DSH matches by default', () => {
    expect(Object.keys(DSH_ICON_FILES)).toHaveLength(52)
    const wrapper = mount(IcIcon, { props: { name: 'search', size: 17 } })
    const svg = wrapper.get('svg')
    expect(svg.attributes('data-icon-source')).toBe('dsh')
    expect(svg.attributes('viewBox')).toBe('0 0 16 16')
    expect(svg.attributes('style')).toContain('font-size: 17px')
    expect(svg.findAll('path').length).toBeGreaterThan(0)
  })

  it('bundles all 70 valid local DSH SVG sources', () => {
    expect(Object.keys(DSH_ASSETS)).toHaveLength(70)
    for (const source of Object.values(DSH_ASSETS)) {
      expect(source).toMatch(/<svg\b[^>]*>[\s\S]*<\/svg>\s*$/u)
      expect(source.match(/xmlns=/gu)).toHaveLength(1)
    }
    for (const file of Object.values(DSH_ICON_FILES)) {
      expect(Object.keys(DSH_ASSETS).some((path) => path.endsWith(`/${file}`))).toBe(true)
    }
  })

  it('uses morphicons for a DSH-missing semantic', () => {
    const wrapper = mount(IcIcon, { props: { name: 'home', size: 18 } })
    const svg = wrapper.get('svg')
    expect(svg.attributes('data-icon-source')).toBe('morphicons')
    expect(svg.attributes('data-icon-name')).toBe('home')
    expect(svg.findAll('path').length).toBeGreaterThan(0)
  })

  it('keeps one morphicons svg mounted across an explicit state transition', async () => {
    const wrapper = mount(IcIcon, { props: { name: 'play', size: 16, morph: true } })
    const initialSvg = wrapper.get('svg').element
    await wrapper.setProps({ name: 'pause' })
    expect(wrapper.get('svg').element).toBe(initialSvg)
    expect(wrapper.get('svg').attributes('data-icon-name')).toBe('pause')
  })
})
