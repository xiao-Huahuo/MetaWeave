/** Application authentication owner. The account and token are memory-only and cannot be replaced by a cached user id. */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { advanceOnboarding, fetchCurrentAccount, loginAccount, logoutAccount, registerAccount, restoreAccount, type AuthCredentials, type AuthIdentity, type AuthSession } from '@/api/auth'
import { setApiSessionToken } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'

export const AUTO_LOGIN_MINIMUM_MS = 2_000

export const useAuthStore = defineStore('auth', () => {
  // The retired vault JWT could contain its derived key; remove only that legacy credential namespace once.
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith('metaweave_vault_token_')) sessionStorage.removeItem(key)
  }
  const session = ref<AuthSession | null>(null)
  const busy = ref(false)
  const rememberedUsername = ref('')
  const notice = ref('')
  const profileReady = ref(false)
  const authenticated = computed(() => Boolean(session.value?.token))
  const canEnter = computed(() => authenticated.value && profileReady.value && session.value?.onboarding_completed === true)
  /** Each new intent invalidates late restoration, login and onboarding responses. */
  let generation = 0
  /** Capture before asynchronous IPC so a logout or new account can invalidate its eventual response. */
  function getRevision(): number { return generation }

  /** Adopt only a real backend session, then load settings through the server identity. */
  async function adopt(next: AuthSession, request = generation): Promise<void> {
    if (request !== generation) return
    session.value = next
    profileReady.value = !next.onboarding_completed
    setApiSessionToken(next.token)
    useSettingsStore().setUserId(next.user_id)
    if (next.onboarding_completed) {
      try {
        const profile = await useSettingsStore().refreshUserProfile()
        if (request === generation && session.value?.token === next.token && profile) profileReady.value = true
      } catch (error) {
        if (request === generation && session.value?.token === next.token) clear()
        throw error
      }
    }
  }

  /** Discard all account-scoped memory and invalidate unfinished work. */
  function clear(): void {
    generation += 1
    session.value = null
    profileReady.value = false
    busy.value = false
    setApiSessionToken('')
    useSettingsStore().clearUserId()
  }

  /** Show remembered username as soon as IPC responds; do not grant access until the 2-second interval ends. */
  async function restore(): Promise<void> {
    const request = ++generation
    busy.value = true
    notice.value = ''
    const started = Date.now()
    let restoredSession: AuthSession | undefined
    try {
      const result = await restoreAccount()
      if (request !== generation) return
      rememberedUsername.value = result.username ?? result.state?.username ?? ''
      notice.value = result.status === 'expired' ? '自动登录已到期，请输入密码并点击确定。' : ''
      if (result.status === 'available') restoredSession = result.state
    } catch {
      // A background restore failure simply leaves the manual form available.
      if (request === generation) notice.value = ''
    } finally {
      const remaining = Math.max(0, AUTO_LOGIN_MINIMUM_MS - (Date.now() - started))
      if (remaining) await new Promise<void>((resolve) => setTimeout(resolve, remaining))
      if (request === generation) {
        if (restoredSession) {
          try { await adopt(restoredSession, request) }
          catch { notice.value = '' }
        }
        if (request === generation) busy.value = false
      }
    }
  }

  /** Explicit Confirm is the sole renderer path that creates or renews a remembered credential. */
  async function authenticate(credentials: AuthCredentials, registering = false): Promise<void> {
    const request = ++generation
    busy.value = true
    notice.value = ''
    try {
      const result = await (registering ? registerAccount(credentials) : loginAccount(credentials))
      if (request !== generation) return
      await adopt(result, request)
      if (request === generation) notice.value = result.notice ?? ''
    } finally {
      if (request === generation) busy.value = false
    }
  }

  /** Persist the next stage only after its settings requests have succeeded. */
  async function advance(step: number): Promise<void> {
    const current = session.value
    if (!current) throw new Error('请先登录')
    const request = generation
    const identity: AuthIdentity = await advanceOnboarding(step)
    if (request === generation && session.value?.token === current.token) {
      session.value = { ...current, ...identity }
      if (identity.onboarding_completed) window.agentEditorDesktop?.windowSync?.('account-progress', null)
    }
  }

  /** Reload only the active backend identity after a trusted account-progress invalidation. */
  async function refreshIdentity(): Promise<void> {
    const current = session.value
    const request = generation
    if (!current) return
    const identity = await fetchCurrentAccount()
    if (request === generation && session.value?.token === current.token) await adopt({ ...current, ...identity }, request)
  }

  /** Revoke remotely and erase the OS-protected credential; local access closes even if the network fails. */
  async function logout(): Promise<void> {
    generation += 1
    try {
      const result = await logoutAccount()
      notice.value = result.notice ?? ''
      if (!result.ok) throw new Error(result.notice || '退出登录未完成，请重试。')
    } catch (error) {
      notice.value = error instanceof Error ? error.message : '退出登录失败，请重试。'
      throw error
    } finally { clear() }
  }

  return { session, busy, rememberedUsername, notice, authenticated, canEnter, getRevision, adopt, clear, restore, authenticate, advance, refreshIdentity, logout }
})
