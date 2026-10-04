/*
 * Electron preload bridge for the editor renderer.
 *
 * Usage:
 * Exposes a small, typed-safe API under window.agentEditorDesktop without
 * enabling Node.js access in the Vue application.
 */
/* eslint-disable @typescript-eslint/no-require-imports */

const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('agentEditorDesktop', {
  isDesktop: true,
  platform: process.platform,
  // The renderer shares main's public loopback API origin; launch authorization stays private.
  backendOrigin: process.env.METAWEAVE_BACKEND_URL || 'http://127.0.0.1:8002',
  // Private vault material remains inside main; this bridge returns session fields only.
  auth: {
    register: (credentials) => ipcRenderer.invoke('auth:register', credentials),
    login: (credentials) => ipcRenderer.invoke('auth:login', credentials),
    restore: () => ipcRenderer.invoke('auth:restore'),
    logout: () => ipcRenderer.invoke('auth:logout'),
    getSession: () => ipcRenderer.invoke('auth:get-session'),
    onSession: (callback) => {
      const handler = (_event, state) => callback(state)
      ipcRenderer.on('auth:session-changed', handler)
      return () => ipcRenderer.removeListener('auth:session-changed', handler)
    },
  },
  minimize: () => ipcRenderer.send('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  beginWindowMove: (screenX, screenY) => ipcRenderer.invoke('window:begin-move', { screenX, screenY }),
  updateWindowMove: (screenX, screenY) => ipcRenderer.send('window:move-to', { screenX, screenY }),
  endWindowMove: () => ipcRenderer.send('window:end-move'),
  beginWindowResize: (edge, screenX, screenY) => ipcRenderer.invoke('window:begin-resize', { edge, screenX, screenY }),
  updateWindowResize: (screenX, screenY) => ipcRenderer.send('window:resize-to', { screenX, screenY }),
  endWindowResize: () => ipcRenderer.send('window:end-resize'),
  onMaximizedChange: (callback) => {
    const handler = (_event, value) => callback(value)
    ipcRenderer.on('window:maximized-changed', handler)
    return () => ipcRenderer.removeListener('window:maximized-changed', handler)
  },
  close: () => ipcRenderer.send('window:close'),
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  openPath: (path) => ipcRenderer.invoke('shell:open-path', path),
  showItemInFolder: (path) => ipcRenderer.invoke('shell:show-item-in-folder', path),
  selectDirectory: () => ipcRenderer.invoke('dialog:select-directory'),
  saveFileAs: (payload) => ipcRenderer.invoke('dialog:save-file', payload),
  copyFilePaths: (paths, mode) => ipcRenderer.invoke('clipboard:write-files', paths, mode),
  readClipboardFiles: () => ipcRenderer.invoke('clipboard:read-files'),
  readClipboardFilePaths: async () => {
    const payload = await ipcRenderer.invoke('clipboard:read-files')
    return Array.isArray(payload?.paths) ? payload.paths : []
  },
  copyExternalPathsIntoDirectory: (paths, targetDir, mode, conflictStrategy) => ipcRenderer.invoke('files:copy-into-directory', paths, targetDir, mode, conflictStrategy),
  listFontFamilies: () => ipcRenderer.invoke('system:list-font-families'),
  getPathForFile: (file) => webUtils?.getPathForFile ? webUtils.getPathForFile(file) : (file?.path || ''),
  writeClipboardText: (text) => ipcRenderer.invoke('clipboard:write-text', text),
  // Sandboxed Chromium browser bridge. External pages never receive this preload.
  browserShow: (payload) => ipcRenderer.invoke('browser:show', payload),
  browserHide: () => ipcRenderer.invoke('browser:hide'),
  browserSetBounds: (bounds) => ipcRenderer.invoke('browser:set-bounds', bounds),
  browserConfigure: (config) => ipcRenderer.invoke('browser:configure', config),
  browserNavigate: (value) => ipcRenderer.invoke('browser:navigate', value),
  browserCommand: (command) => ipcRenderer.invoke('browser:command', command),
  onBrowserState: (callback) => {
    const handler = (_event, state) => callback(state)
    ipcRenderer.on('browser:state', handler)
    return () => ipcRenderer.removeListener('browser:state', handler)
  },
  // Floating window bridge.
  floatingSetBounds: (size) => ipcRenderer.invoke('floating:set-bounds', size),
  floatingSetAlwaysOnTop: (mode) => ipcRenderer.invoke('floating:set-always-on-top', mode),
  floatingClose: () => ipcRenderer.send('floating:close'),
  floatingSetVisible: (visible) => ipcRenderer.invoke('floating:set-visible', { visible }),
  floatingGetState: () => ipcRenderer.invoke('floating:get-state'),
  floatingToggle: () => ipcRenderer.send('floating:toggle'),
  // Bidirectional Agent state bridge shared by the main and floating windows.
  windowSync: (type, value) => ipcRenderer.send('agent:window-sync', { type, value }),
  onWindowSync: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('agent:window-sync', handler)
    return () => ipcRenderer.removeListener('agent:window-sync', handler)
  },
  // Open the full Agent page in the main window from the floating window.
  openAgentPage: () => ipcRenderer.send('floating:open-agent-page'),
  onOpenAgentPage: (callback) => {
    const handler = () => callback()
    ipcRenderer.on('agent:open-agent-page', handler)
    return () => ipcRenderer.removeListener('agent:open-agent-page', handler)
  },
})
