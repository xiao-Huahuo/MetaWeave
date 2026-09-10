<!--
  Editor workspace page.

  Usage:
  Main route for the knowledge editor. It composes the top command bar, file
  tree, Vditor editing pane, Agent panel, and command palette.
-->
<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import ActivityBar from '@/components/editor_workspace/ActivityBar.vue'
import AgentPanel from '@/components/editor_workspace/AgentPanel.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import CommandPalette from '@/components/editor_workspace/CommandPalette.vue'
import EditorPane from '@/components/editor_workspace/EditorPane.vue'
import ImagePreviewer from '@/components/common/ImagePreviewer.vue'
import FileConflictDialog from '@/components/editor_workspace/FileConflictDialog.vue'
import FeedbackPopover from '@/components/editor_workspace/FeedbackPopover.vue'
import FileTreePanel from '@/components/editor_workspace/FileTreePanel.vue'
import FileResourceManager from '@/components/editor_workspace/FileResourceManager.vue'
import GitSidebar from '@/components/git_sidebar/GitSidebar.vue'
import SelectionToolbar from '@/components/editor_workspace/SelectionToolbar.vue'
import TodoSidebar from '@/components/editor_workspace/TodoSidebar.vue'
import TopCommandBar from '@/components/editor_workspace/TopCommandBar.vue'
import SearchResultSidebar from '@/components/search_page/SearchResultSidebar.vue'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { useGitStore } from '@/stores/git'
import type { KnowledgeGraphNodeEvent } from '@/components/knowledge_graph/graphTypes'

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const gitStore = useGitStore()
const HomeView = defineAsyncComponent(() => import('@/views/HomeView.vue'))
const AgentPage = defineAsyncComponent(() => import('@/views/AgentPage.vue'))
const AgentQueueView = defineAsyncComponent(() => import('@/views/AgentQueueView.vue'))
const GraphPane = defineAsyncComponent(() => import('@/components/editor_workspace/GraphPane.vue'))
const DashboardView = defineAsyncComponent(() => import('@/views/DashboardView.vue'))
const DebugView = defineAsyncComponent(() => import('@/views/DebugView.vue'))
const IngestionProgressView = defineAsyncComponent(() => import('@/views/IngestionProgressView.vue'))
const ScannerView = defineAsyncComponent(() => import('@/views/ScannerView.vue'))
const BatchScannerView = defineAsyncComponent(() => import('@/views/BatchScannerView.vue'))
const LibraryView = defineAsyncComponent(() => import('@/views/LibraryView.vue'))
const ComponentLibraryView = defineAsyncComponent(() => import('@/views/ComponentLibraryView.vue'))
const VaultView = defineAsyncComponent(() => import('@/views/VaultView.vue'))
const SmartFormsView = defineAsyncComponent(() => import('@/views/SmartFormsView.vue'))
const LiteratureReadingView = defineAsyncComponent(() => import('@/views/LiteratureReadingView.vue'))
const FavoritesView = defineAsyncComponent(() => import('@/views/FavoritesView.vue'))
const PrivacyView = defineAsyncComponent(() => import('@/views/PrivacyView.vue'))
const MarkdownHtmlVisualizationView = defineAsyncComponent(() => import('@/views/MarkdownHtmlVisualizationView.vue'))
const SearchPage = defineAsyncComponent(() => import('@/views/SearchPage.vue'))
const BrowserPage = defineAsyncComponent(() => import('@/views/BrowserPage.vue'))
import SettingsView from '@/views/SettingsView.vue'

function handleAskAgent(text: string) {
  workspaceStore.pendingAgentReference = text
  workspaceStore.agentSidebarOpen = true
}

const ACTIVITY_BAR_ICON_WIDTH = 64
const ACTIVITY_BAR_MANAGEMENT_WIDTH = 204
const DEFAULT_FILE_WIDTH = 280
const DEFAULT_AGENT_WIDTH = 340
const MIN_PANEL_WIDTH = 180
const MIN_EDITOR_SIDEBAR_WIDTH = 360
const MIN_BROWSER_SIDEBAR_WIDTH = 320
const MIN_MAIN_WIDTH = 180
const MAX_FILE_WIDTH = 460
const MAX_EDITOR_SIDEBAR_WIDTH = 620
const COLLAPSE_THRESHOLD = 150

type ResizeTarget = 'file' | 'editor' | 'browser' | 'agent'
type MobileSidebar = 'file' | 'editor' | 'browser' | 'git' | 'agent' | 'todo'

const workspaceGrid = ref<HTMLElement | null>(null)
const mainShellWidth = ref(Number.POSITIVE_INFINITY)
const fileSidebarOpen = ref(true)
const agentSidebarOpen = ref(true)
const gitLeftOpen = ref(false)
const gitRightOpen = ref(false)
const feedbackOpen = ref(false)
const activityOverlayOpen = ref(false)
const fileWidth = ref(DEFAULT_FILE_WIDTH)
const agentWidth = ref(DEFAULT_AGENT_WIDTH)
const editorSidebarWidth = ref<number | null>(null)
const browserSidebarWidth = ref<number | null>(null)
const activeResizeTarget = ref<ResizeTarget | null>(null)
let pendingResizeClientX = 0
let resizeFrameId = 0
let resizePointerTarget: HTMLElement | null = null
let resizePointerId: number | null = null
const isAgentPage = computed(() => workspaceStore.mainView === 'agent')
const isAgentQueuePage = computed(() => workspaceStore.mainView === 'agent-queue')
const isBatchScannerPage = computed(() => workspaceStore.mainView === 'batch-scanner')
const isGraphPage = computed(() => workspaceStore.mainView === 'graph')
const isHomePage = computed(() => workspaceStore.mainView === 'home')
const isBrowserPage = computed(() => workspaceStore.mainView === 'browser')
/** Match mobile layouts to the stable content span, excluding the docked file-tree width. */
const topCommandBarMobile = computed(() => mainShellWidth.value <= 640)
/** Password-vault filters become an overlay before their legacy horizontal layout can appear. */
const vaultSidebarMobile = computed(() => mainShellWidth.value <= 860)
const browserSidebarVisible = computed(() => (
  workspaceStore.browserSidebarOpen && workspaceStore.mainView !== 'browser'
))
const editorSidebarVisible = computed(() => (
  workspaceStore.editorSidebarOpen && workspaceStore.mainView !== 'editor'
))
const sidebarHidden = computed(() => (
  isAgentPage.value
  || isAgentQueuePage.value
  || isBatchScannerPage.value
  || isGraphPage.value
  || isHomePage.value
  || isBrowserPage.value
))
const visibleFileSidebarOpen = computed(() => fileSidebarOpen.value && !sidebarHidden.value)
const visibleAgentSidebarOpen = computed(() => (
  (gitRightOpen.value || agentSidebarOpen.value || todoSidebarOpen.value) && !sidebarHidden.value
))
const showConflictDialog = computed(() => {
  return workspaceStore.conflictDialog.open
})
const activityBarWidth = computed(() => (
  settingsStore.sidebarDisplayMode === 'management' ? ACTIVITY_BAR_MANAGEMENT_WIDTH : ACTIVITY_BAR_ICON_WIDTH
))

