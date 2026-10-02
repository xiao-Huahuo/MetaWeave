/*
 * 安全全局开关回归：勾选代表启用，保存接口仍接收 *_disabled 的负向标志。
 * Usage: 串行运行本文件，验证加载后的开关与点击后保存的安全语义。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SafetySettingsSection from '../SafetySettingsSection.vue'

const { fetchSensitiveWords, saveSensitiveWords } = vi.hoisted(() => ({
  fetchSensitiveWords: vi.fn(),
  saveSensitiveWords: vi.fn().mockResolvedValue({}),
}))

vi.mock('@/api/settings', () => ({ fetchSensitiveWords, saveSensitiveWords }))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({ profile: { userId: 'safety-test' } }),
}))
vi.mock('@/api/vault', () => ({
  getVaultDebugMasterPassword: vi.fn(),
  getVaultStatus: vi.fn(),
  resetVaultPassword: vi.fn(),
}))

describe('safety enabled toggles', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([false, true])('loads disabled=%s as the opposite checked state and preserves the save contract', async (disabled) => {
    fetchSensitiveWords.mockResolvedValue({
      _sensitive_words_disabled: disabled,
      _safety_disabled: disabled,
      categories: {},
    })
    const wrapper = mount(SafetySettingsSection, {
      global: { stubs: { VaultPasswordResetDialog: true } },
    })
    await flushPromises()

    const toggles = wrapper.findAll<HTMLInputElement>('.safety-global-row input[type="checkbox"]')
    expect(toggles).toHaveLength(2)
    for (const toggle of toggles) {
      expect(toggle.element.checked).toBe(!disabled)
      await toggle.setValue(disabled)
    }
    const rows = wrapper.findAll('.safety-global-row')
    expect(rows.every((row) => row.text().includes(disabled ? '开启中' : '已关闭'))).toBe(true)
    expect(wrapper.find('.safety-global-warning').exists()).toBe(!disabled)

    await wrapper.get('.safety-heading-row button').trigger('click')
    await flushPromises()
    expect(saveSensitiveWords).toHaveBeenCalledWith(expect.objectContaining({
      _sensitive_words_disabled: !disabled,
      _safety_disabled: !disabled,
    }))
    wrapper.unmount()
  })
})
