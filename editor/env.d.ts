/// <reference types="vite/client" />

declare module '@fontsource/jetbrains-mono'

interface AgentEditorDesktopApi {
  isDesktop: boolean
  platform: NodeJS.Platform
  minimize: () => void
  toggleMaximize: () => Promise<boolean>
  beginWindowMove: (screenX: number, screenY: number) => Promise<boolean>
  updateWindowMove: (screenX: number, screenY: number) => void
  endWindowMove: () => void
  beginWindowResize: (edge: 'n' | 'e' | 's' | 'w' | 'ne' | 'nw' | 'se' | 'sw', screenX: number, screenY: number) => Promise<boolean>
  updateWindowResize: (screenX: number, screenY: number) => void
  endWindowResize: () => void
  onMaximizedChange: (callback: (maximized: boolean) => void) => () => void
  close: () => void
  openExternal: (url: string) => Promise<void>
  selectDirectory: () => Promise<string>
  saveFileAs: (payload: { filename: string; data: ArrayBuffer }) => Promise<string>
  copyFilePaths: (paths: string[], mode: 'copy' | 'cut') => Promise<boolean>
  readClipboardFiles: () => Promise<{ mode: 'copy' | 'cut'; paths: string[] }>
  readClipboardFilePaths: () => Promise<string[]>
  copyExternalPathsIntoDirectory: (
    paths: string[],
    targetDir: string,
    mode: 'copy' | 'cut',
    conflictStrategy?: 'overwrite' | 'skip' | 'rename',
  ) => Promise<{ ok: boolean; paths: string[] }>
  listFontFamilies: () => Promise<string[]>
  getPathForFile: (file: File) => string
  writeClipboardText: (text: string) => Promise<boolean>
  browserShow: (payload: { bounds: BrowserViewBounds; proxyUrl: string; homeUrl: string; themeMode: 'dark' | 'light' | 'system' }) => Promise<boolean>
  browserHide: () => Promise<boolean>
  browserSetBounds: (bounds: BrowserViewBounds) => Promise<boolean>
  browserConfigure: (config: { proxyUrl: string; homeUrl: string; themeMode?: 'dark' | 'light' | 'system' }) => Promise<boolean>
  browserNavigate: (value: string) => Promise<boolean>
  browserCommand: (command: 'back' | 'forward' | 'home' | 'reload' | 'stop' | 'external') => Promise<boolean>
  onBrowserState: (callback: (state: BrowserViewState) => void) => () => void
  openPath: (path: string) => Promise<string>
  showItemInFolder: (path: string) => Promise<void>
  floatingSetBounds: (size: { width: number; height: number }) => Promise<boolean>
  floatingSetAlwaysOnTop: (mode: 'off' | 'normal' | 'global') => Promise<boolean>
  floatingClose: () => void
  floatingSetVisible: (visible: boolean) => Promise<boolean>
  floatingGetState: () => Promise<{ visible: boolean; pinMode?: string }>
  floatingToggle: () => void
  windowSync: (type: string, value: unknown) => void
  onWindowSync: (callback: (payload: { type: string; value: unknown }) => void) => () => void
  openAgentPage: () => void
  onOpenAgentPage: (callback: () => void) => () => void
}

/** Viewport-relative rectangle occupied by the native Chromium surface. */
interface BrowserViewBounds {
  x: number
  y: number
  width: number
  height: number
  /** Shared workspace corner radius, applied to the native Chromium surface. */
  borderRadius?: number
}

/** Navigation state mirrored from the isolated browser WebContents. */
interface BrowserViewState {
  url: string
  title: string
  canGoBack: boolean
  canGoForward: boolean
  loading: boolean
  error?: string
}

interface Window {
  agentEditorDesktop?: AgentEditorDesktopApi
}
