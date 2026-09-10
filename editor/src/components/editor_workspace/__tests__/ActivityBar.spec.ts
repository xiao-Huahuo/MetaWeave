/**
 * Activity bar navigation tests.
 *
 * Usage:
 * Verifies the knowledge-base group keeps the existing navigation events
 * while exposing its child entries through the animated submenu.
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ActivityBar from '@/components/editor_workspace/ActivityBar.vue'
import activityBarSource from '@/components/editor_workspace/ActivityBar.vue?raw'
import editorWorkspaceSource from '@/views/EditorWorkspace.vue?raw'

vi.mock('@/components/common/IcIcon.vue', () => ({
  default: { template: '<span />' },
}))

describe('ActivityBar', () => {
  it('allocates a 50 percent wider column in management mode', () => {
    expect(editorWorkspaceSource).toContain('const ACTIVITY_BAR_MANAGEMENT_WIDTH = 204')
  })

  it('keeps management icons and labels left aligned', () => {
    expect(activityBarSource).toContain('.activity-bar.management .activity-button > :deep(.ic-icon:not(.knowledge-chevron))')
    expect(activityBarSource).toMatch(/\.activity-bar\.management \.activity-label \{[^}]*width: 100%;[^}]*text-align: left;/)
  })

  it('compensates for the transparent padding around the Agent raster icon', () => {
    expect(activityBarSource).toMatch(/\.activity-agent-icon \{[^}]*width: 28px;[^}]*height: 28px;/s)
  })

  it('uses the queue-lane frame with mode-specific outer corners', () => {
    expect(editorWorkspaceSource).toContain('const ACTIVITY_BAR_ICON_WIDTH = 64')
    expect(activityBarSource).toMatch(
      /\.activity-bar \{[^}]*border: 1px solid var\(--color-activity-bar-border\);[^}]*background: var\(--color-activity-bar-bg\);[^}]*box-shadow: 0 0 0 4px var\(--color-activity-bar-ring\);/s,
    )
    expect(activityBarSource).toMatch(/\.activity-bar:not\(\.management\) \{[^}]*border-radius: 20px;/s)
    expect(activityBarSource).toMatch(/\.activity-bar\.management \{[^}]*left: -4px;[^}]*border-radius: 0 28px 28px 0;/s)
    expect(editorWorkspaceSource).toMatch(
      /\.main-shell\.ide-panel,[\s\S]*?\.editor-sidebar-content,[\s\S]*?\.agent-col \{[^}]*border: 1px solid var\(--workspace-panel-border\);[^}]*box-shadow: 0 0 0 4px var\(--workspace-panel-ring\);/s,
    )
  })

  it('matches the icon-mode knowledge submenu surface to the activity bar', () => {
    expect(activityBarSource).toMatch(
      /\.knowledge-submenu \{[^}]*min-width: 48px;[^}]*width: 48px;[^}]*padding: var\(--space-8\) 3px;[^}]*border: 1px solid var\(--color-activity-bar-border\);[^}]*border-radius: 20px;[^}]*background: var\(--color-activity-bar-bg\);[^}]*box-shadow: 0 0 0 4px var\(--color-activity-bar-ring\);/s,
    )
  })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const props = {
    displayMode: 'icons' as const,
    homeActive: false,
    fileOpen: false,
    gitActive: false,
    agentOpen: false,
    resourcesActive: false,
  favoritesActive: false,
  privacyActive: false,
    libraryActive: false,
    componentLibraryActive: false,
    vaultActive: false,
    formsActive: false,
    literatureActive: false,
    ingestionActive: false,
    batchScannerActive: false,
    visualizationActive: false,
    agentActive: false,
    agentQueueActive: false,
    graphActive: false,
    dashboardActive: false,
    debugActive: false,
    feedbackOpen: false,
    searchActive: false,
    browserActive: false,
    settingsActive: false,
    isDark: false,
  }

  it('opens knowledge submenu and preserves child navigation events', async () => {
    const wrapper = mount(ActivityBar, { props })

    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(false)
    await wrapper.get('button[aria-label="库"]').trigger('click')

    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(true)
    expect(wrapper.findAll('[aria-label="知识库菜单"] button')).toHaveLength(6)

    await wrapper.get('button[aria-label="组件库"]').trigger('click')
    expect(wrapper.emitted('openComponentLibrary')).toHaveLength(1)

    await wrapper.get('button[aria-label="库"]').trigger('click')

    await wrapper.get('button[aria-label="智能表格"]').trigger('click')
    expect(wrapper.emitted('openForms')).toHaveLength(1)
    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(false)

    await wrapper.get('button[aria-label="库"]').trigger('click')
    await wrapper.get('button[aria-label="文献阅读"]').trigger('click')
    expect(wrapper.emitted('openLiterature')).toHaveLength(1)
  })

  it('opens grouped menus only on click in icon mode', async () => {
    const wrapper = mount(ActivityBar, { props })
    const group = wrapper.get('.knowledge-group')
    const trigger = group.get('.knowledge-button')

    await group.trigger('mouseenter')
    expect(group.find('.knowledge-submenu').exists()).toBe(false)

    await trigger.trigger('click')

    expect(group.find('.knowledge-submenu').exists()).toBe(true)
    expect(wrapper.emitted('knowledgeMenuVisibilityChange')).toEqual([[true]])

    await group.trigger('mouseleave')
    expect(group.find('.knowledge-submenu').exists()).toBe(true)

    await trigger.trigger('click')
    expect(wrapper.emitted('knowledgeMenuVisibilityChange')).toEqual([[true], [false]])
  })

  it('closes an open library submenu when the user clicks elsewhere', async () => {
    const wrapper = mount(ActivityBar, { props, attachTo: document.body })
    await wrapper.get('button[aria-label="库"]').trigger('click')

    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(true)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps the submenu open after child navigation but lets the parent toggle it', async () => {
    const wrapper = mount(ActivityBar, { props: { ...props, displayMode: 'management' } })
    const knowledgeButton = wrapper.get('button[aria-label="库"]')

    await knowledgeButton.trigger('click')
    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(true)

    await wrapper.get('button[aria-label="图书馆"]').trigger('click')
    expect(wrapper.emitted('openLibrary')).toHaveLength(1)
    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(true)

    await knowledgeButton.trigger('click')
    expect(wrapper.find('[aria-label="知识库菜单"]').exists()).toBe(false)
  })

  it('marks the knowledge group active when a child view is active', () => {
    const wrapper = mount(ActivityBar, { props: { ...props, libraryActive: true } })

    expect(wrapper.get('button[aria-label="库"]').classes()).toContain('active')
  })

  it('gives all six library entries distinct color roles and aligns the four searchable libraries', async () => {
    const wrapper = mount(ActivityBar, { props })
    await wrapper.get('button[aria-label="库"]').trigger('click')
    const icons = wrapper.findAll('[aria-label="知识库菜单"] .library-entry-icon')

    expect(icons).toHaveLength(6)
    expect(icons.map((icon) => icon.classes().find((name) => name.startsWith('library-color-')))).toEqual([
      'library-color-files',
      'library-color-library',
      'library-color-components',
      'library-color-vault',
      'library-color-forms',
      'library-color-literature',
    ])
  })

  it('opens the embedded browser from its left-rail entry', async () => {
    const wrapper = mount(ActivityBar, { props })

    await wrapper.get('button[aria-label="浏览器"]').trigger('click')

    expect(wrapper.emitted('openBrowser')).toHaveLength(1)
  })

  it('opens the Agent queue from the entertainment submenu instead of the top-level rail', async () => {
    const wrapper = mount(ActivityBar, { props })

    expect(wrapper.find('.activity-bar > button[aria-label="任务队列"]').exists()).toBe(false)
    await wrapper.get('button[aria-label="娱乐功能"]').trigger('click')
    const menu = wrapper.get('[aria-label="娱乐功能菜单"]')
    await menu.get('button[aria-label="任务队列"]').trigger('click')

    expect(wrapper.emitted('openAgentQueue')).toHaveLength(1)
    expect(wrapper.find('[aria-label="娱乐功能菜单"]').exists()).toBe(false)
  })

  it('groups the scanner and scanner queue beneath one scan entry', async () => {
    const wrapper = mount(ActivityBar, { props })

    expect(wrapper.find('.activity-bar > button[aria-label="扫描器"]').exists()).toBe(false)
    expect(wrapper.find('.activity-bar > button[aria-label="扫描队列"]').exists()).toBe(false)
    await wrapper.get('button[aria-label="扫描"]').trigger('click')
    const menu = wrapper.get('[aria-label="扫描菜单"]')
    expect(menu.findAll('button')).toHaveLength(2)
    await menu.get('button[aria-label="扫描队列"]').trigger('click')

    expect(wrapper.emitted('openBatchScanner')).toHaveLength(1)
    expect(wrapper.find('[aria-label="扫描菜单"]').exists()).toBe(false)
  })

  it('marks the shared scan entry active for either child page', () => {
    const scanner = mount(ActivityBar, { props: { ...props, scannerActive: true } })
    const queue = mount(ActivityBar, { props: { ...props, batchScannerActive: true } })

    expect(scanner.get('button[aria-label="扫描"]').classes()).toContain('active')
    expect(queue.get('button[aria-label="扫描"]').classes()).toContain('active')
  })

  it('moves one shared hover indicator to the pointed navigation button', async () => {
    const wrapper = mount(ActivityBar, { props })
    const activityBar = wrapper.get('.activity-bar')
    const filesButton = wrapper.get('button[aria-label="Files"]')
    vi.spyOn(activityBar.element, 'getBoundingClientRect').mockReturnValue({ top: 10 } as DOMRect)
    vi.spyOn(filesButton.element, 'getBoundingClientRect').mockReturnValue({ top: 58 } as DOMRect)

    await filesButton.trigger('mouseover')

    const indicator = wrapper.get('.activity-hover-indicator')
    expect(indicator.attributes('style')).toContain('translate3d(0, 48px, 0)')
    expect(indicator.attributes('style')).toContain('opacity: 1')

    await activityBar.trigger('mouseleave')
    expect(indicator.attributes('style')).toContain('opacity: 0')
  })

  it('moves a shared hover indicator between knowledge submenu items', async () => {
    const wrapper = mount(ActivityBar, { props: { ...props, displayMode: 'management' } })
    await wrapper.get('button[aria-label="库"]').trigger('click')

    const submenu = wrapper.get('[aria-label="知识库菜单"]')
    const libraryButton = wrapper.get('button[aria-label="图书馆"]')
    vi.spyOn(submenu.element, 'getBoundingClientRect').mockReturnValue({ top: 100 } as DOMRect)
    vi.spyOn(libraryButton.element, 'getBoundingClientRect').mockReturnValue({ top: 144 } as DOMRect)

    await libraryButton.trigger('mouseover')

    const indicator = wrapper.get('.knowledge-hover-indicator')
    expect(indicator.attributes('style')).toContain('translate3d(0, 44px, 0)')
    expect(indicator.attributes('style')).toContain('opacity: 1')
  })

  it('keeps ingestion above Debug and My directly below Debug', () => {
    const wrapper = mount(ActivityBar, { props })
    const labels = wrapper.get('.bottom-group').findAll('.activity-button').map((button) => button.attributes('aria-label'))

    expect(labels).toEqual(['入库进度', 'Debug', '我的', 'Settings'])
    expect(wrapper.find('button[aria-label="娱乐功能"]').exists()).toBe(true)
  })
})
