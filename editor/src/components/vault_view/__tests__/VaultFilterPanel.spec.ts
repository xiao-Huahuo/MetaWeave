/*
 * Password-vault filter panel tests.
 * Verifies that search input lives in the filter panel and updates its model.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import VaultFilterPanel from '../VaultFilterPanel.vue'
import filterPanelSource from '../VaultFilterPanel.vue?raw'

vi.mock('@/components/common/IcIcon.vue', () => ({
  default: { template: '<span />' },
}))

describe('VaultFilterPanel', () => {
  it('emits the sidebar search query', async () => {
    const wrapper = mount(VaultFilterPanel, {
      props: {
        query: '',
        tag: '',
        itemType: '',
        tags: [],
        counts: {},
      },
    })

    const search = wrapper.get('input[type="search"]')
    await search.setValue('邮箱')

    expect(search.attributes('placeholder')).toBe('搜索密码库')
    expect(wrapper.emitted('update:query')).toEqual([['邮箱']])
  })

  it('constrains the search field to the sidebar track', () => {
    expect(filterPanelSource).toContain('flex-direction: column')
    expect(filterPanelSource).toContain('.filter-search')
    expect(filterPanelSource).toContain('max-width: 100%')
  })

  it('uses the component-library translucent bordered card as its sidebar shell', () => {
    expect(filterPanelSource).toMatch(
      /\.filter-panel\s*\{[^}]*margin:\s*var\(--space-12\);[^}]*border:\s*1px solid var\(--color-border\);[^}]*border-radius:\s*28px;[^}]*background:\s*var\(--color-surface\);[^}]*outline:\s*2px solid var\(--workspace-panel-outline\);[^}]*outline-offset:\s*2px;[^}]*box-shadow:\s*0 0 0 2px var\(--library-form-ring\);/su,
    )
  })

  it('places password types before tags and uses the sidebar text colors', () => {
    const wrapper = mount(VaultFilterPanel, {
      props: {
        query: '',
        tag: '',
        itemType: '',
        tags: [{ tag_id: 'tag-1', name: '工作' }],
        counts: {},
      },
    })
    const buttons = wrapper.findAll('button')
    const lastTypeIndex = buttons.map((button) => button.classes().includes('type-filter')).lastIndexOf(true)
    const tagIndex = buttons.findIndex((button) => button.classes('tag-pill'))

    expect(tagIndex).toBeGreaterThan(lastTypeIndex)
    expect(filterPanelSource).toMatch(/\.tag-pill\s*\{[^}]*color:\s*var\(--color-text-secondary\);/su)
    expect(filterPanelSource).toMatch(/\.tag-pill\s*\{[^}]*min-height:\s*38px;[^}]*font-size:\s*calc\(13px \* var\(--font-scale\)\);/su)
    expect(filterPanelSource).toMatch(/\.tag-list\s*\{[^}]*gap:\s*0;/su)
  })
})