// 双向同步: 允许子组件通过 store 打开 Agent 侧边栏
watch(() => workspaceStore.agentSidebarOpen, (val) => {
  if (val !== agentSidebarOpen.value) {
    agentSidebarOpen.value = val
  }
})
watch(agentSidebarOpen, (val) => {
  if (val !== workspaceStore.agentSidebarOpen) {
    workspaceStore.agentSidebarOpen = val
  }
})

watch(
  [() => workspaceStore.mainView, () => workspaceStore.agentSidebarOpen],
  ([mainView, agentOpen]) => {
    if (mainView !== 'editor') {
      gitLeftOpen.value = false
      gitRightOpen.value = false
    }
    if (mainView === 'visualization' && agentOpen) {
      fileSidebarOpen.value = false
    }
    if (mainView === 'literature-reading') {
      fileSidebarOpen.value = false
      agentSidebarOpen.value = false
    }
  },
)


const workspaceGridStyle = computed<Record<string, string>>(() => ({
  '--activity-col-width': `${activityBarWidth.value}px`,
  '--file-col-width': visibleFileSidebarOpen.value && !topCommandBarMobile.value ? `${fileWidth.value}px` : '0px',
  '--file-resizer-width': visibleFileSidebarOpen.value && !topCommandBarMobile.value ? '4px' : '0px',
  '--agent-col-width': visibleAgentSidebarOpen.value && !topCommandBarMobile.value ? `${agentWidth.value}px` : '0px',
  '--agent-resizer-width': visibleAgentSidebarOpen.value && !topCommandBarMobile.value ? '4px' : '0px',
  '--editor-resizer-width': editorSidebarVisible.value && !topCommandBarMobile.value ? '4px' : '0px',
  '--editor-sidebar-width': editorSidebarVisible.value && !topCommandBarMobile.value
    ? editorSidebarWidth.value === null ? 'clamp(360px, 42vw, 620px)' : `${editorSidebarWidth.value}px`
    : '0px',
  '--browser-resizer-width': browserSidebarVisible.value && !topCommandBarMobile.value ? '4px' : '0px',
  '--browser-sidebar-width': browserSidebarVisible.value && !topCommandBarMobile.value
    ? browserSidebarWidth.value === null ? 'minmax(0, 1fr)' : `${browserSidebarWidth.value}px`
    : '0px',
  '--file-mobile-row': visibleFileSidebarOpen.value ? '300px' : '0px',
  '--agent-mobile-row': visibleAgentSidebarOpen.value ? '360px' : '0px',
}))

const workspacePageStyle = computed<Record<string, string>>(() => ({
  '--activity-col-width': `${activityBarWidth.value}px`,
}))

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function openFileSidebar() {
  if (workspaceStore.mainView === 'resources') {
    workspaceStore.setMainView('editor')
  }
  fileSidebarOpen.value = true
  agentSidebarOpen.value = false
  gitLeftOpen.value = false
  fileWidth.value = Math.max(fileWidth.value, DEFAULT_FILE_WIDTH)
}

function toggleFileSidebar() {
  if (sidebarHidden.value) {
    workspaceStore.setMainView('editor')
    openFileSidebar()
    return
  }
  if (gitLeftOpen.value) {
    gitLeftOpen.value = false
    fileSidebarOpen.value = true
    return
  }
  if (fileSidebarOpen.value) {
    fileSidebarOpen.value = false
    return
  }
  openFileSidebar()
}

/** Close the overlay after a normal file opens while retaining desktop docking behavior. */
function handleFileTreeFileOpened(): void {
  if (topCommandBarMobile.value) fileSidebarOpen.value = false
}

function toggleAgentSidebar() {
  gitRightOpen.value = false
  if (sidebarHidden.value) {
    workspaceStore.setMainView('editor')
    agentSidebarOpen.value = true
    agentWidth.value = Math.max(agentWidth.value, DEFAULT_AGENT_WIDTH)
    return
  }
  agentSidebarOpen.value = !agentSidebarOpen.value
  if (agentSidebarOpen.value) {
    agentWidth.value = Math.max(agentWidth.value, DEFAULT_AGENT_WIDTH)
  }
}

const todoSidebarOpen = ref(false)
const todoSplitRatio = ref(0.5)
const TODO_COLLAPSE_THRESHOLD = 0.12
watch(() => workspaceStore.todoSidebarOpen, (val) => {
  todoSidebarOpen.value = val
})

watch(todoSidebarOpen, (val) => {
  workspaceStore.todoSidebarOpen = val
})

/** Keep mobile overlays mutually exclusive while preserving desktop multi-panel layouts. */
const lastOpenedMobileSidebar = ref<MobileSidebar>('file')

