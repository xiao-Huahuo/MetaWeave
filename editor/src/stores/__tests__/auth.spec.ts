/** Fixed-expiry automatic login, stale completion and explicit manual-renewal regression. */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { getApiSessionToken } from '@/api/client'

const { restoreAccount, loginAccount, registerAccount, logoutAccount, advanceOnboarding, fetchCurrentAccount, settings } = vi.hoisted(() => ({
  restoreAccount: vi.fn(), loginAccount: vi.fn(), registerAccount: vi.fn(), logoutAccount: vi.fn(), advanceOnboarding: vi.fn(), fetchCurrentAccount: vi.fn(),
  settings: { setUserId: vi.fn(), clearUserId: vi.fn(), refreshUserProfile: vi.fn().mockResolvedValue({ user_id: '82631459' }) },
}))
vi.mock('@/api/auth', () => ({ restoreAccount, loginAccount, registerAccount, logoutAccount, advanceOnboarding, fetchCurrentAccount }))
vi.mock('@/stores/settings', () => ({ useSettingsStore: () => settings }))
const session = { token: 'real-session', user_id: '82631459', username: '雾松', onboarding_step: 6, onboarding_completed: true, expires_at: '2030-01-01T00:00:00Z' }

beforeEach(() => {
  vi.clearAllMocks(); vi.useFakeTimers(); setActivePinia(createPinia())
  logoutAccount.mockResolvedValue({ ok: true })
  settings.refreshUserProfile.mockResolvedValue({ user_id: '82631459' })
})
afterEach(() => { useAuthStore().clear(); vi.useRealTimers() })

describe('authentication owner', () => {
  it('removes only legacy vault credential caches at initialization and never persists the new session', async () => {
    sessionStorage.setItem('metaweave_vault_token_01', 'legacy-private-key')
    sessionStorage.setItem('metaweave_vault_token_02', 'another-legacy-key')
    sessionStorage.setItem('other-ui-cache', 'preserve')
    const store = useAuthStore()
    expect(sessionStorage.getItem('metaweave_vault_token_01')).toBeNull()
    expect(sessionStorage.getItem('metaweave_vault_token_02')).toBeNull()
    expect(sessionStorage.getItem('other-ui-cache')).toBe('preserve')
    loginAccount.mockResolvedValue(session)
    await store.authenticate({ username: '雾松', password: 'correct-password' })
    expect(JSON.stringify(sessionStorage)).not.toContain(session.token)
    expect(JSON.stringify(localStorage)).not.toContain(session.token)
    sessionStorage.removeItem('other-ui-cache')
  })
  it('shows restored username but grants access only after 2 seconds', async () => {
    restoreAccount.mockResolvedValue({ status: 'available', username: session.username, state: session })
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.rememberedUsername).toBe('雾松')
    expect(store.busy).toBe(true)
    expect(store.canEnter).toBe(false)
    await vi.advanceTimersByTimeAsync(1_999)
    expect(store.canEnter).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    await restore
    expect(store.canEnter).toBe(true)
    expect(getApiSessionToken()).toBe(session.token)
  })

  it('waits for slow validation after the minimum spinner interval', async () => {
    let finish!: (value: unknown) => void
    restoreAccount.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(store.busy).toBe(true)
    expect(store.canEnter).toBe(false)
    finish({ status: 'available', state: session })
    await restore
    expect(store.canEnter).toBe(true)
  })

  it('never logs in or renews an expired credential until the explicit password submission', async () => {
    restoreAccount.mockResolvedValue({ status: 'expired', username: session.username })
    loginAccount.mockResolvedValue(session)
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(2_000)
    await restore
    expect(store.authenticated).toBe(false)
    expect(loginAccount).not.toHaveBeenCalled()
    expect(store.notice).toContain('已到期')
    await store.authenticate({ username: '雾松', password: 'correct-password' })
    expect(loginAccount).toHaveBeenCalledWith({ username: '雾松', password: 'correct-password' })
    expect(store.canEnter).toBe(true)
  })

  it('rejects late restore completion after explicit logout', async () => {
    restoreAccount.mockResolvedValue({ status: 'available', state: session })
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(0)
    await store.logout()
    await vi.advanceTimersByTimeAsync(2_000)
    await restore
    expect(store.authenticated).toBe(false)
    expect(getApiSessionToken()).toBe('')
    expect(logoutAccount).toHaveBeenCalledOnce()
  })

  it('keeps failed validation on login and preserves the two-second spinner', async () => {
    restoreAccount.mockRejectedValue(new Error('validation failed'))
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(1_999)
    expect(store.busy).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    await restore
    expect(store.canEnter).toBe(false)
    expect(store.notice).toBe('')
  })
  it('silently leaves unavailable automatic login on the manual form', async () => {
    restoreAccount.mockResolvedValue({ status: 'unavailable', username: session.username, notice: '自动登录不可用，请手动登录。' })
    const store = useAuthStore()
    const restore = store.restore()
    await vi.advanceTimersByTimeAsync(2_000)
    await restore
    expect(store.notice).toBe('')
    expect(store.rememberedUsername).toBe(session.username)
    expect(store.authenticated).toBe(false)
    expect(loginAccount).not.toHaveBeenCalled()
  })
  it('loads the server profile before exposing the completed account workspace', async () => {
    let finish!: (value: unknown) => void
    settings.refreshUserProfile.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    loginAccount.mockResolvedValue(session)
    const store = useAuthStore()
    const login = store.authenticate({ username: '雾松', password: 'correct-password' })
    await vi.advanceTimersByTimeAsync(0)
    expect(store.authenticated).toBe(true)
    expect(store.canEnter).toBe(false)
    expect(store.busy).toBe(true)
    finish({ user_id: '82631459' })
    await login
    expect(store.canEnter).toBe(true)
  })
  it('reports a failed device revocation and closes local account access', async () => {
    await useAuthStore().adopt(session)
    logoutAccount.mockResolvedValue({ ok: false, notice: '无法撤销自动登录凭据' })
    await expect(useAuthStore().logout()).rejects.toThrow('无法撤销自动登录凭据')
    expect(useAuthStore().canEnter).toBe(false)
    expect(useAuthStore().notice).toContain('无法撤销')
    expect(getApiSessionToken()).toBe('')
  })
  it('rejects a late floating IPC session captured before logout', async () => {
    const store = useAuthStore()
    const revision = store.getRevision()
    store.clear()
    await store.adopt(session, revision)
    expect(store.authenticated).toBe(false)
    expect(getApiSessionToken()).toBe('')
  })
  it('reloads completed onboarding from the backend for an already open floating window', async () => {
    const store = useAuthStore()
    await store.adopt({ ...session, onboarding_completed: false, onboarding_step: 2 })
    fetchCurrentAccount.mockResolvedValue({ user_id: session.user_id, username: session.username, onboarding_completed: true, onboarding_step: 6 })
    expect(store.canEnter).toBe(false)
    await store.refreshIdentity()
    expect(store.canEnter).toBe(true)
    expect(settings.refreshUserProfile).toHaveBeenCalledOnce()
  })
})
