/*
 * Knowledge workspace state store.
 *
 * Usage:
 * This store owns the backend file tree, editor tabs, command palette state,
 * and right-side Agent messages.
 */

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { ApiError, buildApiUrl } from '@/api/client'
import { updateCurrentDocumentContext } from '@/api/agent'
import { searchAllLibraries } from '@/api/unifiedSearch'
import type { GraphDocStatus, KnowledgeIngestionJob } from '@/api/knowledge'
import {
  buildKnowledgeEventsUrl,
  cancelKnowledgeGraphTask,
  cancelKnowledgeIngestionJob,
  copyKnowledgePath,
  createKnowledgeIngestionJobs,
  createKnowledgeFile,
  createKnowledgeFolder,
  deleteKnowledgePath,
  deleteKnowledgeTrashEntry,
  getKnowledgeGraphStatus,
  listKnowledgeIngestionJobs,
  listKnowledgeFiles,
  listKnowledgeTrash,
  previewKnowledgeFile,
  readKnowledgeFile,
  rebuildKnowledgeGraph,
  renameKnowledgePath,
  restoreKnowledgeTrashEntry,
  uploadKnowledgeFile,
  writeKnowledgeFile,
} from '@/api/knowledge'
import type { KnowledgeIngestionProgressEvent } from '@/api/settings'
import { normalizeProgress } from '@/utils/progress'
import { useSettingsStore } from '@/stores/settings'
import type {
  ChatMessage,
  CommandAction,
  EditorTab,
  EditorWorkspaceMode,
  FilePreviewPayload,
  FileViewerKind,
  IngestionHistoryItem,
  IngestionHistoryStatus,
  IngestionQueueItem,
  IndexStatus,
  KnowledgeFileNode,
  KnowledgeTrashEntry,
  MarkdownHtmlVisualizationMode,
  MarkdownHtmlVisualizationOptions,
  MarkdownHtmlVisualizationPayload,
  MarkdownHtmlVisualizationPreset,
  GraphStatus,
  WorkspaceMainView,
} from '@/types/knowledge'
import { SEARCH_SOURCES, type SearchSource, type UnifiedSearchResponse, type UnifiedSearchResult } from '@/types/unifiedSearch'
import {
  updateRecentFileVisits,
  type RecentFileVisit,
} from '@/utils/recentFileHistory'
import { resolveEditorFilePipeline } from '@/utils/editorFilePipeline'

function createId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

/** Calculate whole-task graph progress while retaining active document detail. */
export function calculateGraphProgress(docs: GraphDocStatus[], total: number): number {
  if (total <= 0) return 0
  const completedProgress = docs.reduce((sum, doc) => {
    if (doc.status === 'done' || doc.status === 'skipped' || doc.status === 'failed' || doc.status === 'cancelled') return sum + 100
    return sum + Math.max(0, Math.min(100, doc.progress ?? 0))
  }, 0)
  return Math.round(completedProgress / total)
}

function flattenNodes(nodes: KnowledgeFileNode[]): KnowledgeFileNode[] {
  return nodes.flatMap((node) => [node, ...(node.children ? flattenNodes(node.children) : [])])
}

function flattenIngestibleNodes(nodes: KnowledgeFileNode[]): KnowledgeFileNode[] {
  return flattenNodes(nodes).filter((node) => {
    if (node.isDir || node.indexStatus === 'ignored') {
      return false
    }
    return !node.indexStatus || node.indexStatus === 'dirty' || node.indexStatus === 'failed'
  })
}

/** Return every non-ignored source file that can participate in graph extraction. */
function flattenGraphSourceNodes(nodes: KnowledgeFileNode[]): KnowledgeFileNode[] {
  return flattenNodes(nodes).filter((node) => !node.isDir && node.indexStatus !== 'ignored')
}

/** Return only files that must be ingested before graph extraction can start. */
export function graphIngestionTargets(node: KnowledgeFileNode): KnowledgeFileNode[] {
  return flattenIngestibleNodes([node])
}

/** Detect an explicit re-extraction request from the persisted tree state. */
export function shouldForceGraphExtraction(node: KnowledgeFileNode): boolean {
  return flattenNodes([node]).some((item) => !item.isDir && item.graphStatus === 'graphed')
}

