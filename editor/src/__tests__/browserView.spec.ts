/*
 * Native browser regression tests for managed DSH credentials and view ownership.
 * Usage: run this file with one Vitest worker; the Electron API is replaced by a
 * small transport double so no windows, network requests, or profiles are opened.
 */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'

const require = createRequire(import.meta.url)
const source = readFileSync(require.resolve('../../electron/browser-view.cjs'), 'utf8')
const managedUrl = 'http://127.0.0.1:3080/#mw_token=private-credential&session=child&readonly=1'
type Bounds = { x: number; y: number; width: number; height: number }

/** Load the real CJS manager against a controllable Electron transport. */
function browserHarness() {
  const handlers = new Map<string, (...args: any[]) => any>()
  const sessions = new Map<string, any>()
  const views: NativeView[] = []
  const fromPartition = vi.fn((partition: string, options: { cache: boolean }) => {
    const value = {
      partition, options,
      setPermissionRequestHandler: vi.fn(),
      setProxy: vi.fn().mockResolvedValue(undefined),
      closeAllConnections: vi.fn().mockResolvedValue(undefined),
    }
    sessions.set(partition, value)
    return value
  })

  /** Track the active native surface, its URL, and its deterministic events. */
  class NativeView {
    options: any
    bounds: Bounds = { x: 0, y: 0, width: 1, height: 1 }
    visible = false
    destroyed = false
    url = ''
    events = new Map<string, (...args: any[]) => any>()
    webContents = {
      isDestroyed: () => this.destroyed,
      getURL: () => this.url,
      getTitle: () => 'DSH',
      isLoading: () => false,
      navigationHistory: {
        canGoBack: () => true, canGoForward: () => true,
        goBack: vi.fn(), goForward: vi.fn(),
      },
      on: (name: string, callback: (...args: any[]) => any) => this.events.set(name, callback),
      setWindowOpenHandler: vi.fn(),
      loadURL: vi.fn(async (url: string) => {
        this.url = url
        this.events.get('did-navigate')?.()
      }),
      reload: vi.fn(), stop: vi.fn(),
      close: vi.fn(() => { this.destroyed = true }),
    }

    /** Save the real webPreferences supplied by the manager. */
    constructor(options: any) { this.options = options; views.push(this) }
    /** Native getters expose the bounds and visibility transferred on switching. */
    getBounds() { return this.bounds }
    getVisible() { return this.visible }
    /** Native setters preserve the same surface placement and presentation. */
    setBounds(bounds: Bounds) { this.bounds = bounds }
    setVisible(visible: boolean) { this.visible = visible }
    setBorderRadius() {}
    setBackgroundColor() {}
  }

  const window = {
    isDestroyed: () => false,
    contentView: { addChildView: vi.fn(), removeChildView: vi.fn() },
    webContents: { send: vi.fn() },
  }
  const module = { exports: {} as { registerBrowserViewIpc: (...args: any[]) => () => void } }
  runInNewContext(source, {
    module, URL, URLSearchParams,
    require: (name: string) => name === 'electron'
      ? { nativeTheme: {}, session: { fromPartition }, shell: { openExternal: vi.fn() }, WebContentsView: NativeView }
      : require(name),
  })
  const dispose = module.exports.registerBrowserViewIpc({
    handle: (name: string, callback: (...args: any[]) => any) => handlers.set(name, callback),
  }, () => window)
  const invoke = (name: string, value?: unknown) => handlers.get(`browser:${name}`)?.({}, value)
  const active = () => views.find(view => view.visible && !view.destroyed)!
  return { active, dispose, fromPartition, invoke, sessions, views, window }
}

