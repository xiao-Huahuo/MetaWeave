/**
 * Server readiness regression tests for Electron development and packaged startup.
 *
 * These checks use a real loopback HTTP server so a listening but unhealthy
 * process cannot be mistaken for a ready Vite or Agent service.
 */
import { EventEmitter } from 'node:events'
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { createRequire } from 'node:module'

import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { isMetaWeaveHealthResponse, waitForHttpReady, waitForManagedProcessReady } = require('../../electron/server-readiness.cjs') as {
  isMetaWeaveHealthResponse: (response: { statusCode: number; body: string }) => boolean
  waitForHttpReady: (
    url: string,
    options?: {
      intervalMs?: number
      timeoutMs?: number
      signal?: AbortSignal
      validateResponse?: (response: { statusCode: number; body: string }) => boolean
    },
  ) => Promise<boolean>
  waitForManagedProcessReady: (
    process: EventEmitter,
    url: string,
    options?: {
      intervalMs?: number
      timeoutMs?: number
      timeoutMessage?: string
      validateResponse?: (response: { statusCode: number; body: string }) => boolean
    },
  ) => Promise<void>
}

const servers: ReturnType<typeof createServer>[] = []

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))))
})

type RequestHandler = (request: IncomingMessage, response: ServerResponse) => void

async function listen(handler: RequestHandler): Promise<string> {
  const server = createServer(handler)
  servers.push(server)
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Loopback test server did not expose a port')
  return `http://127.0.0.1:${address.port}`
}

describe('Electron server readiness', () => {
  it('waits through transient failures until the HTTP service is actually ready', async () => {
    let requests = 0
    const url = await listen((_request, response) => {
      requests += 1
      response.writeHead(requests < 3 ? 503 : 200).end('ready')
    })

    await expect(waitForHttpReady(url, { intervalMs: 5, timeoutMs: 500 })).resolves.toBe(true)
    expect(requests).toBe(3)
  })

  it('rejects an unrelated process that happens to own the backend port', async () => {
    const url = await listen((_request, response) => {
      response.writeHead(200, { 'content-type': 'application/json' }).end('{"message":"another service"}')
    })

    await expect(waitForHttpReady(`${url}/health`, {
      intervalMs: 5,
      timeoutMs: 30,
      validateResponse: isMetaWeaveHealthResponse,
    })).resolves.toBe(false)
  })

  it('accepts the packaged backend only after its MetaWeave health response is ready', async () => {
    const process = new EventEmitter()
    const url = await listen((_request, response) => {
      response.writeHead(200, { 'content-type': 'application/json' })
        .end('{"message":"Agent-Core-Service is running"}')
    })

    await expect(waitForManagedProcessReady(process, `${url}/health`, {
      intervalMs: 5,
      timeoutMs: 500,
      validateResponse: isMetaWeaveHealthResponse,
    })).resolves.toBeUndefined()
    expect(process.listenerCount('error')).toBe(0)
    expect(process.listenerCount('exit')).toBe(0)
  })

  it('stops waiting as soon as the managed backend exits', async () => {
    const process = new EventEmitter()
    const startedAt = Date.now()
    setTimeout(() => process.emit('exit', 7, null), 10)

    await expect(waitForManagedProcessReady(process, 'http://127.0.0.1:1/health', {
      intervalMs: 500,
      timeoutMs: 5_000,
    })).rejects.toThrow('code=7')
    expect(Date.now() - startedAt).toBeLessThan(200)
  })
})
