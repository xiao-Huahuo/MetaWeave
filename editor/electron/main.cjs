/*
 * Electron main process for the editor desktop shell.
 *
 * Usage:
 * - Development: npm run dev:electron
 * - Production preview: npm run build && npm run electron
 *
 * The BrowserWindow is intentionally frameless. Window controls are exposed to
 * the renderer through preload.cjs and rendered in TopCommandBar.vue.
 */
/* eslint-disable @typescript-eslint/no-require-imports */

const { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell, Tray, nativeImage } = require('electron')
const childProcess = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { handleEditShortcut } = require('./edit-shortcuts.cjs')
const { boundsForMainDragRestore, finishMainWindowRestore } = require('./main-window-state.cjs')
const { isMetaWeaveHealthResponse, waitForHttpReady, waitForManagedProcessReady } = require('./server-readiness.cjs')
const { isAbortedNavigation, loadWindowContent, restoreExistingWindow } = require('./window-content-loader.cjs')
const { registerBrowserViewIpc } = require('./browser-view.cjs')

const DEV_SERVER_URL = process.env.ELECTRON_RENDERER_URL || 'http://127.0.0.1:5173'
const BACKEND_SERVER_URL = process.env.METAWEAVE_BACKEND_URL || 'http://127.0.0.1:8002'
const BACKEND_HEALTH_URL = new URL('/health', BACKEND_SERVER_URL).toString()
const APP_ICON_FILENAME = process.platform === 'darwin' ? 'app.icns' : 'app.ico'
const APP_ICON_PATH = path.join(__dirname, '..', 'src', 'assets', 'icons', APP_ICON_FILENAME)

app.setName('MetaWeave')

const hasSingleInstanceLock = app.requestSingleInstanceLock({ rendererUrl: DEV_SERVER_URL })
if (!hasSingleInstanceLock) {
  app.quit()
  process.exit(0)
}

let mainWindow = null
let tray = null
let floatingWindow = null
let backendProcess = null
let mainMoveSession = null
let mainResizeSession = null
const disposeBrowserView = registerBrowserViewIpc(ipcMain, () => mainWindow)

const MAIN_MIN_WIDTH = 320
const MAIN_MIN_HEIGHT = 620
const MAIN_WINDOW_RADIUS = 28

/** Resolve the window that owns a given IPC event, falling back to mainWindow. */
function windowFromEvent(event) {
  return BrowserWindow.fromWebContents(event.sender) || mainWindow
}

function buildDropEffectBuffer(mode) {
  const effect = mode === 'cut' ? 2 : 1
  return Buffer.from([effect, 0, 0, 0])
}

function writeWindowsFileClipboard(filePaths, mode) {
  const payload = Buffer.from(JSON.stringify(filePaths), 'utf8').toString('base64')
  const effect = mode === 'cut' ? 2 : 1
  const script = `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$json = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($env:METAWEAVE_CLIPBOARD_FILES_B64))
$paths = ConvertFrom-Json -InputObject $json
$files = New-Object System.Collections.Specialized.StringCollection
foreach ($item in $paths) {
  if ([string]::IsNullOrWhiteSpace([string]$item)) { continue }
  [void]$files.Add([string]$item)
}
if ($files.Count -le 0) { throw 'empty file drop list' }
$data = New-Object System.Windows.Forms.DataObject
$data.SetFileDropList($files)
$effectBytes = [byte[]](${effect}, 0, 0, 0)
$effectStream = New-Object System.IO.MemoryStream
$effectStream.Write($effectBytes, 0, $effectBytes.Length)
$effectStream.Position = 0
$data.SetData('Preferred DropEffect', $effectStream)
[System.Windows.Forms.Clipboard]::SetDataObject($data, $true, 10, 100)
`
  return new Promise((resolve) => {
    const child = childProcess.spawn(
      'powershell.exe',
      ['-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-Command', script],
      {
        env: {
          ...process.env,
          METAWEAVE_CLIPBOARD_FILES_B64: payload,
        },
        windowsHide: true,
      },
    )
    let stderr = ''
    child.stderr.on('data', (chunk) => {
      stderr += String(chunk)
    })
    child.on('error', () => resolve(false))
    child.on('close', (code) => {
      if (code !== 0 && stderr.trim()) {
        console.warn('writeWindowsFileClipboard failed:', stderr.trim())
      }
      resolve(code === 0)
    })
  })
}

function readClipboardDropEffect() {
  const buffer = clipboard.readBuffer('Preferred DropEffect')
  if (!buffer || buffer.length === 0) {
    return 'copy'
  }
  return buffer[0] === 2 ? 'cut' : 'copy'
}

