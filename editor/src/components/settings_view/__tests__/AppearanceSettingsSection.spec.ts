/** Appearance settings UI tests for font and shared tag-color controls. */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppearanceSettingsSection from '@/components/settings_view/AppearanceSettingsSection.vue'
import libraryBarSource from '@/components/library_view/LibraryBar.vue?raw'
import libraryCardSource from '@/components/library_view/LibraryCard.vue?raw'
import libraryTagPickerSource from '@/components/library_view/LibraryTagPicker.vue?raw'
import libraryViewSource from '@/views/LibraryView.vue?raw'
import smartFormsSource from '@/views/SmartFormsView.vue?raw'

describe('AppearanceSettingsSection font sizes', () => {
  it('renders separate UI and editor text font-size controls', () => {
    const wrapper = mount(AppearanceSettingsSection, {
      props: {
        uiFontFamiliesDraft: [],
        textFontFamiliesDraft: [],
        uiFontSizePercentDraft: 90,
        textFontSizePercentDraft: 125,
        themePrimaryColorDraft: '#339cff',
        themeSoftColorDraft: '#339cff',
        tagColorsDraft: ['#7c5cfc', '#eb2463', '#26a269', '#2f88d5', '#e2a72e', '#0ea5b6'],
        tagColorsTranslucentDraft: true,
        themeOptions: [{ value: 'light', label: '亮色' }],
        themeMode: 'light',
        sidebarDisplayMode: 'icons',
        availableFontFamilies: [],
        fontsLoading: false,
        showBacklinks: false,
        userId: 'u1',
        backgroundCoverUrl: '/library/assets/u1/cover.png',
      },
      global: { stubs: { LibraryCoverUploader: { template: '<div class="cover-uploader-stub" />' } } },
    })

    expect(wrapper.text()).toContain('UI 字体大小')
    expect(wrapper.text()).toContain('正文字体大小')
    expect(wrapper.find('[data-font-size="ui"]').exists()).toBe(true)
    expect(wrapper.find('[data-font-size="text"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('显示反向链接')
    expect(wrapper.text()).toContain('背景封面图片')
    expect(wrapper.find('.cover-uploader-stub').exists()).toBe(true)
    expect(wrapper.get('button[aria-label="重置背景封面"]')).toBeTruthy()
    expect(wrapper.find('#show-backlinks-setting').attributes('checked')).toBeUndefined()
    expect(wrapper.findAll('input[type="color"][aria-label^="标签色"]')).toHaveLength(6)
    expect(wrapper.text()).toContain('保存标签色')
    expect(wrapper.text()).toContain('重置标签色')
    expect((wrapper.get('#tag-colors-translucent-setting').element as HTMLInputElement).checked).toBe(true)
  })

  it('uses the same six CSS variables in Library and Smart Forms tags', () => {
    for (let index = 1; index <= 6; index += 1) {
      const variable = `--color-tag-${index}`
      expect(libraryCardSource).toContain(variable)
      expect(libraryBarSource).toContain(variable)
      expect(libraryTagPickerSource).toContain(variable)
      expect(libraryViewSource).toContain(variable)
    }
    expect(smartFormsSource).toContain('var(--color-tag-${index + 1})')
  })
})
