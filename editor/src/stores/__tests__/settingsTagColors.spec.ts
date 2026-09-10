/** Global shared tag-color application tests. */

import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useSettingsStore } from '@/stores/settings'

describe('settings tag colors', () => {
  beforeEach(() => {
    localStorage.clear()
    for (let index = 1; index <= 6; index += 1) {
      document.documentElement.style.removeProperty(`--color-tag-${index}`)
    }
    setActivePinia(createPinia())
  })

  it('applies all six profile colors as shared root variables', () => {
    const colors = ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666']
    const store = useSettingsStore()

    store.updateProfile({ tagColors: colors })

    colors.forEach((color, index) => {
      expect(document.documentElement.style.getPropertyValue(`--color-tag-${index + 1}`)).toBe(color)
    })
    expect(document.documentElement.style.getPropertyValue('--tag-color-library-strength')).toBe('30%')
    expect(document.documentElement.style.getPropertyValue('--tag-color-smart-strength')).toBe('16%')

    store.updateProfile({ tagColorsTranslucent: false })
    expect(document.documentElement.style.getPropertyValue('--tag-color-library-strength')).toBe('100%')
    expect(document.documentElement.style.getPropertyValue('--tag-color-smart-strength')).toBe('100%')
  })
})