function splitNameExtension(filename) {
  const extension = path.extname(filename)
  const stem = extension ? filename.slice(0, -extension.length) : filename
  return { stem, extension }
}

function uniqueChildPath(targetDir, preferredName) {
  const safeName = path.basename(preferredName).trim() || 'untitled'
  const firstPath = path.join(targetDir, safeName)
  if (!fs.existsSync(firstPath)) {
    return firstPath
  }
  const { stem, extension } = splitNameExtension(safeName)
  for (let index = 1; index < 1000; index += 1) {
    const candidate = path.join(targetDir, `${stem} (${index})${extension}`)
    if (!fs.existsSync(candidate)) {
      return candidate
    }
  }
  return path.join(targetDir, `${stem} ${Date.now()}${extension}`)
}

async function copyOrMovePath(sourcePath, targetPath, mode) {
  const sourceStat = await fs.promises.stat(sourcePath)
  if (sourceStat.isDirectory()) {
    await fs.promises.cp(sourcePath, targetPath, { recursive: true, force: true })
  } else {
    await fs.promises.copyFile(sourcePath, targetPath)
  }
  if (mode === 'cut') {
    await fs.promises.rm(sourcePath, { recursive: true, force: true })
  }
}

function readClipboardFilePayload() {
  let filePaths = []
  let mode = 'copy'

  // Electron 15+ native clipboard API reads CF_HDROP correctly.
  if (typeof clipboard.readFiles === 'function') {
    try {
      const files = clipboard.readFiles()
      filePaths = files.filter((f) => f.path).map((f) => f.path)
    } catch {
      filePaths = []
    }
  }

  // Fallback: parse FileNameW buffer manually (older Electron or non-Windows).
  if (filePaths.length === 0) {
    filePaths = clipboard.readText().split(/\r?\n/u).map((item) => item.trim()).filter(Boolean)
  }

  mode = readClipboardDropEffect()

  return {
    mode,
    paths: filePaths.filter((item) => fs.existsSync(item)),
  }
}

function listWindowsFontFamilies() {
  const script = `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$fonts = (New-Object System.Drawing.Text.InstalledFontCollection).Families |
  ForEach-Object { $_.Name } |
  Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
  Sort-Object -Unique
$json = $fonts | ConvertTo-Json -Compress
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
`
  return new Promise((resolve) => {
    const child = childProcess.spawn(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
      { windowsHide: true },
    )
    let stdout = ''
    child.stdout.on('data', (chunk) => {
      stdout += String(chunk)
    })
    child.on('error', () => resolve([]))
    child.on('close', (code) => {
      if (code !== 0 || !stdout.trim()) {
        resolve([])
        return
      }
      try {
        const json = Buffer.from(stdout.trim(), 'base64').toString('utf8')
        const payload = JSON.parse(json)
        resolve(Array.isArray(payload) ? payload : [payload])
      } catch {
        resolve([])
      }
    })
  })
}

function listUnixFontFamilies() {
  return new Promise((resolve) => {
    const child = childProcess.spawn('fc-list', [':', 'family'], { windowsHide: true })
    let stdout = ''
    child.stdout.on('data', (chunk) => {
      stdout += String(chunk)
    })
    child.on('error', () => resolve([]))
    child.on('close', (code) => {
      if (code !== 0) {
        resolve([])
        return
      }
      const fonts = stdout
        .split(/\r?\n/u)
        .flatMap((line) => line.split(','))
        .map((item) => item.trim())
        .filter(Boolean)
      resolve([...new Set(fonts)].sort((a, b) => a.localeCompare(b)))
    })
  })
}

function isDevelopment() {
  return !app.isPackaged && process.env.ELECTRON_FORCE_PROD !== 'true'
}

function shouldOpenDevTools() {
  return process.env.ELECTRON_OPEN_DEVTOOLS === 'true'
}

async function loadDevServer(window, query, serverUrl = DEV_SERVER_URL) {
  if (!await waitForHttpReady(serverUrl, { timeoutMs: 120_000 })) {
    throw new Error(`Vite development server is unavailable: ${serverUrl}`)
  }
  const url = query
    ? `${serverUrl}?${new URLSearchParams(query).toString()}`
    : serverUrl
  await window.loadURL(url)
}

function packagedBackendPath() {
  return path.join(process.resourcesPath, 'backend', 'AgentService.exe')
}

function packagedDefaultResourcesPath() {
  return path.join(process.resourcesPath, 'default-resources')
}

