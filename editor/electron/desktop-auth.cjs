/*
 * Trusted desktop authentication and OS-encrypted remembered-login bridge.
 * Register once from main.cjs. Only owned local top-level renderers receive a
 * session; vault keys and device credentials never cross the preload boundary.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
const { createHash } = require('node:crypto')
const os = require('node:os')

const REQUEST_TIMEOUT_MS = 30_000
const MAX_SEALED_PAYLOAD_SIZE = 64 * 1024
const SESSION_COOKIE_NAME = 'metaweave_session'

/** Derive a stable device identifier for this OS account, without storing files. */
function desktopDeviceId(hostname = os.hostname(), username = os.userInfo().username) {
  return createHash('sha256').update(`MetaWeave\0${hostname}\0${username}`, 'utf8').digest('hex')
}

/** Refuse remote backends before sending passwords, keys or launch authorization. */
function localBackendOrigin(value) {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('桌面登录只能连接本机 Agent 服务')
  }
  return url.origin
}

/** Only the formal SPA entries receive auth; same-origin business HTML is untrusted. */
function isTrustedRendererEntry(value, trustedOrigins) {
  try {
    const url = new URL(value)
    return trustedOrigins.has(url.origin) && ['/', '/index.html'].includes(url.pathname)
  } catch {
    return false
  }
}

/** Share the exact top-frame/window/entry boundary with account-progress relay. */
function assertTrustedDesktopSender(event, windows, trustedOrigins) {
  const owner = windows.find((window) => window && !window.isDestroyed() && window.webContents === event.sender)
  if (!owner || event.senderFrame !== owner.webContents.mainFrame) throw new Error('登录请求来源无效')
  if (!isTrustedRendererEntry(event.senderFrame.url, trustedOrigins)) throw new Error('登录请求来源无效')
}

/** Whitelist session fields so private backend response additions cannot leak. */
function publicAuthState(payload, remembered = false, notice) {
  if (!payload || typeof payload.token !== 'string' || !payload.token || payload.token.length > 4096
      || !/^\d{8}$/u.test(payload.user_id) || typeof payload.username !== 'string'
      || !Number.isInteger(payload.onboarding_step) || typeof payload.onboarding_completed !== 'boolean'
      || !Number.isFinite(Date.parse(payload.expires_at))) {
    throw new Error('本机登录服务返回了无效的会话')
  }
  return {
    token: payload.token,
    user_id: payload.user_id,
    username: payload.username,
    onboarding_step: payload.onboarding_step,
    onboarding_completed: payload.onboarding_completed,
    expires_at: payload.expires_at,
    remembered,
    ...(notice ? { notice } : {}),
  }
}

/** Validate the private key/credential envelope before encryption or restoration. */
function rememberedPayload(value) {
  if (!value || typeof value.credential !== 'string' || value.credential.length < 32
      || value.credential.length > 512 || typeof value.vault_key !== 'string'
      || !/^[A-Za-z0-9_-]{43}=$/u.test(value.vault_key)
      || !Number.isInteger(value.password_version) || value.password_version < 1
      || !/^\d{8}$/u.test(value.user_id) || typeof value.username !== 'string'
      || !Number.isFinite(Date.parse(value.expires_at))) {
    throw new Error('自动登录凭据无效，请手动登录')
  }
  return {
    credential: value.credential,
    vault_key: value.vault_key,
    password_version: value.password_version,
    expires_at: value.expires_at,
    user_id: value.user_id,
    username: value.username,
  }
}

