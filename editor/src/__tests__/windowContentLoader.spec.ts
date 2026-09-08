import { createRequire } from 'node:module'
import { describe, expect, it, vi } from 'vitest'

const require = createRequire(import.meta.url)
const { loadWindowContent, restoreExistingWindow } = require('../../electron/window-content-loader.cjs') as {
  loadWindowContent: (
    window: { isDestroyed: () => boolean },
    load: () => Promise<void>,
    showError: (error: unknown) => Promise<void>,
    logError?: (message: string, error: unknown) => void,
  ) => Promise<boolean>
  restoreExistingWindow: (
    window: { focus: () => void; isDestroyed: () => boolean; isMinimized: () => boolean; restore: () => void; show: () => void },
    reload: () => Promise<void>,
  ) => Promise<boolean>
}

describe('Electron window content loading', () => {
  it('resolves false and shows the startup error when renderer loading fails', async () => {
    const error = new Error('Vite development server is unavailable')
    const showError = vi.fn<(error: unknown) => Promise<void>>().mockResolvedValue(undefined)

    await expect(loadWindowContent(
      { isDestroyed: () => false },
      () => Promise.reject(error),
      showError,
    )).resolves.toBe(false)

    expect(showError).toHaveBeenCalledWith(error)
  })

  it('does not navigate a window that was destroyed while waiting', async () => {
    const showError = vi.fn<(error: unknown) => Promise<void>>().mockResolvedValue(undefined)

    await expect(loadWindowContent(
      { isDestroyed: () => true },
      () => Promise.reject(new Error('renderer unavailable')),
      showError,
    )).resolves.toBe(false)

    expect(showError).not.toHaveBeenCalled()
  })

  it('treats an aborted navigation as an expected settled load', async () => {
    const showError = vi.fn<(error: unknown) => Promise<void>>().mockResolvedValue(undefined)

    await expect(loadWindowContent(
      { isDestroyed: () => false },
      () => Promise.reject(new Error('ERR_ABORTED (-3) loading URL')),
      showError,
    )).resolves.toBe(false)

    expect(showError).not.toHaveBeenCalled()
  })

  it('still settles when rendering the error page itself fails', async () => {
    const error = new Error('Vite development server is unavailable')
    const displayError = new Error('error page failed')
    const logError = vi.fn<(message: string, error: unknown) => void>()

    await expect(loadWindowContent(
      { isDestroyed: () => false },
      () => Promise.reject(error),
      () => Promise.reject(displayError),
      logError,
    )).resolves.toBe(false)

    expect(logError).toHaveBeenCalledWith('Failed to show renderer load error:', displayError)
  })

  it('returns true when the renderer loads successfully', async () => {
    const showError = vi.fn<(error: unknown) => Promise<void>>().mockResolvedValue(undefined)

    await expect(loadWindowContent(
      { isDestroyed: () => false },
      () => Promise.resolve(),
      showError,
    )).resolves.toBe(true)

    expect(showError).not.toHaveBeenCalled()
  })

  it('reloads an existing development window after a second launch', async () => {
    const window = {
      focus: vi.fn(),
      isDestroyed: () => false,
      isMinimized: () => true,
      restore: vi.fn(),
      show: vi.fn(),
    }
    const reload = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)

    await expect(restoreExistingWindow(window, reload)).resolves.toBe(true)

    expect(window.restore).toHaveBeenCalledOnce()
    expect(window.show).toHaveBeenCalledOnce()
    expect(window.focus).toHaveBeenCalledOnce()
    expect(reload).toHaveBeenCalledOnce()
  })
})
