/** Real global login, persisted initialization, blocked save and minimum loader UI regression. */
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuthView from '@/views/AuthView.vue'
import AuthFormShell from '@/components/auth_view/AuthFormShell.vue'
import KnowledgeLibraryStep from '@/components/auth_view/KnowledgeLibraryStep.vue'
import ModelConfigStep from '@/components/auth_view/ModelConfigStep.vue'
import PreferencesStep from '@/components/auth_view/PreferencesStep.vue'
import { useAuthStore } from '@/stores/auth'

const { loginAccount, registerAccount, restoreAccount, advanceOnboarding, loadOnboardingDraft, saveOnboardingPage, saveOnboardingModel } = vi.hoisted(() => ({
  loginAccount: vi.fn(), registerAccount: vi.fn(), restoreAccount: vi.fn(), advanceOnboarding: vi.fn(),
  loadOnboardingDraft: vi.fn(), saveOnboardingPage: vi.fn(), saveOnboardingModel: vi.fn(),
}))
vi.mock('@/api/auth', () => ({ loginAccount, registerAccount, restoreAccount, advanceOnboarding, logoutAccount: vi.fn(), fetchCurrentAccount: vi.fn() }))
vi.mock('@/components/auth_view/onboarding', () => ({ loadOnboardingDraft, saveOnboardingPage, saveOnboardingModel }))
const session = { token: 'real-session', user_id: '82631459', username: '雾松', onboarding_step: 2, onboarding_completed: false, expires_at: '2030-01-01T00:00:00Z' }

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('{"user_id":"82631459","knowledge_dir":"D:/Knowledge"}', { status: 200 })))
  loginAccount.mockResolvedValue(session)
  registerAccount.mockResolvedValue(session)
  restoreAccount.mockResolvedValue({ status: 'missing' })
  loadOnboardingDraft.mockImplementation(async (_id, draft) => { draft.knowledgeDir = 'D:/Knowledge' })
  saveOnboardingPage.mockResolvedValue(undefined)
  saveOnboardingModel.mockResolvedValue(undefined)
  advanceOnboarding.mockImplementation(async (step) => ({ ...session, onboarding_step: step, onboarding_completed: step === 6 }))
})
afterEach(() => { useAuthStore().clear(); vi.useRealTimers(); vi.unstubAllGlobals() })

