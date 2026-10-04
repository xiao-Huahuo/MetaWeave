/** Global account API. Passwords are sent only for explicit authentication and never persisted by the renderer. */
import { ApiError, apiGet, apiPost, apiPut } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

/** Backend-issued stable identity and persisted onboarding progress. */
export interface AuthIdentity {
  user_id: string
  username: string
  onboarding_step: number
  onboarding_completed: boolean
  created_at?: string
}
/** Sanitized session; protected device credential and vault key never cross the desktop bridge. */
export interface AuthSession extends AuthIdentity {
  token: string
  expires_at: string
  remembered?: boolean
  notice?: string
}
/** Fixed-expiry restore outcome; expired credentials require a manual password submission. */
export interface AuthRestoreResult {
  status: 'available' | 'expired' | 'missing' | 'unavailable'
  username?: string
  state?: AuthSession
  notice?: string
}
export interface AuthCredentials { username: string; password: string }

/** Use trusted desktop IPC for encrypted remembering, and the same REST contract in the browser. */
export function registerAccount(credentials: AuthCredentials): Promise<AuthSession> {
  return window.agentEditorDesktop?.auth
    ? window.agentEditorDesktop.auth.register(credentials)
    : apiPost(API_ROUTES.AUTH_REGISTER, credentials)
}
export function loginAccount(credentials: AuthCredentials): Promise<AuthSession> {
  return window.agentEditorDesktop?.auth
    ? window.agentEditorDesktop.auth.login(credentials)
    : apiPost(API_ROUTES.AUTH_LOGIN, credentials)
}
export function restoreAccount(): Promise<AuthRestoreResult> {
  return window.agentEditorDesktop?.auth?.restore() ?? Promise.resolve({ status: 'missing' })
}
export function fetchCurrentAccount(): Promise<AuthIdentity> { return apiGet(API_ROUTES.AUTH_CURRENT) }
export function advanceOnboarding(step: number): Promise<AuthIdentity> {
  return apiPut(API_ROUTES.AUTH_ONBOARDING, { step })
}
export function logoutAccount(): Promise<{ ok: boolean; notice?: string }> {
  const desktop = window.agentEditorDesktop?.auth
  if (desktop) return desktop.logout()
  return apiPost<{ ok: boolean }>(API_ROUTES.AUTH_LOGOUT).catch((error: unknown) => {
    // Password changes already revoke the browser session; no device credential exists in this path.
    if (error instanceof ApiError && error.status === 401) return { ok: true }
    throw error
  })
}
/** Changing the global password re-encrypts the vault and revokes all sessions/devices. */
export function changeAccountPassword(oldPassword: string, newPassword: string): Promise<{ ok: boolean }> {
  return apiPost(API_ROUTES.AUTH_PASSWORD, { old_password: oldPassword, new_password: newPassword })
}