function activateMobileSidebar(sidebar: MobileSidebar): void {
  lastOpenedMobileSidebar.value = sidebar
  if (!topCommandBarMobile.value) return
  if (sidebar !== 'file') {
    fileSidebarOpen.value = false
    gitLeftOpen.value = false
  }
  if (sidebar !== 'editor') workspaceStore.closeEditorSidebar()
  if (sidebar !== 'browser') workspaceStore.closeBrowserSidebar()
  if (sidebar !== 'git') gitRightOpen.value = false
  if (sidebar !== 'agent') agentSidebarOpen.value = false
  if (sidebar !== 'todo') todoSidebarOpen.value = false
}

watch(fileSidebarOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('file')
})
watch(() => workspaceStore.editorSidebarOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('editor')
})
watch(() => workspaceStore.browserSidebarOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('browser')
})
watch(gitRightOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('git')
})
watch(agentSidebarOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('agent')
})
watch(todoSidebarOpen, (open, wasOpen) => {
  if (open && !wasOpen) activateMobileSidebar('todo')
})
watch(topCommandBarMobile, (mobile) => {
  if (mobile) activateMobileSidebar(lastOpenedMobileSidebar.value)
})

function toggleTodoSidebar() {
  gitRightOpen.value = false
  if (sidebarHidden.value) {
    workspaceStore.setMainView('editor')
  }
  todoSidebarOpen.value = !todoSidebarOpen.value
  if (todoSidebarOpen.value) {
    agentWidth.value = Math.max(agentWidth.value, DEFAULT_AGENT_WIDTH)
    todoSplitRatio.value = 0.5
  }
}

function toggleLeftGitSidebar() {
  if (sidebarHidden.value) {
    workspaceStore.setMainView('editor')
  }
  if (gitLeftOpen.value) {
    // Git 面板已打开时再次点击: 直接关闭整个左侧栏, 不回落到文件树。
    gitLeftOpen.value = false
    fileSidebarOpen.value = false
    return
  }
  gitLeftOpen.value = true
  fileSidebarOpen.value = true
  gitRightOpen.value = false
  void gitStore.refresh()
}

function toggleRightGitSidebar() {
  if (sidebarHidden.value) {
    workspaceStore.setMainView('editor')
  }
  gitRightOpen.value = !gitRightOpen.value
  if (gitRightOpen.value) {
    gitLeftOpen.value = false
    agentSidebarOpen.value = false
    todoSidebarOpen.value = false
    agentWidth.value = Math.max(agentWidth.value, DEFAULT_AGENT_WIDTH)
    void gitStore.refresh()
  }
}

let activeTodoResize = false

function startTodoResize(event: PointerEvent) {
  event.preventDefault()
  activeTodoResize = true
  window.addEventListener('pointermove', handleTodoResizeMove)
  window.addEventListener('pointerup', stopTodoResize)
}

function handleTodoResizeMove(event: PointerEvent) {
  if (!activeTodoResize) return
  const container = (document.querySelector('.agent-col') as HTMLElement)
  if (!container) return
  const rect = container.getBoundingClientRect()
  const y = event.clientY - rect.top
  const ratio = y / rect.height
  if (ratio < TODO_COLLAPSE_THRESHOLD) {
    todoSidebarOpen.value = false
    return
  }
  if (ratio > 1 - TODO_COLLAPSE_THRESHOLD) {
    todoSidebarOpen.value = true
    todoSplitRatio.value = 1
    return
  }
  todoSidebarOpen.value = true
  todoSplitRatio.value = ratio
}

function stopTodoResize() {
  activeTodoResize = false
  window.removeEventListener('pointermove', handleTodoResizeMove)
  window.removeEventListener('pointerup', stopTodoResize)
}

function openHome() {
  workspaceStore.setMainView('home')
  fileSidebarOpen.value = false
  agentSidebarOpen.value = false
}

function openAgentPage() {
  workspaceStore.setMainView('agent')
  fileSidebarOpen.value = false
  agentSidebarOpen.value = false
}

/** Open the durable Agent task board from the activity bar. */
function openAgentQueue() {
  workspaceStore.setMainView('agent-queue')
  fileSidebarOpen.value = false
  agentSidebarOpen.value = false
}

