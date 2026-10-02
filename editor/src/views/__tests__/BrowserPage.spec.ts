/*
 * Embedded browser page theme and managed-navigation regression tests.
 *
 * Usage:
 * Verifies that the application theme mode reaches the native Chromium view
 * both at creation time and after a live theme switch, and that a DSH access
 * token reaches native navigation without appearing in the address bar.
 */
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import BrowserPage from '../BrowserPage.vue'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/api/settings', () => ({
  fetchWebSearchConfig: vi.fn().mockResolvedValue({
    browser_proxy_url: '',
    proxy_url: '',
    browser_home_url: 'https://example.com',
  }),
}))

const BrowserChromeStub = defineComponent({
  name: 'BrowserChrome',
  props: { address: { type: String, default: '' } },
  emits: ['bounds'],
  mounted() {
    this.$emit('bounds', { x: 10, y: 20, width: 600, height: 400 })
  },
  template: '<div />',
})

describe('BrowserPage theme synchronization', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('configures Chromium for the initial and updated application theme', async () => {
    const browserShow = vi.fn().mockResolvedValue(true)
    const browserConfigure = vi.fn().mockResolvedValue(true)
    Object.defineProperty(window, 'agentEditorDesktop', {
      configurable: true,
      value: {
        isDesktop: true,
        browserShow,
        browserConfigure,
        browserHide: vi.fn().mockResolvedValue(true),
        browserSetBounds: vi.fn().mockResolvedValue(true),
        browserNavigate: vi.fn().mockResolvedValue(true),
        browserCommand: vi.fn().mockResolvedValue(true),
        onBrowserState: vi.fn().mockReturnValue(() => {}),
      },
    })
    const settingsStore = useSettingsStore()
    settingsStore.setThemeMode('dark')

    const wrapper = mount(BrowserPage, {
      props: { activityOverlayOpen: false },
      global: { stubs: { BrowserChrome: BrowserChromeStub } },
    })
    await flushPromises()

    expect(browserShow).toHaveBeenCalledWith(expect.objectContaining({ themeMode: 'dark' }))

    settingsStore.setThemeMode('light')
    await flushPromises()
    expect(browserConfigure).toHaveBeenLastCalledWith(expect.objectContaining({ themeMode: 'light' }))

    wrapper.unmount()
  })

  it('keeps a managed DSH authentication fragment out of the address bar', async () => {
    const requestedUrl = 'http://127.0.0.1:3080/#mw_token=test-token&session=child-session&readonly=1'
    const displayUrl = 'http://127.0.0.1:3080/#session=child-session&readonly=1'
    const browserNavigate = vi.fn().mockResolvedValue(true)
    let receiveState: ((state: BrowserViewState) => void) | undefined
    Object.defineProperty(window, 'agentEditorDesktop', {
      configurable: true,
      value: {
        isDesktop: true,
        browserShow: vi.fn().mockResolvedValue(true),
        browserConfigure: vi.fn().mockResolvedValue(true),
        browserHide: vi.fn().mockResolvedValue(true),
        browserSetBounds: vi.fn().mockResolvedValue(true),
        browserNavigate,
        browserCommand: vi.fn().mockResolvedValue(true),
        onBrowserState: vi.fn((callback) => {
          receiveState = callback
          return () => {}
        }),
      },
    })

    const wrapper = mount(BrowserPage, {
      props: { activityOverlayOpen: false, initialUrl: requestedUrl, sidebar: true },
      global: { stubs: { BrowserChrome: BrowserChromeStub } },
    })
    await flushPromises()

    expect(browserNavigate).toHaveBeenCalledWith(requestedUrl)
    expect(wrapper.findComponent(BrowserChromeStub).props('address')).not.toContain('test-token')
    receiveState?.({ url: displayUrl, title: 'DSH', canGoBack: false, canGoForward: false, loading: false })
    await flushPromises()
    expect(wrapper.findComponent(BrowserChromeStub).props('address')).toBe(displayUrl)

    wrapper.unmount()
  })
})
