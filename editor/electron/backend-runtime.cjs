/*
 * Packaged backend startup parameters and existing-service authorization check.
 * Main uses the same environment for AgentService startup and offline device
 * revocation, preserving the parent Windows environment and runtime DB location.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
const { randomBytes } = require('node:crypto')
const path = require('node:path')
const { localBackendOrigin } = require('./desktop-auth.cjs')

/** Bind the executable's config to the exact public URL used by the desktop. */
function packagedBackendEnvironment(backendUrl, projectRoot, desktopNonce, environment = process.env) {
  const origin = localBackendOrigin(backendUrl)
  const backend = new URL(origin)
  return {
    ...environment,
    AGENT_PROJECT_ROOT: projectRoot,
    AGENT_BASE_DATA_DIR: path.join(projectRoot, 'runtime'),
    AGENT_HTTP_HOST: backend.hostname.replace(/^\[|\]$/gu, ''),
    AGENT_HTTP_PORT: backend.port || '80',
    AGENT_FRONTEND_ORIGIN: origin,
    AGENT_DESKTOP_AUTH_NONCE: desktopNonce,
  }
}

/** Reuse only a compatible service that accepts this launch's private nonce. */
async function verifyExistingBackendAuthorization(backendUrl, desktopNonce, fetchImpl = globalThis.fetch, timeoutMs = 2_000) {
  const origin = localBackendOrigin(backendUrl)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    if (!desktopNonce) throw new Error('Missing desktop authorization')
    const deviceId = randomBytes(32).toString('hex')
    const response = await fetchImpl(`${origin}/auth/device/remembered?device_id=${deviceId}`, {
      method: 'GET', redirect: 'error', signal: controller.signal,
      headers: { 'X-Desktop-Auth': desktopNonce },
    })
    // A normal route-level 404 proves the nonce guard ran; an unknown endpoint's
    // 404 must not let an old service without global authentication be reused.
    if (response.status !== 404 || (await response.json()).detail !== 'No remembered device') {
      throw new Error('Existing service authorization rejected')
    }
  } catch {
    throw new Error('不能接管现有 Agent 服务：桌面授权不匹配或服务版本不兼容。请先关闭现有服务，再启动 MetaWeave。')
  } finally {
    clearTimeout(timer)
  }
}

module.exports = { packagedBackendEnvironment, verifyExistingBackendAuthorization }
