/*
 * Supervised desktop development launcher: npm run dev:electron.
 * Owns Vite, the local Python backend and Electron, shares a private per-launch
 * auth nonce, and stops all owned child processes on quit, failure or interrupt.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
const { spawn, spawnSync } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const { localBackendOrigin } = require('../electron/desktop-auth.cjs')
const { isMetaWeaveHealthResponse, waitForManagedProcessReady } = require('../electron/server-readiness.cjs')

const editorRoot = path.resolve(__dirname, '..')
const projectRoot = path.resolve(editorRoot, '..')
const backendUrl = localBackendOrigin(process.env.METAWEAVE_BACKEND_URL || 'http://127.0.0.1:8002')
const rendererUrl = localBackendOrigin(process.env.ELECTRON_RENDERER_URL || process.env.VITE_DEV_SERVER_URL
  || `http://127.0.0.1:${process.env.VITE_PORT || '5173'}`)
const nonce = randomBytes(32).toString('hex')
const children = new Set()
let stopping = false

/** Require free ports so this launch never claims or kills another user's service. */
function assertPortFree(origin) {
  const url = new URL(origin)
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', () => reject(new Error(`端口已占用，请关闭现有服务后重试：${origin}`)))
    server.listen(Number(url.port || 80), url.hostname.replace(/^\[|\]$/gu, ''), () => server.close(resolve))
  })
}

/** Stop only processes owned by this launcher, including Windows child trees. */
function stop(code = 0) {
  if (stopping) return
  stopping = true
  process.exitCode = code
  for (const child of children) {
    if (!child.pid || child.exitCode !== null) continue
    if (process.platform === 'win32') {
      spawnSync('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' })
    } else {
      try { process.kill(-child.pid, 'SIGTERM') } catch { child.kill('SIGTERM') }
    }
  }
  children.clear()
}

/** Spawn one supervised child with hidden helper windows and an explicit owner. */
function launch(executable, args, cwd, env) {
  const child = spawn(executable, args, { cwd, env, windowsHide: true, stdio: 'inherit', detached: process.platform !== 'win32' })
  children.add(child)
  child.once('error', () => {
    console.error('桌面开发子进程启动失败，请检查 Python/Node/Electron 运行环境。')
    stop(1)
  })
  child.once('exit', (code) => {
    children.delete(child)
    if (!stopping) stop(code || 0)
  })
  return child
}

/** Resolve the existing Python environment; METAWEAVE_PYTHON permits explicit selection. */
function pythonExecutable() {
  if (process.env.METAWEAVE_PYTHON) return process.env.METAWEAVE_PYTHON
  const candidate = path.join(projectRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  return fs.existsSync(candidate) ? candidate : process.platform === 'win32' ? 'python' : 'python3'
}

/** Start each service with matching URLs, then launch Electron after both are ready. */
async function main() {
  await assertPortFree(backendUrl)
  await assertPortFree(rendererUrl)
  const backend = new URL(backendUrl)
  const renderer = new URL(rendererUrl)
  const desktopEnv = {
    ...process.env,
    AGENT_DESKTOP_AUTH_NONCE: nonce,
    AGENT_FRONTEND_ORIGIN: rendererUrl,
    AGENT_HTTP_HOST: backend.hostname.replace(/^\[|\]$/gu, ''),
    AGENT_HTTP_PORT: backend.port || '80',
    METAWEAVE_BACKEND_URL: backendUrl,
    ELECTRON_RENDERER_URL: rendererUrl,
  }
  const backendProcess = launch(pythonExecutable(), [
    '-m', 'uvicorn', 'main:app', '--host', backend.hostname.replace(/^\[|\]$/gu, ''), '--port', backend.port || '80',
  ], projectRoot, desktopEnv)
  await waitForManagedProcessReady(backendProcess, `${backendUrl}/health`, {
    timeoutMs: 120_000, validateResponse: isMetaWeaveHealthResponse,
  })
  if (stopping) return
  const viteEnv = { ...process.env, VITE_DEV_PROXY_TARGET: backendUrl, VITE_PORT: renderer.port || '80' }
  delete viteEnv.AGENT_DESKTOP_AUTH_NONCE
  const vite = launch(process.execPath, [path.join(editorRoot, 'node_modules/vite/bin/vite.js'),
    '--host', renderer.hostname.replace(/^\[|\]$/gu, ''), '--port', renderer.port || '80'], editorRoot, viteEnv)
  await waitForManagedProcessReady(vite, rendererUrl, { timeoutMs: 120_000 })
  if (stopping) return
  launch(require('electron'), [path.join(editorRoot, 'electron/main.cjs')], editorRoot, desktopEnv)
}

process.once('SIGINT', () => stop(130))
process.once('SIGTERM', () => stop(143))
process.once('exit', () => stop(process.exitCode || 0))
main().catch((error) => {
  console.error(error.message)
  stop(1)
})
