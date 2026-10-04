/*
 * Packaged startup regressions for URL/config alignment and nonce-based reuse.
 * Run one worker after desktopAuth.spec.ts; no executable or listener is started.
 */
import { createRequire } from 'node:module'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

const require = createRequire(import.meta.url)
const { packagedBackendEnvironment, verifyExistingBackendAuthorization } = require('../../electron/backend-runtime.cjs') as {
  packagedBackendEnvironment: (url: string, root: string, nonce: string, environment: Record<string, string>) => Record<string, string>
  verifyExistingBackendAuthorization: (url: string, nonce: string, fetchImpl: unknown, timeoutMs?: number) => Promise<void>
}

/** Minimal HTTP stub distinguishes a signed device miss from an unknown route. */
function response(status: number, detail = 'No remembered device'): Response {
  return { status, json: async () => ({ detail }) } as Response
}

afterEach(() => { vi.useRealTimers() })

describe('packaged backend runtime', () => {
  it('aligns a custom port, frontend origin and offline CLI DB while preserving Windows environment', () => {
    const root = path.resolve('packaged-user-data')
    const environment = packagedBackendEnvironment('http://127.0.0.1:18764', root, 'private-launch-nonce', {
      SystemDrive: 'C:', PATH: 'existing-runtime-path', AGENT_HTTP_PORT: '8002', AGENT_FRONTEND_ORIGIN: 'http://127.0.0.1:5173',
    })
    expect(environment).toEqual({
      SystemDrive: 'C:', PATH: 'existing-runtime-path',
      AGENT_PROJECT_ROOT: root, AGENT_BASE_DATA_DIR: path.join(root, 'runtime'),
      AGENT_HTTP_HOST: '127.0.0.1', AGENT_HTTP_PORT: '18764', AGENT_FRONTEND_ORIGIN: 'http://127.0.0.1:18764',
      AGENT_DESKTOP_AUTH_NONCE: 'private-launch-nonce',
    })
    expect(packagedBackendEnvironment('http://[::1]:8127', root, 'nonce', {}).AGENT_HTTP_HOST).toBe('::1')
  })

  it('accepts an authorized missing-device response and uses a fresh bounded random ID', async () => {
    const fetchImpl = vi.fn(async (_url: string, _init: RequestInit) => response(404))
    await expect(verifyExistingBackendAuthorization('http://127.0.0.1:18764', 'nonce', fetchImpl)).resolves.toBeUndefined()
    const [url, init] = fetchImpl.mock.calls[0]!
    expect(url).toMatch(/^http:\/\/127\.0\.0\.1:18764\/auth\/device\/remembered\?device_id=[0-9a-f]{64}$/u)
    expect(init).toMatchObject({ method: 'GET', redirect: 'error', headers: { 'X-Desktop-Auth': 'nonce' } })
  })

  it('rejects health-compatible services with a different nonce or unknown auth route', async () => {
    await expect(verifyExistingBackendAuthorization('http://127.0.0.1:8002', 'nonce', vi.fn(async () => response(403))))
      .rejects.toThrow('不能接管现有')
    await expect(verifyExistingBackendAuthorization('http://127.0.0.1:8002', 'nonce', vi.fn(async () => response(404, 'Not Found'))))
      .rejects.toThrow('服务版本不兼容')
  })

  it('rejects unsigned or remote destinations before any authorization request', async () => {
    const fetchImpl = vi.fn()
    await expect(verifyExistingBackendAuthorization('http://127.0.0.1:8002', '', fetchImpl)).rejects.toThrow('不能接管现有')
    await expect(verifyExistingBackendAuthorization('http://example.com', 'nonce', fetchImpl)).rejects.toThrow('只能连接本机')
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('bounds an unresponsive existing-service probe and releases its timer', async () => {
    vi.useFakeTimers()
    const fetchImpl = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
    }))
    const probe = verifyExistingBackendAuthorization('http://127.0.0.1:8002', 'nonce', fetchImpl, 20)
    const rejected = expect(probe).rejects.toThrow('不能接管现有')
    await vi.advanceTimersByTimeAsync(20)
    await rejected
    expect(vi.getTimerCount()).toBe(0)
  })
})
