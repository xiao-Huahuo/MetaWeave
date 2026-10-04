/*
 * Security and lifecycle checks for the Electron desktop authentication bridge.
 * Run serially: npm run test:unit -- --run src/__tests__/desktopAuth.spec.ts --maxWorkers=1
 */
import { createRequire } from 'node:module'
import { afterEach, describe, expect, it, vi } from 'vitest'

const require = createRequire(import.meta.url)
type Handler = (event: unknown, payload?: unknown) => Promise<unknown> | unknown
type TestStorage = {
  isEncryptionAvailable: () => boolean
  encryptString: (value: string) => Buffer
  decryptString: (value: Buffer) => string
  getSelectedStorageBackend?: () => string
}
const { desktopDeviceId, localBackendOrigin, registerDesktopAuthIpc, restrictSessionCookie } = require('../../electron/desktop-auth.cjs') as {
  desktopDeviceId: (host?: string, user?: string) => string
  localBackendOrigin: (value: string) => string
  registerDesktopAuthIpc: (ipc: unknown, options: unknown) => () => void
  restrictSessionCookie: (details: { url: string; requestHeaders: Record<string, string> }, origin: string,
    callback: (value: { requestHeaders: Record<string, string> }) => void,
    proxyAuth?: { rendererOrigin: string; token: string }) => void
}

const expiresAt = '2026-11-03T00:00:00.000Z'
const publicState = {
  token: 'session-secret', user_id: '12345678', username: 'Alice',
  onboarding_step: 2, onboarding_completed: false, expires_at: '2026-10-04T08:00:00.000Z',
}
const remember = { credential: 'd'.repeat(48), vault_key: `${'a'.repeat(43)}=`, password_version: 1, expires_at: expiresAt }
const cleanups: Array<() => void> = []

/** Small transport fixture exercises the actual main-process module without Electron. */
function fixture(fetchImpl = vi.fn(async (_url: string, _init: RequestInit) => response({ ...publicState, remember })),
  storageOverrides: Partial<TestStorage> = {}, forgetDeviceOffline?: (deviceId: string) => Promise<void>) {
  const handlers = new Map<string, Handler>()
  const frame = { url: 'http://127.0.0.1:5173/' }
  const webContents = { mainFrame: frame, getURL: () => frame.url, send: vi.fn() }
  const mainWindow = { isDestroyed: () => false, webContents }
  const floatingFrame = { url: 'http://127.0.0.1:5173/?floating=1' }
  const floatingContents = { mainFrame: floatingFrame, getURL: () => floatingFrame.url, send: vi.fn() }
  const safeStorage: TestStorage = {
    isEncryptionAvailable: () => true,
    encryptString: vi.fn((value: string) => Buffer.from(`sealed:${value}`, 'utf8')),
    decryptString: vi.fn((value: Buffer) => value.toString('utf8').replace(/^sealed:/u, '')),
    ...storageOverrides,
  }
  const cookies = { set: vi.fn(async () => {}), remove: vi.fn(async () => {}) }
  const dispose = registerDesktopAuthIpc({
    handle: (channel: string, handler: Handler) => handlers.set(channel, handler),
    removeHandler: (channel: string) => handlers.delete(channel),
  }, {
    safeStorage, getMainWindow: () => mainWindow,
    getFloatingWindow: () => ({ isDestroyed: () => false, webContents: floatingContents }),
    rendererOrigin: 'http://127.0.0.1:5173', backendUrl: 'http://127.0.0.1:8002',
    desktopNonce: 'launch-nonce', deviceId: 'device-id', fetch: fetchImpl,
    now: () => Date.parse('2026-10-04T00:00:00.000Z'), sessionCookies: cookies,
    forgetDeviceOffline,
  })
  cleanups.push(dispose)
  const event = { sender: webContents, senderFrame: frame }
  return {
    call: async (method: string, payload?: unknown, sender = event) => handlers.get(`auth:${method}`)?.(sender, payload),
    fetchImpl, safeStorage, cookies, handlers, frame, event, webContents, floatingFrame, floatingContents, dispose,
  }
}

/** JSON response stub preserves HTTP status handling while avoiding a server process. */
function response(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response
}

afterEach(() => {
  cleanups.splice(0).forEach((dispose) => dispose())
})