describe('native managed DSH browser', () => {
  it('keeps DSH credentials in a temporary session and masks renderer state', async () => {
    const browser = browserHarness()
    await browser.invoke('show', { bounds: { x: 20, y: 30, width: 600, height: 400 } })
    const ordinary = browser.active()
    await browser.invoke('navigate', managedUrl)
    const managed = browser.active()

    expect(managed).not.toBe(ordinary)
    expect(managed.options.webPreferences.session.partition).not.toMatch(/^persist:/)
    expect(managed.options.webPreferences.session.options.cache).toBe(false)
    expect(managed.webContents.getURL()).toBe(managedUrl)
    expect(managed.bounds).toEqual(ordinary.bounds)
    expect(ordinary.visible).toBe(false)
    expect(JSON.stringify(browser.window.webContents.send.mock.calls)).not.toContain('private-credential')
    browser.dispose()
  })

  it('masks navigation errors without removing the native authentication fragment', async () => {
    const browser = browserHarness()
    await browser.invoke('show', {})
    await browser.invoke('navigate', managedUrl)
    const managed = browser.active()
    managed.events.get('did-fail-load')?.({}, -105, 'ERR_NAME_NOT_RESOLVED', managedUrl, true)
    managed.webContents.loadURL.mockRejectedValueOnce(new Error(`failed loading ${managedUrl}`))
    await browser.invoke('navigate', managedUrl)

    const states = JSON.stringify(browser.window.webContents.send.mock.calls)
    expect(states).toContain('ERR_NAME_NOT_RESOLVED')
    expect(states).not.toContain('private-credential')
    expect(managed.webContents.getURL()).toBe(managedUrl)
    browser.dispose()
  })

  it('retains authenticated reload and history while restoring ordinary browsing', async () => {
    const browser = browserHarness()
    await browser.invoke('show', {})
    const ordinary = browser.active()
    await browser.invoke('navigate', managedUrl)
    const managed = browser.active()
    await browser.invoke('command', 'reload')
    await browser.invoke('command', 'back')
    await browser.invoke('command', 'forward')

    expect(managed.webContents.reload).toHaveBeenCalledOnce()
    expect(managed.webContents.navigationHistory.goBack).toHaveBeenCalledOnce()
    expect(managed.webContents.navigationHistory.goForward).toHaveBeenCalledOnce()
    expect(managed.webContents.getURL()).toBe(managedUrl)
    const displayed = browser.window.webContents.send.mock.calls.at(-1)?.[1].url
    await browser.invoke('navigate', displayed)
    expect(browser.active()).toBe(managed)
    expect(managed.webContents.loadURL).toHaveBeenLastCalledWith(managedUrl)
    await browser.invoke('navigate', 'https://example.com')
    expect(browser.active()).toBe(ordinary)
    expect(ordinary.options.webPreferences.session.partition).toBe('persist:metaweave-browser')
    const stateCount = browser.window.webContents.send.mock.calls.length
    managed.events.get('did-navigate')?.()
    managed.events.get('will-navigate')?.({ preventDefault: vi.fn() }, managedUrl)
    expect(browser.window.webContents.send.mock.calls).toHaveLength(stateCount)
    browser.dispose()
    expect(ordinary.destroyed).toBe(true)
    expect(managed.destroyed).toBe(true)
  })

  it('uses direct loopback networking and releases the previous DSH runtime view', async () => {
    const browser = browserHarness()
    await browser.invoke('show', { proxyUrl: 'http://proxy.example:8080' })
    const ordinary = browser.active()
    await browser.invoke('navigate', managedUrl)
    const first = browser.active()
    expect(first.options.webPreferences.session.setProxy).toHaveBeenLastCalledWith({ mode: 'direct' })
    await browser.invoke('navigate', managedUrl.replace(':3080', ':3081'))
    expect(browser.active()).not.toBe(first)
    expect(first.destroyed).toBe(true)
    expect(browser.window.contentView.removeChildView).toHaveBeenCalledWith(first)
    await browser.invoke('navigate', 'https://example.com')
    expect(browser.active()).toBe(ordinary)
    expect(ordinary.options.webPreferences.session.setProxy).toHaveBeenLastCalledWith({ mode: 'fixed_servers', proxyRules: 'http://proxy.example:8080' })
    browser.dispose()
  })

  it('keeps the DSH surface active when navigation overlaps browser configuration', async () => {
    const browser = browserHarness()
    await browser.invoke('show', {})
    const ordinary = browser.active()
    let releaseProxy!: () => void
    ordinary.options.webPreferences.session.setProxy.mockImplementationOnce(
      () => new Promise<void>(resolve => { releaseProxy = resolve }),
    )
    const showing = browser.invoke('show', { proxyUrl: 'http://proxy.example:8080' })
    await browser.invoke('navigate', managedUrl)
    const managed = browser.active()
    releaseProxy()
    await showing

    expect(browser.active()).toBe(managed)
    expect(ordinary.visible).toBe(false)
    expect(managed.webContents.getURL()).toBe(managedUrl)
    browser.dispose()
  })

  it('retains the existing empty-omnibox home navigation before first show', async () => {
    const browser = browserHarness()
    await browser.invoke('navigate', '')
    expect(browser.views[0]?.webContents.getURL()).toBe('https://www.google.com')
    browser.dispose()
  })
})
