/** Global auth request construction and memory-only bearer boundary regression. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { advanceOnboarding, changeAccountPassword, fetchCurrentAccount, loginAccount, logoutAccount, registerAccount, restoreAccount } from '@/api/auth'
import { apiFetch, apiGet, apiPostForm, setApiSessionToken, streamLines } from '@/api/client'

afterEach(() => { setApiSessionToken(''); vi.unstubAllGlobals() })

describe('global auth API', () => {
  it('constructs registration, manual login, current account, progress, password and logout requests', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await registerAccount({ username: '雾松', password: 'private-password' })
    await loginAccount({ username: '雾松', password: 'private-password' })
    setApiSessionToken('account-session')
    await fetchCurrentAccount()
    await advanceOnboarding(3)
    await changeAccountPassword('private-password', 'next-password')
    await logoutAccount()
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/auth/register', '/auth/login', '/auth/me', '/auth/onboarding', '/auth/password', '/auth/logout'])
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ username: '雾松', password: 'private-password' })
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body))).toEqual({ step: 3 })
    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body))).toEqual({ old_password: 'private-password', new_password: 'next-password' })
    expect(new Headers(fetchMock.mock.calls[2]?.[1]?.headers).get('Authorization')).toBe('Bearer account-session')
    expect(JSON.stringify(localStorage)).not.toContain('private-password')
    expect(JSON.stringify(sessionStorage)).not.toContain('account-session')
    expect(await restoreAccount()).toEqual({ status: 'missing' })
  })

  it('uses encrypted desktop auth IPC instead of constructing a renderer remember credential', async () => {
    const login = vi.fn().mockResolvedValue({ token: 'opaque-session', user_id: '82631459', username: '雾松', onboarding_step: 6, onboarding_completed: true, expires_at: '2030-01-01T00:00:00Z' })
    const restore = vi.fn().mockResolvedValue({ status: 'expired', username: '雾松' })
    vi.stubGlobal('agentEditorDesktop', { auth: { login, restore } })
    await loginAccount({ username: '雾松', password: 'private-password' })
    expect(login).toHaveBeenCalledWith({ username: '雾松', password: 'private-password' })
    expect(await restoreAccount()).toEqual({ status: 'expired', username: '雾松' })
  })

  it('applies the global bearer to JSON, multipart and stream without setting multipart Content-Type', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (path) => new Response(path === '/stream' ? 'data: [DONE]\n\n' : '{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    setApiSessionToken('shared-session')
    await apiGet('/settings/profile')
    await apiPostForm('/vault/assets', new FormData())
    for await (const _event of streamLines('/stream')) { /* No emitted events. */ }
    expect(fetchMock.mock.calls.every(([, init]) => new Headers(init?.headers).get('Authorization') === 'Bearer shared-session')).toBe(true)
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).has('Content-Type')).toBe(false)
    expect(fetchMock.mock.calls.every(([, init]) => init?.credentials === 'include')).toBe(true)
  })

  it('expires only the session whose rejected request is still active', async () => {
    const expired = vi.fn()
    window.addEventListener('metaweave:session-expired', expired)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"expired"}', { status: 401 })))
    setApiSessionToken('expired-session')
    await expect(apiGet('/vault/items')).rejects.toThrow('401')
    expect(expired).toHaveBeenCalledOnce()
    window.removeEventListener('metaweave:session-expired', expired)
  })
  it('does not disclose the app bearer to an external URL', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchMock)
    setApiSessionToken('shared-session')
    await apiFetch('https://external.example/document')
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).has('Authorization')).toBe(false)
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe('same-origin')
  })
  it('honors the caller cancellation signal while keeping its own timeout ownership', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn((_path: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true })
    })))
    const request = apiGet('/health', undefined, { signal: controller.signal, timeoutMs: 10_000 })
    controller.abort()
    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('uses the same configured desktop backend origin for profile requests and IPC authentication', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('agentEditorDesktop', { isDesktop: true, backendOrigin: 'http://127.0.0.1:18123' })
    setApiSessionToken('shared-session')
    await apiGet('/settings/profile')
    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://127.0.0.1:18123/settings/profile')
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Authorization')).toBe('Bearer shared-session')
  })
  it('rejects an old authenticated response after switching the current account token', async () => {
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { finish = resolve })))
    setApiSessionToken('first-session')
    const pending = apiGet('/knowledge/files')
    setApiSessionToken('second-session')
    finish(new Response('{"tree":[{"path":"private.md"}]}'))
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('treats an already-revoked browser token after password change as successful logout', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Invalid session"}', { status: 401 })))
    setApiSessionToken('revoked-session')
    await expect(logoutAccount()).resolves.toEqual({ ok: true })
  })
})