/** Cookie domains ignore ports; strip this session from every other destination. */
function restrictSessionCookie(details, backendOrigin, callback, proxyAuth) {
  const headers = { ...details.requestHeaders }
  const destination = new URL(details.url)
  if (destination.origin !== backendOrigin) {
    for (const name of Object.keys(headers)) {
      if (name.toLowerCase() !== 'cookie') continue
      const retained = String(headers[name]).split(';').filter((cookie) => cookie.trim().split('=')[0] !== SESSION_COOKIE_NAME)
      if (retained.length) headers[name] = retained.join(';').trim()
      else delete headers[name]
    }
  }
  // Vite forwards these relative resource URLs; browsers cannot attach Bearer themselves.
  if (proxyAuth?.token && destination.origin === proxyAuth.rendererOrigin
      && (['/library/assets/', '/knowledge/assets/', '/downloads/', '/visualizations/'].some((prefix) => destination.pathname.startsWith(prefix))
        || ['/knowledge/files/preview', '/knowledge/files/pdf-page', '/agent/attachments/raw'].includes(destination.pathname))) {
    headers.Authorization = `Bearer ${proxyAuth.token}`
  }
  callback({ requestHeaders: headers })
}

/** Register narrow auth handlers; cleanup cancels work without forgetting login. */
function registerDesktopAuthIpc(ipcMain, options) {
  const { safeStorage, getMainWindow, getFloatingWindow, rendererOrigin, desktopNonce,
    sessionCookies, webRequest, forgetDeviceOffline } = options
  const backendOrigin = localBackendOrigin(options.backendUrl)
  const trustedOrigins = new Set([localBackendOrigin(rendererOrigin), backendOrigin])
  const deviceId = options.deviceId || desktopDeviceId()
  const fetchImpl = options.fetch || globalThis.fetch
  const now = options.now || Date.now
  const timeoutMs = options.timeoutMs || REQUEST_TIMEOUT_MS
  let currentSession = null
  let generation = 0
  let restoreController = null
  let pending = Promise.resolve()
  let disposed = false
  const controllers = new Set()
  const channels = []
  // This bridge owns the default application session hook; browser views use separate partitions.
  webRequest?.onBeforeSendHeaders((details, callback) => {
    const owner = [getMainWindow(), getFloatingWindow()].find((window) => window && !window.isDestroyed()
      && window.webContents.id === details.webContentsId)
    const trustedFrame = owner && isTrustedRendererEntry(details.frame?.url || details.referrer, trustedOrigins)
    restrictSessionCookie(details, backendOrigin, callback, trustedFrame && currentSession
      ? { rendererOrigin: new URL(rendererOrigin).origin, token: currentSession.token } : undefined)
  })

  /** Accept only the owned application's top frame, never an embedded browser. */
  function trustedSender(event, mainOnly = true) {
    const windows = mainOnly ? [getMainWindow()] : [getMainWindow(), getFloatingWindow()]
    assertTrustedDesktopSender(event, windows, trustedOrigins)
  }

  /** Treat Linux's plaintext basic_text fallback as unavailable encrypted storage. */
  function canRemember() {
    try {
      return safeStorage.isEncryptionAvailable()
        && (!safeStorage.getSelectedStorageBackend || safeStorage.getSelectedStorageBackend() !== 'basic_text')
    } catch {
      return false
    }
  }

  /** Publish only sanitized session state to currently trusted application pages. */
  function publishSession(state) {
    currentSession = state
    for (const window of [getMainWindow(), getFloatingWindow()]) {
      if (!window || window.isDestroyed()) continue
      if (isTrustedRendererEntry(window.webContents.getURL(), trustedOrigins)) {
        window.webContents.send('auth:session-changed', state)
      }
    }
  }

  /** Keep HttpOnly resource authorization in Chromium's jar, never browser storage. */
  async function syncSessionCookie(state) {
    if (!sessionCookies) return
    if (state) {
      await sessionCookies.set({
        url: backendOrigin, name: SESSION_COOKIE_NAME, value: state.token,
        path: '/', httpOnly: true, secure: false, sameSite: 'strict',
        expirationDate: Date.parse(state.expires_at) / 1000,
      })
    } else {
      await sessionCookies.remove(backendOrigin, SESSION_COOKIE_NAME)
    }
  }

  /** Bound each request, disallow redirects and keep nonce/key headers private. */
  async function request(path, { method = 'GET', body, token, signal } = {}) {
    if (!desktopNonce) throw new Error('本机登录服务未配置桌面授权，请使用桌面启动命令')
    const controller = new AbortController()
    controllers.add(controller)
    const abort = () => controller.abort()
    if (signal?.aborted) abort()
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(abort, timeoutMs)
    try {
      const response = await fetchImpl(`${backendOrigin}${path}`, {
        method,
        redirect: 'error',
        headers: {
          'Content-Type': 'application/json',
          'X-Desktop-Auth': desktopNonce,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: controller.signal,
      })
      if (!response.ok) {
        const error = new Error(response.status === 401 ? '用户名、密码或登录凭据无效'
          : response.status === 409 ? '用户名已存在'
            : response.status === 429 ? '登录尝试过于频繁，请稍后重试'
              : '本机登录服务请求失败，请稍后重试')
        error.status = response.status
        throw error
      }
      return response.status === 204 ? undefined : await response.json()
    } catch (error) {
      if (controller.signal.aborted) throw new Error('登录请求已取消或超时，请重试')
      throw error
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      controllers.delete(controller)
    }
  }

  /** Serialize device mutations so logout follows every already-issued login. */
  function enqueue(operation) {
    const result = pending.then(operation)
    pending = result.catch(() => {})
    return result
  }

  /** Invalidate superseded work before it can publish or save a late credential. */
  function beginOperation() {
    generation += 1
    restoreController?.abort()
    restoreController = null
    return generation
  }

  /** Reject work that lost ownership because another action or quit superseded it. */
  function checkOperation(version) {
    if (disposed || version !== generation) throw new Error('登录操作已取消')
  }

  /** Read only username/password, adding the stable device identity in main. */
  function credentials(payload) {
    if (!payload || typeof payload.username !== 'string' || !payload.username.trim()
        || payload.username.length > 128 || typeof payload.password !== 'string'
        || !payload.password || payload.password.length > 1024) {
      throw new Error('请输入有效的用户名和密码')
    }
    return { username: payload.username, password: payload.password, device_id: deviceId }
  }

  /** Manually authenticate and save only the OS-encrypted private response to DB. */
  function manualLogin(endpoint, payload) {
    const body = credentials(payload)
    const version = beginOperation()
    return enqueue(async () => {
      checkOperation(version)
      const response = await request(`/auth/${endpoint}`, { method: 'POST', body })
      checkOperation(version)
      let remembered = false
      let notice
      if (!canRemember()) {
        notice = '系统加密存储不可用，本次登录成功；下次启动需手动登录。'
      } else {
        try {
          const privatePayload = rememberedPayload({ ...response.remember, user_id: response.user_id, username: response.username })
          const sealedPayload = safeStorage.encryptString(JSON.stringify({ version: 1, ...privatePayload })).toString('base64')
          await request('/auth/device/remembered', {
            method: 'PUT', token: response.token, body: { device_id: deviceId, sealed_payload: sealedPayload },
          })
          remembered = true
        } catch {
          notice = '本次登录成功，但自动登录凭据保存失败；下次启动需手动登录。'
        }
      }
      checkOperation(version)
      const state = publicAuthState(response, remembered, notice)
      await syncSessionCookie(state)
      checkOperation(version)
      publishSession(state)
      return state
    })
  }

  /** Restore one fixed-expiry device credential without updating its DB expiry. */
  function restore() {
    const version = beginOperation()
    const controller = new AbortController()
    restoreController = controller
    return enqueue(async () => {
      let username
      try {
        checkOperation(version)
        if (!canRemember()) return { status: 'unavailable', notice: '系统加密存储不可用，请手动登录。' }
        let row
        try {
          row = await request(`/auth/device/remembered?device_id=${encodeURIComponent(deviceId)}`, { signal: controller.signal })
        } catch (error) {
          if (error.status === 404) return { status: 'missing' }
          throw error
        }
        checkOperation(version)
        username = typeof row.username === 'string' ? row.username : undefined
        if (row.expired === true || now() >= Date.parse(row.expires_at)) {
          return { status: 'expired', ...(username ? { username } : {}) }
        }
        if (typeof row.sealed_payload !== 'string' || !row.sealed_payload || row.sealed_payload.length > MAX_SEALED_PAYLOAD_SIZE) {
          return { status: 'missing' }
        }
        const decoded = JSON.parse(safeStorage.decryptString(Buffer.from(row.sealed_payload, 'base64')))
        if (decoded.version !== 1) throw new Error('自动登录凭据版本无效')
        const privatePayload = rememberedPayload(decoded)
        username = privatePayload.username
        if (Date.parse(row.expires_at) !== Date.parse(privatePayload.expires_at)) throw new Error('自动登录凭据失效')
        if (now() >= Date.parse(privatePayload.expires_at)) return { status: 'expired', username: privatePayload.username }
        const response = await request('/auth/restore', {
          method: 'POST', signal: controller.signal,
          body: { device_id: deviceId, credential: privatePayload.credential, vault_key: privatePayload.vault_key,
            password_version: privatePayload.password_version },
        })
        checkOperation(version)
        const state = publicAuthState(response, true)
        await syncSessionCookie(state)
        checkOperation(version)
        publishSession(state)
        return { status: 'available', username: privatePayload.username, state }
      } catch (error) {
        if (version !== generation || disposed) return { status: 'missing' }
        return { status: 'unavailable', ...(username ? { username } : {}), notice: error.status === 401
          ? '自动登录凭据已失效，请输入密码并点击确定。' : '自动登录不可用，请手动登录。' }
      } finally {
        if (restoreController === controller) restoreController = null
      }
    })
  }

  /** Clear memory and revoke the formal DB grant, including when HTTP is offline. */
  function logout() {
    beginOperation()
    const token = currentSession?.token
    publishSession(null)
    return enqueue(async () => {
      let cookieCleared = true
      try { await syncSessionCookie(null) } catch { cookieCleared = false }
      try {
        await request(`/auth/device/remembered?device_id=${encodeURIComponent(deviceId)}`, { method: 'DELETE', token })
      } catch {
        try {
          if (!forgetDeviceOffline) throw new Error('本机撤销不可用')
          await forgetDeviceOffline(deviceId)
        } catch {
          return { ok: false, notice: '退出未完成：无法撤销自动登录凭据，请恢复本机服务后重试。' }
        }
      }
      return cookieCleared ? { ok: true } : { ok: false, notice: '自动登录已撤销，但会话清理失败，请关闭应用后重新打开。' }
    })
  }

  /** Keep sender checks centralized for every exposed authentication operation. */
  function handle(channel, handler, mainOnly = true) {
    channels.push(channel)
    ipcMain.handle(channel, async (event, payload) => {
      trustedSender(event, mainOnly)
      if (disposed) throw new Error('登录服务已关闭')
      const result = await handler(payload)
      // Navigation may replace the formal entry while an HTTP/KDF request is pending.
      trustedSender(event, mainOnly)
      if (disposed) throw new Error('登录服务已关闭')
      return result
    })
  }

  handle('auth:register', (payload) => manualLogin('register', payload))
  handle('auth:login', (payload) => manualLogin('login', payload))
  handle('auth:restore', restore)
  handle('auth:logout', logout)
  handle('auth:get-session', () => currentSession && now() < Date.parse(currentSession.expires_at) ? currentSession : null, false)

  return () => {
    disposed = true
    beginOperation()
    for (const controller of controllers) controller.abort()
    for (const channel of channels) ipcMain.removeHandler(channel)
    webRequest?.onBeforeSendHeaders(null)
    currentSession = null
  }
}

module.exports = { desktopDeviceId, localBackendOrigin, publicAuthState, registerDesktopAuthIpc, restrictSessionCookie, assertTrustedDesktopSender }
