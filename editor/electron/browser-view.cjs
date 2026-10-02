/*
 * Embedded Chromium browser view manager.
 *
 * Usage:
 * Register once from the Electron main process. The renderer controls a single
 * sandboxed WebContentsView through the narrow IPC surface exposed by preload.
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

/** Register the embedded browser IPC handlers and return its cleanup hook. */
function registerBrowserViewIpc(ipcMain, getMainWindow) {
  let browserView = null
  let browserSession = null
  let homeUrl = DEFAULT_HOME_URL
  let currentProxy = null

  /** Send current navigation state only to the trusted application renderer. */
  function emitState(extra = {}) {
    const window = getMainWindow()
    if (!window || window.isDestroyed() || !browserView || browserView.webContents.isDestroyed()) return
    window.webContents.send('browser:state', {
      url: browserView.webContents.getURL(),
      title: browserView.webContents.getTitle() || '新标签页',
      canGoBack: browserView.webContents.navigationHistory.canGoBack(),
      canGoForward: browserView.webContents.navigationHistory.canGoForward(),
      loading: browserView.webContents.isLoading(),
      ...extra,
    })
  }

  /** Lazily create one isolated browser session and its visual surface. */
  function ensureBrowserView() {
    const window = getMainWindow()
    if (!window || window.isDestroyed()) return null
    if (browserView && !browserView.webContents.isDestroyed()) return browserView

    browserSession = session.fromPartition(BROWSER_PARTITION, { cache: true })
    browserSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
    browserView = new WebContentsView({
      webPreferences: {
        session: browserSession,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    })
    browserView.setBackgroundColor('#ffffff')
    window.contentView.addChildView(browserView)
    browserView.setVisible(false)

    browserView.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//iu.test(url)) void browserView.webContents.loadURL(url)
      return { action: 'deny' }
    })
    browserView.webContents.on('will-navigate', (event, url) => {
      if (!/^https?:\/\//iu.test(url)) event.preventDefault()
    })
    browserView.webContents.on('did-start-loading', () => emitState({ loading: true, error: '' }))
    browserView.webContents.on('did-stop-loading', () => emitState({ loading: false }))
    browserView.webContents.on('did-navigate', () => emitState())
    browserView.webContents.on('did-navigate-in-page', () => emitState())
    browserView.webContents.on('page-title-updated', () => emitState())
    browserView.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      if (isMainFrame && code !== -3) emitState({ loading: false, error: `${description}: ${url}` })
    })
    return browserView
  }

  /** Keep the browser surface alive when Chromium renders a network error page. */
  async function loadBrowserUrl(view, url) {
    try {
      await view.webContents.loadURL(url)
      return true
    } catch (error) {
      if (!view.webContents.isDestroyed()) {
        emitState({ loading: false, error: error instanceof Error ? error.message : String(error) })
      }
      return false
    }
  }

  /** Apply the resolved browser proxy without touching the application's own session. */
  async function applyProxy(proxyUrl) {
    ensureBrowserView()
    const nextProxy = String(proxyUrl || '').trim()
    if (!browserSession || nextProxy === currentProxy) return
    currentProxy = nextProxy
    await browserSession.setProxy(nextProxy
      ? { mode: 'fixed_servers', proxyRules: nextProxy }
      : { mode: 'direct' })
    await browserSession.closeAllConnections()
  }

  ipcMain.handle('browser:show', async (_event, payload) => {
    const view = ensureBrowserView()
    if (!view) return false
    const bounds = payload?.bounds || {}
    homeUrl = normalizeBrowserUrl(payload?.homeUrl, DEFAULT_HOME_URL)
    applyBrowserTheme(payload?.themeMode)
    await applyProxy(payload?.proxyUrl)
    view.setBounds({
      x: Math.max(0, Math.round(Number(bounds.x) || 0)),
      y: Math.max(0, Math.round(Number(bounds.y) || 0)),
      width: Math.max(1, Math.round(Number(bounds.width) || 1)),
      height: Math.max(1, Math.round(Number(bounds.height) || 1)),
    })
    view.setBorderRadius(Math.max(0, Math.round(Number(bounds.borderRadius) || 0)))
    view.setVisible(true)
    if (!view.webContents.getURL()) void loadBrowserUrl(view, homeUrl)
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
    browserView.setBorderRadius(Math.max(0, Math.round(Number(bounds?.borderRadius) || 0)))
    return true
  })

  ipcMain.handle('browser:hide', () => {
    browserView?.setVisible(false)
    return true
  })

  ipcMain.handle('browser:configure', async (_event, config) => {
    homeUrl = normalizeBrowserUrl(config?.homeUrl, DEFAULT_HOME_URL)
    applyBrowserTheme(config?.themeMode)
    await applyProxy(config?.proxyUrl)
    return true
  })

  ipcMain.handle('browser:navigate', async (_event, value) => {
    const view = ensureBrowserView()
    if (!view) return false
    return loadBrowserUrl(view, normalizeBrowserUrl(value, homeUrl))
  })

  ipcMain.handle('browser:command', async (_event, command) => {
    const view = ensureBrowserView()
    if (!view) return false
    const history = view.webContents.navigationHistory
    if (command === 'back' && history.canGoBack()) history.goBack()
    else if (command === 'forward' && history.canGoForward()) history.goForward()
    else if (command === 'home') await loadBrowserUrl(view, homeUrl)
    else if (command === 'reload') view.webContents.reload()
    else if (command === 'stop') view.webContents.stop()
    else if (command === 'external' && /^https?:\/\//iu.test(view.webContents.getURL())) {
      await shell.openExternal(view.webContents.getURL())
    }
    return true
  })

  return () => {
    if (browserView && !browserView.webContents.isDestroyed()) browserView.webContents.close()
    browserView = null
    browserSession = null
  }
}

module.exports = { DEFAULT_HOME_URL, normalizeBrowserUrl, registerBrowserViewIpc }
