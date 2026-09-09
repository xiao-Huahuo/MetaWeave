/** OCR preview overlay geometry and interaction tests. */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OcrBlockOverlay from '@/components/common/OcrBlockOverlay.vue'

describe('OcrBlockOverlay', () => {
  it('uses source coordinates and shares hover plus locked selection ids', async () => {
    const wrapper = mount(OcrBlockOverlay, {
      props: {
        page: 1,
        width: 800,
        height: 600,
        activeBlockId: '1:7',
        blocks: [{ page: 1, type: 'table', content: 'A', bbox: [80, 60, 400, 300], id: 7, order: 0 }],
      },
    })
    const rect = wrapper.get('rect[data-block-id="1:7"]')

    expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 800 600')
    expect(rect.attributes()).toMatchObject({ x: '80', y: '60', width: '320', height: '240' })
    expect(rect.classes()).toContain('active')

    await rect.trigger('pointerenter')
    await rect.trigger('click')
    expect(wrapper.emitted('blockHover')).toEqual([['1:7']])
    expect(wrapper.emitted('blockSelect')).toEqual([['1:7']])
  })
})
