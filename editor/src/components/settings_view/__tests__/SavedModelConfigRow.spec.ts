/** Shared saved-model row alignment and slot contract tests. */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SavedModelConfigRow from '@/components/settings_view/SavedModelConfigRow.vue'

describe('SavedModelConfigRow', () => {
  it('uses a library-bar-aligned visual anchor, metadata column, and action rail', () => {
    const wrapper = mount(SavedModelConfigRow, {
      props: { title: 'MinerU 精准', model: 'vlm', endpoint: 'MinerU API', detail: '200 MB · 600 页', icon: 'visibility' },
      slots: { actions: '<button type="button">加载</button>' },
      global: { stubs: { IcIcon: true } },
    })

    expect(wrapper.find('.saved-config-mark').exists()).toBe(true)
    expect(wrapper.find('.saved-config-main').text()).toContain('MinerU 精准')
    expect(wrapper.find('.saved-config-actions').text()).toContain('加载')
  })
})