describe('trusted desktop authentication', () => {
  it('uses stable OS-account device IDs and refuses remote backend destinations', () => {
    expect(desktopDeviceId('host', 'Alice')).toMatch(/^[0-9a-f]{64}$/u)
    expect(desktopDeviceId('host', 'Alice')).toBe(desktopDeviceId('host', 'Alice'))
    expect(desktopDeviceId('host', 'Bob')).not.toBe(desktopDeviceId('host', 'Alice'))
    expect(() => localBackendOrigin('https://example.com')).toThrow()
    expect(() => localBackendOrigin('http://127.0.0.1:8002/unsafe')).toThrow()
  })

  it('sends the HttpOnly auth cookie exclusively to the configured backend origin', () => {
    const callback = vi.fn()
    const headers = { Cookie: 'other=keep; metaweave_session=private; last=keep' }
    restrictSessionCookie({ url: 'http://127.0.0.1:5173/auth', requestHeaders: headers }, 'http://127.0.0.1:8002', callback)
    expect(callback).toHaveBeenCalledWith({ requestHeaders: { Cookie: 'other=keep; last=keep' } })
    callback.mockClear()
    restrictSessionCookie({ url: 'http://127.0.0.1:8002/knowledge/assets/image.png', requestHeaders: headers }, 'http://127.0.0.1:8002', callback)
    expect(callback).toHaveBeenCalledWith({ requestHeaders: headers })
  })

  it('authorizes trusted Vite resource proxies with Bearer while withholding the cookie', () => {
    const callback = vi.fn()
    const proxyAuth = { rendererOrigin: 'http://127.0.0.1:5173', token: 'session-secret' }
    const headers = { Cookie: 'metaweave_session=private' }
    restrictSessionCookie({ url: 'http://127.0.0.1:5173/library/assets/cover.png', requestHeaders: headers },
      'http://127.0.0.1:8002', callback, proxyAuth)
    expect(callback).toHaveBeenCalledWith({ requestHeaders: { Authorization: 'Bearer session-secret' } })
    callback.mockClear()
    restrictSessionCookie({ url: 'http://127.0.0.1:5173/knowledge/files/pdf-page?path=a.pdf', requestHeaders: headers },
      'http://127.0.0.1:8002', callback, proxyAuth)
    expect(callback).toHaveBeenCalledWith({ requestHeaders: { Authorization: 'Bearer session-secret' } })
    callback.mockClear()
    restrictSessionCookie({ url: 'http://127.0.0.1:5173/@vite/client', requestHeaders: headers },
      'http://127.0.0.1:8002', callback, proxyAuth)
    expect(callback).toHaveBeenCalledWith({ requestHeaders: {} })
  })

  it('encrypts a manual login only in main and persists its ciphertext to the formal API', async () => {
    const app = fixture()
    const result = await app.call('login', { username: 'Alice', password: 'master-password', device_id: 'injected' })
    expect(result).toEqual({ ...publicState, remembered: true })
    expect(JSON.stringify(result)).not.toContain('vault_key')
    expect(app.fetchImpl).toHaveBeenCalledTimes(2)
    const login = JSON.parse(String(app.fetchImpl.mock.calls[0]?.[1].body))
    expect(login).toEqual({ username: 'Alice', password: 'master-password', device_id: 'device-id' })
    const saved = JSON.parse(String(app.fetchImpl.mock.calls[1]?.[1].body))
    expect(saved.device_id).toBe('device-id')
    expect(saved.sealed_payload).not.toContain('master-password')
    expect(app.safeStorage.encryptString).toHaveBeenCalledOnce()
    expect(app.cookies.set).toHaveBeenCalledWith(expect.objectContaining({
      url: 'http://127.0.0.1:8002', name: 'metaweave_session', httpOnly: true, sameSite: 'strict', secure: false,
    }))
  })

  it('restores without any PUT, expiry extension or renderer-readable private fields', async () => {
    const sealed = Buffer.from(`sealed:${JSON.stringify({ version: 1, ...remember, user_id: '12345678', username: 'Alice' })}`).toString('base64')
    const fetchImpl = vi.fn(async (url: string, _init: RequestInit) => response(url.includes('/device/')
      ? { sealed_payload: sealed, expires_at: expiresAt } : publicState))
    const app = fixture(fetchImpl)
    await expect(app.call('restore')).resolves.toEqual({ status: 'available', username: 'Alice', state: { ...publicState, remembered: true } })
    expect(fetchImpl.mock.calls.map((call) => call[1].method)).toEqual(['GET', 'POST'])
    const restoredBody = JSON.parse(String(fetchImpl.mock.calls[1]?.[1].body))
    expect(restoredBody).toEqual({ device_id: 'device-id', credential: remember.credential, vault_key: remember.vault_key, password_version: 1 })
  })

  it('requires manual confirmation after expiry without decoding expired private material', async () => {
    const fetchImpl = vi.fn(async (_url: string, _init: RequestInit) => response({
      username: 'Alice', expires_at: '2026-10-03T00:00:00.000Z', expired: true, sealed_payload: '',
    }))
    const app = fixture(fetchImpl)
    await expect(app.call('restore')).resolves.toEqual({ status: 'expired', username: 'Alice' })
    expect(fetchImpl).toHaveBeenCalledOnce()
    expect(app.safeStorage.decryptString).not.toHaveBeenCalled()
  })

  it('keeps manual login available when OS encryption or secure Linux storage is unavailable', async () => {
    const app = fixture(undefined, { getSelectedStorageBackend: () => 'basic_text' })
    const result = await app.call('login', { username: 'Alice', password: 'master-password' })
    expect(result).toMatchObject({ ...publicState, remembered: false, notice: expect.any(String) })
    expect(app.fetchImpl).toHaveBeenCalledOnce()
    expect(app.safeStorage.encryptString).not.toHaveBeenCalled()
  })

  it('rejects webviews, subframes, remote navigation and floating-window mutation', async () => {
    const app = fixture()
    await expect(app.call('login', {}, { sender: {} as typeof app.webContents, senderFrame: app.frame })).rejects.toThrow('来源')
    await expect(app.call('restore', undefined, { sender: app.webContents, senderFrame: { ...app.frame } })).rejects.toThrow('来源')
    app.frame.url = 'https://example.com/'
    await expect(app.call('restore')).rejects.toThrow('来源')
    app.frame.url = 'http://127.0.0.1:5173/'
    await expect(app.call('logout', undefined, { sender: app.floatingContents, senderFrame: app.floatingFrame })).rejects.toThrow('来源')
    expect(app.fetchImpl).not.toHaveBeenCalled()
  })

  it('accepts root/index SPA entries and refuses same-origin private HTML/raw paths', async () => {
    const app = fixture()
    app.frame.url = 'http://127.0.0.1:8002/index.html?floating=1#/'
    await app.call('login', { username: 'Alice', password: 'master-password' })
    await expect(app.call('get-session')).resolves.toEqual({ ...publicState, remembered: true })
    for (const path of ['/visualizations/12345678/private.html', '/library/assets/12345678/image.svg',
      '/knowledge/files/raw?path=private.html', '/vault/assets/private', '/auth/me']) {
      app.frame.url = `http://127.0.0.1:8002${path}`
      await expect(app.call('get-session')).rejects.toThrow('来源')
      await expect(app.call('restore')).rejects.toThrow('来源')
    }
    expect(app.fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('does not broadcast a late session into a same-origin business page', async () => {
    let finishLogin: ((value: Response) => void) | undefined
    const fetchImpl = vi.fn((url: string, _init: RequestInit): Promise<Response> => url.endsWith('/auth/login')
      ? new Promise((resolve) => { finishLogin = resolve }) : Promise.resolve(response(undefined, 204)))
    const app = fixture(fetchImpl)
    const login = app.call('login', { username: 'Alice', password: 'master-password' })
    const rejectedLogin = expect(login).rejects.toThrow('来源')
    await Promise.resolve()
    app.frame.url = 'http://127.0.0.1:8002/visualizations/12345678/private.html'
    finishLogin?.(response({ ...publicState, remember }))
    await rejectedLogin
    expect(app.webContents.send).not.toHaveBeenCalled()
    expect(app.floatingContents.send).toHaveBeenCalledWith('auth:session-changed', { ...publicState, remembered: true })
  })

  it('bootstraps the trusted floating renderer and clears its session on explicit logout', async () => {
    const app = fixture()
    await app.call('login', { username: 'Alice', password: 'master-password' })
    await expect(app.call('get-session', undefined, { sender: app.floatingContents, senderFrame: app.floatingFrame }))
      .resolves.toEqual({ ...publicState, remembered: true })
    await expect(app.call('logout')).resolves.toEqual({ ok: true })
    expect(app.cookies.remove).toHaveBeenCalledWith('http://127.0.0.1:8002', 'metaweave_session')
    expect(app.fetchImpl.mock.calls[2]?.[1]).toMatchObject({ method: 'DELETE', headers: { Authorization: 'Bearer session-secret' } })
    expect(app.floatingContents.send).toHaveBeenLastCalledWith('auth:session-changed', null)
    await expect(app.call('get-session')).resolves.toBeNull()
  })

  it('orders logout after in-flight login and refuses its late authenticated result', async () => {
    let finishLogin: ((value: Response) => void) | undefined
    const fetchImpl = vi.fn((url: string, _init: RequestInit): Promise<Response> => url.endsWith('/auth/login')
      ? new Promise((resolve) => { finishLogin = resolve }) : Promise.resolve(response(undefined, 204)))
    const app = fixture(fetchImpl)
    const login = app.call('login', { username: 'Alice', password: 'master-password' })
    const rejectedLogin = expect(login).rejects.toThrow('取消')
    await Promise.resolve()
    const logout = app.call('logout')
    finishLogin?.(response({ ...publicState, remember }))
    await rejectedLogin
    await expect(logout).resolves.toEqual({ ok: true })
    expect(fetchImpl.mock.calls.map((call) => call[1].method)).toEqual(['POST', 'DELETE'])
    expect(app.safeStorage.encryptString).not.toHaveBeenCalled()
    await expect(app.call('get-session')).resolves.toBeNull()
  })

  it('cancels a superseded restore before the logout revokes the device', async () => {
    let requestSignal: AbortSignal | undefined
    const fetchImpl = vi.fn((url: string, init: RequestInit): Promise<Response> => init.method === 'GET'
      ? new Promise((_resolve, reject) => {
        requestSignal = init.signal as AbortSignal
        requestSignal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
      }) : Promise.resolve(response(undefined, 204)))
    const app = fixture(fetchImpl)
    const restore = app.call('restore')
    await Promise.resolve()
    const logout = app.call('logout')
    expect(requestSignal?.aborted).toBe(true)
    await expect(restore).resolves.toEqual({ status: 'missing' })
    await expect(logout).resolves.toEqual({ ok: true })
    expect(fetchImpl.mock.calls.map((call) => call[1].method)).toEqual(['GET', 'DELETE'])
  })

  it('uses the formal local DB revocation callback when the backend is offline', async () => {
    const offline = vi.fn(async (_deviceId: string) => {})
    const fetchImpl = vi.fn(async (_url: string, _init: RequestInit): Promise<Response> => { throw new Error('backend offline') })
    const app = fixture(fetchImpl, {}, offline)
    await expect(app.call('logout')).resolves.toEqual({ ok: true })
    expect(offline).toHaveBeenCalledWith('device-id')
    expect(app.cookies.remove).toHaveBeenCalledOnce()
    await expect(app.call('get-session')).resolves.toBeNull()
  })

  it('reports incomplete logout if both HTTP and local DB revocation fail', async () => {
    const offline = vi.fn(async (_deviceId: string) => { throw new Error('DB unavailable') })
    const fetchImpl = vi.fn(async (_url: string, _init: RequestInit): Promise<Response> => { throw new Error('backend offline') })
    const app = fixture(fetchImpl, {}, offline)
    await expect(app.call('logout')).resolves.toMatchObject({ ok: false, notice: expect.any(String) })
    expect(offline).toHaveBeenCalledOnce()
  })

  it('quitting disposes handlers without revoking the remembered login', async () => {
    const app = fixture()
    await app.call('login', { username: 'Alice', password: 'master-password' })
    app.dispose()
    expect(app.handlers.size).toBe(0)
    expect(app.fetchImpl.mock.calls.some((call) => call[1].method === 'DELETE')).toBe(false)
  })
})