function formatMtime(date = new Date()): string {
  const pad = (value: number) => value.toString().padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function normalizeTreePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

function joinTreePath(parentPath: string, childName: string): string {
  return normalizeTreePath(parentPath ? `${parentPath}/${childName}` : childName)
}

function getParentPath(path: string): string {
  const parts = normalizeTreePath(path).split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

function getBaseName(path: string): string {
  const parts = normalizeTreePath(path).split('/').filter(Boolean)
  return parts[parts.length - 1] ?? ''
}

function buildAbsoluteKnowledgePath(knowledgeDir: string, relativePath: string): string {
  const root = knowledgeDir.replace(/[\\/]+$/g, '')
  const child = normalizeTreePath(relativePath)
  if (!child) {
    return root
  }
  return `${root}\\${child.replace(/\//g, '\\')}`
}

function splitExtension(name: string): { stem: string; extension: string } {
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex <= 0) {
    return { stem: name, extension: '' }
  }
  return { stem: name.slice(0, dotIndex), extension: name.slice(dotIndex) }
}

function extensionForImageMimeType(mimeType: string): string {
  const normalized = mimeType.toLowerCase()
  if (normalized.includes('jpeg')) return '.jpg'
  if (normalized.includes('gif')) return '.gif'
  if (normalized.includes('webp')) return '.webp'
  return '.png'
}

function normalizeEditorAssetDirectory(value: string | undefined): string {
  const parts = (value ?? './assets/')
    .replace(/\\/g, '/')
    .split('/')
    .filter((part) => part && part !== '.' && part !== '..')
  return parts.join('/') || 'assets'
}

type FileConflictStrategy = 'overwrite' | 'skip' | 'rename'
type FileConflictDialogOwner = 'tree' | 'resources' | 'scanner'

const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown'])
const CODE_EXTENSIONS = new Set([
  'c',
  'bash',
  'cpp',
  'cs',
  'css',
  'go',
  'h',
  'hpp',
  'html',
  'java',
  'js',
  'json',
  'jsx',
  'kt',
  'kts',
  'php',
  'py',
  'rs',
  'sh',
  'sql',
  'tex',
  'ts',
  'tsx',
  'vue',
  'xml',
  'yaml',
  'yml',
])
function extensionOf(path: string): string {
  const name = getBaseName(path).toLowerCase()
  const dotIndex = name.lastIndexOf('.')
  return dotIndex >= 0 ? name.slice(dotIndex + 1) : ''
}

function viewerKindForPath(path: string): FileViewerKind {
  const extension = extensionOf(path)
  if (MARKDOWN_EXTENSIONS.has(extension)) return 'markdown'
  if (CODE_EXTENSIONS.has(extension)) return 'code'
  if (extension === 'txt') return 'text'
  return 'unsupported'
}

function shouldUsePreviewEndpoint(path: string): boolean {
  return resolveEditorFilePipeline(path).usesPreviewEndpoint
}

function defaultEditorMode(path: string, kind?: FileViewerKind): EditorWorkspaceMode {
  /** 多模态文件每次打开默认展示原始预览,即使已有灌库文本也不抢占编辑视图。 */

  return resolveEditorFilePipeline(path, kind).defaultMode
}

function childDirectoryFor(node?: KnowledgeFileNode | null): string {
  if (!node) {
    return ''
  }
  return node.isDir ? node.path : getParentPath(node.path)
}

function getRelativeFilePath(file: File): string {
  return normalizeTreePath(file.webkitRelativePath || file.name)
}

function stripRootFolder(path: string): string {
  const parts = normalizeTreePath(path).split('/').filter(Boolean)
  return parts.length > 1 ? parts.slice(1).join('/') : parts.join('/')
}

function createImportedFileNode(path: string, file: File): KnowledgeFileNode {
  const parts = normalizeTreePath(path).split('/').filter(Boolean)
  return {
    name: parts[parts.length - 1] ?? file.name,
    path,
    isDir: false,
    size: file.size,
    mtime: formatMtime(new Date(file.lastModified || Date.now())),
    indexStatus: 'indexing',
  }
}

function upsertFileNode(
  nodes: KnowledgeFileNode[],
  relativePath: string,
  file: File,
  expanded: Set<string>,
) {
  const parts = normalizeTreePath(relativePath).split('/').filter(Boolean)
  if (parts.length === 0) {
    return
  }
  let currentNodes = nodes
  let currentPath = ''
  for (const part of parts.slice(0, -1)) {
    currentPath = joinTreePath(currentPath, part)
    let dirNode = currentNodes.find((node) => node.isDir && node.name === part)
    if (!dirNode) {
      dirNode = {
        name: part,
        path: currentPath,
        isDir: true,
        indexStatus: 'indexing',
        children: [],
      }
      currentNodes.push(dirNode)
    }
    dirNode.indexStatus = 'indexing'
    dirNode.children ??= []
    expanded.add(dirNode.path)
    currentNodes = dirNode.children
  }

  const filePath = normalizeTreePath(relativePath)
  const importedNode = createImportedFileNode(filePath, file)
  const existingIndex = currentNodes.findIndex((node) => node.path === importedNode.path)
  if (existingIndex >= 0) {
    currentNodes.splice(existingIndex, 1, importedNode)
    return
  }
  currentNodes.push(importedNode)
}

function isLikelyTextFile(file: File): boolean {
  if (file.type.startsWith('text/')) {
    return true
  }
  return /\.(c|cpp|css|go|html|java|js|json|jsx|md|py|rs|ts|tsx|txt|vue|xml|yaml|yml)$/i.test(file.name)
}

async function readFilePreview(file: File): Promise<string> {
  if (!isLikelyTextFile(file)) {
    return `# ${file.name}\n\nBinary file placeholder. Backend import and indexing will handle the original file.`
  }
  try {
    return await file.text()
  } catch {
    return `# ${file.name}\n\nUnable to preview this file in the browser shell.`
  }
}

export const useWorkspaceStore = defineStore('workspace', () => {
  /** Recursive knowledge file tree loaded from the backend. */
  const tree = ref<KnowledgeFileNode[]>([])

  /** Expanded directory paths. */
  const expandedPaths = ref<Set<string>>(new Set())

  /** Current file path selected in the editor. */
  const selectedPath = ref('')

  /** Current file or directory path highlighted in the tree. */
  const selectedTreePath = ref('')

  /** Whether the user explicitly cleared the tree highlight while keeping the editor file open. */
  const treeSelectionCleared = ref(false)

  /** Active editor mode. */
  const editorMode = ref<EditorWorkspaceMode>('edit')

  /** Active center workspace view. 默认进入主页。 */
  const mainView = ref<WorkspaceMainView>('home')

  /** Temporary editor pane shown beside non-editor pages without changing the active page. */
  const editorSidebarOpen = ref(false)

  /** Temporary right-side browser visibility; it is intentionally not persisted. */
  const browserSidebarOpen = ref(false)

  /** Latest external URL requested by library or Agent citation navigation. */
  const browserSidebarUrl = ref('')

  /** Monotonic navigation request used to reload an identical clicked URL. */
  const browserSidebarNavigationId = ref(0)

  /** Pending virtual-library collection to open when LibraryView is mounted. */
  const pendingLibraryParentId = ref('')

  /** One-shot four-library result consumed by a main library view. */
  const pendingMainSearchResult = ref<UnifiedSearchResult | null>(null)

  /** One-shot smart-form row target consumed when LiteratureReadingView mounts. */
  const pendingLiteratureEntry = ref<{ formId: string; rowId: string } | null>(null)

  /** Active tab within the ingestion progress view: 'queue' | 'graph-queue' | 'history'. */
  const ingestionViewTab = ref<'queue' | 'graph-queue' | 'history'>('queue')

  /** Open file tabs. */
  const openTabs = ref<EditorTab[]>([])

  /** Local file content cache. */
  const contentByPath = ref<Record<string, string>>({})

  /** Backend-generated multimodal preview cache for binary/table/document files. */
  const previewByPath = ref<Record<string, FilePreviewPayload>>({})

  /** Files opened by the current user, newest visit first. */
  const recentFileVisits = ref<RecentFileVisit[]>([])
  let recentFileHistoryKey = ''

  /** Abort controller for the current preview fetch — cancels stale in-flight requests. */
  let _previewAbort: AbortController | null = null

  /** Abort controller for the current text-content fetch — cancels stale in-flight requests. */
  let _contentAbort: AbortController | null = null

  /** Paths currently being loaded via loadFilePreview (prevents duplicate concurrent loads). */
  const _pendingPreviewLoads = new Set<string>()

  /** Paths currently being loaded via loadFileContent (prevents duplicate concurrent loads). */
  const _pendingContentLoads = new Set<string>()

  /** Whether any file load is currently in-flight (for UI loading indicator). */
  const isFileLoading = ref(false)

  /** Command palette visibility. */
  const commandPaletteOpen = ref(false)

  /** Agent panel message history. */
  const chatMessages = ref<ChatMessage[]>([
    {
      id: 'system_intro',
      role: 'system',
      content: 'Agent panel is ready. Backend streaming will be connected later.',
    },
  ])

  /** Active backend file-event stream. */
  const fileEvents = ref<EventSource | null>(null)

  /** File tree loading state. */
  const treeLoading = ref(false)

  /** Recently deleted knowledge files loaded from backend trash metadata. */
  const trashEntries = ref<KnowledgeTrashEntry[]>([])
  const trashLoading = ref(false)

  /** Tracks how many pending tree_dirty events should suppress tab-dirty marking. */
  const ignoreNextTreeEvent = ref(0)

  /** Whether the refresh/indexing operation is in progress. */
  const refreshing = ref(false)

  /** Header-level ingestion progress shown while uploads or rebuilds are running. */
  const ingestionProgressVisible = ref(false)
  const ingestionProgress = ref(0)
  const ingestionProgressDetail = ref('正在检查需要灌库的文件')
  const ingestionProgressStats = ref({ succeeded: 0, total: 0, failed: 0 })
  const ingestionQueue = ref<IngestionQueueItem[]>([])
  const ingestionHistory = ref<IngestionHistoryItem[]>([])
  const INGESTION_HISTORY_KEY = 'metaweave_ingestion_history'
  const INGESTION_HISTORY_LIMIT = 240
  let ingestionProgressTimer: ReturnType<typeof setTimeout> | null = null
  let ingestionProgressPulseTimer: ReturnType<typeof setInterval> | null = null
  let activeIngestionRuns = 0
  const trackedIngestionJobIds = new Set<string>()
  const graphRequestedIngestionJobIds = new Set<string>()
  let completedIngestionQueueItems: IngestionQueueItem[] = []
  let lastIngestionQueueProcessed = 0
  let ingestionQueuePlannedTotal = 0
  let ingestionFileChunksByPath = new Map<string, number>()

  /** Header-level graph extraction progress shown while graph rebuild runs. */
  const graphProgressVisible = ref(false)
  const graphProgress = ref(0)
  const graphProgressDetail = ref('正在检查需要抽取的文件')
  const graphProgressStats = ref({ current: 0, total: 0 })
  const graphQueue = ref<IngestionQueueItem[]>([])
  const graphRebuildPending = ref(false)
  let graphPollingTimer: ReturnType<typeof setInterval> | null = null
  let graphProgressTimer: ReturnType<typeof setTimeout> | null = null
  let graphQueuePlannedTotal = 0

  /** Graph extraction history (persisted to localStorage). */
  const GRAPH_HISTORY_KEY = 'metaweave_graph_history'
  const GRAPH_HISTORY_LIMIT = 120
  const graphHistory = ref<IngestionHistoryItem[]>([])
  try {
    const raw = localStorage.getItem(GRAPH_HISTORY_KEY)
    if (raw) graphHistory.value = JSON.parse(raw) as IngestionHistoryItem[]
  } catch { /* ignore corrupt data */ }

  function persistGraphHistory() {
    try {
      localStorage.setItem(GRAPH_HISTORY_KEY, JSON.stringify(graphHistory.value))
    } catch { /* ignore storage failures */ }
  }

  function setGraphProgress(value: number) {
    graphProgress.value = Math.max(0, Math.min(100, Math.round(value)))
  }

  function beginGraphProgress(initialValue = 6) {
    if (graphProgressTimer !== null) {
      clearTimeout(graphProgressTimer)
      graphProgressTimer = null
    }
    graphProgressVisible.value = true
    setGraphProgress(initialValue)
    graphProgressDetail.value = '正在检查需要抽取的文件'
    graphProgressStats.value = { current: 0, total: 0 }
  }

  function stopGraphPolling() {
    if (graphPollingTimer !== null) {
      clearInterval(graphPollingTimer)
      graphPollingTimer = null
    }
  }

  function finishGraphProgress(message: string, isError = false) {
    setGraphProgress(100)
    showToast(message, isError ? 5000 : 3000)
    if (graphProgressTimer !== null) {
      clearTimeout(graphProgressTimer)
    }
    graphProgressTimer = setTimeout(() => {
      graphProgressVisible.value = false
      graphProgress.value = 0
      graphProgressDetail.value = ''
      graphProgressStats.value = { current: 0, total: 0 }
      graphProgressTimer = null
    }, 1500)
  }

  function completeGraphQueue(
    status: IngestionHistoryStatus,
    total: number,
    current: number,
    message?: string,
  ) {
    const finishedAt = new Date().toISOString()
    if (total > 0) {
      const historyItem: IngestionHistoryItem = {
        id: createId('graph_history'),
        name: `图谱抽取 ${finishedAt.slice(0, 16).replace('T', ' ')}`,
        path: '',
        isDir: false,
        status,
        finishedAt,
        filesSeen: total,
        filesIngested: current,
        filesSkipped: total - current,
        message,
        sourceType: 'graph',
      }
      graphHistory.value = [historyItem, ...graphHistory.value].slice(0, GRAPH_HISTORY_LIMIT)
      persistGraphHistory()
    }
    graphQueue.value = []
    graphQueuePlannedTotal = 0
    graphRebuildPending.value = false
    stopGraphPolling()
    if (status === 'finished') {
      finishGraphProgress(message ?? '图谱抽取完成')
    } else if (status === 'cancelled') {
      finishGraphProgress(message ?? '图谱抽取已中止')
    } else {
      finishGraphProgress(message ?? '图谱抽取失败', true)
    }
  }

  function syncGraphQueueFromDocs(docs: GraphDocStatus[], message?: string) {
    const queueMap = new Map<string, IngestionQueueItem>()
    for (const item of graphQueue.value) {
      queueMap.set(item.path, item)
    }

    for (const doc of docs) {
      if (doc.status === 'done' || doc.status === 'skipped' || doc.status === 'failed' || doc.status === 'cancelled') {
        updateTreeNodeGraphStatus(doc.path, graphStatusFromGraphDoc(doc))
        queueMap.delete(doc.path)
        continue
      }
      const existing = queueMap.get(doc.path)
      if (existing) {
        queueMap.set(doc.path, {
          ...existing,
          status: doc.status === 'processing' ? 'running' as const : doc.status === 'cancelling' ? 'cancelling' as const : 'waiting' as const,
          progress: doc.progress ?? existing.progress,
          stageLabel: doc.stage_label ?? existing.stageLabel,
          stageCurrent: doc.stage_current ?? existing.stageCurrent,
          stageTotal: doc.stage_total ?? existing.stageTotal,
          message: doc.message || (doc.status === 'processing' ? message : existing.message),
        })
      } else if (doc.status === 'pending' || doc.status === 'processing' || doc.status === 'cancelling') {
        queueMap.set(doc.path, {
          id: `graph_doc_${doc.path}`,
          name: doc.name,
          path: doc.path,
          isDir: false,
          status: doc.status === 'processing' ? 'running' as const : doc.status === 'cancelling' ? 'cancelling' as const : 'waiting' as const,
          progress: doc.progress ?? 0,
          stageLabel: doc.stage_label,
          stageCurrent: doc.stage_current,
          stageTotal: doc.stage_total,
          queuedAt: new Date().toISOString(),
          message: doc.message || (doc.status === 'processing' ? message : undefined),
        })
      }
    }

    graphQueue.value = [...queueMap.values()]
    graphQueuePlannedTotal = docs.filter((d) => d.status === 'pending' || d.status === 'processing' || d.status === 'done').length
  }

  function graphStatusFromGraphDoc(doc: GraphDocStatus): GraphStatus {
    if (doc.status === 'done' || doc.status === 'skipped') {
      return 'graphed'
    }
    return 'dirty'
  }

  function updateTreeNodeGraphStatus(path: string, status: GraphStatus) {
    const normalizedPath = normalizeTreePath(path)
    if (!normalizedPath) {
      return
    }
    const visit = (nodes: KnowledgeFileNode[]): KnowledgeFileNode[] => nodes.map((node) => {
      const nodePath = normalizeTreePath(node.path)
      if (nodePath === normalizedPath) {
        return { ...node, graphStatus: node.indexStatus === 'ignored' ? 'ignored' : status }
      }
      if (node.children && normalizedPath.startsWith(`${nodePath}/`)) {
        return { ...node, children: visit(node.children) }
      }
      return node
    })
    tree.value = visit(tree.value)
  }

  async function pollGraphStatus() {
    const userId = useSettingsStore().profile.userId
    if (!userId) return
    try {
      const status = await getKnowledgeGraphStatus(userId)
      const docs = status.docs ?? []
      graphProgressDetail.value = status.message || '正在抽取知识图谱'
      graphProgressStats.value = { current: status.current, total: status.total }
      if (docs.length > 0) {
        syncGraphQueueFromDocs(docs, status.message)
      }
      if (status.status === 'running' || status.status === 'idle') {
        if (docs.length > 0) {
          setGraphProgress(calculateGraphProgress(docs, status.total))
        }
        return
      }
      if (status.status === 'completed') {
        setGraphProgress(100)
        completeGraphQueue('finished', status.total, status.current, status.message || '图谱抽取完成')
        return
      }
      if (status.status === 'cancelled') {
        setGraphProgress(100)
        completeGraphQueue('cancelled', status.total, status.current, status.message || '图谱抽取已中止')
        return
      }
      if (status.status === 'failed') {
        completeGraphQueue('failed', status.total, status.current, status.message || '图谱抽取失败')
      }
    } catch {
      stopGraphPolling()
      graphQueue.value = []
      graphQueuePlannedTotal = 0
      finishGraphProgress('轮询图谱状态失败', true)
    }
  }

  function startGraphPolling() {
    stopGraphPolling()
    void pollGraphStatus()
    graphPollingTimer = setInterval(pollGraphStatus, 500)
  }

  async function _triggerGraphExtraction(targetPath?: string, force = false) {
    const userId = useSettingsStore().profile.userId
    if (!userId) {
      return false
    }
    if (!graphProgressVisible.value || graphProgressTimer !== null) {
      beginGraphProgress(0)
      graphQueuePlannedTotal = 0
    }
    try {
      await rebuildKnowledgeGraph(userId, targetPath, force)
      if (graphPollingTimer === null) startGraphPolling()
      return true
    } catch (error) {
      graphRebuildPending.value = false
      showToast(error instanceof Error ? error.message : '图谱任务入队失败', 5000)
      return false
    }
  }

  async function startGraphRebuild() {
    const userId = useSettingsStore().profile.userId
    if (!userId) {
      return
    }
    graphRebuildPending.value = true
    try {
      await loadKnowledgeTree()
      const sources = flattenGraphSourceNodes(tree.value)
      const ingestionTargets = sources.filter((node) => graphIngestionTargets(node).length > 0)
      const readyTargets = sources.filter((node) => !ingestionTargets.includes(node))
      showToast('已启动逐文件灌库与图谱抽取流水线')
      await Promise.all(readyTargets.map((node) => _triggerGraphExtraction(node.path, false)))
      void runIngestionJobs(ingestionTargets, true)
    } finally {
      graphRebuildPending.value = false
    }
  }

  async function extractGraphForNode(node: KnowledgeFileNode) {
    const userId = useSettingsStore().profile.userId
    if (!userId) {
      return
    }
    const force = shouldForceGraphExtraction(node)
    const sources = flattenGraphSourceNodes([node])
    const ingestionTargets = sources.filter((item) => graphIngestionTargets(item).length > 0)
    if (ingestionTargets.length > 0) {
      showToast(node.isDir ? '文件夹逐文件灌库并抽取图谱' : '文件灌库后立即抽取图谱')
      void runIngestionJobs(ingestionTargets, true)
    }
    await Promise.all(
      sources
        .filter((item) => !ingestionTargets.includes(item))
        .map((target) => _triggerGraphExtraction(target.path, force)),
    )
  }

  async function extractGraphForNodes(nodes: KnowledgeFileNode[]) {
    const targets = pruneNestedNodes(nodes)
    if (targets.length === 0) {
      return
    }
    if (targets.length === 1) {
      const target = targets[0]
      if (target) {
        await extractGraphForNode(target)
      }
      return
    }
    const sources = flattenGraphSourceNodes(targets)
    const ingestionTargets = sources.filter((node) => graphIngestionTargets(node).length > 0)
    if (ingestionTargets.length > 0) {
      showToast('选中文件逐个灌库并抽取图谱')
      void runIngestionJobs(ingestionTargets, true)
    }
    await Promise.all(
      sources
        .filter((item) => !ingestionTargets.includes(item))
        .map((node) => _triggerGraphExtraction(node.path, shouldForceGraphExtraction(node))),
    )
  }

  function clearGraphHistory() {
    graphHistory.value = []
    try { localStorage.removeItem(GRAPH_HISTORY_KEY) } catch { /* ignore */ }
  }

  /** Toast notification message (empty = hidden). */
  const toastMessage = ref('')
  const toastVisible = ref(false)
  let toastTimer: ReturnType<typeof setTimeout> | null = null

  /** File-tree multi-selection set used by click, Shift-click, and Ctrl-click. */
  const selectedTreePaths = ref<Set<string>>(new Set())

  /** Last focused tree path used as the range anchor for Shift-click. */
  const selectionAnchorPath = ref('')

  /** Pending copy/cut operation for context-menu paste and keyboard paste. */
  const fileClipboard = ref<{ mode: 'copy' | 'cut'; nodes: KnowledgeFileNode[] } | null>(null)

  /**
   * Conflict resolution dialog state.
   *
   * When importing files that have name collisions at the target directory,
   * this dialog asks the user to pick a strategy: overwrite, skip, or rename.
   * The resolve callback is stored so the promptConflictStrategy Promise can
   * be settled from the template's button click handlers.
   */
  const conflictDialog = ref<{
    open: boolean
    owner: FileConflictDialogOwner
    targetDir: string
    conflictingNames: string[]
    resolve: ((strategy: FileConflictStrategy | null) => void) | null
  }>({
    open: false,
    owner: 'tree',
    targetDir: '',
    conflictingNames: [],
    resolve: null,
  })

  /** Whether the Agent sidebar is visible. Shared so child components can open it. */
  const agentSidebarOpen = ref(true)

  /** Whether the Todo sidebar section is visible within the agent column. */
  const todoSidebarOpen = ref(false)

  /** 由子组件设置的待发送 Agent 消息,AgentPanel 消费后清空。 */
  const pendingAgentPrompt = ref('')

  /** 用户引用的文本,AgentPanel 消费后清空,由 SelectionToolbar 设置。 */
  const pendingAgentReference = ref('')

  /** Runtime HTML generated by the Agent document visualization tool. */
  const markdownHtmlVisualization = ref<MarkdownHtmlVisualizationPayload | null>(null)
  const markdownHtmlVisualizationOpen = ref(false)
  const markdownHtmlVisualizationMode = ref<MarkdownHtmlVisualizationMode>('structure')
  const markdownHtmlVisualizationPreset = ref<MarkdownHtmlVisualizationPreset>('balanced')
  const markdownHtmlVisualizationCustomRequirement = ref('')
  const markdownHtmlVisualizationOptions = ref<MarkdownHtmlVisualizationOptions>({
    strongMotion: false,
    shadow: false,
    rounded: false,
    emoji: false,
    visualHierarchy: true,
    gridLayout: true,
    callouts: true,
    denseLayout: false,
    typographyScale: true,
    contrast: true,
    accentColor: false,
    microInteractions: true,
    scrollReveal: false,
  })
  const markdownHtmlVisualizationUrl = computed(() => {
    const url = markdownHtmlVisualization.value?.url ?? ''
    if (!url) {
      return ''
    }
    return /^(https?:|file:|blob:)/u.test(url) ? url : buildApiUrl(url)
  })

  /** Search palette state. */
  const searchQuery = ref('')
  const searchResults = ref<UnifiedSearchResponse | null>(null)
  const searchOpen = ref(false)
  const searching = ref(false)
  const searchError = ref('')
  const fulltextEnabled = ref(true)
  const semanticEnabled = ref(false)
  const searchUnified = ref(true)
  const searchSources = ref<SearchSource[]>([...SEARCH_SOURCES])
  /** Non-file search resource rendered inside the reusable editor sidebar column. */
  const searchSidebarResult = ref<UnifiedSearchResult | null>(null)
  let searchRequestId = 0

  /** Search history (persisted to localStorage). */
  const SEARCH_HISTORY_KEY = 'metweave_search_history'
  const searchHistory = ref<string[]>([])
  try {
    const raw = localStorage.getItem(SEARCH_HISTORY_KEY)
    if (raw) searchHistory.value = JSON.parse(raw) as string[]
  } catch { /* ignore corrupt data */ }

  try {
    const raw = localStorage.getItem(INGESTION_HISTORY_KEY)
    if (raw) ingestionHistory.value = normalizeStoredIngestionHistory(JSON.parse(raw) as IngestionHistoryItem[])
  } catch { /* ignore corrupt data */ }

  function addSearchHistory(query: string) {
    const trimmed = query.trim()
    if (!trimmed) return
    searchHistory.value = [trimmed, ...searchHistory.value.filter((q) => q !== trimmed)].slice(0, 20)
    try { localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(searchHistory.value)) } catch { /* ignore */ }
  }

  function clearSearchHistory() {
    searchHistory.value = []
    try { localStorage.removeItem(SEARCH_HISTORY_KEY) } catch { /* ignore */ }
  }

  let currentDocumentContextTimer: number | null = null

  function setIngestionProgress(value: number) {
    ingestionProgress.value = normalizeProgress(value)
  }

  function persistIngestionHistory() {
    try {
      localStorage.setItem(INGESTION_HISTORY_KEY, JSON.stringify(ingestionHistory.value))
    } catch { /* ignore storage failures */ }
  }

  function normalizeStoredIngestionHistory(rows: IngestionHistoryItem[]): IngestionHistoryItem[] {
    const groups = new Map<string, number>()
    rows.forEach((row) => {
      const key = `${row.finishedAt}:${row.filesSeen ?? ''}:${row.filesIngested ?? ''}:${row.filesSkipped ?? ''}:${row.chunksCreated ?? ''}`
      groups.set(key, (groups.get(key) ?? 0) + 1)
    })
    return rows.map((row) => {
      const key = `${row.finishedAt}:${row.filesSeen ?? ''}:${row.filesIngested ?? ''}:${row.filesSkipped ?? ''}:${row.chunksCreated ?? ''}`
      if (row.chunksCreated !== undefined && (row.filesSeen ?? 0) > 1 && (groups.get(key) ?? 0) > 1) {
        return {
          ...row,
          chunksCreated: undefined,
          message: row.message?.startsWith('已生成 ') ? undefined : row.message,
        }
      }
      if ((row.filesSeen ?? 0) > 1 && row.message?.startsWith('已生成 ')) {
        return { ...row, message: undefined }
      }
      return row
    })
  }

  function nodeToQueueItem(node: KnowledgeFileNode, status: IngestionQueueItem['status'], index: number): IngestionQueueItem {
    return {
      id: `${node.path}:${Date.now().toString(36)}:${index}`,
      name: node.name,
      path: node.path,
      isDir: node.isDir,
      size: node.size,
      mtime: node.mtime,
      status,
      progress: status === 'running' ? ingestionProgress.value : 0,
      queuedAt: new Date().toISOString(),
    }
  }

  function beginIngestionQueue(nodes: KnowledgeFileNode[], fallback?: KnowledgeFileNode) {
    const sourceNodes = nodes.length > 0 ? nodes : (fallback ? [fallback] : [])
    completedIngestionQueueItems = []
    lastIngestionQueueProcessed = 0
    ingestionQueuePlannedTotal = sourceNodes.length
    ingestionFileChunksByPath = new Map()
    ingestionQueue.value = sourceNodes.map((node, index) => nodeToQueueItem(node, index === 0 ? 'running' : 'queued', index))
    sourceNodes.forEach((node) => updateTreeNodeIndexStatus(node.path, 'indexing', { force: true }))
    setIngestionProgressFromQueue()
  }

  function findFlatNode(path: string): KnowledgeFileNode | undefined {
    const normalizedPath = normalizeTreePath(path)
    return flatNodes.value.find((node) => normalizeTreePath(node.path) === normalizedPath)
  }

  function shouldApplyIndexEventToTree(path: string): boolean {
    const normalizedPath = normalizeTreePath(path)
    if (!normalizedPath) {
      return false
    }
    const activeQueueHasPath = ingestionQueue.value.some((item) => normalizeTreePath(item.path) === normalizedPath)
    const completedQueueHasPath = completedIngestionQueueItems.some((item) => normalizeTreePath(item.path) === normalizedPath)
    if (activeQueueHasPath || completedQueueHasPath) {
      return true
    }
    const node = findFlatNode(normalizedPath)
    return !node?.indexStatus || ['dirty', 'failed', 'indexing'].includes(node.indexStatus)
  }

  function updateTreeNodeIndexStatus(path: string, status: IndexStatus, options: { force?: boolean } = {}) {
    const normalizedPath = normalizeTreePath(path)
    if (!normalizedPath || (!options.force && !shouldApplyIndexEventToTree(normalizedPath))) {
      return
    }
    const visit = (nodes: KnowledgeFileNode[]): KnowledgeFileNode[] => nodes.map((node) => {
      const nodePath = normalizeTreePath(node.path)
      if (nodePath === normalizedPath) {
        return { ...node, indexStatus: status }
      }
      if (node.children && normalizedPath.startsWith(`${nodePath}/`)) {
        return { ...node, children: visit(node.children) }
      }
      return node
    })
    tree.value = visit(tree.value)
  }

  function indexStatusFromIngestionEvent(event: KnowledgeIngestionProgressEvent): IndexStatus | null {
    const status = String(event.status ?? '')
    const message = String(event.message ?? '').toLowerCase()
    if (status === 'failed') {
      return 'failed'
    }
    if (status === 'started' || event.phase === 'frontmatter') {
      return 'indexing'
    }
    if (event.phase !== 'ingestion') {
      return null
    }
    if (status === 'ingested') {
      return 'indexed'
    }
    if (status === 'skipped') {
      return message.includes('ignored') || message.includes('unsupported') ? 'ignored' : 'indexed'
    }
    return null
  }

  function updateTreeIndexStatusFromEvent(event: KnowledgeIngestionProgressEvent) {
    const path = normalizeTreePath(String(event.path ?? ''))
    const status = indexStatusFromIngestionEvent(event)
    if (!path || !status) {
      return
    }
    updateTreeNodeIndexStatus(path, status)
  }

  function setIngestionProgressFromQueue() {
    const total = Math.max(0, ingestionQueuePlannedTotal)
    if (total <= 0) {
      setIngestionProgress(0)
      return
    }
    const completed = Math.min(total, completedIngestionQueueItems.length)
    setIngestionProgress((completed / total) * 100)
    setIngestionProgressStats(completed, total, Math.max(0, total - completed - ingestionQueue.value.length))
  }

  function syncIngestionQueueProgress(processed: number, total: number) {
    if (ingestionQueue.value.length === 0) {
      return
    }
    const deltaProcessed = Math.max(0, processed - lastIngestionQueueProcessed)
    lastIngestionQueueProcessed = Math.max(lastIngestionQueueProcessed, processed)
    const rowsToDequeue = Math.max(0, Math.min(deltaProcessed, ingestionQueue.value.length))
    if (rowsToDequeue > 0) {
      completedIngestionQueueItems = [
        ...completedIngestionQueueItems,
        ...ingestionQueue.value.slice(0, rowsToDequeue).map((item) => ({
          ...item,
          chunksCreated: ingestionFileChunksByPath.get(normalizeTreePath(item.path)) ?? item.chunksCreated,
        })),
      ]
    }
    ingestionQueue.value = ingestionQueue.value
      .slice(rowsToDequeue)
      .map((item, index) => ({
        ...item,
        status: index === 0 ? 'running' : 'queued',
        progress: index === 0 ? normalizeProgress(Math.min(96, ((processed % Math.max(1, total)) / Math.max(1, total)) * 100)) : 0,
      }))
    setIngestionProgressFromQueue()
  }

  function updateIngestionQueueFromEvent(event: KnowledgeIngestionProgressEvent, progress: number) {
    const normalizedPath = normalizeTreePath(String(event.path ?? ''))
    if (!normalizedPath || ingestionQueue.value.length === 0) {
      syncIngestionQueueProgress(Math.max(0, Number(event.processed ?? 0)), Math.max(1, Number(event.total ?? 0)))
      return
    }
    const status = String(event.status ?? '')
    const isTerminal = event.phase === 'ingestion' && ['ingested', 'skipped', 'failed'].includes(status)
    if (isTerminal) {
      ingestionFileChunksByPath.set(normalizedPath, Number(event.file_chunks_created ?? 0))
    }
    const rowIndex = ingestionQueue.value.findIndex((item) => normalizeTreePath(item.path) === normalizedPath)
    if (rowIndex < 0) {
      if (isTerminal) {
        completedIngestionQueueItems = completedIngestionQueueItems.map((item) => {
          if (normalizeTreePath(item.path) !== normalizedPath) {
            return item
          }
          return {
            ...item,
            chunksCreated: ingestionFileChunksByPath.get(normalizedPath),
            message: event.message ?? item.message,
          }
        })
      }
      return
    }
    if (isTerminal) {
      const [completed] = ingestionQueue.value.slice(rowIndex, rowIndex + 1)
      if (completed) {
        completedIngestionQueueItems = [
          ...completedIngestionQueueItems,
          {
            ...completed,
            progress: 100,
            chunksCreated: ingestionFileChunksByPath.get(normalizedPath) ?? 0,
            message: event.message,
          },
        ]
      }
      const nextQueue = ingestionQueue.value.filter((_, index) => index !== rowIndex)
      ingestionQueue.value = nextQueue.map((item, index) => ({
        ...item,
        status: index === 0 ? 'running' : 'queued',
        progress: index === 0 ? progress : 0,
      }))
      setIngestionProgressFromQueue()
      return
    }
    ingestionQueue.value = ingestionQueue.value.map((item, index) => {
      if (index === rowIndex) {
        return {
          ...item,
          status: 'running',
          progress,
          message: event.message,
        }
      }
      return {
        ...item,
        status: item.status === 'running' && event.phase === 'ingestion' ? 'queued' : item.status,
      }
    })
  }

  function completeIngestionQueue(
    status: IngestionHistoryStatus,
    result?: {
      files_seen?: number
      files_ingested?: number
      files_skipped?: number
      chunks_created?: number
      status_message?: string
    },
    message?: string,
  ) {
    const finishedAt = new Date().toISOString()
    const rows = [...completedIngestionQueueItems, ...ingestionQueue.value]
    if (rows.length > 0) {
      const nextRows = rows.map<IngestionHistoryItem>((item) => ({
        id: createId('ingestion_history'),
        name: item.name,
        path: item.path,
        isDir: item.isDir,
        size: item.size,
        mtime: item.mtime,
        status,
        finishedAt,
        filesSeen: result?.files_seen,
        filesIngested: result?.files_ingested,
        filesSkipped: result?.files_skipped,
        chunksCreated: item.chunksCreated ?? ingestionFileChunksByPath.get(normalizeTreePath(item.path)) ?? (rows.length === 1 ? result?.chunks_created : undefined),
        message: item.message ?? (rows.length === 1 ? (message ?? result?.status_message) : undefined),
      }))
      ingestionHistory.value = [...nextRows, ...ingestionHistory.value].slice(0, INGESTION_HISTORY_LIMIT)
      persistIngestionHistory()
    }
    completedIngestionQueueItems = []
    lastIngestionQueueProcessed = 0
    ingestionQueuePlannedTotal = 0
    ingestionFileChunksByPath = new Map()
    ingestionQueue.value = []
  }

  function clearIngestionHistory() {
    ingestionHistory.value = []
    try { localStorage.removeItem(INGESTION_HISTORY_KEY) } catch { /* ignore */ }
  }

  function stopIngestionProgressPulse() {
    if (ingestionProgressPulseTimer !== null) {
      clearInterval(ingestionProgressPulseTimer)
      ingestionProgressPulseTimer = null
    }
  }

  function beginIngestionProgress(initialValue = 6) {
    if (ingestionProgressTimer !== null) {
      clearTimeout(ingestionProgressTimer)
      ingestionProgressTimer = null
    }
    stopIngestionProgressPulse()
    ingestionProgressVisible.value = true
    ingestionProgressDetail.value = '正在检查需要灌库的文件'
    ingestionProgressStats.value = { succeeded: 0, total: 0, failed: 0 }
    setIngestionProgress(initialValue)
  }

  function setIngestionProgressStats(succeeded: number, total: number, failed: number) {
    ingestionProgressStats.value = {
      succeeded: Math.max(0, succeeded),
      total: Math.max(0, total),
      failed: Math.max(0, failed),
    }
  }

  function applyIngestionProgressEvent(event: KnowledgeIngestionProgressEvent) {
    updateTreeIndexStatusFromEvent(event)
    if (event.type === 'done' && event.result) {
      setIngestionProgressFromQueue()
      return
    }
    const total = Math.max(1, Number(event.total ?? 0))
    const processed = Math.max(0, Math.min(total, Number(event.processed ?? 0)))
    const ratio = total > 0 ? processed / total : 0
    if (event.phase === 'frontmatter') {
      const progress = 8 + ratio * 34
      if (event.path) {
        updateIngestionQueueFromEvent(event, progress)
      }
      return
    }
    if (event.phase === 'ingestion') {
      const progress = 42 + ratio * 50
      updateIngestionQueueFromEvent(event, progress)
      return
    }
    if (event.phase === 'cleanup') {
      setIngestionProgressFromQueue()
      return
    }
    if (event.phase === 'graph') {
      setIngestionProgressFromQueue()
    }
  }

  function finishIngestionProgress(delay = 1000) {
    stopIngestionProgressPulse()
    setIngestionProgress(100)
    if (ingestionProgressTimer !== null) {
      clearTimeout(ingestionProgressTimer)
    }
    ingestionProgressTimer = setTimeout(() => {
      if (activeIngestionRuns > 0) {
        ingestionProgressTimer = null
        return
      }
      ingestionProgressVisible.value = false
      ingestionProgress.value = 0
      trackedIngestionJobIds.clear()
      graphRequestedIngestionJobIds.clear()
      ingestionProgressTimer = null
    }, delay)
  }

  const flatNodes = computed(() => flattenNodes(tree.value))

  const selectedNode = computed(() => flatNodes.value.find((node) => node.path === selectedPath.value))

  const activeContent = computed(() => contentByPath.value[selectedPath.value] ?? '')

  const activePreview = computed(() => previewByPath.value[selectedPath.value] ?? null)

  const activeViewerKind = computed<FileViewerKind>(() => activePreview.value?.kind ?? viewerKindForPath(selectedPath.value))

  const activeFileReadonly = computed(() => (
    Boolean(activePreview.value?.readonly)
    || !resolveEditorFilePipeline(selectedPath.value, activePreview.value?.kind).editable
  ))

  const activeTab = computed(() => openTabs.value.find((tab) => tab.path === selectedPath.value))

  const dirtyFilePaths = computed(() => new Set(openTabs.value.filter((tab) => tab.dirty).map((tab) => tab.path)))

  const hasDirtyTabs = computed(() => openTabs.value.some((tab) => tab.dirty))

  function activeDocumentContextNode(): KnowledgeFileNode | null {
    if (!selectedPath.value) {
      return null
    }
    return flatNodes.value.find((node) => node.path === selectedPath.value) ?? null
  }

  function syncCurrentDocumentContext() {
    if (currentDocumentContextTimer !== null) {
      window.clearTimeout(currentDocumentContextTimer)
      currentDocumentContextTimer = null
    }
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) {
      return
    }
    const node = activeDocumentContextNode()
    const tab = activeTab.value
    const library = settingsStore.activeKnowledgeLibrary
    void updateCurrentDocumentContext({
      user_id: settingsStore.profile.userId,
      path: selectedPath.value,
      name: node?.name ?? tab?.title ?? getBaseName(selectedPath.value),
      knowledge_dir: settingsStore.profile.knowledgeDir,
      library_id: library?.libraryId ?? settingsStore.profile.activeLibraryId,
      library_name: library?.name ?? '',
      size: node?.size,
      mtime: node?.mtime,
      dirty: Boolean(tab?.dirty),
      open_tab_count: openTabs.value.length,
      selected_paths: Array.from(selectedTreePaths.value),
    }).catch(() => {
      // Current-document context is a best-effort UI hint for Agent tools.
    })
  }

  function queueCurrentDocumentContextSync() {
    if (currentDocumentContextTimer !== null) {
      window.clearTimeout(currentDocumentContextTimer)
    }
    currentDocumentContextTimer = window.setTimeout(() => {
      currentDocumentContextTimer = null
      syncCurrentDocumentContext()
    }, 350)
  }

  const commands = computed<CommandAction[]>(() => [
    {
      id: 'toggle-theme',
      label: 'Toggle theme',
      shortcut: 'T',
      description: 'Switch between dark and light editor surfaces.',
    },
    {
      id: 'run-index',
      label: 'Run indexing',
      shortcut: 'I',
      description: 'Queue a mock re-index job for the current knowledge root.',
    },
    {
      id: 'open-settings',
      label: 'Open settings',
      shortcut: ',',
      description: 'Adjust knowledge root and watcher settings.',
    },
    {
      id: 'open-graph',
      label: 'Open graph',
      shortcut: 'G',
      description: 'Preview the future knowledge graph page.',
    },
  ])

  function toggleDirectory(path: string) {
    if (expandedPaths.value.has(path)) {
      expandedPaths.value.delete(path)
      return
    }
    expandedPaths.value.add(path)
  }

  function setTreeSelection(paths: string[], anchorPath = paths[paths.length - 1] ?? '') {
    selectedTreePaths.value = new Set(paths.map(normalizeTreePath).filter(Boolean))
    selectionAnchorPath.value = anchorPath
    treeSelectionCleared.value = false
    queueCurrentDocumentContextSync()
  }

  function clearTreeSelection() {
    selectedTreePaths.value = new Set()
    selectionAnchorPath.value = ''
    selectedTreePath.value = ''
    treeSelectionCleared.value = true
    queueCurrentDocumentContextSync()
  }

  function selectTreeNode(node: KnowledgeFileNode, options: { rangePaths?: string[]; additive?: boolean } = {}) {
    const path = normalizeTreePath(node.path)
    if (options.rangePaths && options.rangePaths.length > 0) {
      setTreeSelection(options.rangePaths, selectionAnchorPath.value || path)
      selectedTreePath.value = path
      queueCurrentDocumentContextSync()
      return
    }
    if (options.additive) {
      const next = new Set(selectedTreePaths.value)
      const currentPath = normalizeTreePath(selectedTreePath.value || selectedPath.value)
      if (next.size === 0 && currentPath) {
        next.add(currentPath)
      }
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      const nextPaths = Array.from(next)
      selectedTreePaths.value = next
      selectedTreePath.value = next.has(path) ? path : nextPaths[nextPaths.length - 1] ?? ''
      selectionAnchorPath.value = selectedTreePath.value
      treeSelectionCleared.value = next.size === 0
      queueCurrentDocumentContextSync()
      return
    }
    selectedTreePaths.value = new Set()
    selectionAnchorPath.value = path
    selectedTreePath.value = path
    treeSelectionCleared.value = false
    queueCurrentDocumentContextSync()
  }

  function getSelectedTreeNodes(fallbackNode?: KnowledgeFileNode | null): KnowledgeFileNode[] {
    const selected = flatNodes.value.filter((node) => selectedTreePaths.value.has(node.path))
    if (fallbackNode && selected.some((node) => node.path === fallbackNode.path)) {
      return selected
    }
    if (fallbackNode) {
      return [fallbackNode]
    }
    return selected
  }

  function pruneNestedNodes(nodes: KnowledgeFileNode[]): KnowledgeFileNode[] {
    return nodes.filter((node) => !nodes.some((candidate) => candidate.path !== node.path && isSameOrChildPath(node.path, candidate.path)))
  }

  async function selectFile(node: KnowledgeFileNode) {
    selectedTreePath.value = node.path
    treeSelectionCleared.value = false
    if (node.isDir) {
      return
    }
    selectedPath.value = node.path
    editorMode.value = defaultEditorMode(node.path, previewByPath.value[node.path]?.kind)
    recordRecentFileVisit(node.path)
    if (!openTabs.value.some((tab) => tab.path === node.path)) {
      openTabs.value.push({ path: node.path, title: node.name, dirty: false, mtime: node.mtime })
    }
    // Fire-and-forget: loads run in background so rapid file switching
    // never blocks the UI or exhausts the browser connection pool.
    if (shouldUsePreviewEndpoint(node.path)) {
      if (previewByPath.value[node.path] === undefined) {
        loadFilePreview(node.path)
      }
    } else if (contentByPath.value[node.path] === undefined) {
      loadFileContent(node.path)
    }
    queueCurrentDocumentContextSync()
  }

  function activateTab(path: string) {
    selectedPath.value = path
    selectedTreePath.value = path
    treeSelectionCleared.value = false
    editorMode.value = defaultEditorMode(path, previewByPath.value[path]?.kind)
    recordRecentFileVisit(path)
    syncCurrentDocumentContext()
  }

  function recentFileStorageKey(): string {
    const settingsStore = useSettingsStore()
    const root = encodeURIComponent(settingsStore.profile.knowledgeDir)
    return `metaweave_recent_files:${settingsStore.profile.userId}:${root}`
  }

  function loadRecentFileVisits() {
    const storageKey = recentFileStorageKey()
    if (storageKey === recentFileHistoryKey) return
    recentFileHistoryKey = storageKey
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) ?? '[]') as unknown
      recentFileVisits.value = Array.isArray(parsed)
        ? parsed.filter((visit): visit is RecentFileVisit => {
            if (!visit || typeof visit !== 'object') return false
            const candidate = visit as Partial<RecentFileVisit>
            return typeof candidate.path === 'string' && typeof candidate.lastViewedAt === 'string'
          })
        : []
    } catch {
      recentFileVisits.value = []
    }
  }

  function persistRecentFileVisits() {
    try {
      localStorage.setItem(recentFileStorageKey(), JSON.stringify(recentFileVisits.value))
    } catch {
      // Browsing history is optional when browser storage is unavailable.
    }
  }

  function recordRecentFileVisit(path: string) {
    loadRecentFileVisits()
    recentFileVisits.value = updateRecentFileVisits(recentFileVisits.value, path, new Date().toISOString())
    persistRecentFileVisits()
  }

  function closeTab(path: string) {
    const nextTabs = openTabs.value.filter((tab) => tab.path !== path)
    openTabs.value = nextTabs
    if (selectedPath.value !== path) {
      return
    }
    const fallback = nextTabs[0]
    selectedPath.value = fallback?.path ?? ''
    if (selectedTreePath.value === path) {
      selectedTreePath.value = fallback?.path ?? ''
    }
    syncCurrentDocumentContext()
  }

  function setEditorMode(mode: EditorWorkspaceMode) {
    editorMode.value = mode
  }

  function setMainView(view: WorkspaceMainView) {
    mainView.value = view
    if (view === 'editor') {
      editorSidebarOpen.value = false
      searchSidebarResult.value = null
    }
  }

  /** Select a real knowledge file and reveal it in the reusable editor sidebar. */
  async function openEditorSidebar(node: KnowledgeFileNode) {
    searchSidebarResult.value = null
    editorSidebarOpen.value = true
    await selectFile(node)
  }

  /** Open any search result in the existing draggable editor-sidebar column. */
  async function openSearchResultSidebar(result: UnifiedSearchResult) {
    if (result.source === 'files') {
      await openEditorSidebar(result.item as unknown as KnowledgeFileNode)
      return
    }
    searchSidebarResult.value = result
    editorSidebarOpen.value = true
    if (result.source === 'literature') {
      const entry = result.item as Record<string, unknown>
      const path = String(entry.asset_path || '')
      if (path) {
        await selectFile({
          name: String(entry.file_name || result.title),
          path,
          isDir: false,
          mtime: String(entry.updated_at || result.updated_at),
          size: Number(entry.file_size || 0),
        })
      }
    }
  }

  /** Open an Agent-mounted result in-place or hand it to its owning main library. */
  async function openAgentSearchResult(result: UnifiedSearchResult, compact: boolean): Promise<void> {
    if (!compact) {
      await openSearchResultSidebar(result)
      return
    }
    closeEditorSidebar()
    pendingMainSearchResult.value = null
    if (result.source === 'files') {
      const node = result.item as unknown as KnowledgeFileNode
      const liveNode = flatNodes.value.find((item) => item.path === node.path) ?? node
      setMainView('editor')
      await selectFile(liveNode)
      return
    }
    if (result.source === 'literature') {
      const item = result.item as Record<string, unknown>
      openLiteratureEntry(String(item.form_id || ''), String(item.row_id || ''))
      return
    }
    pendingMainSearchResult.value = result
    setMainView(result.source === 'library' ? 'library' : 'component-library')
  }

  /** Replace one edited result in place so watchers do not interpret the edit as a new search. */
  function updateSearchSidebarResult(result: UnifiedSearchResult) {
    searchSidebarResult.value = result
    const response = searchResults.value
    if (!response) return
    const resultIndex = response.results.findIndex((item) => item.source === result.source && item.id === result.id)
    if (resultIndex >= 0) response.results.splice(resultIndex, 1, result)
    const group = response.groups[result.source]
    const groupIndex = group.findIndex((item) => item.id === result.id)
    if (groupIndex >= 0) group.splice(groupIndex, 1, result)
  }

  /** Close the temporary editor sidebar while retaining the current file tab. */
  function closeEditorSidebar() {
    editorSidebarOpen.value = false
    searchSidebarResult.value = null
  }

  /** Open the half-width browser panel and optionally navigate its shared session. */
  function openBrowserSidebar(url = '') {
    const nextUrl = url.trim()
    if (nextUrl) {
      browserSidebarUrl.value = nextUrl
      browserSidebarNavigationId.value += 1
    }
    browserSidebarOpen.value = true
  }

  /** Close the temporary browser panel without discarding its Chromium session. */
  function closeBrowserSidebar() {
    browserSidebarOpen.value = false
  }

  /** Toggle the top-bar browser panel while retaining the last visited page. */
  function toggleBrowserSidebar() {
    browserSidebarOpen.value = !browserSidebarOpen.value
  }

  function openLibraryParent(parentId: string) {
    pendingLibraryParentId.value = parentId
    mainView.value = 'library'
  }

  /** Opens literature reading and records the exact smart-form row to select. */
  function openLiteratureEntry(formId: string, rowId: string): void {
    pendingLiteratureEntry.value = { formId, rowId }
    editorSidebarOpen.value = false
    mainView.value = 'literature-reading'
  }

  /** Returns and clears the pending row after the literature list has loaded. */
  function consumePendingLiteratureEntry(): { formId: string; rowId: string } | null {
    const target = pendingLiteratureEntry.value
    pendingLiteratureEntry.value = null
    return target
  }

  function updateActiveContent(content: string) {
    if (!selectedPath.value || activeFileReadonly.value) {
      return
    }
    contentByPath.value[selectedPath.value] = content
    const tab = openTabs.value.find((item) => item.path === selectedPath.value)
    if (tab) {
      tab.dirty = true
    }
    queueCurrentDocumentContextSync()
  }

  async function saveActiveFile() {
    const tab = activeTab.value
    if (!tab || !selectedPath.value || activeFileReadonly.value) {
      return
    }
    await saveFileByPath(tab.path)
  }

  async function saveFileByPath(path: string) {
    const tab = openTabs.value.find((item) => item.path === path)
    if (!tab || !resolveEditorFilePipeline(path, previewByPath.value[path]?.kind).editable) {
      return
    }
    const settingsStore = useSettingsStore()
    ignoreNextTreeEvent.value += 3
    await writeKnowledgeFile(settingsStore.profile.userId, path, contentByPath.value[path] ?? '')
    tab.dirty = false
    if (shouldUsePreviewEndpoint(path)) await loadFilePreview(path)
    await loadKnowledgeTree()
    // 文件内容已变更，重置索引状态和图谱状态为未入库
    updateTreeNodeIndexStatus(path, 'dirty', { force: true })
    updateTreeNodeGraphStatus(path, 'dirty')
    window.dispatchEvent(new CustomEvent('metaweave-knowledge-file-change', { detail: { path } }))
    const savedNode = flatNodes.value.find((n) => n.path === path)
    if (savedNode?.mtime) tab.mtime = savedNode.mtime
    if (path === selectedPath.value) {
      syncCurrentDocumentContext()
    }
  }

  async function saveAllDirtyFiles() {
    const dirtyPaths = openTabs.value.filter((tab) => tab.dirty).map((tab) => tab.path)
    for (const path of dirtyPaths) {
      await saveFileByPath(path)
    }
  }

  async function confirmSaveDirtyBeforeExit() {
    if (!hasDirtyTabs.value) {
      return true
    }
    const shouldSave = window.confirm('还有未保存的文件。是否保存所有文件后退出？')
    if (!shouldSave) {
      return false
    }
    await saveAllDirtyFiles()
    return true
  }

  function basenameOfPath(path: string): string {
    return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? path
  }

  function childNamesInDirectory(targetDirPath: string): Set<string> {
    const targetDir = normalizeTreePath(targetDirPath)
    return new Set(
      flatNodes.value
        .filter((node) => getParentPath(node.path) === targetDir)
        .map((node) => node.name),
    )
  }

  function hasNameConflict(targetDirPath: string, names: string[]): boolean {
    const existingNames = childNamesInDirectory(targetDirPath)
    return names.some((name) => existingNames.has(name))
  }

  /**
   * Checks whether ANY of the given names already exist in the target dir.
   * If no conflict, returns immediately with 'overwrite' (no dialog needed).
   * On conflict it opens the conflict dialog and returns a Promise that
   * resolves with the user's choice when they click a button.
   *
   * The resolve callback is stored in conflictDialog.value.resolve so the
   * FileTreePanel dialog template can settle it via resolveConflict().
   */
  function promptConflictStrategy(
    targetDirPath: string,
    names: string[],
    owner: FileConflictDialogOwner = 'tree',
  ): Promise<FileConflictStrategy | null> {
    return new Promise((resolve) => {
      const targetDir = normalizeTreePath(targetDirPath)
      if (!hasNameConflict(targetDir, names)) {
        resolve('overwrite')
        return
      }
      const existingNames = childNamesInDirectory(targetDir)
      const conflictingNames = names.filter((name) => existingNames.has(name))
      conflictDialog.value = {
        open: true,
        owner,
        targetDir,
        conflictingNames,
        resolve,
      }
    })
  }

  /** Called by the conflict dialog's "覆盖" button. */
  function resolveConflict(strategy: FileConflictStrategy) {
    const resolve = conflictDialog.value.resolve
    conflictDialog.value = {
      open: false,
      owner: 'tree',
      targetDir: '',
      conflictingNames: [],
      resolve: null,
    }
    resolve?.(strategy)
  }

  /** Called by the conflict dialog's "取消" / backdrop click. */
  function cancelConflict() {
    const resolve = conflictDialog.value.resolve
    conflictDialog.value = {
      open: false,
      owner: 'tree',
      targetDir: '',
      conflictingNames: [],
      resolve: null,
    }
    resolve?.(null)
  }

  async function importFilesToPath(
    files: File[],
    targetDirPath = '',
    conflictStrategy?: FileConflictStrategy,
    conflictOwner: FileConflictDialogOwner = 'tree',
  ) {
    const targetPath = normalizeTreePath(targetDirPath)
    let importedFiles = files.filter((file) => file.name)
    if (importedFiles.length === 0) {
      return
    }
    const strategy = conflictStrategy
      ?? await promptConflictStrategy(targetPath, importedFiles.map((file) => file.name), conflictOwner)
    if (!strategy) {
      return
    }
    if (strategy === 'skip') {
      const existingNames = childNamesInDirectory(targetPath)
      importedFiles = importedFiles.filter((file) => !existingNames.has(file.name))
      if (importedFiles.length === 0) {
        showToast('已跳过 — 所有选中文件已存在')
        return
      }
    }
    const existingNames = strategy === 'overwrite' ? childNamesInDirectory(targetPath) : new Set<string>()
    const settingsStore = useSettingsStore()
    ignoreNextTreeEvent.value += 3
    const uploaded: string[] = []
    const failed: string[] = []
    if (settingsStore.profile.autoIngestOnUpload) {
      beginIngestionProgress(12)
      beginIngestionQueue(importedFiles.map((file) => createImportedFileNode(joinTreePath(targetPath, file.name), file)))
    }
    try {
      for (const [index, file] of importedFiles.entries()) {
        try {
          // When overwriting, delete existing file first so the backend
          // cleans up its vector-library entries before the new copy lands.
          if (strategy === 'overwrite' && existingNames.has(file.name)) {
            const existingPath = joinTreePath(targetPath, file.name)
            ignoreNextTreeEvent.value += 1
            await deleteKnowledgePath(settingsStore.profile.userId, existingPath)
          }
          await uploadKnowledgeFile(
            settingsStore.profile.userId,
            file,
            targetPath,
            Boolean(settingsStore.profile.autoIngestOnUpload),
            strategy,
          )
          uploaded.push(file.name)
        } catch {
          failed.push(file.name)
        } finally {
          if (settingsStore.profile.autoIngestOnUpload) {
            syncIngestionQueueProgress(index + 1, importedFiles.length)
          }
        }
      }
      await loadKnowledgeTree()
      selectedTreePath.value = targetPath
      syncCurrentDocumentContext()
      if (settingsStore.profile.autoIngestOnUpload) {
        completeIngestionQueue(
          failed.length > 0 ? 'failed' : 'finished',
          {
            files_seen: importedFiles.length,
            files_ingested: uploaded.length,
            files_skipped: failed.length,
          },
          failed.length > 0 ? `导入失败 ${failed.length} 个文件` : '上传后自动灌库完成',
        )
        finishIngestionProgress()
      }
      if (failed.length === 0 && uploaded.length > 0) {
        const suffix = settingsStore.profile.autoIngestOnUpload ? '并已灌库' : ''
        showToast(`已导入 ${uploaded.length} 个文件${suffix}`)
      } else if (failed.length > 0 && uploaded.length > 0) {
        showToast(`已导入 ${uploaded.length} 个, 跳过 ${failed.length} 个`)
      } else if (failed.length > 0) {
        showToast(`导入失败 ${failed.length} 个文件`)
      }
    } catch (error) {
      if (settingsStore.profile.autoIngestOnUpload) {
        const message = error instanceof Error ? error.message : '请检查连接'
        completeIngestionQueue('failed', undefined, message)
        finishIngestionProgress()
      }
      const message = error instanceof Error ? error.message : '请检查连接'
      showToast(`导入失败 — ${message}`)
    }
  }

  async function importExternalPathsToPath(
    paths: string[],
    targetDirPath = '',
    conflictStrategy?: FileConflictStrategy,
    conflictOwner: FileConflictDialogOwner = 'tree',
  ) {
    const desktop = window.agentEditorDesktop
    if (!desktop?.copyExternalPathsIntoDirectory) {
      return
    }
    const sourcePaths = paths.map((item) => item.trim()).filter(Boolean)
    if (sourcePaths.length === 0) {
      return
    }
    const targetPath = normalizeTreePath(targetDirPath)
    const strategy = conflictStrategy
      ?? await promptConflictStrategy(targetPath, sourcePaths.map(basenameOfPath), conflictOwner)
    if (!strategy) {
      return
    }
    const effectivePaths = strategy === 'skip'
      ? sourcePaths.filter((item) => !childNamesInDirectory(targetPath).has(basenameOfPath(item)))
      : sourcePaths
    if (effectivePaths.length === 0) {
      showToast('已跳过 — 所有选中文件已存在')
      return
    }
    // When overwriting, delete existing files via backend first so
    // the vector-library entries are cleaned up before the new copy lands.
    if (strategy === 'overwrite') {
      const settingsStore = useSettingsStore()
      const existingNames = childNamesInDirectory(targetPath)
      for (const item of effectivePaths) {
        const name = basenameOfPath(item)
        if (existingNames.has(name)) {
          const existingPath = joinTreePath(targetPath, name)
          ignoreNextTreeEvent.value += 1
          await deleteKnowledgePath(settingsStore.profile.userId, existingPath).catch(() => {})
        }
      }
    }
    const targetAbsoluteDir = buildAbsoluteKnowledgePath(useSettingsStore().profile.knowledgeDir, targetPath)
    ignoreNextTreeEvent.value += effectivePaths.length
    try {
      const result = await desktop.copyExternalPathsIntoDirectory(effectivePaths, targetAbsoluteDir, 'copy', strategy)
      await loadKnowledgeTree()
      if (result.paths.length > 0) {
        const root = useSettingsStore().profile.knowledgeDir.replace(/[\\/]+$/g, '')
        const relativePaths = result.paths.map((path) => normalizeTreePath(path.replace(root, '')))
        setTreeSelection(relativePaths, relativePaths[relativePaths.length - 1] ?? '')
        showToast(`已导入 ${result.paths.length} 项`)
      } else {
        showToast('导入已跳过')
      }
      syncCurrentDocumentContext()
    } catch (error) {
      const message = error instanceof Error ? error.message : '请检查连接'
      showToast(`导入失败 — ${message}`)
    }
  }

  async function scanKnowledgeRoot(files: File[]) {
    const nextTree: KnowledgeFileNode[] = []
    const nextContent: Record<string, string> = {}
    const nextExpandedPaths = new Set<string>()
    for (const file of files.filter((item) => item.name)) {
      const relativePath = stripRootFolder(getRelativeFilePath(file))
      if (!relativePath) {
        continue
      }
      upsertFileNode(nextTree, relativePath, file, nextExpandedPaths)
      nextContent[relativePath] = await readFilePreview(file)
    }
    tree.value = nextTree
    expandedPaths.value = nextExpandedPaths
    contentByPath.value = nextContent
    previewByPath.value = {}
    selectedPath.value = ''
    selectedTreePath.value = ''
    openTabs.value = []
    syncCurrentDocumentContext()
  }

  function openCommandPalette() {
    commandPaletteOpen.value = true
  }

  function closeCommandPalette() {
    commandPaletteOpen.value = false
  }

  function openSearch() {
    searchOpen.value = true
    searchQuery.value = ''
    searchResults.value = null
  }

  function closeSearch() {
    searchRequestId += 1
    searchOpen.value = false
    searchQuery.value = ''
    searchResults.value = null
  }

  async function performSearch(query: string) {
    const trimmed = query.trim()
    const requestId = ++searchRequestId
    if (!trimmed) {
      searchResults.value = null
      searchError.value = ''
      searching.value = false
      return
    }
    addSearchHistory(trimmed)
    searching.value = true
    searchError.value = ''
    try {
      const settingsStore = useSettingsStore()
      const response = await searchAllLibraries(
        settingsStore.profile.userId,
        trimmed,
        searchSources.value,
        fulltextEnabled.value,
        semanticEnabled.value,
      )
      if (requestId === searchRequestId) searchResults.value = response
    } catch (error: unknown) {
      if (requestId === searchRequestId) {
        searchResults.value = null
        searchError.value = error instanceof ApiError ? error.message : '搜索失败，请稍后重试'
      }
    } finally {
      if (requestId === searchRequestId) searching.value = false
    }
  }

  /** Toggle one library filter while ensuring at least one source remains active. */
  function toggleSearchSource(source: SearchSource) {
    if (searchSources.value.includes(source)) {
      if (searchSources.value.length === 1) return
      searchSources.value = searchSources.value.filter((item) => item !== source)
    } else {
      searchSources.value = SEARCH_SOURCES.filter((item) => (
        item === source || searchSources.value.includes(item)
      ))
    }
    if (searchQuery.value.trim()) {
      void performSearch(searchQuery.value)
    }
  }

  let _searchTimer: ReturnType<typeof setTimeout> | null = null
  watch(searchQuery, (value) => {
    if (_searchTimer !== null) {
      clearTimeout(_searchTimer)
    }
    _searchTimer = setTimeout(() => {
      _searchTimer = null
      performSearch(value)
    }, 300)
  })

  function askAgent(content: string) {
    const trimmed = content.trim()
    if (!trimmed) {
      return
    }
    chatMessages.value.push({
      id: createId('user'),
      role: 'user',
      content: trimmed,
      sourcePath: selectedPath.value,
    })
    chatMessages.value.push({
      id: createId('assistant'),
      role: 'assistant',
      content: `Mock response scoped to ${selectedPath.value || 'the whole knowledge base'}. Backend Agent streaming will replace this placeholder.`,
      sourcePath: selectedPath.value,
    })
  }

  function ingestionJobToQueueItem(job: KnowledgeIngestionJob): IngestionQueueItem {
    return {
      id: job.job_id,
      jobId: job.job_id,
      name: job.name,
      path: job.path,
      isDir: false,
      size: job.size,
      mtime: job.mtime,
      status: job.status as IngestionQueueItem['status'],
      progress: job.progress,
      pipeline: job.pipeline,
      stage: job.stage,
      stageLabel: job.stage_label,
      stageCurrent: job.stage_current,
      stageTotal: job.stage_total,
      queuedAt: job.created_at,
      message: job.message || job.error,
    }
  }

  function syncPersistentIngestionJobs(jobs: KnowledgeIngestionJob[]) {
    const activeStatuses = new Set(['queued', 'running', 'cancelling'])
    const activeJobs = jobs.filter((job) => activeStatuses.has(job.status))
    const hadActiveJobs = ingestionQueue.value.length > 0
    activeJobs.forEach((job) => trackedIngestionJobIds.add(job.job_id))
    ingestionQueue.value = activeJobs.map(ingestionJobToQueueItem)
    const trackedBatch = jobs.filter((job) => trackedIngestionJobIds.has(job.job_id))
    const activeCutoff = activeJobs.reduce(
      (earliest, job) => !earliest || job.created_at < earliest ? job.created_at : earliest,
      '',
    )
    const currentBatch = trackedBatch.length > 0
      ? trackedBatch
      : (activeCutoff ? jobs.filter((job) => job.created_at >= activeCutoff) : [])
    if (activeJobs.length > 0 && !ingestionProgressVisible.value) beginIngestionProgress(0)
    ingestionQueuePlannedTotal = currentBatch.length
    const succeeded = currentBatch.filter((job) => job.status === 'finished').length
    const failed = currentBatch.filter((job) => ['failed', 'cancelled'].includes(job.status)).length
    const totalProgress = currentBatch.reduce(
      (sum, job) => sum + (['cancelled', 'finished', 'skipped', 'failed'].includes(job.status) ? 100 : job.progress),
      0,
    )
    setIngestionProgress(currentBatch.length ? totalProgress / currentBatch.length : 0)
    setIngestionProgressStats(succeeded, currentBatch.length, failed)
    const activeJob = activeJobs.find((job) => job.status === 'running' || job.status === 'cancelling') ?? activeJobs[0]
    const lastCancelled = currentBatch.find((job) => job.status === 'cancelled')
    if (activeJob) {
      const stageCount = activeJob.stage_total ? ` · ${activeJob.stage_current}/${activeJob.stage_total}` : ''
      ingestionProgressDetail.value = `${activeJob.name} · ${activeJob.stage_label || '等待灌库'}${stageCount}`
    } else if (lastCancelled) {
      ingestionProgressDetail.value = `${lastCancelled.name} · 已中止`
    } else if (currentBatch.length > 0) {
      ingestionProgressDetail.value = '灌库任务已结束'
    }
    jobs.forEach((job) => {
      if (activeStatuses.has(job.status)) updateTreeNodeIndexStatus(job.path, 'indexing', { force: true })
      else if (job.status === 'finished') updateTreeNodeIndexStatus(job.path, 'indexed', { force: true })
      else if (job.status === 'skipped') {
        const status = job.message.includes('source hash unchanged') ? 'indexed' : 'dirty'
        updateTreeNodeIndexStatus(job.path, status, { force: true })
      }
      else if (job.status === 'failed') updateTreeNodeIndexStatus(job.path, 'failed', { force: true })
      else if (job.status === 'cancelled') updateTreeNodeIndexStatus(job.path, 'dirty', { force: true })
    })
    const persistentHistory = jobs
      .filter((job) => !activeStatuses.has(job.status))
      .map((job): IngestionHistoryItem => ({
        id: job.job_id,
        name: job.name,
        path: job.path,
        isDir: false,
        size: job.size,
        mtime: job.mtime,
        status: job.status as IngestionHistoryStatus,
        finishedAt: job.finished_at || job.updated_at,
        message: job.message || job.error || job.stage_label,
        sourceType: 'ingestion',
      }))
    ingestionHistory.value = [
      ...persistentHistory,
      ...ingestionHistory.value.filter((row) => !row.id.startsWith('ingest_')),
    ].slice(0, 200)
    persistIngestionHistory()
    if (hadActiveJobs && activeJobs.length === 0 && activeIngestionRuns === 0) finishIngestionProgress()
  }

  async function loadIngestionJobs(): Promise<KnowledgeIngestionJob[]> {
    const userId = useSettingsStore().profile.userId
    if (!userId) return []
    const response = await listKnowledgeIngestionJobs(userId)
    syncPersistentIngestionJobs(response.jobs)
    return response.jobs
  }

  async function runIngestionJobs(nodes: KnowledgeFileNode[], extractGraphAfter = false) {
    if (nodes.length === 0) return
    const userId = useSettingsStore().profile.userId
    if (!userId) return
    activeIngestionRuns += 1
    refreshing.value = true
    if (!ingestionProgressVisible.value) beginIngestionProgress(0)
    try {
      const created = await createKnowledgeIngestionJobs(userId, nodes.map((node) => node.path))
      const targetIds = new Set(created.jobs.map((job) => job.job_id))
      created.jobs.forEach((job) => trackedIngestionJobIds.add(job.job_id))
      await loadIngestionJobs()
      while (true) {
        const jobs = await loadIngestionJobs()
        const targets = jobs.filter((job) => targetIds.has(job.job_id))
        if (extractGraphAfter) {
          for (const job of targets) {
            if (!['finished', 'skipped'].includes(job.status) || graphRequestedIngestionJobIds.has(job.job_id)) continue
            graphRequestedIngestionJobIds.add(job.job_id)
            const queued = await _triggerGraphExtraction(job.path, false)
            if (!queued) graphRequestedIngestionJobIds.delete(job.job_id)
          }
        }
        if (targets.length > 0 && targets.every((job) => ['cancelled', 'finished', 'skipped', 'failed'].includes(job.status))) {
          const finished = targets.filter((job) => job.status === 'finished').length
          const cancelled = targets.filter((job) => job.status === 'cancelled').length
          showToast(cancelled > 0 ? `灌库结束 — ${finished} 个完成，${cancelled} 个中止` : `灌库完成 — ${finished} 个文件已索引`)
          break
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250))
      }
      await loadKnowledgeTree()
    } catch (error) {
      const message = error instanceof Error ? error.message : '未知错误'
      showToast(`灌库失败 — ${message}`)
    } finally {
      activeIngestionRuns = Math.max(0, activeIngestionRuns - 1)
      refreshing.value = activeIngestionRuns > 0
      if (!refreshing.value) finishIngestionProgress()
    }
  }

  async function cancelIngestionJob(item: IngestionQueueItem) {
    const userId = useSettingsStore().profile.userId
    if (!userId || !item.jobId) return
    try {
      await cancelKnowledgeIngestionJob(userId, item.jobId)
      await loadIngestionJobs()
      showToast(`已中止 ${item.name}，文件保持未灌库状态`)
    } catch (error) {
      showToast(`中止失败 — ${error instanceof Error ? error.message : '未知错误'}`)
    }
  }

  async function cancelGraphTask(item: IngestionQueueItem) {
    const userId = useSettingsStore().profile.userId
    if (!userId) return
    graphQueue.value = graphQueue.value.map((row) => (
      row.path === item.path
        ? { ...row, status: 'cancelling', stageLabel: '正在中止图谱抽取', message: '已请求中止，正在等待当前步骤结束' }
        : row
    ))
    graphProgressDetail.value = `正在中止图谱任务：${item.name}`
    try {
      await cancelKnowledgeGraphTask(userId, item.path)
      await pollGraphStatus()
    } catch (error) {
      showToast(`中止失败 — ${error instanceof Error ? error.message : '未知错误'}`)
      await pollGraphStatus()
    }
  }

  async function markIndexing() {
    await loadKnowledgeTree()
    await runIngestionJobs(flattenIngestibleNodes(tree.value))
  }

  async function ingestFile(node: KnowledgeFileNode) {
    const targetNodes = node.isDir ? flattenIngestibleNodes([node]) : [node]
    await runIngestionJobs(targetNodes)
  }

  function setMarkdownHtmlVisualizationMode(mode: MarkdownHtmlVisualizationMode) {
    markdownHtmlVisualizationMode.value = mode
  }

  function setMarkdownHtmlVisualizationPreset(preset: MarkdownHtmlVisualizationPreset) {
    markdownHtmlVisualizationPreset.value = preset
  }

  function setMarkdownHtmlVisualizationOption(
    key: keyof MarkdownHtmlVisualizationOptions,
    value: boolean,
  ) {
    markdownHtmlVisualizationOptions.value = {
      ...markdownHtmlVisualizationOptions.value,
      [key]: value,
    }
  }

  function setMarkdownHtmlVisualizationCustomRequirement(value: string) {
    markdownHtmlVisualizationCustomRequirement.value = value
  }

  function showMarkdownHtmlVisualization(payload: MarkdownHtmlVisualizationPayload) {
    markdownHtmlVisualization.value = payload
    markdownHtmlVisualizationOpen.value = true
    mainView.value = 'visualization'
    showToast('HTML 可视化已生成')
  }

  function closeMarkdownHtmlVisualization() {
    markdownHtmlVisualizationOpen.value = false
    markdownHtmlVisualization.value = null
  }

  async function selectMarkdownHtmlVisualizationDocument(targetNode?: KnowledgeFileNode) {
    const node = targetNode ?? selectedNode.value
    if (!node || node.isDir) {
      showToast('请选择一个文档')
      return
    }
    await selectFile(node)
    closeMarkdownHtmlVisualization()
    mainView.value = 'visualization'
    agentSidebarOpen.value = false
    todoSidebarOpen.value = false
  }

  function buildMarkdownHtmlVisualizationPrompt(node: KnowledgeFileNode): string {
    const modeLine = markdownHtmlVisualizationMode.value === 'structure'
      ? '原结构模式: 严格保留并可视化文档原本的层级、章节、列表、表格和引用关系。不要额外扩展文档没有表达的知识。'
      : 'AI提炼模式: 先理解文档和相关知识，再重组为更清晰的知识页面，可以总结、归纳和补充必要的解释。'
    const presetEntries: Record<MarkdownHtmlVisualizationPreset, string> = {
      balanced: '均衡展示: 兼顾阅读、结构和视觉重点，适合大多数文档。',
      reader: '阅读导向: 优先长文可读性、稳定排版、清晰章节和低干扰视觉。',
      dashboard: '仪表盘导向: 优先摘要、指标、对比、分组和快速扫描。',
      magazine: '杂志导向: 优先强标题、叙事节奏、重点图文区和更鲜明的版面层次。',
    }
    const optionEntries: Array<[keyof MarkdownHtmlVisualizationOptions, string]> = [
      ['strongMotion', '强动效'],
      ['shadow', '阴影'],
      ['rounded', '圆角'],
      ['emoji', 'emoji'],
      ['visualHierarchy', '视觉层级'],
      ['gridLayout', '网格系统'],
      ['callouts', '重点标注'],
      ['denseLayout', '高信息密度'],
      ['typographyScale', '字体层级'],
      ['contrast', '对比度'],
      ['accentColor', '强调色'],
      ['microInteractions', '微交互'],
      ['scrollReveal', '滚动揭示'],
    ]
    const optionLines = optionEntries
      .map(([key, label]) => `- ${label}: ${markdownHtmlVisualizationOptions.value[key] ? '启用' : '禁用'}`)
      .join('\n')
    const customRequirement = markdownHtmlVisualizationCustomRequirement.value.trim()
    const preferredName = `${splitExtension(getBaseName(node.path)).stem || 'visualization'}.html`
    return [
      '请必须先调用 create_task_list 创建任务列表，并逐项完成后再结束。',
      '',
      `任务: 为当前文档生成 Markdown-HTML 可视化并展示。`,
      `当前文档路径: ${node.path}`,
      `当前文档名称: ${node.name}`,
      '',
      '执行要求:',
      '1. 先确认当前文档上下文；如果当前文档路径已经明确，直接按该路径读取，不要为了确认路径而额外列目录。',
      '2. 无论任何类型的知识库文档，获取内容都必须调用知识库读取工具；禁止用 run_terminal_command、Python 库、get_knowledge_file_url、download_file 或系统源文件路径自行解析知识库源文件。',
      '3. 所有支持的源文件统一用 read_knowledge_file 读取 `.mw/md` Markdown 中间层；尚未灌库或投影过期时，该工具会自动触发单文件灌库，再基于返回的 Markdown 生成 HTML。',
      '4. 只有在对应读取工具调用成功后，才能把“读取文档内容/确认上下文”类任务列表项标记为完成；工具失败时先重试正确 path 或说明失败，不要改走终端解析。',
      '5. 生成完整、可独立打开的 HTML。不要只给 Markdown，不要只描述方案。',
      `6. ${modeLine}`,
      '7. 生成结束后必须调用 show_markdown_html 工具，传入 title、source_path、filename 和完整 html，让前端自动挂载展示。',
      '',
      '高级生成配置:',
      `- 展示预设: ${presetEntries[markdownHtmlVisualizationPreset.value]}`,
      optionLines,
      ...(customRequirement ? ['', '自定义要求:', customRequirement] : []),
      '',
      `show_markdown_html 参数建议: source_path="${node.path}", filename="${preferredName}"。`,
    ].join('\n')
  }

  async function startMarkdownHtmlVisualization(targetNode?: KnowledgeFileNode) {
    const node = targetNode ?? selectedNode.value
    if (!node || node.isDir) {
      showToast('请选择一个文档后再可视化')
      return
    }
    if (refreshing.value) {
      showToast('已有灌库任务进行中，请稍后再试')
      return
    }
    await selectFile(node)
    if (activeTab.value?.path === node.path && activeTab.value.dirty && !activeFileReadonly.value) {
      await saveFileByPath(node.path)
    }
    await ingestFile(node)
    mainView.value = 'visualization'
    agentSidebarOpen.value = true
    todoSidebarOpen.value = false
    pendingAgentPrompt.value = buildMarkdownHtmlVisualizationPrompt(node)
    showToast('已提交可视化任务给 Agent')
  }

  async function saveMarkdownHtmlVisualizationToKnowledge() {
    const visualization = markdownHtmlVisualization.value
    const url = markdownHtmlVisualizationUrl.value
    if (!visualization || !url) {
      showToast('没有可保存的 HTML 可视化')
      return
    }
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) {
      showToast('缺少用户信息，无法保存')
      return
    }
    try {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const html = await response.text()
      const targetDirectory = `${settingsStore.profile.userId}_html`
      await createKnowledgeFolder(settingsStore.profile.userId, targetDirectory).catch(() => undefined)
      const targetPath = uniquePathInDirectory(targetDirectory, visualization.filename || 'visualization.html')
      ignoreNextTreeEvent.value += 1
      await writeKnowledgeFile(settingsStore.profile.userId, targetPath, html)
      await loadKnowledgeTree()
      showToast(`已保存到知识库: ${targetPath}`)
    } catch (error) {
      const message = error instanceof Error ? error.message : '未知错误'
      showToast(`保存 HTML 失败: ${message}`)
    }
  }

  async function revealMarkdownHtmlVisualization() {
    const visualization = markdownHtmlVisualization.value
    if (!visualization) {
      showToast('没有可定位的 HTML 可视化')
      return
    }
    if (window.agentEditorDesktop?.showItemInFolder && visualization.path) {
      await window.agentEditorDesktop.showItemInFolder(visualization.path)
      return
    }
    if (markdownHtmlVisualizationUrl.value) {
      window.open(markdownHtmlVisualizationUrl.value, '_blank', 'noopener,noreferrer')
    }
  }

  function showToast(message: string, duration = 3500) {
    toastMessage.value = message
    toastVisible.value = true
    if (toastTimer !== null) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toastVisible.value = false
      toastTimer = null
    }, duration)
  }

  async function createFileAt(parentDirPath = '', preferredName = 'untitled.md') {
    const settingsStore = useSettingsStore()
    const targetPath = uniquePathInDirectory(parentDirPath, preferredName)
    ignoreNextTreeEvent.value += 1
    await createKnowledgeFile(settingsStore.profile.userId, targetPath, '')
    contentByPath.value = { ...contentByPath.value, [targetPath]: '' }
    await loadKnowledgeTree()
    await selectFile({ name: getBaseName(targetPath), path: targetPath, isDir: false })
  }

  async function createFolderAt(parentDirPath = '', preferredName = 'New Folder') {
    const settingsStore = useSettingsStore()
    const targetPath = uniquePathInDirectory(parentDirPath, preferredName)
    ignoreNextTreeEvent.value += 1
    await createKnowledgeFolder(settingsStore.profile.userId, targetPath)
    await loadKnowledgeTree()
    expandedPaths.value.add(targetPath)
    selectedTreePath.value = targetPath
  }

  async function copyNode(node: KnowledgeFileNode) {
    const nodes = pruneNestedNodes(getSelectedTreeNodes(node))
    fileClipboard.value = { mode: 'copy', nodes }
    await copyNodesToSystemClipboard(nodes, 'copy')
  }

  async function cutNode(node: KnowledgeFileNode) {
    const nodes = pruneNestedNodes(getSelectedTreeNodes(node))
    fileClipboard.value = { mode: 'cut', nodes }
    await copyNodesToSystemClipboard(nodes, 'cut')
  }

  /**
   * Writes the absolute paths of selected tree nodes to the system clipboard.
   *
   * On Electron/Windows the main process writes a real FileDropList to the
   * native clipboard, which File Explorer recognises as file paths for paste.
   * When Electron is unavailable we fall back to writing plain text paths via
   * the Web Clipboard API.
   *
   * IMPORTANT: we must NOT call both APIs — the second call would overwrite
   * the formats set by the first, breaking external paste.
   */
  async function copyNodesToSystemClipboard(nodes: KnowledgeFileNode[], mode: 'copy' | 'cut') {
    const settingsStore = useSettingsStore()
    const absolutePaths = nodes.map((node) => buildAbsoluteKnowledgePath(settingsStore.profile.knowledgeDir, node.path))
    if (window.agentEditorDesktop?.copyFilePaths) {
      const copied = await window.agentEditorDesktop.copyFilePaths(absolutePaths, mode)
      if (!copied) {
        showToast('复制失败 — 无法写入系统文件剪贴板')
        return
      }
      showToast(mode === 'cut' ? `已剪切 ${absolutePaths.length} 项` : `已复制 ${absolutePaths.length} 项`)
      return
    }
    await navigator.clipboard?.writeText(absolutePaths.join('\n'))
    showToast(mode === 'cut' ? `已复制路径 ${absolutePaths.length} 项` : `已复制路径 ${absolutePaths.length} 项`)
  }

  async function pasteNode(targetNode?: KnowledgeFileNode | null, conflictOwner: FileConflictDialogOwner = 'tree') {
    const pending = fileClipboard.value
    if (!pending || pending.nodes.length === 0) {
      await pasteExternalClipboardPaths(targetNode, conflictOwner)
      return
    }
    const settingsStore = useSettingsStore()
    const targetDir = childDirectoryFor(targetNode)
    const reservedPaths = new Set(flatNodes.value.map((node) => node.path))
    let lastTargetPath = ''
    ignoreNextTreeEvent.value += pending.nodes.length
    for (const node of pending.nodes) {
      if (pending.mode === 'cut' && targetDir === getParentPath(node.path)) {
        continue
      }
      const targetPath = uniquePathInDirectoryWithReserved(targetDir, node.name, reservedPaths)
      reservedPaths.add(targetPath)
      if (pending.mode === 'copy') {
        await copyKnowledgePath(settingsStore.profile.userId, node.path, targetPath)
      } else {
        await renameKnowledgePath(settingsStore.profile.userId, node.path, targetPath)
        rewriteOpenPaths(node.path, targetPath)
      }
      lastTargetPath = targetPath
    }
    if (pending.mode === 'cut') {
      fileClipboard.value = null
    }
    await loadKnowledgeTree()
    if (lastTargetPath) {
      setTreeSelection([lastTargetPath], lastTargetPath)
      selectedTreePath.value = lastTargetPath
    }
    syncCurrentDocumentContext()
  }

  async function moveNodesToDirectory(nodes: KnowledgeFileNode[], targetNode?: KnowledgeFileNode | null) {
    const targetDir = childDirectoryFor(targetNode)
    const movableNodes = pruneNestedNodes(nodes).filter((node) => {
      if (targetDir === getParentPath(node.path)) {
        return false
      }
      return !node.isDir || !isSameOrChildPath(targetDir, node.path)
    })
    if (movableNodes.length === 0) {
      return
    }
    const settingsStore = useSettingsStore()
    const reservedPaths = new Set(flatNodes.value.map((node) => node.path))
    const movedPaths: string[] = []
    ignoreNextTreeEvent.value += movableNodes.length
    for (const node of movableNodes) {
      const targetPath = uniquePathInDirectoryWithReserved(targetDir, node.name, reservedPaths)
      reservedPaths.add(targetPath)
      await renameKnowledgePath(settingsStore.profile.userId, node.path, targetPath)
      rewriteOpenPaths(node.path, targetPath)
      movedPaths.push(targetPath)
    }
    await loadKnowledgeTree()
    setTreeSelection(movedPaths, movedPaths[movedPaths.length - 1] ?? '')
    syncCurrentDocumentContext()
  }

  async function pasteExternalClipboardPaths(
    targetNode?: KnowledgeFileNode | null,
    conflictOwner: FileConflictDialogOwner = 'tree',
  ) {
    const desktop = window.agentEditorDesktop
    if (!desktop?.copyExternalPathsIntoDirectory) {
      return
    }
    const clipboardFiles = desktop.readClipboardFiles
      ? await desktop.readClipboardFiles()
      : { mode: 'copy' as const, paths: await desktop.readClipboardFilePaths?.() ?? [] }
    const sourcePaths = clipboardFiles.paths
    if (sourcePaths.length === 0) {
      return
    }
    const targetDir = childDirectoryFor(targetNode)
    const targetAbsoluteDir = buildAbsoluteKnowledgePath(useSettingsStore().profile.knowledgeDir, targetDir)
    const strategy = await promptConflictStrategy(targetDir, sourcePaths.map(basenameOfPath), conflictOwner)
    if (!strategy) {
      return
    }
    const effectiveSourcePaths = strategy === 'skip'
      ? sourcePaths.filter((item) => !childNamesInDirectory(targetDir).has(basenameOfPath(item)))
      : sourcePaths
    if (effectiveSourcePaths.length === 0) {
      showToast('粘贴已跳过 — 所有文件已存在')
      return
    }
    // When overwriting, delete existing files via backend first so
    // the vector-library entries are cleaned up before the new copy.
    if (strategy === 'overwrite') {
      const settingsStore = useSettingsStore()
      const existingNames = childNamesInDirectory(targetDir)
      for (const item of effectiveSourcePaths) {
        const name = basenameOfPath(item)
        if (existingNames.has(name)) {
          const existingPath = joinTreePath(targetDir, name)
          ignoreNextTreeEvent.value += 1
          await deleteKnowledgePath(settingsStore.profile.userId, existingPath).catch(() => {})
        }
      }
    }
    ignoreNextTreeEvent.value += effectiveSourcePaths.length
    const result = await desktop.copyExternalPathsIntoDirectory(
      effectiveSourcePaths,
      targetAbsoluteDir,
      clipboardFiles.mode,
      strategy,
    )
    await loadKnowledgeTree()
    if (result.paths.length > 0) {
      const root = useSettingsStore().profile.knowledgeDir.replace(/[\\/]+$/g, '')
      const relativePaths = result.paths.map((path) => normalizeTreePath(path.replace(root, '')))
      setTreeSelection(relativePaths, relativePaths[relativePaths.length - 1] ?? '')
    }
    syncCurrentDocumentContext()
  }

  async function savePastedEditorImage(file: File): Promise<string> {
    const settingsStore = useSettingsStore()
    const activePath = selectedPath.value
    if (!settingsStore.profile.userId || !activePath || selectedNode.value?.isDir) {
      showToast('请选择可编辑文件后再粘贴图片')
      return ''
    }
    const configuredDir = normalizeEditorAssetDirectory(settingsStore.profile.editorImageAssetsDir)
    const targetDir = joinTreePath(getParentPath(activePath), configuredDir)
    const extension = extensionForImageMimeType(file.type || 'image/png')
    const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/u, '').replace('T', '-')
    const targetPath = uniquePathInDirectory(targetDir, `image-${timestamp}${extension}`)
    const filename = getBaseName(targetPath)
    const uploadFile = new File([file], filename, { type: file.type || 'image/png' })
    ignoreNextTreeEvent.value += 1
    await uploadKnowledgeFile(settingsStore.profile.userId, uploadFile, targetDir, false, 'overwrite')
    await loadKnowledgeTree()
    return `![](./${joinTreePath(configuredDir, filename)})`
  }

  async function renameNode(node: KnowledgeFileNode, nextName: string) {
    const normalizedName = normalizeTreePath(nextName)
    if (!normalizedName || normalizedName.includes('/')) {
      return
    }
    const targetPath = joinTreePath(getParentPath(node.path), normalizedName)
    if (targetPath === node.path) {
      return
    }
    const settingsStore = useSettingsStore()
    ignoreNextTreeEvent.value += 1
    await renameKnowledgePath(settingsStore.profile.userId, node.path, targetPath)
    rewriteOpenPaths(node.path, targetPath)
    await loadKnowledgeTree()
    selectedTreePath.value = targetPath
    syncCurrentDocumentContext()
  }

  async function deleteNode(node: KnowledgeFileNode) {
    const settingsStore = useSettingsStore()
    ignoreNextTreeEvent.value += 1
    try {
      await deleteKnowledgePath(settingsStore.profile.userId, node.path)
    } catch (err: unknown) {
      ignoreNextTreeEvent.value -= 1
      showToast(err instanceof ApiError ? err.message : '删除失败')
      await loadKnowledgeTree()
      return
    }
    openTabs.value = openTabs.value.filter((tab) => !isSameOrChildPath(tab.path, node.path))
    recentFileVisits.value = recentFileVisits.value.filter((visit) => !isSameOrChildPath(visit.path, node.path))
    persistRecentFileVisits()
    Object.keys(contentByPath.value).forEach((path) => {
      if (isSameOrChildPath(path, node.path)) {
        delete contentByPath.value[path]
      }
    })
    Object.keys(previewByPath.value).forEach((path) => {
      if (isSameOrChildPath(path, node.path)) {
        delete previewByPath.value[path]
      }
    })
    if (isSameOrChildPath(selectedPath.value, node.path)) {
      selectedPath.value = openTabs.value[0]?.path ?? ''
    }
    selectedTreePath.value = selectedPath.value
    await loadKnowledgeTree()
    await loadKnowledgeTrash()
    showToast('已移入最近删除')
    syncCurrentDocumentContext()
  }

  async function loadKnowledgeTree() {
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) {
      return
    }
    loadRecentFileVisits()
    treeLoading.value = true
    try {
      const response = await listKnowledgeFiles(settingsStore.profile.userId)
      tree.value = response.tree
      // 新加载的文件树默认保持全部文件夹折叠，由用户操作决定后续展开状态。
      expandedPaths.value = new Set()
      if (selectedPath.value && !flatNodes.value.some((node) => node.path === selectedPath.value)) {
        selectedPath.value = ''
        selectedTreePath.value = ''
        openTabs.value = []
      }
      syncCurrentDocumentContext()
    } finally {
      treeLoading.value = false
    }
  }

  async function loadKnowledgeTrash() {
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) {
      trashEntries.value = []
      return
    }
    trashLoading.value = true
    try {
      const response = await listKnowledgeTrash(settingsStore.profile.userId)
      trashEntries.value = response.entries
    } catch (err: unknown) {
      showToast(err instanceof ApiError ? err.message : '最近删除加载失败')
    } finally {
      trashLoading.value = false
    }
  }

  async function restoreTrashEntry(entry: KnowledgeTrashEntry) {
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) return
    ignoreNextTreeEvent.value += 1
    try {
      const result = await restoreKnowledgeTrashEntry(settingsStore.profile.userId, entry.trash_id)
      await loadKnowledgeTree()
      await loadKnowledgeTrash()
      selectedTreePath.value = result.restored_path
      setTreeSelection([result.restored_path], result.restored_path)
      showToast(result.artifacts_restored ? `已恢复 ${entry.name}` : `已恢复 ${entry.name}，但索引或图谱重建失败`)
    } catch (err: unknown) {
      ignoreNextTreeEvent.value -= 1
      showToast(err instanceof ApiError ? err.message : '恢复失败')
    }
  }

  async function deleteTrashEntry(entry: KnowledgeTrashEntry) {
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId) return
    try {
      await deleteKnowledgeTrashEntry(settingsStore.profile.userId, entry.trash_id)
      await loadKnowledgeTrash()
      showToast(`已彻底删除 ${entry.name}`)
    } catch (err: unknown) {
      showToast(err instanceof ApiError ? err.message : '彻底删除失败')
    }
  }

  async function loadFileContent(path: string): Promise<void> {
    if (_pendingContentLoads.has(path)) return
    _pendingContentLoads.add(path)
    isFileLoading.value = true
    // Abort previous content fetch — user switched to a different file.
    _contentAbort?.abort()
    const controller = new AbortController()
    _contentAbort = controller
    let timedOut = false
    const timeoutTimer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 8_000)
    try {
      const settingsStore = useSettingsStore()
      const response = await readKnowledgeFile(settingsStore.profile.userId, path, controller.signal)
      // Stale guard: if user switched away while this request was in-flight, skip.
      if (selectedPath.value !== path) return
      contentByPath.value = { ...contentByPath.value, [path]: response.content }
      const nextPreview = { ...previewByPath.value }
      delete nextPreview[path]
      previewByPath.value = nextPreview
      const tab = openTabs.value.find((t) => t.path === path)
      if (tab) tab.mtime = response.mtime
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        if (timedOut) {
          showToast(`文件加载超时 (${path})`)
          contentByPath.value = { ...contentByPath.value, [path]: '' }
        }
        return
      }
      const msg = err instanceof ApiError ? err.message : '读取文件内容失败'
      showToast(msg)
    } finally {
      clearTimeout(timeoutTimer)
      _pendingContentLoads.delete(path)
      if (_contentAbort === controller) {
        _contentAbort = null
        isFileLoading.value = false
      }
    }
    syncCurrentDocumentContext()
  }

  async function loadFilePreview(path: string): Promise<void> {
    if (_pendingPreviewLoads.has(path)) return
    _pendingPreviewLoads.add(path)
    isFileLoading.value = true
    // Abort previous preview fetch — user switched to a different file.
    _previewAbort?.abort()
    const controller = new AbortController()
    _previewAbort = controller
    let timedOut = false
    const timeoutTimer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 15_000)
    try {
      const settingsStore = useSettingsStore()
      const response = await previewKnowledgeFile(settingsStore.profile.userId, path, controller.signal)
      // Stale guard: if user switched away while this request was in-flight, skip.
      if (selectedPath.value !== path) return
      previewByPath.value = { ...previewByPath.value, [path]: response }
      const resolvedPipeline = resolveEditorFilePipeline(path, response.kind)
      if (!resolvedPipeline.modes.some((item) => item.mode === editorMode.value)) {
        editorMode.value = resolvedPipeline.defaultMode
      }
      if (response.content !== undefined && !response.readonly) {
        contentByPath.value = { ...contentByPath.value, [path]: response.content }
      }
      const tab = openTabs.value.find((t) => t.path === path)
      if (tab) tab.mtime = response.mtime
    } catch (err: unknown) {
      // Silent abort — user navigated away from this file.
      if (err instanceof DOMException && err.name === 'AbortError') {
        if (timedOut) {
          showToast(`文件预览超时 (${path})`)
          previewByPath.value = {
            ...previewByPath.value,
            [path]: {
              path,
              kind: 'unsupported' as const,
              message: '预览加载超时',
              mtime: '',
              size: 0,
              extension: '',
              readonly: true,
            },
          }
        }
        return
      }
      showToast(err instanceof ApiError ? err.message : '文件预览加载失败')
      previewByPath.value = {
        ...previewByPath.value,
        [path]: {
          path,
          kind: 'unsupported' as const,
          message: '预览加载失败',
          mtime: '',
          size: 0,
          extension: '',
          readonly: true,
        },
      }
    } finally {
      clearTimeout(timeoutTimer)
      _pendingPreviewLoads.delete(path)
      if (_previewAbort === controller) {
        _previewAbort = null
        isFileLoading.value = false
      }
    }
    syncCurrentDocumentContext()
  }

  function startFileWatcher() {
    const settingsStore = useSettingsStore()
    if (!settingsStore.profile.userId || fileEvents.value || typeof EventSource === 'undefined') {
      return
    }
    const eventSource = new EventSource(buildKnowledgeEventsUrl(settingsStore.profile.userId))
    eventSource.addEventListener('tree_dirty', async () => {
      if (ignoreNextTreeEvent.value > 0) {
        ignoreNextTreeEvent.value -= 1
        return
      }
      await loadKnowledgeTree()
      markOpenTabsDirty()
      // 重置外部修改文件的索引和图谱状态为未入库
      for (const tab of openTabs.value) {
        if (tab.dirty) {
          updateTreeNodeIndexStatus(tab.path, 'dirty', { force: true })
          updateTreeNodeGraphStatus(tab.path, 'dirty')
        }
      }
      window.dispatchEvent(new CustomEvent('metaweave-knowledge-file-change'))
    })
    eventSource.onerror = () => {
      eventSource.close()
      fileEvents.value = null
    }
    fileEvents.value = eventSource
  }

  function stopFileWatcher() {
    fileEvents.value?.close()
    fileEvents.value = null
  }

  function restartFileWatcher() {
    stopFileWatcher()
    startFileWatcher()
  }

  function markOpenTabsDirty() {
    const nodeByPath = new Map(flatNodes.value.map((n) => [n.path, n]))
    openTabs.value = openTabs.value.map((tab) => {
      const node = nodeByPath.get(tab.path)
      if (!node || !tab.mtime) return { ...tab, dirty: true }
      const changed = node.mtime !== tab.mtime
      return { ...tab, dirty: changed, mtime: changed ? tab.mtime : node.mtime }
    })
  }

  function uniquePathInDirectory(parentDirPath: string, preferredName: string): string {
    const existingPaths = new Set(flatNodes.value.map((node) => node.path))
    return uniquePathInDirectoryWithReserved(parentDirPath, preferredName, existingPaths)
  }

  function uniquePathInDirectoryWithReserved(
    parentDirPath: string,
    preferredName: string,
    existingPaths: Set<string>,
  ): string {
    const safeName = normalizeTreePath(preferredName).split('/').filter(Boolean).join('-') || 'untitled.md'
    const firstPath = joinTreePath(parentDirPath, safeName)
    if (!existingPaths.has(firstPath)) {
      return firstPath
    }
    const { stem, extension } = splitExtension(safeName)
    for (let index = 1; index < 1000; index += 1) {
      const candidate = joinTreePath(parentDirPath, `${stem} (${index})${extension}`)
      if (!existingPaths.has(candidate)) {
        return candidate
      }
    }
    return joinTreePath(parentDirPath, `${stem} ${Date.now()}${extension}`)
  }

  function rewriteOpenPaths(sourcePath: string, targetPath: string) {
    openTabs.value = openTabs.value.map((tab) => {
      if (!isSameOrChildPath(tab.path, sourcePath)) {
        return tab
      }
      const nextPath = tab.path.replace(sourcePath, targetPath)
      return { ...tab, path: nextPath, title: getBaseName(nextPath) }
    })
    Object.entries(contentByPath.value).forEach(([path, content]) => {
      if (!isSameOrChildPath(path, sourcePath)) {
        return
      }
      const nextPath = path.replace(sourcePath, targetPath)
      delete contentByPath.value[path]
      contentByPath.value[nextPath] = content
    })
    Object.entries(previewByPath.value).forEach(([path, preview]) => {
      if (!isSameOrChildPath(path, sourcePath)) {
        return
      }
      const nextPath = path.replace(sourcePath, targetPath)
      delete previewByPath.value[path]
      previewByPath.value[nextPath] = { ...preview, path: nextPath }
    })
    if (isSameOrChildPath(selectedPath.value, sourcePath)) {
      selectedPath.value = selectedPath.value.replace(sourcePath, targetPath)
    }
    recentFileVisits.value = recentFileVisits.value.map((visit) => {
      if (!isSameOrChildPath(visit.path, sourcePath)) return visit
      return { ...visit, path: visit.path.replace(sourcePath, targetPath) }
    })
    persistRecentFileVisits()
  }

  function isSameOrChildPath(path: string, parentPath: string): boolean {
    return path === parentPath || path.startsWith(`${parentPath}/`)
  }

  return {
    tree,
    recentFileVisits,
    expandedPaths,
    selectedPath,
    selectedTreePath,
    treeSelectionCleared,
    selectedTreePaths,
    selectionAnchorPath,
    selectedNode,
    mainView,
    editorSidebarOpen,
    searchSidebarResult,
    browserSidebarOpen,
    browserSidebarUrl,
    browserSidebarNavigationId,
    pendingLibraryParentId,
    pendingMainSearchResult,
    pendingLiteratureEntry,
    ingestionViewTab,
    editorMode,
    openTabs,
    activeContent,
    activePreview,
    activeViewerKind,
    activeFileReadonly,
    activeTab,
    dirtyFilePaths,
    hasDirtyTabs,
    isFileLoading,
    commandPaletteOpen,
    chatMessages,
    commands,
    treeLoading,
    fileClipboard,
    conflictDialog,
    promptConflictStrategy,
    refreshing,
    ingestionProgress,
    ingestionProgressDetail,
    ingestionProgressStats,
    ingestionProgressVisible,
    ingestionQueue,
    ingestionHistory,
    trashEntries,
    trashLoading,
    toastMessage,
    toastVisible,
    showToast,
    resolveConflict,
    cancelConflict,
    agentSidebarOpen,
    todoSidebarOpen,
    pendingAgentPrompt,
    pendingAgentReference,
    markdownHtmlVisualization,
    markdownHtmlVisualizationOpen,
    markdownHtmlVisualizationMode,
    markdownHtmlVisualizationPreset,
    markdownHtmlVisualizationCustomRequirement,
    markdownHtmlVisualizationOptions,
    markdownHtmlVisualizationUrl,
    setMarkdownHtmlVisualizationMode,
    setMarkdownHtmlVisualizationPreset,
    setMarkdownHtmlVisualizationOption,
    setMarkdownHtmlVisualizationCustomRequirement,
    showMarkdownHtmlVisualization,
    closeMarkdownHtmlVisualization,
    selectMarkdownHtmlVisualizationDocument,
    startMarkdownHtmlVisualization,
    saveMarkdownHtmlVisualizationToKnowledge,
    revealMarkdownHtmlVisualization,
    toggleDirectory,
    selectTreeNode,
    setTreeSelection,
    clearTreeSelection,
    getSelectedTreeNodes,
    selectFile,
    activateTab,
    closeTab,
    setEditorMode,
    setMainView,
    openEditorSidebar,
    openSearchResultSidebar,
    openAgentSearchResult,
    updateSearchSidebarResult,
    closeEditorSidebar,
    openBrowserSidebar,
    closeBrowserSidebar,
    toggleBrowserSidebar,
    openLibraryParent,
    openLiteratureEntry,
    consumePendingLiteratureEntry,
    updateActiveContent,
    saveActiveFile,
    saveAllDirtyFiles,
    confirmSaveDirtyBeforeExit,
    importFilesToPath,
    importExternalPathsToPath,
    scanKnowledgeRoot,
    openCommandPalette,
    closeCommandPalette,
    flatNodes,
    searchQuery,
    searchResults,
    searchOpen,
    searching,
    searchError,
    fulltextEnabled,
    semanticEnabled,
    searchUnified,
    searchSources,
    toggleSearchSource,
    openSearch,
    closeSearch,
    searchHistory,
    addSearchHistory,
    clearSearchHistory,
    clearIngestionHistory,
    graphProgressVisible,
    graphProgress,
    graphProgressDetail,
    graphProgressStats,
    graphQueue,
    graphHistory,
    graphRebuildPending,
    startGraphRebuild,
    extractGraphForNode,
    extractGraphForNodes,
    clearGraphHistory,
    performSearch,
    askAgent,
    syncCurrentDocumentContext,
    markIndexing,
    ingestFile,
    loadIngestionJobs,
    cancelIngestionJob,
    cancelGraphTask,
    createFileAt,
    createFolderAt,
    copyNode,
    cutNode,
    pasteNode,
    savePastedEditorImage,
    moveNodesToDirectory,
    renameNode,
    deleteNode,
    loadKnowledgeTree,
    loadKnowledgeTrash,
    restoreTrashEntry,
    deleteTrashEntry,
    startFileWatcher,
    stopFileWatcher,
    restartFileWatcher,
  }
})
