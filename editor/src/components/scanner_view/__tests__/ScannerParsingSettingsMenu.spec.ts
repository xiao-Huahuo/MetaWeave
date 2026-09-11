/** Shared scanner parsing menu state and connectivity tests. */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ScannerParsingSettingsMenu from '@/components/scanner_view/ScannerParsingSettingsMenu.vue'
import { useSettingsStore } from '@/stores/settings'

describe('ScannerParsingSettingsMenu', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('automatically closes temporary online mode when MinerU is unreachable', async () => {
    useSettingsStore().updateProfile({ userId: 'u1', vlmEnabled: true })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ online: false, authorized: false, message: '当前无网络' }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const wrapper = mount(ScannerParsingSettingsMenu, {
      props: {
        ocrEnabled: true,
        onlineEnabled: true,
        'onUpdate:onlineEnabled': (value: boolean) => wrapper.setProps({ onlineEnabled: value }),
      },
      global: { stubs: { IcIcon: true, DropdownMenu: true, DropdownMenuContent: true, DropdownMenuItem: true, DropdownMenuPortal: true, DropdownMenuTrigger: true } },
    })
    await flushPromises()

    expect(wrapper.props('onlineEnabled')).toBe(false)
    expect(wrapper.emitted('error')?.[0]).toEqual(['当前无网络'])
  })
})