function mountEntry(backendReady = false) {
  return mount(AuthView, { props: { backendReady }, global: { plugins: [createPinia()], stubs: { IcIcon: true, LineWaves: true } } })
}
async function submitLogin(wrapper: ReturnType<typeof mountEntry>) {
  await wrapper.get('input[autocomplete="username"]').setValue('雾松')
  await wrapper.get('input[autocomplete="current-password"]').setValue('correct-password')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

describe('global account entry', () => {
  it('keeps the transformed page viewport at horizontal origin while preserving vertical scrolling', async () => {
    const wrapper = mountEntry()
    const viewport = wrapper.get<HTMLElement>('.auth-viewport')
    viewport.element.scrollLeft = 120
    viewport.element.scrollTop = 67
    await viewport.trigger('scroll')
    expect(viewport.element.scrollLeft).toBe(0)
    expect(viewport.element.scrollTop).toBe(67)
    wrapper.unmount()
  })
  it('starts on login and prevents arbitrary five-page navigation before authentication', async () => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({ userId: 'old-user' }))
    const wrapper = mountEntry()
    expect(wrapper.get('.auth-page-number').text()).toBe('01')
    expect(wrapper.findAll('.auth-navigation button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    wrapper.getComponent(AuthFormShell).vm.$emit('navigate', 1)
    await wrapper.vm.$nextTick()
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(0)
    expect(useAuthStore().authenticated).toBe(false)
    expect(localStorage.getItem('agent_editor_profile')).toBeNull()
    wrapper.unmount()
  })

  it('manually authenticates, restores absolute defaults and uses the native directory picker', async () => {
    const picker = vi.fn().mockResolvedValue('D:/SelectedKnowledge')
    vi.stubGlobal('agentEditorDesktop', { selectDirectory: picker })
    const wrapper = mountEntry()
    await submitLogin(wrapper)
    expect(loginAccount).toHaveBeenCalledWith({ username: '雾松', password: 'correct-password' })
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(1)
    expect(wrapper.get<HTMLInputElement>('input[autocomplete="current-password"]').element.value).toBe('')
    const step = wrapper.getComponent(KnowledgeLibraryStep)
    expect((step.findAll('input')[1]!.element as HTMLInputElement).value).toBe('D:/Knowledge')
    await step.get('button[aria-label="选择知识目录"]').trigger('click')
    await flushPromises()
    expect(picker).toHaveBeenCalledOnce()
    expect((step.findAll('input')[1]!.element as HTMLInputElement).value).toBe('D:/SelectedKnowledge')
    wrapper.unmount()
  })

  it('saves each page before advancing persisted progress and stays on a failed page', async () => {
    const wrapper = mountEntry()
    await submitLogin(wrapper)
    saveOnboardingPage.mockRejectedValueOnce(new Error('目录无法写入'))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain('目录无法写入')
    expect(advanceOnboarding).not.toHaveBeenCalled()
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(1)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(saveOnboardingPage).toHaveBeenCalledWith(session.user_id, expect.objectContaining({ knowledgeDir: 'D:/Knowledge' }), 1, expect.any(String))
    expect(advanceOnboarding).toHaveBeenCalledWith(3)
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(2)
    wrapper.getComponent(ModelConfigStep).vm.$emit('save', 'vision')
    await flushPromises()
    expect(saveOnboardingModel).toHaveBeenCalledWith(session.user_id, expect.any(Object), 'vision')
    wrapper.unmount()
  })

  it('restores incomplete progress, but completed accounts cannot access onboarding pages', async () => {
    loginAccount.mockResolvedValueOnce({ ...session, onboarding_step: 4 })
    const wrapper = mountEntry()
    await submitLogin(wrapper)
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(3)
    wrapper.unmount()
    useAuthStore().clear()
    loginAccount.mockResolvedValueOnce({ ...session, onboarding_step: 6, onboarding_completed: true })
    const complete = mountEntry()
    await submitLogin(complete)
    expect(useAuthStore().canEnter).toBe(true)
    expect(complete.get('.auth-page-number').text()).toBe('01')
    expect(complete.findAll('.auth-navigation button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    complete.unmount()
  })

  it('places the real automatic loader left of Confirm for at least two seconds', async () => {
    vi.useFakeTimers()
    restoreAccount.mockResolvedValue({ status: 'available', username: '雾松', state: { ...session, onboarding_completed: true, onboarding_step: 6 } })
    const wrapper = mountEntry(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.get('.auth-confirm-loader').element.nextElementSibling?.textContent).toBe('确定')
    expect(wrapper.get<HTMLInputElement>('input[autocomplete="username"]').element.value).toBe('雾松')
    expect(useAuthStore().canEnter).toBe(false)
    await vi.advanceTimersByTimeAsync(1_999)
    expect(wrapper.find('.auth-confirm-loader').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    expect(useAuthStore().canEnter).toBe(true)
    wrapper.unmount()
  })
  it('resets the complete theme group by clearing real backend overrides without advancing progress', async () => {
    loginAccount.mockResolvedValueOnce({ ...session, onboarding_step: 4 })
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"user_id":"82631459","theme_primary_color":"","theme_soft_color":""}'))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mountEntry()
    await submitLogin(wrapper)
    wrapper.getComponent(PreferencesStep).vm.$emit('resetColors')
    await flushPromises()
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/settings/appearance/config')
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: '82631459', theme_primary_color: '', theme_soft_color: '' })
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(3)
    expect(advanceOnboarding).not.toHaveBeenCalled()
    expect(wrapper.get('[role="status"]').text()).toContain('主题色已重置')
    wrapper.unmount()
  })
  it('returns from page02 to login01 then advances back without reauthenticating or renewing the session', async () => {
    const wrapper = mountEntry()
    await submitLogin(wrapper)
    const original = { ...useAuthStore().session! }
    wrapper.getComponent(AuthFormShell).vm.$emit('navigate', -1)
    await flushPromises()
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(0)
    expect(wrapper.get('h1').text()).toBe('登录')
    expect(wrapper.get<HTMLInputElement>('input[autocomplete="username"]').element.value).toBe(session.username)
    expect(wrapper.get<HTMLInputElement>('input[autocomplete="current-password"]').element.value).toBe('')
    wrapper.getComponent(AuthFormShell).vm.$emit('navigate', 1)
    await flushPromises()
    expect(wrapper.getComponent(AuthFormShell).props('page')).toBe(1)
    expect(loginAccount).toHaveBeenCalledOnce()
    expect(registerAccount).not.toHaveBeenCalled()
    expect(advanceOnboarding).not.toHaveBeenCalled()
    expect(useAuthStore().session?.token).toBe(original.token)
    expect(useAuthStore().session?.expires_at).toBe(original.expires_at)
    wrapper.unmount()
  })
})