function startupPage(title, message, isError = false) {
  const accent = isError ? '#ff6b7a' : '#8b7bff'
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: #11121a; color: #f4f4f7; }
    body { display: grid; place-items: center; }
    main { width: min(560px, calc(100vw - 64px)); padding: 32px; box-sizing: border-box; border: 1px solid #303243; border-radius: 16px; background: #191b27; box-shadow: 0 20px 60px #0008; }
    h1 { margin: 0 0 12px; font-size: 22px; font-weight: 600; }
    p { margin: 0; color: #aeb1c2; line-height: 1.6; white-space: pre-wrap; }
    .mark { width: 10px; height: 10px; margin-bottom: 20px; border-radius: 50%; background: ${accent}; box-shadow: 0 0 18px ${accent}; }
  </style></head><body><main><div class="mark"></div><h1>${title}</h1><p>${message}</p></main></body></html>`
}

async function loadStartupPage(window) {
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(startupPage('MetaWeave', '正在启动本地 Agent 服务，请稍候…'))}`)
}

async function showStartupError(window, error) {
  if (!window || window.isDestroyed()) {
    return
  }
  const message = error instanceof Error ? error.message : String(error)
  await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(startupPage('MetaWeave 启动失败', message, true))}`)
  window.show()
  window.focus()
}

function loadRenderer(window, query, displayError = false, developmentServerUrl = DEV_SERVER_URL) {
  return loadWindowContent(
    window,
    () => isDevelopment() ? loadDevServer(window, query, developmentServerUrl) : loadPackagedBackend(window, query),
    (error) => {
      if (displayError) {
        return showStartupError(window, error)
      }
      console.error('Failed to load floating renderer:', error)
      return Promise.resolve()
    },
  )
}

function userProjectRoot() {
  return app.getPath('userData')
}

function copyMissing(source, target) {
  if (!fs.existsSync(source) || fs.existsSync(target)) {
    return
  }
  fs.cpSync(source, target, { recursive: true })
}

function ensurePackagedUserResources() {
  if (!app.isPackaged) {
    return userProjectRoot()
  }
  const projectRoot = userProjectRoot()
  const resourcesRoot = path.join(projectRoot, 'resources')
  const defaultsRoot = packagedDefaultResourcesPath()

  fs.mkdirSync(path.join(resourcesRoot, 'knowledge'), { recursive: true })
  fs.mkdirSync(path.join(resourcesRoot, 'mcp'), { recursive: true })
  copyMissing(path.join(defaultsRoot, 'mcp', 'example.json'), path.join(resourcesRoot, 'mcp', 'example.json'))
  copyMissing(path.join(defaultsRoot, 'safety'), path.join(resourcesRoot, 'safety'))
  copyMissing(path.join(defaultsRoot, 'skills'), path.join(resourcesRoot, 'skills'))

  return projectRoot
}

async function startPackagedBackend() {
  if (!app.isPackaged || process.platform !== 'win32') {
    return
  }
  if (await waitForHttpReady(BACKEND_HEALTH_URL, {
    timeoutMs: 1_000,
    validateResponse: isMetaWeaveHealthResponse,
  })) {
    return
  }
  const backendExe = packagedBackendPath()
  if (!fs.existsSync(backendExe)) {
    throw new Error(`未找到内置后端: ${backendExe}`)
  }
  const projectRoot = ensurePackagedUserResources()
  const spawnedProcess = childProcess.spawn(backendExe, [], {
    cwd: projectRoot,
    detached: false,
    env: {
      ...process.env,
      AGENT_PROJECT_ROOT: projectRoot,
      AGENT_BASE_DATA_DIR: path.join(projectRoot, 'runtime'),
    },
    stdio: 'ignore',
    windowsHide: true,
  })
  backendProcess = spawnedProcess
  spawnedProcess.once('error', () => {
    if (backendProcess === spawnedProcess) backendProcess = null
  })
  spawnedProcess.once('exit', () => {
    if (backendProcess === spawnedProcess) backendProcess = null
  })
  await waitForManagedProcessReady(spawnedProcess, BACKEND_HEALTH_URL, {
    timeoutMs: 120_000,
    validateResponse: isMetaWeaveHealthResponse,
    timeoutMessage: `内置 Agent 服务未能在规定时间内启动: ${BACKEND_SERVER_URL}`,
  })
}

function stopPackagedBackend() {
  if (!backendProcess) {
    return
  }
  const processToStop = backendProcess
  const pid = processToStop.pid
  processToStop.removeAllListeners()
  backendProcess = null
  if (process.platform === 'win32') {
    childProcess.spawnSync('taskkill.exe', ['/pid', String(pid), '/t', '/f'], {
      windowsHide: true,
      stdio: 'ignore',
    })
    return
  }
  processToStop.kill()
}

async function loadPackagedBackend(window, query) {
  if (!await waitForHttpReady(BACKEND_HEALTH_URL, {
    timeoutMs: 5_000,
    validateResponse: isMetaWeaveHealthResponse,
  })) {
    throw new Error(`内置 Agent 服务未能在规定时间内启动: ${BACKEND_SERVER_URL}`)
  }
  const url = query
    ? `${BACKEND_SERVER_URL}?${new URLSearchParams(query).toString()}`
    : BACKEND_SERVER_URL
  await window.loadURL(url)
}

function createTray() {
  const icon = nativeImage.createFromPath(APP_ICON_PATH)
  tray = new Tray(icon.resize({ width: 16, height: 16 }))
  tray.setToolTip('MetaWeave')

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.focus()
      } else {
        mainWindow.show()
        mainWindow.focus()
      }
    }
  })

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示 / Show',
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    {
      label: '悬浮窗 / Floating',
      click: () => {
        toggleFloatingWindow()
      },
    },
    { type: 'separator' },
    {
      label: '退出 / Quit',
      click: () => {
        app.isQuitting = true
        app.quit()
      },
    },
  ])
  tray.setContextMenu(contextMenu)
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: MAIN_MIN_WIDTH,
    minHeight: MAIN_MIN_HEIGHT,
    frame: false,
    transparent: true,
    // 透明窗口默认仍带系统阴影,Windows 会在四角绘制直角的半透明阴影边框,
    // 与 CSS 圆角不匹配(暗色下明显)。关闭阴影让四角真正透明。
    hasShadow: false,
    // Windows 关键约束:可调整大小的 frameless 窗口必须保留 WS_THICKFRAME 样式
    // 才能从边缘拖拽改尺寸,该样式会强制窗口带一圈系统装饰(雾化/阴影"隔层",
    // 暗色下可见),并让 thickFrame:false 失效。与悬浮窗完全一致:resizable:false
    // + thickFrame:false 改用 WS_POPUP,彻底去掉这层装饰。最大化期间会临时
    // 恢复 resizable,让 Windows 原生标题栏拖拽可以还原窗口。
    resizable: false,
    thickFrame: false,
    // 必须显式全透明:Electron 未设置 backgroundColor 时窗口默认绘制白色,
    // 暗色模式下 #app 圆角裁剪掉的四角会露出白色直角层
    backgroundColor: '#00000000',
    show: false,
    title: 'AgentService Editor',
    icon: APP_ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  // 最大化时窗口铺满工作区,shape 内缩会让四边露出 1px 桌面,故最大化
  // 清除 shape;非最大化时裁掉 DWM 边缘线。
  const applyMainWindowShape = () => {
    if (mainWindow.isDestroyed()) return
    if (mainWindow.isMaximized()) {
      mainWindow.setShape([])
    } else {
      applyTransparentShape(mainWindow, MAIN_WINDOW_RADIUS)
    }
  }

  mainWindow.once('ready-to-show', () => {
    // 运行时兜底:部分 Windows 构建下构造参数里的透明背景不生效,
    // 圆角裁剪掉的四角会残留窗口默认白色直角层
    mainWindow.setBackgroundColor('#00000000')
    applyMainWindowShape()
    mainWindow.show()
  })

  // Notify the renderer about maximize state so the window corner radius can
  // be dropped while maximized (transparent corners would otherwise show through).
  const sendMaximizedState = () => {
    if (!mainWindow.isDestroyed()) {
      mainWindow.webContents.send('window:maximized-changed', mainWindow.isMaximized())
    }
  }
  mainWindow.on('maximize', () => {
    mainWindow.setResizable(true)
    sendMaximizedState()
    applyMainWindowShape()
  })
  mainWindow.on('unmaximize', () => {
    sendMaximizedState()
    // Windows is still running the native move loop when drag-to-restore emits
    // `unmaximize`. Removing WS_THICKFRAME synchronously aborts restoration and
    // leaves the window at maximized bounds, so restore the popup style next turn.
    finishMainWindowRestore(mainWindow, applyMainWindowShape)
  })
  // setShape 区域是绝对像素,窗口 resize(拖动)后必须重新套用
  mainWindow.on('resize', applyMainWindowShape)

  createTray()

  // Override close to hide to tray instead of quitting.
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })

  // Register shell-level clipboard shortcuts. Undo/redo must reach the renderer
  // because Vditor owns its history stack.
  const ctrlKey = process.platform === 'darwin' ? 'meta' : 'control'
  mainWindow.webContents.on('before-input-event', (event, input) => {
    handleEditShortcut(event, input, mainWindow.webContents, ctrlKey)
  })

  if (isDevelopment()) {
    void loadRenderer(mainWindow, undefined, true)
    if (shouldOpenDevTools()) {
      mainWindow.webContents.openDevTools({ mode: 'detach' })
    }
  } else {
    void loadStartupPage(mainWindow).catch((error) => {
      if (!isAbortedNavigation(error)) {
        console.error('Failed to load startup page:', error)
      }
    })
  }
}

const FLOATING_DEFAULT_WIDTH = 460
const FLOATING_DEFAULT_HEIGHT = 172
const FLOATING_CHAT_HEIGHT = 600
const FLOATING_WINDOW_SHAPE_INSET = 10
const FLOATING_WINDOW_SHAPE_RADIUS = 38

// Windows 透明无边框窗口在矩形边缘仍会残留一条 1px 边框线(暗色下可见,
// 直角的、紧贴窗口矩形)。thickFrame: false 对这种 DWM/Chromium 绘制无效。
// 用 setShape 把窗口绘制区域内缩 1px,从原生层直接裁掉这条线。
// 主窗口传入与 CSS 一致的圆角半径;悬浮窗额外内缩到阴影外沿,
// 既从原生层排除透明裁角区域,又保留卡片阴影的完整绘制范围。
function applyTransparentShape(win, radius = 0, boundsInset = 0) {
  if (process.platform !== 'win32' || !win || win.isDestroyed()) {
    return
  }
  const [width, height] = win.getSize()
  const safeBoundsInset = Math.max(0, Math.floor(boundsInset))
  const edgeInset = Math.max(1, safeBoundsInset)
  const maxRadius = Math.max(0, Math.floor(Math.min(width, height) / 2) - safeBoundsInset)
  const safeRadius = Math.max(0, Math.min(Math.floor(radius), maxRadius))
  if (safeRadius === 0) {
    win.setShape([{
      x: edgeInset,
      y: edgeInset,
      width: Math.max(width - edgeInset * 2, 1),
      height: Math.max(height - edgeInset * 2, 1),
    }])
    return
  }
  const centerOffset = safeBoundsInset + safeRadius
  const shape = [{
    x: edgeInset,
    y: centerOffset,
    width: Math.max(width - edgeInset * 2, 1),
    height: Math.max(height - centerOffset * 2, 1),
  }]
  for (let y = edgeInset; y < centerOffset; y += 1) {
    const distanceY = centerOffset - y - 0.5
    const insetX = Math.max(edgeInset, Math.ceil(centerOffset - Math.sqrt(safeRadius ** 2 - distanceY ** 2) - 0.5))
    const row = { x: insetX, width: Math.max(width - insetX * 2, 1), height: 1 }
    shape.push({ ...row, y }, { ...row, y: height - y - 1 })
  }
  win.setShape(shape)
}

function boundsForMainResize(session, screenX, screenY) {
  const dx = Math.round(screenX - session.screenX)
  const dy = Math.round(screenY - session.screenY)
  const next = { ...session.bounds }
  if (session.edge.includes('e')) {
    next.width = Math.max(MAIN_MIN_WIDTH, session.bounds.width + dx)
  }
  if (session.edge.includes('s')) {
    next.height = Math.max(MAIN_MIN_HEIGHT, session.bounds.height + dy)
  }
  if (session.edge.includes('w')) {
    const width = Math.max(MAIN_MIN_WIDTH, session.bounds.width - dx)
    next.x = session.bounds.x + session.bounds.width - width
    next.width = width
  }
  if (session.edge.includes('n')) {
    const height = Math.max(MAIN_MIN_HEIGHT, session.bounds.height - dy)
    next.y = session.bounds.y + session.bounds.height - height
    next.height = height
  }
  return next
}

function createFloatingWindow() {
  if (floatingWindow && !floatingWindow.isDestroyed()) {
    return floatingWindow
  }
  floatingWindow = new BrowserWindow({
    width: FLOATING_DEFAULT_WIDTH,
    height: FLOATING_DEFAULT_HEIGHT,
    frame: false,
    transparent: true,
    hasShadow: false,
    // Windows 上无边框窗口默认仍用 WS_THICKFRAME 样式,会保留一圈系统
    // 描边线(暗色透明窗口下露出直角细线)。关闭它改为 WS_POPUP,去掉这条线。
    thickFrame: false,
    backgroundColor: '#00000000',
    show: false,
    skipTaskbar: true,
    resizable: false,
    title: 'MetaWeave Floating',
    icon: APP_ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  floatingWindow.once('ready-to-show', () => {
    floatingWindow.setBackgroundColor('#00000000')
    applyTransparentShape(floatingWindow, FLOATING_WINDOW_SHAPE_RADIUS, FLOATING_WINDOW_SHAPE_INSET)
  })

  // Close hides the floating window instead of destroying it.
  floatingWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault()
      floatingWindow.hide()
    }
  })

  if (isDevelopment()) {
    void loadRenderer(floatingWindow, { floating: '1' })
    if (shouldOpenDevTools()) {
      floatingWindow.webContents.openDevTools({ mode: 'detach' })
    }
  } else {
    void loadRenderer(floatingWindow, { floating: '1' })
  }
  return floatingWindow
}

function toggleFloatingWindow() {
  const win = createFloatingWindow()
  if (win.isVisible()) {
    win.hide()
  } else {
    win.showInactive()
  }
}

if (hasSingleInstanceLock) {
  app.on('second-instance', (_event, _commandLine, _workingDirectory, additionalData) => {
    const rendererUrl = typeof additionalData?.rendererUrl === 'string'
      ? additionalData.rendererUrl
      : DEV_SERVER_URL
    void restoreExistingWindow(
      mainWindow,
      () => isDevelopment() ? loadRenderer(mainWindow, undefined, true, rendererUrl) : Promise.resolve(),
    )
  })
}

app.whenReady().then(async () => {
  createMainWindow()

  if (!isDevelopment()) {
    try {
      await startPackagedBackend()
      await loadPackagedBackend(mainWindow)
    } catch (error) {
      await showStartupError(mainWindow, error)
      return
    }
  }

  // 悬浮窗随主窗口同步启动。
  createFloatingWindow()

  // Keep clipboard roles available without claiming renderer-owned history keys.
  const template = [
    {
      label: 'Edit',
      submenu: [
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow()
    }
  })
}).catch((error) => {
  console.error('Failed to initialize Electron:', error)
  if (mainWindow && !mainWindow.isDestroyed()) {
    void loadWindowContent(
      mainWindow,
      () => Promise.reject(error),
      (startupError) => showStartupError(mainWindow, startupError),
    )
  } else {
    dialog.showErrorBox('MetaWeave 启动失败', error instanceof Error ? error.message : String(error))
  }
})

app.on('window-all-closed', () => {
  // Close hides to tray instead of quitting.
})

app.on('will-quit', () => {
  disposeBrowserView()
  if (tray) {
    tray.destroy()
    tray = null
  }
  stopPackagedBackend()
})

ipcMain.on('window:minimize', (event) => {
  windowFromEvent(event)?.minimize()
})

ipcMain.handle('window:toggle-maximize', (event) => {
  const win = windowFromEvent(event)
  if (!win) {
    return false
  }
  if (win.isMaximized()) {
    win.unmaximize()
    return false
  }
  // The normal window uses a popup style to avoid Windows' square DWM frame.
  // Re-enable the native resize frame before asking Windows to maximize it.
  win.setResizable(true)
  win.maximize()
  return true
})

ipcMain.handle('window:begin-move', (event, payload) => {
  const win = windowFromEvent(event)
  const screenX = Number(payload?.screenX)
  const screenY = Number(payload?.screenY)
  if (!win || win !== mainWindow || !win.isMaximized() || !Number.isFinite(screenX) || !Number.isFinite(screenY)) {
    return false
  }
  const restore = boundsForMainDragRestore(win.getBounds(), win.getNormalBounds(), screenX, screenY)
  win.unmaximize()
  win.setBounds(restore.bounds)
  mainMoveSession = {
    webContentsId: event.sender.id,
    offsetX: restore.offsetX,
    offsetY: restore.offsetY,
  }
  applyTransparentShape(win, MAIN_WINDOW_RADIUS)
  return true
})

ipcMain.on('window:move-to', (event, payload) => {
  if (!mainMoveSession || mainMoveSession.webContentsId !== event.sender.id) {
    return
  }
  const win = windowFromEvent(event)
  const screenX = Number(payload?.screenX)
  const screenY = Number(payload?.screenY)
  if (!win || win !== mainWindow || !Number.isFinite(screenX) || !Number.isFinite(screenY)) {
    return
  }
  win.setPosition(
    Math.round(screenX - mainMoveSession.offsetX),
    Math.round(screenY - mainMoveSession.offsetY),
  )
})

ipcMain.on('window:end-move', (event) => {
  if (mainMoveSession?.webContentsId === event.sender.id) {
    mainMoveSession = null
    applyTransparentShape(mainWindow, MAIN_WINDOW_RADIUS)
  }
})

ipcMain.handle('window:begin-resize', (event, payload) => {
  const win = windowFromEvent(event)
  const edge = typeof payload?.edge === 'string' ? payload.edge : ''
  if (!win || win !== mainWindow || win.isMaximized() || !/^(n|e|s|w|ne|nw|se|sw)$/u.test(edge)) {
    return false
  }
  mainResizeSession = {
    webContentsId: event.sender.id,
    edge,
    screenX: Number(payload.screenX) || 0,
    screenY: Number(payload.screenY) || 0,
    bounds: win.getBounds(),
  }
  return true
})

ipcMain.on('window:resize-to', (event, payload) => {
  if (!mainResizeSession || mainResizeSession.webContentsId !== event.sender.id) {
    return
  }
  const win = windowFromEvent(event)
  if (!win || win !== mainWindow || win.isMaximized()) {
    mainResizeSession = null
    return
  }
  const screenX = Number(payload?.screenX)
  const screenY = Number(payload?.screenY)
  if (!Number.isFinite(screenX) || !Number.isFinite(screenY)) {
    return
  }
  win.setBounds(boundsForMainResize(mainResizeSession, screenX, screenY))
  applyTransparentShape(win, MAIN_WINDOW_RADIUS)
})

ipcMain.on('window:end-resize', (event) => {
  if (mainResizeSession?.webContentsId === event.sender.id) {
    mainResizeSession = null
  }
})

ipcMain.handle('system:list-font-families', async () => {
  const fonts = process.platform === 'win32'
    ? await listWindowsFontFamilies()
    : await listUnixFontFamilies()
  return fonts
    .map((item) => String(item).trim())
    .filter(Boolean)
})

ipcMain.on('window:close', (event) => {
  windowFromEvent(event)?.close()
})

ipcMain.handle('shell:open-external', async (_event, url) => {
  if (typeof url === 'string' && /^https?:\/\//u.test(url)) {
    await shell.openExternal(url)
  }
})

ipcMain.handle('shell:open-path', async (_event, filePath) => {
  if (typeof filePath !== 'string' || !filePath.trim()) {
    return ''
  }
  try {
    return await shell.openPath(filePath)
  } catch {
    return 'error'
  }
})

ipcMain.handle('shell:show-item-in-folder', async (_event, filePath) => {
  if (typeof filePath !== 'string' || !filePath.trim()) {
    return
  }
  shell.showItemInFolder(filePath)
})

ipcMain.handle('dialog:select-directory', async (event) => {
  const win = windowFromEvent(event)
  if (!win) {
    return ''
  }
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
  })
  if (result.canceled || result.filePaths.length === 0) {
    return ''
  }
  return result.filePaths[0]
})

ipcMain.handle('dialog:save-file', async (event, payload) => {
  const win = windowFromEvent(event)
  const filename = path.basename(String(payload?.filename || 'scanner-export'))
  const data = payload?.data
  if (!win || !data || typeof data.byteLength !== 'number') {
    return ''
  }
  const extension = path.extname(filename).toLowerCase()
  const result = await dialog.showSaveDialog(win, {
    defaultPath: filename,
    filters: extension === '.zip'
      ? [{ name: 'ZIP 压缩包', extensions: ['zip'] }]
      : [{ name: 'Markdown', extensions: ['md'] }],
  })
  if (result.canceled || !result.filePath) {
    return ''
  }
  await fs.promises.writeFile(result.filePath, Buffer.from(data))
  return result.filePath
})

ipcMain.handle('clipboard:write-text', async (_event, text) => {
  if (typeof text !== 'string' || !text.trim()) {
    return false
  }
  clipboard.writeText(text)
  return true
})

ipcMain.handle('clipboard:write-files', async (_event, filePaths, mode) => {
  if (!Array.isArray(filePaths) || filePaths.length === 0) {
    return false
  }
  const normalizedPaths = filePaths
    .filter((item) => typeof item === 'string' && item.trim())
    .map((item) => path.resolve(item))
    .filter((item) => fs.existsSync(item))
  if (normalizedPaths.length === 0) {
    return false
  }

  if (process.platform === 'win32') {
    const ok = await writeWindowsFileClipboard(normalizedPaths, mode)
    if (ok) {
      return true
    }
  }

  if (typeof clipboard.writeFiles === 'function') {
    clipboard.writeFiles(normalizedPaths)
  } else {
    clipboard.writeText(normalizedPaths.join('\n'))
  }

  // PreferredDropEffect signals whether this was a copy or cut.
  if (mode === 'cut') {
    clipboard.writeBuffer('Preferred DropEffect', buildDropEffectBuffer(mode))
  }

  return true
})

ipcMain.handle('clipboard:read-files', async () => readClipboardFilePayload())

ipcMain.handle('files:copy-into-directory', async (_event, sourcePaths, targetDir, mode, conflictStrategy = 'rename') => {
  if (!Array.isArray(sourcePaths) || typeof targetDir !== 'string' || !targetDir.trim()) {
    return { ok: false, paths: [] }
  }
  await fs.promises.mkdir(targetDir, { recursive: true })
  const copiedPaths = []
  for (const sourcePath of sourcePaths) {
    if (typeof sourcePath !== 'string' || !sourcePath.trim() || !fs.existsSync(sourcePath)) {
      continue
    }
    const preferredPath = path.join(targetDir, path.basename(sourcePath))
    const exists = fs.existsSync(preferredPath)
    if (exists && conflictStrategy === 'skip') {
      continue
    }
    const targetPath = exists && conflictStrategy === 'rename'
      ? uniqueChildPath(targetDir, path.basename(sourcePath))
      : preferredPath
    if (exists && conflictStrategy === 'overwrite') {
      await fs.promises.rm(targetPath, { recursive: true, force: true })
    }
    await copyOrMovePath(sourcePath, targetPath, mode === 'cut' ? 'cut' : 'copy')
    copiedPaths.push(targetPath)
  }
  return { ok: copiedPaths.length > 0, paths: copiedPaths }
})

/* ---- Floating window IPC ---- */

ipcMain.handle('floating:set-bounds', (event, size) => {
  const win = windowFromEvent(event)
  if (!win || win !== floatingWindow) {
    return false
  }
  const width = Number.isFinite(size?.width) ? size.width : FLOATING_DEFAULT_WIDTH
  const height = Number.isFinite(size?.height) ? size.height : FLOATING_DEFAULT_HEIGHT
  const bounds = win.getBounds()
  win.setBounds({ x: bounds.x, y: bounds.y, width, height })
  // setShape 区域是绝对像素,窗口 resize 后必须重新套用,否则边缘线会回来
  applyTransparentShape(floatingWindow, FLOATING_WINDOW_SHAPE_RADIUS, FLOATING_WINDOW_SHAPE_INSET)
  return true
})

ipcMain.handle('floating:set-always-on-top', (event, mode) => {
  const win = windowFromEvent(event)
  if (!win || win !== floatingWindow) {
    return false
  }
  if (mode === 'global') {
    win.setAlwaysOnTop(true, 'screen-saver')
  } else if (mode === 'normal') {
    win.setAlwaysOnTop(true, 'normal')
  } else {
    win.setAlwaysOnTop(false)
  }
  return true
})

ipcMain.on('floating:close', (event) => {
  const win = windowFromEvent(event)
  if (win && win === floatingWindow) {
    win.close()
  }
})

ipcMain.handle('floating:set-visible', (_event, options) => {
  const win = options?.visible ? createFloatingWindow() : floatingWindow
  if (!win || win.isDestroyed()) {
    return false
  }
  if (options?.visible) {
    win.showInactive()
  } else {
    win.hide()
  }
  return true
})

ipcMain.handle('floating:get-state', () => {
  if (!floatingWindow || floatingWindow.isDestroyed()) {
    return { visible: false, pinMode: 'off' }
  }
  return { visible: floatingWindow.isVisible() }
})

ipcMain.on('floating:toggle', () => {
  toggleFloatingWindow()
})

// Relay Agent state between the main and floating renderer windows. Electron
// BrowserWindows do not share Pinia or localStorage events, so both directions
// must receive session, settings, and live-chat updates over IPC.
ipcMain.on('agent:window-sync', (event, payload) => {
  const sender = BrowserWindow.fromWebContents(event.sender)
  const { type, value } = payload || {}
  const allowedTypes = new Set([
    'theme',
    'session',
    'chat-mode',
    'agent-loop-mode',
    'agent-access-mode',
    'chat-state',
    'chat-meta',
    'chat-stream',
    'chat-sync-request',
    'chat-cancel',
  ])
  if (!allowedTypes.has(type)) return
  for (const target of [mainWindow, floatingWindow]) {
    if (target && !target.isDestroyed() && target !== sender) {
      // Hidden windows receive the terminal snapshot but never pay for live
      // token painting; their state catches up when chat-state arrives.
      if (type === 'chat-stream' && !target.isVisible()) continue
      target.webContents.send('agent:window-sync', { type, value })
    }
  }
})

// Floating "Expand Agent page" → bring the main window forward and switch it
// to the Agent view. The main window renderer subscribes via onOpenAgentPage.
ipcMain.on('floating:open-agent-page', () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore()
  }
  mainWindow.show()
  mainWindow.focus()
  mainWindow.webContents.send('agent:open-agent-page')
})
