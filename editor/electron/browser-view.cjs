/*
 * Embedded Chromium browser view manager.
 *
 * Usage:
 * Register once from the Electron main process. The renderer controls the active
 * sandboxed WebContentsView through the narrow IPC surface exposed by preload.
 * Ordinary browsing retains its persistent session; managed DSH pages use an
 * isolated memory session because their bootstrap stores an authentication cookie.
 */
/* eslint-disable @typescript-eslint/no-require-imports */

const { nativeTheme, session, shell, WebContentsView } = require('electron')

const BROWSER_PARTITION = 'persist:metaweave-browser'
const DEFAULT_HOME_URL = 'https://www.google.com'

/** Keep Chromium color preferences within Electron's supported theme values. */
function applyBrowserTheme(themeMode) {
  if (themeMode === 'dark' || themeMode === 'light' || themeMode === 'system') {
    nativeTheme.themeSource = themeMode
  }
}

/** Accept only browser-safe HTTP(S) destinations. */
function normalizeBrowserUrl(value, homeUrl = DEFAULT_HOME_URL) {
  const input = String(value || '').trim()
  if (!input) return homeUrl
  if (/^https?:\/\//iu.test(input)) return input
  if (/^(localhost|127\.0\.0\.1)(:\d+)?(?:\/|$)/iu.test(input)) return `http://${input}`
  if (/^[\w.-]+\.[a-z]{2,}(?::\d+)?(?:\/|$)/iu.test(input)) return `https://${input}`
  return `https://www.google.com/search?q=${encodeURIComponent(input)}`
}

/** Mask the DSH bootstrap credential in display URLs and navigation diagnostics. */
function redactBrowserText(value) {
  return String(value || '').replace(/([#?&]mw_token=)[^&#\s"'<>)]*/giu, '$1[redacted]')
}

/** Register the embedded browser IPC handlers and return its cleanup hook. */
function registerBrowserViewIpc(ipcMain, getMainWindow) {
  let browserView = null
  let homeUrl = DEFAULT_HOME_URL
  let configuredProxy = ''
  let ordinaryBrowser = null
  let managedBrowser = null
  let activeBrowser = null
  let borderRadius = 0

  /** Send current navigation state only to the trusted application renderer. */
  function emitState(extra = {}, owner = browserView) {
    const window = getMainWindow()
    if (!window || window.isDestroyed() || !browserView || owner !== browserView || browserView.webContents.isDestroyed()) return
    window.webContents.send('browser:state', {
      url: redactBrowserText(browserView.webContents.getURL()),
      title: redactBrowserText(browserView.webContents.getTitle()) || '新标签页',
      canGoBack: browserView.webContents.navigationHistory.canGoBack(),
      canGoForward: browserView.webContents.navigationHistory.canGoForward(),
      loading: browserView.webContents.isLoading(),
      ...extra,
      ...(extra.error !== undefined ? { error: redactBrowserText(extra.error) } : {}),
    })
  }

  /** Close the obsolete native surface; at most ordinary and current DSH remain. */
  function closeBrowser(context) {
    if (!context || context.view.webContents.isDestroyed()) return
    const window = getMainWindow()
    if (window && !window.isDestroyed()) window.contentView.removeChildView(context.view)
    context.view.webContents.close()
  }

  /** Create a native surface with a partition whose storage policy cannot change. */
  function createBrowser(window, partition, origin = '') {
    const isolatedSession = session.fromPartition(partition, { cache: !origin })
    isolatedSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
    const view = new WebContentsView({
      webPreferences: { session: isolatedSession, contextIsolation: true, nodeIntegration: false, sandbox: true },
    })
    view.setBackgroundColor('#ffffff')
    window.contentView.addChildView(view)
    view.setVisible(false)
    view.webContents.setWindowOpenHandler(({ url }) => {
      if (view === browserView && /^https?:\/\//iu.test(url)) void loadBrowserUrl(url)
      return { action: 'deny' }
    })
    view.webContents.on('will-navigate', (event, url) => {
      event.preventDefault()
      if (view === browserView && /^https?:\/\//iu.test(url)) void loadBrowserUrl(url)
    })
    view.webContents.on('did-start-loading', () => emitState({ loading: true, error: '' }, view))
    view.webContents.on('did-stop-loading', () => emitState({ loading: false }, view))
    view.webContents.on('did-navigate', () => emitState({}, view))
    view.webContents.on('did-navigate-in-page', () => emitState({}, view))
    view.webContents.on('page-title-updated', () => emitState({}, view))
    view.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      if (isMainFrame && code !== -3) emitState({ loading: false, error: `${description}: ${url}` }, view)
    })
    return { view, session: isolatedSession, origin, proxy: null }
  }

  /** Select the normal session or an isolated memory session for a DSH origin. */
  function ensureBrowserView(destination = '') {
    const window = getMainWindow()
    if (!window || window.isDestroyed()) return null
    const bounds = browserView && !browserView.webContents.isDestroyed() ? browserView.getBounds() : null
    const visible = browserView && !browserView.webContents.isDestroyed() ? browserView.getVisible() : false
    const url = destination ? new URL(destination) : null
    const params = url ? new URLSearchParams(url.hash.slice(1)) : null
    const managed = url && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && (params.has('mw_token') || managedBrowser?.origin === url.origin)
    let next = !destination ? activeBrowser : null
    if (managed) {
      if (!managedBrowser || managedBrowser.origin !== url.origin || managedBrowser.view.webContents.isDestroyed()) {
        closeBrowser(managedBrowser)
        // A separate origin partition prevents cookies from crossing loopback ports.
        managedBrowser = createBrowser(window, `metaweave-dsh:${url.origin}`, url.origin)
      }
      next = managedBrowser
    }
    if (!next) {
      if (!ordinaryBrowser || ordinaryBrowser.view.webContents.isDestroyed()) ordinaryBrowser = createBrowser(window, BROWSER_PARTITION)
      next = ordinaryBrowser
    }
    if (next !== activeBrowser) {
      if (browserView && !browserView.webContents.isDestroyed()) browserView.setVisible(false)
      activeBrowser = next
      browserView = next.view
      if (bounds) browserView.setBounds(bounds)
      browserView.setBorderRadius(borderRadius)
      browserView.setVisible(visible)
    }
    return browserView
  }

  /** Keep the browser surface alive when Chromium renders a network error page. */
  async function loadBrowserUrl(url) {
    const view = ensureBrowserView(url)
    if (!view) return false
    try {
      const context = view === managedBrowser?.view ? managedBrowser : ordinaryBrowser
      await applyProxy(configuredProxy, context)
      await view.webContents.loadURL(url)
      return true
    } catch (error) {
      if (!view.webContents.isDestroyed()) {
        emitState({ loading: false, error: error instanceof Error ? error.message : String(error) }, view)
      }
      return false
    }
  }

  /** Apply the resolved browser proxy without touching the application's own session. */
  async function applyProxy(proxyUrl, context = activeBrowser) {
    if (!context) { ensureBrowserView(); context = activeBrowser }
    const nextProxy = context?.origin ? '' : String(proxyUrl || '').trim()
    if (!context || nextProxy === context.proxy) return
    await context.session.setProxy(nextProxy
      ? { mode: 'fixed_servers', proxyRules: nextProxy }
      : { mode: 'direct' })
    await context.session.closeAllConnections()
    context.proxy = nextProxy
  }

  ipcMain.handle('browser:show', async (_event, payload) => {
    let view = ensureBrowserView()
    if (!view) return false
    const bounds = payload?.bounds || {}
    homeUrl = normalizeBrowserUrl(payload?.homeUrl, DEFAULT_HOME_URL)
    applyBrowserTheme(payload?.themeMode)
    configuredProxy = String(payload?.proxyUrl || '').trim()
    await applyProxy(configuredProxy)
    // Navigation may switch sessions while proxy configuration is pending.
    view = ensureBrowserView()
    if (!view) return false
    view.setBounds({
      x: Math.max(0, Math.round(Number(bounds.x) || 0)),
      y: Math.max(0, Math.round(Number(bounds.y) || 0)),
      width: Math.max(1, Math.round(Number(bounds.width) || 1)),
      height: Math.max(1, Math.round(Number(bounds.height) || 1)),
    })
    borderRadius = Math.max(0, Math.round(Number(bounds.borderRadius) || 0))
    view.setBorderRadius(borderRadius)
    view.setVisible(true)
    if (!view.webContents.getURL()) void loadBrowserUrl(homeUrl)
    emitState()
    return true
  })

  ipcMain.handle('browser:set-bounds', (_event, bounds) => {
    if (!browserView || browserView.webContents.isDestroyed()) return false
    browserView.setBounds({
      x: Math.max(0, Math.round(Number(bounds?.x) || 0)),
      y: Math.max(0, Math.round(Number(bounds?.y) || 0)),
      width: Math.max(1, Math.round(Number(bounds?.width) || 1)),
      height: Math.max(1, Math.round(Number(bounds?.height) || 1)),
    })
    borderRadius = Math.max(0, Math.round(Number(bounds?.borderRadius) || 0))
    browserView.setBorderRadius(borderRadius)
    return true
  })

  ipcMain.handle('browser:hide', () => {
    browserView?.setVisible(false)
    return true
  })

  ipcMain.handle('browser:configure', async (_event, config) => {
    homeUrl = normalizeBrowserUrl(config?.homeUrl, DEFAULT_HOME_URL)
    applyBrowserTheme(config?.themeMode)
    configuredProxy = String(config?.proxyUrl || '').trim()
    await applyProxy(configuredProxy)
    return true
  })

  ipcMain.handle('browser:navigate', async (_event, value) => {
    const currentUrl = browserView?.webContents.getURL() || ''
    const url = currentUrl && String(value || '').trim() === redactBrowserText(currentUrl)
      ? currentUrl : normalizeBrowserUrl(value, homeUrl)
    return loadBrowserUrl(url)
  })

  ipcMain.handle('browser:command', async (_event, command) => {
    const view = ensureBrowserView()
    if (!view) return false
    const history = view.webContents.navigationHistory
    if (command === 'back' && history.canGoBack()) history.goBack()
    else if (command === 'forward' && history.canGoForward()) history.goForward()
    else if (command === 'home') await loadBrowserUrl(homeUrl)
    else if (command === 'reload') view.webContents.reload()
    else if (command === 'stop') view.webContents.stop()
    else if (command === 'external' && /^https?:\/\//iu.test(view.webContents.getURL())) {
      await shell.openExternal(view.webContents.getURL())
    }
    return true
  })

  return () => {
    closeBrowser(ordinaryBrowser)
    closeBrowser(managedBrowser)
    browserView = null
    activeBrowser = ordinaryBrowser = managedBrowser = null
  }
}

module.exports = { DEFAULT_HOME_URL, normalizeBrowserUrl, registerBrowserViewIpc }
