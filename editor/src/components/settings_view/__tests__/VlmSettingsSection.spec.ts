/** OCR/VLM settings layout and persistence contract tests. */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import VlmSettingsSection from '@/components/settings_view/VlmSettingsSection.vue'
import { useSettingsStore } from '@/stores/settings'

const config = {
  user_id: 'u1', enabled: false, api_key: '', configured: false, base_url: 'https://mineru.net', model: 'vlm',
  max_concurrency: 2, max_file_bytes: 209715200, max_pages: 600, submit_rate_per_minute: 300,
  result_rate_per_minute: 1000, batch_max_files: 200, poll_interval_seconds: 3, timeout_seconds: 300, ocr_enabled: false,
}

describe('VlmSettingsSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useSettingsStore().updateProfile({ userId: 'u1' })
  })

  it('shows the persisted VLM master switch, OCR switch, model and official limits', async () => {
    let requestCount = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => {
      requestCount += 1
      return requestCount === 1
        ? new Response(JSON.stringify(config), { status: 200, headers: { 'Content-Type': 'application/json' } })
        : new Response('missing preset endpoint', { status: 404 })
    }))
    const wrapper = mount(VlmSettingsSection)
    await flushPromises()

    expect(wrapper.text()).toContain('开启 VLM')
    expect(wrapper.text()).toContain('OCR')
    expect(wrapper.get('#vlm-model').element).toBeInstanceOf(HTMLSelectElement)
    expect(wrapper.findAll('.vlm-limits-grid input')).toHaveLength(5)
    await wrapper.get('button.edit-model-btn').trigger('click')
    expect(wrapper.get('#vlm-preset-name').isVisible()).toBe(true)
  })
})
