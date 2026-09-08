/*
 * Loopback HTTP readiness checks shared by Electron startup and 启动.bat.
 *
 * Usage:
 * - Require this module from the Electron main process.
 * - CLI: node server-readiness.cjs <url> [timeout-ms] [metaweave]
 */
/* eslint-disable @typescript-eslint/no-require-imports */

const http = require('node:http')
const https = require('node:https')

const DEFAULT_REQUEST_TIMEOUT_MS = 2_000
const MAX_RESPONSE_CHARS = 64 * 1024

/** Read one bounded HTTP response; connection failures are reported as null. */
function requestUrl(url, timeoutMs, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve(null)
      return
    }
    const target = new URL(url)
    const transport = target.protocol === 'https:' ? https : http
    let settled = false
    let body = ''
    const finish = (value) => {
      if (settled) return
      settled = true
      signal?.removeEventListener('abort', abort)
      resolve(value)
    }
    const request = transport.get(target, { timeout: timeoutMs }, (response) => {
      response.setEncoding('utf8')
      response.on('data', (chunk) => {
        if (body.length < MAX_RESPONSE_CHARS) body += String(chunk)
      })
      response.on('end', () => finish({ statusCode: response.statusCode || 0, body }))
      response.on('error', () => finish(null))
    })
    const abort = () => {
      request.destroy()
      finish(null)
    }
    signal?.addEventListener('abort', abort, { once: true })
    request.on('timeout', () => request.destroy())
    request.on('error', () => finish(null))
  })
}

/** Return whether the response is a successful MetaWeave Agent health payload. */
function isMetaWeaveHealthResponse(response) {
  if (response.statusCode !== 200) return false
  try {
    return JSON.parse(response.body).message === 'Agent-Core-Service is running'
  } catch {
    return false
  }
}

/** Wait for a retry delay while allowing a managed process exit to cancel it immediately. */
function waitForDelay(delayMs, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve()
      return
    }
    const timer = setTimeout(finish, delayMs)
    function finish() {
      clearTimeout(timer)
      signal?.removeEventListener('abort', finish)
      resolve()
    }
    signal?.addEventListener('abort', finish, { once: true })
  })
}

/** Poll an HTTP URL until its response passes validation, timeout, or cancellation. */
async function waitForHttpReady(url, options = {}) {
  const intervalMs = Math.max(1, Number(options.intervalMs) || 250)
  const timeoutMs = Math.max(1, Number(options.timeoutMs) || 20_000)
  const validateResponse = options.validateResponse || ((response) => response.statusCode >= 200 && response.statusCode < 400)
  const deadline = Date.now() + timeoutMs

  while (!options.signal?.aborted && Date.now() < deadline) {
    const remainingMs = deadline - Date.now()
    const response = await requestUrl(url, Math.min(DEFAULT_REQUEST_TIMEOUT_MS, remainingMs), options.signal)
    if (response && validateResponse(response)) return true
    if (options.signal?.aborted || Date.now() >= deadline) break
    await waitForDelay(Math.min(intervalMs, deadline - Date.now()), options.signal)
  }
  return false
}

/** Wait for a child-owned HTTP service and fail immediately if that child exits. */
async function waitForManagedProcessReady(process, url, options = {}) {
  const controller = new AbortController()
  let startupFailure = null
  const onError = (error) => {
    startupFailure = new Error(`内置 Agent 服务启动失败: ${error}`)
    controller.abort()
  }
  const onExit = (code, signal) => {
    startupFailure = new Error(`内置 Agent 服务在启动期间退出: code=${code ?? 'null'}, signal=${signal ?? 'none'}`)
    controller.abort()
  }
  process.once('error', onError)
  process.once('exit', onExit)
  try {
    const ready = await waitForHttpReady(url, { ...options, signal: controller.signal })
    if (!ready) throw startupFailure || new Error(options.timeoutMessage || `服务未能在规定时间内启动: ${url}`)
  } finally {
    process.removeListener('error', onError)
    process.removeListener('exit', onExit)
  }
}

module.exports = { isMetaWeaveHealthResponse, waitForHttpReady, waitForManagedProcessReady }

if (require.main === module) {
  const url = process.argv[2]
  const timeoutMs = Number(process.argv[3]) || 120_000
  const validateResponse = process.argv[4] === 'metaweave' ? isMetaWeaveHealthResponse : undefined
  if (!url) {
    console.error('Usage: node server-readiness.cjs <url> [timeout-ms] [metaweave]')
    process.exitCode = 2
  } else {
    waitForHttpReady(url, { timeoutMs, validateResponse }).then((ready) => {
      process.exitCode = ready ? 0 : 1
    })
  }
}
