/** User-specific safety switches and removal of plaintext-password debug/reset paths. */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SafetySettingsSection from '../SafetySettingsSection.vue'

const { fetchSensitiveWords, saveSensitiveWords, fetchSafetyConfig, saveSafetyConfig, changeAccountPassword, logout, updateProfile } = vi.hoisted(() => ({
  fetchSensitiveWords: vi.fn(), saveSensitiveWords: vi.fn().mockResolvedValue({}), fetchSafetyConfig: vi.fn(),
  saveSafetyConfig: vi.fn(), changeAccountPassword: vi.fn().mockResolvedValue({ ok: true }), logout: vi.fn().mockResolvedValue(undefined), updateProfile: vi.fn(),
}))
vi.mock('@/api/settings', () => ({ fetchSensitiveWords, saveSensitiveWords, fetchSafetyConfig, saveSafetyConfig }))
vi.mock('@/api/auth', () => ({ changeAccountPassword }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ logout }) }))
vi.mock('@/stores/settings', () => ({ useSettingsStore: () => ({ profile: { userId: '82631459' }, updateProfile }) }))

describe('account safety settings', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([false, true])('loads enabled=%s from this account and saves switches outside the shared word list', async (enabled) => {
    fetchSensitiveWords.mockResolvedValue({ _sensitive_words_disabled: enabled, _safety_disabled: enabled, categories: {} })
    fetchSafetyConfig.mockResolvedValue({ sensitive_words_enabled: enabled, safety_enabled: enabled })
    saveSafetyConfig.mockResolvedValue({ sensitive_words_enabled: !enabled, safety_enabled: !enabled })
    const wrapper = mount(SafetySettingsSection, { global: { stubs: { AccountPasswordDialog: true } } })
    await flushPromises()
    const toggles = wrapper.findAll<HTMLInputElement>('.safety-global-row input[type="checkbox"]')
    for (const toggle of toggles) { expect(toggle.element.checked).toBe(enabled); await toggle.setValue(!enabled) }
    await wrapper.get('.safety-heading-row button').trigger('click')
    await flushPromises()
    expect(saveSafetyConfig).toHaveBeenCalledWith('82631459', { sensitive_words_enabled: !enabled, safety_enabled: !enabled })
    expect(saveSensitiveWords.mock.calls[0]?.[0]).not.toHaveProperty('_safety_disabled')
    expect(saveSensitiveWords.mock.calls[0]?.[0]).not.toHaveProperty('_sensitive_words_disabled')
    expect(wrapper.text()).not.toContain('获取密码库主密码')
    expect(wrapper.text()).not.toContain('重设密码库密码')
    wrapper.unmount()
  })

  it('changes the global login password and then requires a fresh login', async () => {
    fetchSensitiveWords.mockResolvedValue({ categories: {} })
    fetchSafetyConfig.mockResolvedValue({ sensitive_words_enabled: true, safety_enabled: true })
    const wrapper = mount(SafetySettingsSection, { global: { stubs: { AccountPasswordDialog: true } } })
    await flushPromises()
    wrapper.getComponent({ name: 'AccountPasswordDialog' }).vm.$emit('submit', 'old-password', 'new-password', 'new-password')
    await flushPromises()
    expect(changeAccountPassword).toHaveBeenCalledWith('old-password', 'new-password')
    expect(logout).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