function toggleGraphView() {
  const next = workspaceStore.mainView === 'graph' ? 'editor' : 'graph'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openDashboard() {
  const next = workspaceStore.mainView === 'dashboard' ? 'editor' : 'dashboard'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openDebug() {
  const next = workspaceStore.mainView === 'debug' ? 'editor' : 'debug'
  workspaceStore.setMainView(next)
  feedbackOpen.value = false
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function toggleFeedback() {
  feedbackOpen.value = !feedbackOpen.value
}

function openResources() {
  if (workspaceStore.mainView === 'resources') {
    workspaceStore.setMainView('editor')
    return
  }
  workspaceStore.setMainView('resources')
  fileSidebarOpen.value = false
  agentSidebarOpen.value = false
}

function openFavorites() {
  const next = workspaceStore.mainView === 'favorites' ? 'editor' : 'favorites'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openPrivacy() {
  const next = workspaceStore.mainView === 'privacy' ? 'editor' : 'privacy'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openLibrary() {
  const next = workspaceStore.mainView === 'library' ? 'editor' : 'library'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

/** Toggle the fifth library surface and collapse editor side panels. */
function openComponentLibrary() {
  const next = workspaceStore.mainView === 'component-library' ? 'editor' : 'component-library'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openVault() {
  const next = workspaceStore.mainView === 'vault' ? 'editor' : 'vault'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openForms() {
  const next = workspaceStore.mainView === 'forms' ? 'editor' : 'forms'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

/** Opens the smart-form-backed literature reading workspace. */
function openLiterature() {
  const next = workspaceStore.mainView === 'literature-reading' ? 'editor' : 'literature-reading'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openIngestion() {
  const next = workspaceStore.mainView === 'ingestion' ? 'editor' : 'ingestion'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

/** Opens the persistent scanner workspace. */
function openScanner() {
  const next = workspaceStore.mainView === 'scanner' ? 'editor' : 'scanner'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

/** Open the persistent multi-source scanner board as a full-width queue page. */
function openBatchScanner() {
  workspaceStore.setMainView('batch-scanner')
  fileSidebarOpen.value = false
  agentSidebarOpen.value = false
}

function openVisualization() {
  const next = workspaceStore.mainView === 'visualization' ? 'editor' : 'visualization'
  workspaceStore.setMainView(next)
  if (next === 'visualization') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openSearch() {
  const next = workspaceStore.mainView === 'search' ? 'editor' : 'search'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

function openBrowser() {
  const next = workspaceStore.mainView === 'browser' ? 'editor' : 'browser'
  if (next === 'browser') workspaceStore.closeBrowserSidebar()
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

/** Toggle half-width browser mode; convert the full-page browser when needed. */
function toggleBrowserSidebar() {
  if (workspaceStore.mainView === 'browser') {
    workspaceStore.setMainView('editor')
    workspaceStore.openBrowserSidebar()
    return
  }
  workspaceStore.toggleBrowserSidebar()
}

function openSettings() {
  const next = workspaceStore.mainView === 'settings' ? 'editor' : 'settings'
  workspaceStore.setMainView(next)
  if (next !== 'editor') {
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
  }
}

async function openGraphNode(node: KnowledgeGraphNodeEvent) {
  if (node.kind === 'root') {
    return
  }
  if (node.kind === 'virtual-group' && node.id.startsWith('library:')) {
    workspaceStore.openLibraryParent(node.id.slice('library:'.length))
    fileSidebarOpen.value = false
    agentSidebarOpen.value = false
    return
  }
  if (!node.path) {
    return
  }
  workspaceStore.setMainView('editor')
  await workspaceStore.selectFile({
    name: node.label,
    path: node.path,
    isDir: node.kind === 'folder',
  })
}

function applyResizeMove(clientX: number) {
  const grid = workspaceGrid.value
  if (!grid || !activeResizeTarget.value) {
    return
  }
  if (isAgentPage.value && (activeResizeTarget.value === 'file' || activeResizeTarget.value === 'agent')) {
    return
  }
  const rect = grid.getBoundingClientRect()
  if (activeResizeTarget.value === 'file') {
    const nextWidth = clientX - rect.left - activityBarWidth.value
    if (nextWidth < COLLAPSE_THRESHOLD) {
      fileSidebarOpen.value = false
      return
    }
    fileSidebarOpen.value = true
    fileWidth.value = clamp(nextWidth, MIN_PANEL_WIDTH, MAX_FILE_WIDTH)
    return
  }

  if (activeResizeTarget.value === 'editor' || activeResizeTarget.value === 'browser') {
    const editorTarget = activeResizeTarget.value === 'editor'
    const panel = grid.querySelector<HTMLElement>(editorTarget ? '.editor-sidebar-content' : '.browser-sidebar-content')
    const mainPanel = grid.querySelector<HTMLElement>('.editor-col')
    if (!panel || !mainPanel) return
    const panelRect = panel.getBoundingClientRect()
    const nextWidth = panelRect.right - clientX
    if (nextWidth < COLLAPSE_THRESHOLD) {
      if (editorTarget) {
        workspaceStore.closeEditorSidebar()
      } else {
        workspaceStore.closeBrowserSidebar()
      }
      return
    }
    const minimumWidth = editorTarget ? MIN_EDITOR_SIDEBAR_WIDTH : MIN_BROWSER_SIDEBAR_WIDTH
    const availableWidth = Math.max(minimumWidth, panelRect.width + mainPanel.getBoundingClientRect().width - MIN_MAIN_WIDTH)
    const maximumWidth = editorTarget
      ? Math.max(minimumWidth, Math.min(MAX_EDITOR_SIDEBAR_WIDTH, availableWidth))
      : availableWidth
    if (editorTarget) {
      editorSidebarWidth.value = clamp(nextWidth, minimumWidth, maximumWidth)
    } else {
      browserSidebarWidth.value = clamp(nextWidth, minimumWidth, maximumWidth)
    }
    return
  }

  const nextWidth = rect.right - clientX
  if (nextWidth < COLLAPSE_THRESHOLD) {
    if (gitRightOpen.value) {
      gitRightOpen.value = false
      return
    }
    if (agentSidebarOpen.value) {
      agentSidebarOpen.value = false
    }
    return
  }
  if (!visibleAgentSidebarOpen.value) {
    agentSidebarOpen.value = true
  }
  const fileColumnWidth = fileSidebarOpen.value ? fileWidth.value : 0
  const maxAgentWidth = Math.max(MIN_PANEL_WIDTH, rect.width - activityBarWidth.value - fileColumnWidth - 8)
  agentWidth.value = clamp(nextWidth, MIN_PANEL_WIDTH, maxAgentWidth)
}

function handleResizeMove(event: PointerEvent) {
  event.preventDefault()
  pendingResizeClientX = event.clientX
  if (resizeFrameId) {
    return
  }
  resizeFrameId = window.requestAnimationFrame(() => {
    resizeFrameId = 0
    applyResizeMove(pendingResizeClientX)
  })
}

function stopResize() {
  if (resizeFrameId) {
    window.cancelAnimationFrame(resizeFrameId)
    resizeFrameId = 0
  }
  if (resizePointerTarget && resizePointerId !== null) {
    try {
      resizePointerTarget.releasePointerCapture(resizePointerId)
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }
  resizePointerTarget = null
  resizePointerId = null
  activeResizeTarget.value = null
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
}

function startResize(target: ResizeTarget, event: PointerEvent) {
  event.preventDefault()
  resizePointerTarget = event.currentTarget as HTMLElement
  resizePointerId = event.pointerId
  try {
    resizePointerTarget.setPointerCapture(event.pointerId)
  } catch {
    // Pointer capture is an optimization; window listeners still keep resizing usable.
  }
  activeResizeTarget.value = target
  pendingResizeClientX = event.clientX
  window.addEventListener('pointermove', handleResizeMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function handleKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    workspaceStore.openCommandPalette()
  }
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    workspaceStore.openSearch()
  }
  if (event.key === 'Escape') {
    if (workspaceStore.commandPaletteOpen) {
      workspaceStore.closeCommandPalette()
      return
    }
    workspaceStore.closeSearch()
  }
}

function refreshGitAfterKnowledgeFileChange(): void {
  // 知识文件保存会吞掉文件监听事件，工作区需要常驻刷新 Git 状态以驱动文件树颜色。
  void gitStore.refresh()
}

let unsubscribeOpenAgentPage: (() => void) | undefined
let mainShellResizeObserver: ResizeObserver | null = null

/** Measure the stable workspace span so sidebar layout changes cannot flip the mobile breakpoint. */
function updateMainShellWidth(): void {
  const grid = workspaceGrid.value
  if (!grid) return
  const gridRect = grid.getBoundingClientRect()
  mainShellWidth.value = gridRect.width - activityBarWidth.value
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('metaweave-knowledge-file-change', refreshGitAfterKnowledgeFileChange)
  // Floating "Expand Agent page" → switch to the full Agent view.
  unsubscribeOpenAgentPage = window.agentEditorDesktop?.onOpenAgentPage?.(() => {
    workspaceStore.setMainView('agent')
  })
  if (workspaceGrid.value) {
    updateMainShellWidth()
    mainShellResizeObserver = new ResizeObserver(updateMainShellWidth)
    mainShellResizeObserver.observe(workspaceGrid.value)
  }
  void gitStore.refresh()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('metaweave-knowledge-file-change', refreshGitAfterKnowledgeFileChange)
  unsubscribeOpenAgentPage?.()
  mainShellResizeObserver?.disconnect()
  stopResize()
  stopTodoResize()
})

watch(
  () => settingsStore.profile.knowledgeDir,
  () => {
    gitStore.reset()
    void gitStore.refresh()
  },
)
</script>

<template>
  <div
    class="workspace-page"
    :class="{
      resizing: activeResizeTarget || activeTodoResize,
      'resizing-column': activeResizeTarget,
      'resizing-row': activeTodoResize,
    }"
    :style="workspacePageStyle"
  >
    <TopCommandBar
      :git-open="gitRightOpen"
      :browser-open="browserSidebarVisible"
      :mobile="topCommandBarMobile"
      @toggle-agent="toggleAgentSidebar"
      @open-home="openHome"
      @open-settings="openSettings"
      @toggle-todo="toggleTodoSidebar"
      @toggle-git="toggleRightGitSidebar"
      @toggle-browser="toggleBrowserSidebar"
    />
    <div
      ref="workspaceGrid"
      class="workspace-grid"
      :class="{
        'file-sidebar-collapsed': !visibleFileSidebarOpen,
        'agent-sidebar-collapsed': !visibleAgentSidebarOpen,
        'editor-sidebar-collapsed': !editorSidebarVisible,
        'browser-sidebar-collapsed': !browserSidebarVisible,
        'agent-main-view': isAgentPage,
        'graph-main-view': isGraphPage,
        'mobile-main-layout': topCommandBarMobile,
      }"
      :style="workspaceGridStyle"
    >
      <ActivityBar
        class="activity-col"
        :home-active="workspaceStore.mainView === 'home'"
        :file-open="visibleFileSidebarOpen && !gitLeftOpen"
        :git-active="gitLeftOpen"
        :agent-open="visibleAgentSidebarOpen"
        :resources-active="workspaceStore.mainView === 'resources'"
        :favorites-active="workspaceStore.mainView === 'favorites'"
        :privacy-active="workspaceStore.mainView === 'privacy'"
        :library-active="workspaceStore.mainView === 'library'"
        :component-library-active="workspaceStore.mainView === 'component-library'"
        :vault-active="workspaceStore.mainView === 'vault'"
        :forms-active="workspaceStore.mainView === 'forms'"
        :literature-active="workspaceStore.mainView === 'literature-reading'"
        :ingestion-active="workspaceStore.mainView === 'ingestion'"
        :scanner-active="workspaceStore.mainView === 'scanner'"
        :batch-scanner-active="workspaceStore.mainView === 'batch-scanner'"
        :visualization-active="workspaceStore.mainView === 'visualization'"
        :agent-active="workspaceStore.mainView === 'agent'"
        :agent-queue-active="workspaceStore.mainView === 'agent-queue'"
        :graph-active="workspaceStore.mainView === 'graph'"
        :dashboard-active="workspaceStore.mainView === 'dashboard'"
        :debug-active="workspaceStore.mainView === 'debug'"
        :feedback-open="feedbackOpen"
        :search-active="workspaceStore.mainView === 'search'"
        :browser-active="workspaceStore.mainView === 'browser'"
        :settings-active="workspaceStore.mainView === 'settings'"
        :display-mode="settingsStore.sidebarDisplayMode"
        :is-dark="settingsStore.isDark"
        @open-home="openHome"
        @toggle-file="toggleFileSidebar"
        @toggle-git="toggleLeftGitSidebar"
        @open-resources="openResources"
        @open-favorites="openFavorites"
        @open-privacy="openPrivacy"
        @open-library="openLibrary"
        @open-component-library="openComponentLibrary"
        @open-vault="openVault"
        @open-forms="openForms"
        @open-literature="openLiterature"
        @open-ingestion="openIngestion"
        @open-scanner="openScanner"
        @open-batch-scanner="openBatchScanner"
        @open-visualization="openVisualization"
        @toggle-agent="openAgentPage"
        @open-agent-queue="openAgentQueue"
        @toggle-graph="toggleGraphView"
        @toggle-todo="toggleTodoSidebar"
        @open-dashboard="openDashboard"
        @toggle-feedback="toggleFeedback"
        @open-debug="openDebug"
        @open-search="openSearch"
        @open-browser="openBrowser"
        @knowledge-menu-visibility-change="activityOverlayOpen = $event"
        @open-settings="openSettings"
        @toggle-theme="settingsStore.toggleTheme"
      />
      <div class="file-col ide-panel" :aria-hidden="!visibleFileSidebarOpen">
        <GitSidebar v-if="gitLeftOpen" />
        <FileTreePanel
          v-else
          :mobile-overlay="topCommandBarMobile"
          @collapse="toggleFileSidebar"
          @file-opened="handleFileTreeFileOpened"
        />
      </div>
      <div
        class="resize-handle file-resizer"
        role="separator"
        aria-label="Resize file tree"
        @pointerdown="startResize('file', $event)"
      ></div>
      <main
        class="main-shell editor-col ide-panel"
        :class="{
          'agent-page-main-shell': isAgentPage && !topCommandBarMobile,
        }"
      >
        <Transition name="mobile-sidebar-toggle">
          <button
            v-if="topCommandBarMobile && workspaceStore.mainView === 'editor' && !visibleFileSidebarOpen"
            class="mobile-file-sidebar-expand"
            type="button"
            title="展开文件树"
            aria-label="展开文件树侧边栏"
            @click="openFileSidebar"
          >
            <IcIcon name="arrow-right" :size="18" />
          </button>
        </Transition>
        <HomeView v-if="workspaceStore.mainView === 'home'" class="main-shell-content" />
        <EditorPane v-else-if="workspaceStore.mainView === 'editor'" class="main-shell-content" />
        <FileResourceManager v-else-if="workspaceStore.mainView === 'resources'" class="main-shell-content" />
        <FavoritesView v-else-if="workspaceStore.mainView === 'favorites'" class="main-shell-content" />
        <PrivacyView v-else-if="workspaceStore.mainView === 'privacy'" class="main-shell-content" />
        <LibraryView v-else-if="workspaceStore.mainView === 'library'" class="main-shell-content" />
        <ComponentLibraryView
          v-else-if="workspaceStore.mainView === 'component-library'"
          class="main-shell-content"
          :mobile="topCommandBarMobile"
        />
        <VaultView
          v-else-if="workspaceStore.mainView === 'vault'"
          class="main-shell-content"
          :mobile="vaultSidebarMobile"
        />
        <SmartFormsView
          v-else-if="workspaceStore.mainView === 'forms'"
          class="main-shell-content"
          :mobile="topCommandBarMobile"
          :available-width="mainShellWidth"
        />
        <LiteratureReadingView v-else-if="workspaceStore.mainView === 'literature-reading'" class="main-shell-content" />
        <IngestionProgressView v-else-if="workspaceStore.mainView === 'ingestion'" class="main-shell-content" />
        <ScannerView v-else-if="workspaceStore.mainView === 'scanner'" class="main-shell-content" />
        <BatchScannerView v-else-if="workspaceStore.mainView === 'batch-scanner'" class="main-shell-content" />
        <MarkdownHtmlVisualizationView v-else-if="workspaceStore.mainView === 'visualization'" class="main-shell-content" />
        <AgentPage
          v-else-if="workspaceStore.mainView === 'agent'"
          class="main-shell-content"
          :mobile="topCommandBarMobile"
        />
        <AgentQueueView v-else-if="workspaceStore.mainView === 'agent-queue'" class="main-shell-content" />
        <GraphPane
          v-else-if="workspaceStore.mainView === 'graph'"
          class="main-shell-content"
          :available-width="mainShellWidth"
          @open-node="openGraphNode"
        />
        <DashboardView v-else-if="workspaceStore.mainView === 'dashboard'" class="main-shell-content" />
        <DebugView v-else-if="workspaceStore.mainView === 'debug'" class="main-shell-content" />
        <SearchPage v-else-if="workspaceStore.mainView === 'search'" class="main-shell-content" />
        <BrowserPage
          v-else-if="workspaceStore.mainView === 'browser'"
          class="main-shell-content"
          :activity-overlay-open="activityOverlayOpen"
        />
        <SettingsView v-else-if="workspaceStore.mainView === 'settings'" class="main-shell-content" />
      </main>
      <div
        class="resize-handle editor-resizer"
        role="separator"
        aria-label="Resize editor sidebar"
        @pointerdown="startResize('editor', $event)"
      ></div>
      <aside class="editor-sidebar-content" :aria-hidden="!editorSidebarVisible">
        <SearchResultSidebar
          v-if="editorSidebarVisible && workspaceStore.searchSidebarResult"
          :result="workspaceStore.searchSidebarResult"
          @close="workspaceStore.closeEditorSidebar"
        />
        <EditorPane v-else-if="editorSidebarVisible" sidebar @close="workspaceStore.closeEditorSidebar" />
      </aside>
      <div
        class="resize-handle browser-resizer"
        role="separator"
        aria-label="Resize browser sidebar"
        @pointerdown="startResize('browser', $event)"
      ></div>
      <BrowserPage
        v-if="!isBrowserPage"
        class="browser-sidebar-content"
        :visible="browserSidebarVisible"
        :activity-overlay-open="activityOverlayOpen"
        :initial-url="workspaceStore.browserSidebarUrl"
        :navigation-request-id="workspaceStore.browserSidebarNavigationId"
        sidebar
      />
      <div
        class="resize-handle agent-resizer"
        role="separator"
        aria-label="Resize Agent panel"
        @pointerdown="startResize('agent', $event)"
      ></div>
      <div v-if="!isAgentPage" class="agent-col" :class="{ 'todo-open': todoSidebarOpen }" :aria-hidden="!visibleAgentSidebarOpen">
        <GitSidebar v-if="gitRightOpen" />
        <template v-else>
        <div class="todo-section" :style="{ flex: todoSidebarOpen ? (agentSidebarOpen ? todoSplitRatio : 1) : 0 }">
          <div class="todo-body-wrap" :class="{ visible: todoSidebarOpen }">
            <TodoSidebar />
          </div>
        </div>
        <div
          class="todo-agent-divider"
          :class="{ visible: todoSidebarOpen }"
          @pointerdown="startTodoResize"
        ></div>
        <div class="agent-section" :class="{ visible: agentSidebarOpen }" :style="{ flex: agentSidebarOpen ? (todoSidebarOpen ? 1 - todoSplitRatio : 1) : 0 }">
          <div class="agent-body-wrap" :class="{ visible: agentSidebarOpen }">
            <AgentPanel @expand="openAgentPage" />
          </div>
        </div>
        </template>
      </div>
    </div>
    <CommandPalette />
    <SelectionToolbar @ask="handleAskAgent" />
    <FileConflictDialog v-if="showConflictDialog" />
    <ImagePreviewer />
    <FeedbackPopover
      :open="feedbackOpen"
      :user-id="settingsStore.profile.userId"
      :page="workspaceStore.mainView"
      @close="feedbackOpen = false"
    />
  </div>
</template>

<style scoped>
.workspace-page {
  --workspace-card-radius: 28px;
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100%;
  height: 100%;
  background: var(--color-chrome-rail-bg);
}

.workspace-grid {
  position: relative;
  display: grid;
  grid-template-columns:
    var(--activity-col-width) var(--file-col-width) var(--file-resizer-width) minmax(0, 1fr)
    var(--editor-resizer-width) var(--editor-sidebar-width) var(--browser-resizer-width)
    var(--browser-sidebar-width) var(--agent-resizer-width) var(--agent-col-width);
  column-gap: 0;
  min-width: 0;
  min-height: 0;
  padding: 0;
  transition:
    grid-template-columns 180ms ease,
    grid-template-rows 180ms ease;
}

.activity-col {
  grid-column: 1;
  min-width: 0;
  min-height: 0;
}

.file-col,
.editor-col,
.agent-col {
  min-width: 0;
  min-height: 0;
}

.file-col {
  grid-column: 2;
  overflow: hidden;
  background: var(--color-chrome-rail-bg);
  transition:
    opacity 160ms ease,
    transform 180ms ease;
}

.workspace-grid.mobile-main-layout .file-col {
  position: absolute;
  grid-column: auto;
  grid-row: auto;
  top: var(--space-8);
  bottom: var(--space-8);
  left: calc(var(--activity-col-width) + var(--space-8));
  z-index: 90;
  width: min(320px, calc(100% - var(--activity-col-width) - var(--space-16)));
  border: 1px solid var(--workspace-panel-border);
  border-radius: 18px;
  background: var(--color-bg-app);
  box-shadow: 12px 0 32px rgba(12, 18, 38, 0.22);
  opacity: 1;
  transform: translateX(0);
}

.workspace-grid.mobile-main-layout.file-sidebar-collapsed .file-col {
  opacity: 0;
  transform: translateX(calc(-100% - var(--space-16)));
}

.workspace-grid.mobile-main-layout .file-resizer {
  display: none;
}

.workspace-grid.mobile-main-layout .editor-sidebar-content,
.workspace-grid.mobile-main-layout .browser-sidebar-content,
.workspace-grid.mobile-main-layout .agent-col {
  position: absolute;
  grid-column: auto;
  top: var(--space-8);
  right: var(--space-8);
  bottom: var(--space-8);
  z-index: 90;
  width: min(360px, calc(100% - var(--activity-col-width) - var(--space-16)));
  max-width: calc(100% - var(--activity-col-width) - var(--space-16));
  box-sizing: border-box;
  margin: 0;
  border: 1px solid var(--workspace-panel-border);
  border-radius: 18px;
  background: var(--color-bg-app);
  box-shadow: -12px 0 32px rgba(12, 18, 38, 0.22);
  opacity: 1;
  transform: translateX(0);
}

.workspace-grid.mobile-main-layout .editor-resizer,
.workspace-grid.mobile-main-layout .browser-resizer,
.workspace-grid.mobile-main-layout .agent-resizer {
  display: none;
}

/* Keep the search editor card inside the viewport even if top-bar content widens the grid. */
.workspace-grid.mobile-main-layout .editor-sidebar-content {
  position: fixed;
  top: 64px;
  right: var(--space-8);
  width: min(360px, calc(100vw - var(--activity-col-width) - var(--space-16)));
  max-width: calc(100vw - var(--activity-col-width) - var(--space-16));
}

.workspace-grid.mobile-main-layout.editor-sidebar-collapsed .editor-sidebar-content,
.workspace-grid.mobile-main-layout.browser-sidebar-collapsed .browser-sidebar-content,
.workspace-grid.mobile-main-layout.agent-sidebar-collapsed .agent-col {
  opacity: 0;
  transform: translateX(calc(100% + var(--space-16)));
}

.mobile-file-sidebar-expand {
  position: absolute;
  top: var(--space-8);
  left: var(--space-10);
  z-index: 70;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.mobile-file-sidebar-expand:hover {
  background: var(--color-selection-blue-soft);
  color: var(--color-selection-blue);
}

.mobile-file-sidebar-expand + .main-shell-content :deep(.tab-list) {
  margin-left: 36px;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.tab-strip) {
  position: relative;
  align-items: stretch;
  flex-direction: column;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.tab-list) {
  margin-right: 36px;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.tab-actions) {
  width: 100%;
  justify-content: flex-start;
  overflow: visible;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.editor-mode-control) {
  align-self: flex-start;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.editor-mode-control.single-mode) {
  display: none;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.code-editor-header) {
  display: none;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.save-button) {
  position: absolute;
  top: var(--space-8);
  right: var(--space-10);
  width: 28px;
  padding: 0;
}

.workspace-grid.mobile-main-layout .main-shell-content :deep(.save-button span) {
  display: none;
}

.mobile-sidebar-toggle-enter-active,
.mobile-sidebar-toggle-leave-active {
  transition: opacity 160ms ease, transform 180ms ease;
}

.mobile-sidebar-toggle-enter-from,
.mobile-sidebar-toggle-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}

.main-shell.ide-panel,
.editor-sidebar-content,
.agent-col {
  border: 1px solid var(--workspace-panel-border);
  box-shadow: 0 0 0 4px var(--workspace-panel-ring);
}

.file-resizer {
  grid-column: 3;
}

.editor-col {
  grid-column: 4;
}

.main-shell.ide-panel {
  position: relative;
  z-index: 60;
  display: flex;
  min-width: 0;
  min-height: 0;
  margin: var(--space-12);
  overflow: hidden;
  outline: none;
  border-radius: var(--workspace-card-radius);
  background: var(--color-bg-app);
}

.main-shell.ide-panel.agent-page-main-shell {
  overflow: visible;
}

.main-shell-content {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.browser-sidebar-content {
  grid-column: 8;
  min-width: 0;
  min-height: 0;
  margin: 0 0 var(--space-12) 0;
  border-left: 1px solid var(--color-border-subtle);
  overflow: hidden;
  opacity: 1;
  transform: translateX(0);
  transition: opacity 160ms ease, transform 180ms ease;
}

.editor-sidebar-content {
  grid-column: 6;
  display: flex;
  min-width: 0;
  min-height: 0;
  margin: var(--space-12);
  overflow: hidden;
  border-radius: var(--workspace-card-radius);
  background: var(--color-bg-app);
  transition: opacity 160ms ease, transform 180ms ease;
  contain: inline-size;
}

.editor-sidebar-content > * { width: 100%; max-width: 100%; }

.workspace-grid.editor-sidebar-collapsed .editor-sidebar-content {
  pointer-events: none;
  opacity: 0;
  transform: translateX(18px);
}

.workspace-grid.browser-sidebar-collapsed .browser-sidebar-content {
  pointer-events: none;
  opacity: 0;
  transform: translateX(18px);
}

@media (prefers-reduced-motion: reduce) {
  .workspace-grid {
    transition: none;
  }

  .browser-sidebar-content {
    transition: opacity 100ms ease;
  }
}

.editor-resizer {
  grid-column: 5;
}

.browser-resizer {
  grid-column: 7;
}

.agent-resizer {
  grid-column: 9;
}

.agent-col {
  grid-column: 10;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
  margin: var(--space-12);
  border-radius: var(--workspace-card-radius);
  background: var(--color-bg-app);
  transition:
    opacity 160ms ease,
    transform 180ms ease;
}

.agent-col :deep(.agent-panel) {
  border-radius: var(--workspace-card-radius);
}

.todo-section {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  height: 100%;
}

.todo-body-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  opacity: 0;
  transform: translateY(-12px);
  transition: opacity 180ms ease, transform 180ms ease;
}

.todo-body-wrap.visible {
  opacity: 1;
  transform: translateY(0);
}

.agent-section {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.agent-body-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 180ms ease, transform 180ms ease;
}

.agent-body-wrap.visible {
  opacity: 1;
  transform: translateY(0);
}

.todo-agent-divider {
  flex: 0 0 4px;
  cursor: row-resize;
  background: transparent;
  border-top: 1px solid transparent;
  border-bottom: 1px solid transparent;
  opacity: 0;
  transition: opacity 160ms ease, background var(--transition-fast);
}

.todo-agent-divider.visible {
  opacity: 1;
}

.todo-agent-divider:hover,
.workspace-page.resizing .todo-agent-divider {
  background: var(--color-primary-soft);
}

.workspace-grid.file-sidebar-collapsed .file-col {
  pointer-events: none;
  opacity: 0;
  transform: translateX(-18px);
}

.workspace-grid.agent-sidebar-collapsed .agent-col {
  pointer-events: none;
  opacity: 0;
  transform: translateX(18px);
}

.workspace-grid.file-sidebar-collapsed .file-resizer,
.workspace-grid.editor-sidebar-collapsed .editor-resizer,
.workspace-grid.browser-sidebar-collapsed .browser-resizer,
.workspace-grid.agent-sidebar-collapsed .agent-resizer {
  pointer-events: none;
  opacity: 0;
}

.ide-panel {
  border-top: 0;
  border-bottom: 0;
  border-radius: 0;
}

.file-col {
  border-left: 0;
}

.editor-col {
  border-left: 0;
  border-right: 0;
  background: transparent;
}

.resize-handle {
  min-width: 0;
  border-left: 1px solid transparent;
  border-right: 1px solid transparent;
  cursor: col-resize;
  background: transparent;
  transition:
    background var(--transition-fast),
    opacity 160ms ease;
}

.resize-handle:hover,
.workspace-page.resizing .resize-handle {
  background: var(--color-primary-soft);
}

.workspace-page.resizing {
  user-select: none;
}

.workspace-page.resizing-column,
.workspace-page.resizing-column * {
  cursor: col-resize !important;
}

.workspace-page.resizing-row,
.workspace-page.resizing-row * {
  cursor: row-resize !important;
}

.workspace-page.resizing .workspace-grid,
.workspace-page.resizing .file-col,
.workspace-page.resizing .editor-col,
.workspace-page.resizing .editor-sidebar-content,
.workspace-page.resizing .browser-sidebar-content,
.workspace-page.resizing .agent-col {
  transition: none;
}

.workspace-page.resizing-column .file-col,
.workspace-page.resizing-column .editor-col,
.workspace-page.resizing-column .editor-sidebar-content,
.workspace-page.resizing-column .browser-sidebar-content,
.workspace-page.resizing-column .agent-col {
  pointer-events: none;
}

@media (max-width: 1180px) {
  .workspace-grid {
    padding-right: 0;
  }
}

@media (max-width: 760px) {
  .workspace-page {
    --workspace-card-radius: 24px;
  }

  .main-shell.ide-panel,
  .editor-sidebar-content,
  .agent-col {
    margin: var(--space-8);
  }
}
</style>
