<!--
  Knowledge file resource manager.

  Usage:
  Rendered as a center workspace page. It offers Explorer-style file browsing,
  view modes, range/discrete multi-selection, folder-size summaries, previews,
  and visible drop targets for external files.
-->
<script setup lang="ts">
import { checkModelDisk } from '@/api/settings'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import FavoriteButton from '@/components/common/FavoriteButton.vue'
import PrivacyButton from '@/components/common/PrivacyButton.vue'
import AnimatedFolderIcon from './AnimatedFolderIcon.vue'
import FileContextMenu from '@/components/editor_workspace/FileContextMenu.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  displayIngestedAt,
  displayMtime,
  fileKind,
  formatSize,
  isImageNode,
  nodeSize,
  normalizeTreePath,
  parentPath,
  timestampOf,
} from '@/components/editor_workspace/fileResourceManagerUtils'
import { materialFileIconForNode } from '@/components/editor_workspace/materialFileIcons'
import { previewKnowledgeFile, readKnowledgeFile } from '@/api/knowledge'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { useGitStore } from '@/stores/git'
import { useFavoritesStore } from '@/stores/favorites'
import { usePrivacyStore } from '@/stores/privacy'
import type { FilePreviewPayload, KnowledgeFileNode, KnowledgeTrashEntry } from '@/types/knowledge'

defineOptions({ name: 'FileResourceManager' })

const props = withDefaults(defineProps<{
  embeddedPicker?: boolean
  favoritesOnlyLocked?: boolean
  privacyOnlyLocked?: boolean
}>(), {
  embeddedPicker: false,
  favoritesOnlyLocked: false,
  privacyOnlyLocked: false,
})

type ResourcePage = 'files' | 'trash'
type ResourceViewMode = 'list' | 'content' | 'small' | 'medium' | 'large'
type SortKey = 'name' | 'mtime' | 'ingested' | 'size'
type SortDirection = 'asc' | 'desc'

const workspaceStore = useWorkspaceStore()
const settingsStore = useSettingsStore()
const gitStore = useGitStore()
const favoritesStore = useFavoritesStore()
const privacyStore = usePrivacyStore()
const currentDir = ref('')
const resourcePage = ref<ResourcePage>('files')
const pageSwitchRef = ref<HTMLElement | null>(null)
const pageSliderStyle = ref({ width: '0px', left: '0px' })
const directoryBackStack = ref<string[]>([])
const directoryForwardStack = ref<string[]>([])
const viewMode = ref<ResourceViewMode>('list')
const multiSelectMode = ref(false)
const sortMenuOpen = ref(false)
const sortKey = ref<SortKey>('name')
const sortDirection = ref<SortDirection>('asc')
const favoritesOnly = ref(false)
const privacyOnly = ref(false)
const switchingRoot = ref(false)
const rootError = ref('')
const dragging = ref(false)
const dragTargetPath = ref('')
const previewLoading = ref(false)
const previewError = ref('')
const previewPayloadByPath = ref<Record<string, FilePreviewPayload>>({})
const contentByPath = ref<Record<string, string>>({})
const imagePreviewUrls = ref<Record<string, string>>({})
const contextMenu = ref<{
  open: boolean
  x: number
  y: number
  node: KnowledgeFileNode | null
}>({ open: false, x: 0, y: 0, node: null })
const contextMenuStyle = ref<Record<string, string>>({ left: '0px', top: '0px' })
const contextMenuRef = ref<{ getBoundingClientRect: () => DOMRect } | null>(null)

/* ---- 模型阻断模态框 ---- */
const modelModalVisible = ref(false)
const modelModalMessage = ref('')

async function checkEmbeddingBefore(action: () => Promise<void>): Promise<void> {
  try {
    const status = await checkModelDisk()
    if (status.embedding === 'not_downloaded' || status.embedding === 'error') {
      modelModalMessage.value = 'Embedding 模型未就绪，请先下载'
      modelModalVisible.value = true
      return
    }
  } catch { /* 检查失败时允许继续 */ }
  await action()
}

function closeModelModal() { modelModalVisible.value = false }
function goToStorageSettings() {
  modelModalVisible.value = false
  window.location.hash = '#/settings'
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('agent-settings-tab', { detail: 'storage' }))
  }, 100)
}

const viewModes: { value: ResourceViewMode; label: string; title: string }[] = [
  { value: 'list', label: '列表', title: '详细列表' },
  { value: 'small', label: '小', title: '小图标' },
  { value: 'medium', label: '中', title: '中图标' },
  { value: 'large', label: '大', title: '大图标' },
]
const sortKeyOptions: { value: SortKey; label: string }[] = [
  { value: 'name', label: '名称排序' },
  { value: 'mtime', label: '修改时间排序' },
  { value: 'ingested', label: '入库时间排序' },
  { value: 'size', label: '大小排序' },
]
const sortDirectionOptions: { value: SortDirection; label: string }[] = [
  { value: 'asc', label: '递增' },
  { value: 'desc', label: '递减' },
]

const flatNodes = computed(() => workspaceStore.flatNodes)
const selectedPaths = computed(() => workspaceStore.selectedTreePaths)
const isMultiSelecting = computed(() => multiSelectMode.value || selectedPaths.value.size > 0)
const canPaste = computed(() => Boolean(workspaceStore.fileClipboard) || Boolean(window.agentEditorDesktop?.readClipboardFilePaths))
const selectedNode = computed(() => flatNodes.value.find((node) => node.path === workspaceStore.selectedTreePath) ?? null)
const contextSelectionCount = computed(() => contextTargetNodes().length)
const selectedPreviewPayload = computed(() => {
  const path = selectedNode.value?.path ?? ''
  return path ? previewPayloadByPath.value[path] ?? workspaceStore.activePreview : null
})
const selectedContent = computed(() => {
  const path = selectedNode.value?.path ?? ''
  return path ? contentByPath.value[path] ?? workspaceStore.activeContent : ''
})

const canGoBack = computed(() => directoryBackStack.value.length > 0)
const canGoForward = computed(() => directoryForwardStack.value.length > 0)
const canGoUp = computed(() => Boolean(currentDir.value))
const pathCapsuleParts = computed(() => {
  const parts = currentDir.value.split('/').filter(Boolean)
  return [
    { label: '根目录', path: '' },
    ...parts.map((part, index) => ({
      label: part,
      path: parts.slice(0, index + 1).join('/'),
    })),
  ]
})

const visibleItems = computed(() => {
  if (!privacyStore.hasLoaded('knowledge_path')) return []
  const targetParent = currentDir.value
  const favoritePaths = favoritesStore.idsFor('knowledge_path')
  const privatePaths = privacyStore.idsFor('knowledge_path')
  return flatNodes.value
    .filter((node) => {
      if (effectivePrivacyOnly.value) return privatePaths.has(node.path)
      if (privatePaths.has(node.path)) return false
      if (effectiveFavoritesOnly.value) return favoritePaths.has(node.path)
      return parentPath(node.path) === targetParent
    })
    .sort(compareNodes)
})
const effectiveFavoritesOnly = computed(() => props.favoritesOnlyLocked || favoritesOnly.value)
const effectivePrivacyOnly = computed(() => props.privacyOnlyLocked || privacyOnly.value)

const listGridColumns = computed(() => {
  const selectionColumn = isMultiSelecting.value ? '28px ' : ''
  const indexColumn = settingsStore.showIndexColumn ? '118px' : ''
  const graphColumn = settingsStore.showGraphColumn ? '118px' : ''
  const favoriteColumn = settingsStore.showFavoriteColumn ? '64px' : ''
  const privacyColumn = settingsStore.showPrivacyColumn ? '78px' : ''
  const trailingColumns = [privacyColumn, favoriteColumn, indexColumn, graphColumn].filter(Boolean).join(' ')
  return `${selectionColumn}minmax(240px, 1fr) 168px 168px 112px 96px${trailingColumns ? ` ${trailingColumns}` : ''}`
})
const trashGridColumns = 'minmax(220px, 1fr) minmax(260px, 1.2fr) 156px 156px 96px 96px 132px'

watch(
  () => workspaceStore.selectedTreePath,
  () => {
    if (viewMode.value === 'content') {
      void ensureSelectedPreview()
    }
  },
)

watch(
  [visibleItems, viewMode],
  () => {
    if (viewMode.value === 'large') {
      void ensureLargeImagePreviews()
    }
  },
  { immediate: true },
)

function joinAbsoluteKnowledgePath(relativePath: string): string {
  const root = settingsStore.profile.knowledgeDir.replace(/[\\/]+$/g, '')
  const child = normalizeTreePath(relativePath)
  if (!child) {
    return root
  }
  return `${root}\\${child.replace(/\//g, '\\')}`
}

function contextTargetDir(): string {
  const node = contextMenu.value.node
  if (!node) {
    return currentDir.value
  }
  return node.isDir ? node.path : parentPath(node.path)
}

function compareNodes(a: KnowledgeFileNode, b: KnowledgeFileNode): number {
  const dirOrder = Number(b.isDir) - Number(a.isDir)
  if (dirOrder !== 0) {
    return dirOrder
  }
  let result = 0
  if (sortKey.value === 'name') {
    result = a.name.localeCompare(b.name)
  } else if (sortKey.value === 'mtime') {
    result = timestampOf(a.mtime) - timestampOf(b.mtime)
  } else if (sortKey.value === 'ingested') {
    result = timestampOf(displayIngestedAt(a)) - timestampOf(displayIngestedAt(b))
  } else {
    result = nodeSize(a) - nodeSize(b)
  }
  if (result === 0) {
    result = a.name.localeCompare(b.name)
  }
  return sortDirection.value === 'asc' ? result : -result
}

async function openRootPicker() {
  rootError.value = ''
  if (!window.agentEditorDesktop?.selectDirectory) {
    rootError.value = 'Switching a local knowledge root requires the Electron directory picker.'
    workspaceStore.showToast(rootError.value)
    return
  }
  const selectedDir = await window.agentEditorDesktop.selectDirectory()
  if (!selectedDir) {
    return
  }
  switchingRoot.value = true
  try {
    await settingsStore.switchKnowledgeRoot(selectedDir)
    currentDir.value = ''
    directoryBackStack.value = []
    directoryForwardStack.value = []
    workspaceStore.clearTreeSelection()
  } catch (error) {
    rootError.value = error instanceof Error ? error.message : 'Failed to switch knowledge root.'
    workspaceStore.showToast(rootError.value)
  } finally {
    await workspaceStore.loadKnowledgeTree()
    workspaceStore.restartFileWatcher()
    switchingRoot.value = false
  }
}

function navigateToDirectory(path: string, recordHistory = true) {
  const normalizedPath = normalizeTreePath(path)
  if (normalizedPath === currentDir.value) {
    return
  }
  if (recordHistory) {
    directoryBackStack.value = [...directoryBackStack.value, currentDir.value]
    directoryForwardStack.value = []
  }
  currentDir.value = normalizedPath
  workspaceStore.clearTreeSelection()
}

function goBackDirectory() {
  const previousPath = directoryBackStack.value[directoryBackStack.value.length - 1]
  if (previousPath === undefined) {
    return
  }
  directoryBackStack.value = directoryBackStack.value.slice(0, -1)
  directoryForwardStack.value = [...directoryForwardStack.value, currentDir.value]
  navigateToDirectory(previousPath, false)
}

function goForwardDirectory() {
  const nextPath = directoryForwardStack.value[directoryForwardStack.value.length - 1]
  if (nextPath === undefined) {
    return
  }
  directoryForwardStack.value = directoryForwardStack.value.slice(0, -1)
  directoryBackStack.value = [...directoryBackStack.value, currentDir.value]
  navigateToDirectory(nextPath, false)
}

function goUpDirectory() {
  if (!currentDir.value) {
    return
  }
  navigateToDirectory(parentPath(currentDir.value))
}

async function refreshResources() {
  if (resourcePage.value === 'trash') {
    await workspaceStore.loadKnowledgeTrash()
    return
  }
  await workspaceStore.loadKnowledgeTree()
  if (settingsStore.profile.userId) {
    await Promise.all([
      favoritesStore.load(settingsStore.profile.userId, 'knowledge_path', favoritesStore.activeLibraryId()),
      privacyStore.load(settingsStore.profile.userId, 'knowledge_path', privacyStore.activeLibraryId()),
    ])
  }
  if (!flatNodes.value.some((node) => node.path === currentDir.value) && currentDir.value) {
    navigateToDirectory('', false)
  }
}

function updatePageSlider() {
  nextTick(() => {
    const container = pageSwitchRef.value
    if (!container) return
    const active = container.querySelector('.page-switch-button.active') as HTMLElement | null
    if (!active) return
    pageSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

async function switchResourcePage(page: ResourcePage) {
  resourcePage.value = page
  if (page === 'trash') {
    await workspaceStore.loadKnowledgeTrash()
  }
  updatePageSlider()
}

function materialIconForEntry(entry: KnowledgeTrashEntry) {
  return materialFileIconForNode({
    name: entry.name,
    path: entry.original_relative_path || entry.name,
    isDir: entry.is_dir,
  })
}

function indexStatusIcon(node: KnowledgeFileNode) {
  if (node.indexStatus === 'indexed' || node.indexStatus === 'clean') return 'check-circle'
  if (node.indexStatus === 'ignored') return 'block'
  return 'error-outline'
}

function indexStatusTitle(node: KnowledgeFileNode): string {
  if (node.indexStatus === 'indexed' || node.indexStatus === 'clean') return '已进入向量库'
  if (node.indexStatus === 'ignored') return '已屏蔽'
  if (node.indexStatus === 'failed') return '入库失败'
  return '未进入向量库'
}

function indexStatusClass(node: KnowledgeFileNode): string {
  if (node.indexStatus === 'indexed' || node.indexStatus === 'clean') return 'indexed'
  if (node.indexStatus === 'ignored') return 'ignored'
  if (node.indexStatus === 'failed') return 'failed'
  return 'dirty'
}

function graphStatusIcon(node: KnowledgeFileNode) {
  if (node.graphStatus === 'graphed') return 'hub'
  if (node.graphStatus === 'ignored') return 'block'
  return 'git'
}

function graphStatusTitle(node: KnowledgeFileNode): string {
  if (node.graphStatus === 'graphed') return '已入图谱'
  if (node.graphStatus === 'ignored') return '已屏蔽'
  return '未入图谱'
}

function graphStatusClass(node: KnowledgeFileNode): string {
  if (node.graphStatus === 'graphed') return 'graphed'
  if (node.graphStatus === 'ignored') return 'ignored'
  return 'dirty'
}

function gitStatusClass(node: KnowledgeFileNode): string {
  // Resource views share the same semantic Git colors as the recursive tree.

  return gitStore.statusClassForPath(node.path, node.isDir)
}

function toggleStatusColumns() {
  const nextVisible = !(
    settingsStore.showIndexColumn
    && settingsStore.showGraphColumn
    && settingsStore.showFavoriteColumn
    && settingsStore.showPrivacyColumn
  )
  settingsStore.setShowIndexColumn(nextVisible)
  settingsStore.setShowGraphColumn(nextVisible)
  settingsStore.setShowFavoriteColumn(nextVisible)
  settingsStore.setShowPrivacyColumn(nextVisible)
}

function toggleFavoritesOnly() {
  if (props.favoritesOnlyLocked) return
  favoritesOnly.value = !favoritesOnly.value
  if (favoritesOnly.value) privacyOnly.value = false
}

function togglePrivacyOnly() {
  if (props.privacyOnlyLocked) return
  privacyOnly.value = !privacyOnly.value
  if (privacyOnly.value) favoritesOnly.value = false
}

function visibleRangePaths(anchorPath: string, targetPath: string): string[] {
  const paths = visibleItems.value.map((node) => node.path)
  const anchorIndex = paths.indexOf(anchorPath)
  const targetIndex = paths.indexOf(targetPath)
  if (anchorIndex < 0 || targetIndex < 0) {
    return [targetPath]
  }
  const start = Math.min(anchorIndex, targetIndex)
  const end = Math.max(anchorIndex, targetIndex)
  return paths.slice(start, end + 1)
}

function handleItemClick(node: KnowledgeFileNode, event: MouseEvent) {
  if (event.shiftKey) {
    workspaceStore.selectTreeNode(node, {
      rangePaths: visibleRangePaths(workspaceStore.selectionAnchorPath || workspaceStore.selectedTreePath, node.path),
    })
    return
  }
  if (event.ctrlKey || event.metaKey) {
    workspaceStore.selectTreeNode(node, { additive: true })
    return
  }
  if (multiSelectMode.value) {
    workspaceStore.selectTreeNode(node, { additive: true })
    return
  }
  workspaceStore.selectTreeNode(node)
  if (node.isDir) {
    navigateToDirectory(node.path)
    return
  }
  void workspaceStore.selectFile(node)
  if (viewMode.value === 'content') {
    void ensureSelectedPreview()
  }
}

function handleItemDblClick(node: KnowledgeFileNode) {
  if (node.isDir) {
    navigateToDirectory(node.path)
    workspaceStore.selectedTreePath = node.path
    return
  }
  if (props.embeddedPicker) {
    void workspaceStore.selectFile(node)
    return
  }
  void workspaceStore.openEditorSidebar(node)
}

function selectBreadcrumb(path: string) {
  navigateToDirectory(path)
}

function cancelMultiSelection() {
  multiSelectMode.value = false
  workspaceStore.clearTreeSelection()
}

function toggleMultiSelectMode() {
  multiSelectMode.value = !multiSelectMode.value
  if (!multiSelectMode.value) {
    workspaceStore.clearTreeSelection()
  }
}

async function openContextMenu(node: KnowledgeFileNode | null, event: MouseEvent) {
  if (node && !workspaceStore.selectedTreePaths.has(node.path)) {
    workspaceStore.selectTreeNode(node)
  }
  const rawX = event.clientX
  const rawY = event.clientY
  contextMenu.value = { open: true, x: rawX, y: rawY, node }
  contextMenuStyle.value = { left: `${rawX}px`, top: `${rawY}px` }
  await nextTick()
  const menu = contextMenuRef.value
  if (!menu) return
  const rect = menu.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const overflowRight = Math.max(0, rect.right - vw)
  const overflowBottom = Math.max(0, rect.bottom - vh)
  if (overflowRight > 0 || overflowBottom > 0) {
    contextMenuStyle.value = {
      left: `${Math.max(0, rawX - overflowRight)}px`,
      top: `${Math.max(0, rawY - overflowBottom)}px`,
    }
  }
}

function closeContextMenu() {
  contextMenu.value.open = false
}

function contextTargetNodes(): KnowledgeFileNode[] {
  const node = contextMenu.value.node
  if (!node) {
    return []
  }
  if (!workspaceStore.selectedTreePaths.has(node.path)) {
    return [node]
  }
  return workspaceStore.getSelectedTreeNodes(node)
}

async function writeClipboardText(text: string) {
  if (window.agentEditorDesktop?.writeClipboardText) {
    await window.agentEditorDesktop.writeClipboardText(text)
    return
  }
  await navigator.clipboard?.writeText(text)
}

async function createFileFromMenu() {
  const name = window.prompt('新建文件名', 'untitled.md')?.trim()
  const parentDir = contextTargetDir()
  closeContextMenu()
  if (name) {
    await workspaceStore.createFileAt(parentDir, name)
  }
}

async function createFolderFromMenu() {
  const name = window.prompt('新建文件夹名', 'New Folder')?.trim()
  const parentDir = contextTargetDir()
  closeContextMenu()
  if (name) {
    await workspaceStore.createFolderAt(parentDir, name)
  }
}

async function copyFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (node) await workspaceStore.copyNode(node)
}

async function cutFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (node) await workspaceStore.cutNode(node)
}

async function copyNameFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (node) await writeClipboardText(node.name)
}

async function copyAbsolutePathFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (node) await writeClipboardText(joinAbsoluteKnowledgePath(node.path))
}

async function copyRelativePathFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (node) await writeClipboardText(node.path)
}

async function pasteFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  await workspaceStore.pasteNode(node, 'resources')
}

async function renameFromMenu() {
  const node = contextMenu.value.node
  if (!node) {
    closeContextMenu()
    return
  }
  const nextName = window.prompt('重命名', node.name)?.trim()
  closeContextMenu()
  if (nextName) {
    await workspaceStore.renameNode(node, nextName)
  }
}

async function showInFolderFromMenu() {
  const node = contextTargetNodes()[0] ?? contextMenu.value.node
  const absolutePath = node ? joinAbsoluteKnowledgePath(node.path) : settingsStore.profile.knowledgeDir
  closeContextMenu()
  await window.agentEditorDesktop?.showItemInFolder?.(absolutePath)
}

async function openWithDefaultFromMenu() {
  const node = contextMenu.value.node
  const absolutePath = node ? joinAbsoluteKnowledgePath(node.path) : settingsStore.profile.knowledgeDir
  closeContextMenu()
  await window.agentEditorDesktop?.openPath?.(absolutePath)
}

async function extractGraphFromMenu() {
  const nodes = contextTargetNodes()
  closeContextMenu()
  if (nodes.length === 0) return
  await checkEmbeddingBefore(() => workspaceStore.extractGraphForNodes(nodes))
}

async function askAgentFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  workspaceStore.setMainView('editor')
  if (node && !node.isDir) {
    await workspaceStore.selectFile(node)
    workspaceStore.syncCurrentDocumentContext()
    workspaceStore.agentSidebarOpen = true
    workspaceStore.pendingAgentPrompt = 'Help me review the currently open file.'
  }
}

async function htmlVisualizeFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (!node || node.isDir) {
    return
  }
  await workspaceStore.selectMarkdownHtmlVisualizationDocument(node)
}

async function ingestFromMenu() {
  const nodes = contextTargetNodes()
  closeContextMenu()
  await checkEmbeddingBefore(async () => {
    for (const node of nodes) {
      await workspaceStore.ingestFile(node)
    }
  })
}

function toggleFavoriteFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (!node) return
  void favoritesStore.toggle('knowledge_path', node.path)
}

function togglePrivacyFromMenu() {
  const node = contextMenu.value.node
  closeContextMenu()
  if (!node) return
  void privacyStore.toggle('knowledge_path', node.path)
}

function ignorePatternForNode(node: KnowledgeFileNode): string {
  const normalizedPath = normalizeTreePath(node.path)
  return node.isDir ? `${normalizedPath}/` : normalizedPath
}

function normalizeIgnorePatternLine(line: string): string {
  return line.replace(/\\/g, '/').trim()
}

async function toggleIgnoreFromMenu() {
  const nodes = contextTargetNodes()
  closeContextMenu()
  if (nodes.length === 0) return
  let currentLines = (settingsStore.profile.knowledgeIgnorePatterns ?? '')
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
  for (const node of nodes) {
    const pattern = ignorePatternForNode(node)
    const isCurrentlyIgnored = node.indexStatus === 'ignored'
    currentLines = isCurrentlyIgnored
      ? currentLines.filter((line) => normalizeIgnorePatternLine(line) !== pattern)
      : [...currentLines.filter((line) => normalizeIgnorePatternLine(line) !== `!${pattern}`), pattern]
  }
  await settingsStore.saveKnowledgeIngestionSettings({ knowledgeIgnorePatterns: currentLines.join('\n') })
  await workspaceStore.loadKnowledgeTree()
}

async function deleteFromMenu() {
  const nodes = contextTargetNodes()
  closeContextMenu()
  const firstNode = nodes[0]
  if (nodes.length === 1 && firstNode && window.confirm(`删除 ${firstNode.name}?`)) {
    await workspaceStore.deleteNode(firstNode)
    return
  }
  if (nodes.length > 1 && window.confirm(`删除选中的 ${nodes.length} 项?`)) {
    for (const node of [...nodes].sort((a, b) => b.path.split('/').length - a.path.split('/').length)) {
      await workspaceStore.deleteNode(node)
    }
  }
}

async function ensureSelectedPreview() {
  const node = selectedNode.value
  if (!node || node.isDir) {
    return
  }
  previewError.value = ''
  previewLoading.value = true
  try {
    await workspaceStore.selectFile(node)
    if (contentByPath.value[node.path] === undefined) {
      const response = await readKnowledgeFile(settingsStore.profile.userId, node.path)
      contentByPath.value = { ...contentByPath.value, [node.path]: response.content }
    }
  } catch {
    try {
      const preview = await previewKnowledgeFile(settingsStore.profile.userId, node.path)
      previewPayloadByPath.value = { ...previewPayloadByPath.value, [node.path]: preview }
      if (preview.content !== undefined) {
        contentByPath.value = { ...contentByPath.value, [node.path]: preview.content }
      }
    } catch (error) {
      previewError.value = error instanceof Error ? error.message : '内容预览加载失败'
    }
  } finally {
    previewLoading.value = false
  }
}

async function ensureLargeImagePreviews() {
  const images = visibleItems.value.filter((node) => (
    isImageNode(node)
    && !privacyStore.loading
    && !privacyStore.isPrivate('knowledge_path', node.path)
    && !imagePreviewUrls.value[node.path]
  ))
  if (images.length === 0) {
    return
  }
  for (const node of images.slice(0, 24)) {
    try {
      const preview = await previewKnowledgeFile(settingsStore.profile.userId, node.path)
      if (preview.data_url || preview.raw_url) {
        imagePreviewUrls.value = { ...imagePreviewUrls.value, [node.path]: preview.data_url || preview.raw_url || '' }
      }
    } catch {
      imagePreviewUrls.value = { ...imagePreviewUrls.value, [node.path]: '' }
    }
  }
}

function filesFromEvent(event: DragEvent): File[] {
  return Array.from(event.dataTransfer?.files ?? [])
}

function desktopPathsFromFiles(files: File[]): string[] {
  const getPathForFile = window.agentEditorDesktop?.getPathForFile
  if (!getPathForFile) {
    return []
  }
  return files
    .map((file) => {
      try {
        return getPathForFile(file)
      } catch {
        return ''
      }
    })
    .filter(Boolean)
}

function handleDragEnter(path = currentDir.value) {
  dragging.value = true
  dragTargetPath.value = path
}

function handleDragLeave(event: DragEvent) {
  const el = event.currentTarget as HTMLElement | null
  const related = event.relatedTarget as HTMLElement | null
  if (el && related && el.contains(related)) return
  dragging.value = false
  dragTargetPath.value = ''
}

async function handleDrop(event: DragEvent, targetNode?: KnowledgeFileNode) {
  dragging.value = false
  const targetDir = targetNode?.isDir ? targetNode.path : currentDir.value
  dragTargetPath.value = ''
  const files = filesFromEvent(event)
  if (files.length === 0) {
    return
  }
  const desktopPaths = desktopPathsFromFiles(files)
  if (desktopPaths.length > 0) {
    await workspaceStore.importExternalPathsToPath(desktopPaths, targetDir, undefined, 'resources')
    multiSelectMode.value = false
    workspaceStore.clearTreeSelection()
    workspaceStore.selectedTreePath = targetDir
    return
  }
  await workspaceStore.importFilesToPath(files, targetDir, undefined, 'resources')
  multiSelectMode.value = false
  workspaceStore.clearTreeSelection()
  workspaceStore.selectedTreePath = targetDir
}

function previewSummary(node: KnowledgeFileNode): string {
  if (node.isDir) {
    return `${node.children?.length ?? 0} 项, ${formatSize(nodeSize(node))}`
  }
  const text = contentByPath.value[node.path]
  if (text) {
    return text.replace(/\s+/g, ' ').trim().slice(0, 180)
  }
  return `${fileKind(node)} | ${formatSize(nodeSize(node))}`
}

function displayTrashDate(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.replace('T', ' ').slice(0, 16)
  const pad = (input: number) => input.toString().padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function trashKind(entry: { is_dir: boolean; name: string }): string {
  return entry.is_dir ? '文件夹' : fileKind({ name: entry.name, path: entry.name, isDir: false })
}

async function restoreTrash(entry: KnowledgeTrashEntry) {
  await workspaceStore.restoreTrashEntry(entry)
  resourcePage.value = 'files'
}

async function deleteTrash(entry: KnowledgeTrashEntry) {
  if (!window.confirm(`彻底删除 ${entry.name}? 此操作不能恢复。`)) {
    return
  }
  await workspaceStore.deleteTrashEntry(entry)
}

onMounted(() => {
  document.addEventListener('click', closeContextMenu)
  if (settingsStore.profile.userId) {
    void Promise.all([
      favoritesStore.load(settingsStore.profile.userId, 'knowledge_path', favoritesStore.activeLibraryId()),
      privacyStore.load(settingsStore.profile.userId, 'knowledge_path', privacyStore.activeLibraryId()),
    ])
  }
  void workspaceStore.loadKnowledgeTrash()
  void gitStore.refresh()
  updatePageSlider()
})

onUnmounted(() => {
  document.removeEventListener('click', closeContextMenu)
})
</script>

<template>
  <section
    class="resource-manager"
    :class="{ dragging, 'theme-dark': settingsStore.isDark }"
    @dragenter.prevent="resourcePage === 'files' && handleDragEnter()"
    @dragover.prevent="resourcePage === 'files' && handleDragEnter()"
    @dragleave="handleDragLeave"
    @drop.prevent="resourcePage === 'files' && handleDrop($event)"
    @contextmenu.prevent="resourcePage === 'files' && openContextMenu(null, $event)"
  >
    <header class="resource-toolbar">
      <div class="toolbar-primary">
        <div ref="pageSwitchRef" class="resource-page-switch" aria-label="Resource pages">
        <div class="page-slider" :style="pageSliderStyle"></div>
        <button
          class="page-switch-button"
          :class="{ active: resourcePage === 'files' }"
          type="button"
          @click="switchResourcePage('files')"
        >
          <IcIcon name="document" :size="17" />
          <span>文件</span>
        </button>
        <button
          class="page-switch-button"
          :class="{ active: resourcePage === 'trash' }"
          type="button"
          @click="switchResourcePage('trash')"
        >
          <IcIcon name="trash" :size="17" />
          <span>最近删除</span>
        </button>
        </div>
        <span class="toolbar-separator"></span>
        <div class="nav-controls" aria-label="Folder navigation">
        <button class="tool-button v1-icon-button" type="button" title="回退" :disabled="!canGoBack" @click="goBackDirectory">
          <IcIcon name="arrow-left" :size="17" />
        </button>
        <button class="tool-button v1-icon-button" type="button" title="反回退" :disabled="!canGoForward" @click="goForwardDirectory">
          <IcIcon name="arrow-right" :size="17" />
        </button>
        <button class="tool-button v1-icon-button" type="button" title="去上级文件夹" :disabled="!canGoUp" @click="goUpDirectory">
          <IcIcon name="arrow-up" :size="17" />
        </button>
        <button
          class="tool-button v1-icon-button"
          :class="{ loading: workspaceStore.treeLoading || workspaceStore.trashLoading, 'refresh-btn': true }"
          type="button"
          title="刷新"
          :disabled="workspaceStore.treeLoading || workspaceStore.trashLoading"
          @click="refreshResources"
        >
          <IcIcon name="refresh" :size="17" />
        </button>
        </div>
        <span class="toolbar-separator"></span>
        <button
        class="root-button v1-icon-button"
        type="button"
        :disabled="switchingRoot"
        :title="rootError || 'Switch knowledge root'"
        @click="openRootPicker"
      >
        <IcIcon name="folder-open" :size="20" />
        </button>
        <div v-if="resourcePage === 'files'" class="path-capsule" aria-label="Current path">
        <button
          v-for="part in pathCapsuleParts"
          :key="part.path || '__root'"
          class="path-part"
          type="button"
          @click="selectBreadcrumb(part.path)"
        >
          {{ part.label }}
        </button>
        </div>
        <div v-else class="path-capsule trash-path-capsule" aria-label="Current page">
          <IcIcon name="trash" :size="17" />
          <span>最近删除</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <button
        v-if="resourcePage === 'files'"
        class="tool-button v1-icon-button"
        :class="{ active: settingsStore.showIndexColumn || settingsStore.showGraphColumn || settingsStore.showFavoriteColumn || settingsStore.showPrivacyColumn }"
        type="button"
        :title="(settingsStore.showIndexColumn || settingsStore.showGraphColumn || settingsStore.showFavoriteColumn || settingsStore.showPrivacyColumn) ? '隐藏索引、图谱、收藏与隐私状态' : '显示索引、图谱、收藏与隐私状态'"
        :aria-label="(settingsStore.showIndexColumn || settingsStore.showGraphColumn || settingsStore.showFavoriteColumn || settingsStore.showPrivacyColumn) ? '隐藏索引、图谱、收藏与隐私状态' : '显示索引、图谱、收藏与隐私状态'"
        @click="toggleStatusColumns"
      >
        <IcIcon name="filter" :size="17" />
        </button>
        <button
        v-if="resourcePage === 'files'"
        class="tool-button v1-icon-button"
        :class="{ active: effectiveFavoritesOnly }"
        type="button"
        title="我的收藏"
        aria-label="我的收藏"
        :aria-pressed="effectiveFavoritesOnly"
        :disabled="favoritesOnlyLocked"
        @click="toggleFavoritesOnly"
      >
        <IcIcon name="star" :size="17" />
        </button>
        <button
        v-if="resourcePage === 'files'"
        class="tool-button v1-icon-button"
        :class="{ active: effectivePrivacyOnly }"
        type="button"
        title="我的隐私"
        aria-label="我的隐私"
        :aria-pressed="effectivePrivacyOnly"
        :disabled="privacyOnlyLocked"
        @click="togglePrivacyOnly"
      >
        <IcIcon name="visibility-off" :size="17" />
        </button>
        <button
        v-if="resourcePage === 'files'"
        class="tool-button v1-icon-button"
        :class="{ active: multiSelectMode }"
        type="button"
        title="多选"
        aria-label="多选"
        @click="toggleMultiSelectMode"
      >
        <IcIcon name="multi-select" :size="17" />
        </button>
        <DropdownMenu v-if="resourcePage === 'files'" v-model:open="sortMenuOpen">
        <DropdownMenuTrigger as-child>
          <button
            class="tool-button v1-icon-button"
            :class="{ active: sortMenuOpen }"
            type="button"
            title="排序"
            aria-label="排序"
          >
            <IcIcon name="sort" :size="17" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuPortal>
          <DropdownMenuContent align="end">
            <DropdownMenuGroup>
              <DropdownMenuLabel>排序依据</DropdownMenuLabel>
              <DropdownMenuRadioGroup v-model="sortKey">
                <DropdownMenuRadioItem
                  v-for="option in sortKeyOptions"
                  :key="option.value"
                  :value="option.value"
                  @select.prevent
                >
                  {{ option.label }}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>排列方式</DropdownMenuLabel>
              <DropdownMenuRadioGroup v-model="sortDirection">
                <DropdownMenuRadioItem
                  v-for="option in sortDirectionOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  <span class="sort-direction-copy">
                    <IcIcon :name="option.value === 'asc' ? 'arrow-up' : 'arrow-down'" :size="16" />
                    <span>{{ option.label }}</span>
                  </span>
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenuPortal>
        </DropdownMenu>
        <div v-if="resourcePage === 'files'" class="view-switch" aria-label="View mode">
        <button
          v-for="mode in viewModes"
          :key="mode.value"
          class="view-button"
          :class="{ active: viewMode === mode.value }"
          type="button"
          :title="mode.title"
          @click="viewMode = mode.value"
        >
          <IcIcon v-if="mode.value === 'list'" name="view-stream" :size="17" />
          <IcIcon v-else-if="mode.value === 'small'" name="view-list" :size="17" />
          <IcIcon v-else-if="mode.value === 'medium'" name="grid-view" :size="17" />
          <IcIcon v-else name="image" :size="17" />
          <span>{{ mode.label }}</span>
        </button>
        </div>
      </div>
    </header>

    <div v-if="resourcePage === 'files' && isMultiSelecting" class="multi-banner">
      <span>{{ selectedPaths.size > 0 ? `已选择 ${selectedPaths.size} 项` : '多选模式' }}</span>
      <button class="banner-close" type="button" title="取消多选" @click="cancelMultiSelection">
        <IcIcon name="close" :size="15" />
      </button>
    </div>

    <div class="content-shell" :class="resourcePage === 'files' ? `mode-${viewMode}` : 'mode-trash'">
      <div v-if="resourcePage === 'trash'" class="trash-view">
        <div class="trash-list">
          <div class="trash-header" :style="{ gridTemplateColumns: trashGridColumns }">
            <span class="trash-column-name">名称</span>
            <span class="trash-column-original">原路径</span>
            <span class="trash-column-deleted">删除时间</span>
            <span class="trash-column-retained">保留到</span>
            <span class="trash-column-type">类型</span>
            <span class="trash-column-size">大小</span>
            <span class="trash-column-actions">操作</span>
          </div>
          <div v-if="workspaceStore.trashLoading" class="trash-empty">正在加载最近删除</div>
          <div v-else-if="workspaceStore.trashEntries.length === 0" class="trash-empty">最近删除为空</div>
          <div
            v-for="(entry, index) in workspaceStore.trashEntries"
            v-else
            :key="entry.trash_id"
            class="trash-row"
            :style="{
              gridTemplateColumns: trashGridColumns,
              animationDelay: `${Math.min(index, 24) * 18}ms`,
            }"
          >
            <span class="trash-column-name name-cell">
              <img class="material-file-icon" :src="materialIconForEntry(entry).src" alt="" aria-hidden="true" />
              <span class="file-name">{{ entry.name }}</span>
            </span>
            <span class="trash-column-original">{{ entry.original_relative_path }}</span>
            <span class="trash-column-deleted">{{ displayTrashDate(entry.deleted_at) }}</span>
            <span class="trash-column-retained">{{ displayTrashDate(entry.expires_at) }}</span>
            <span class="trash-column-type">{{ trashKind(entry) }}</span>
            <span class="trash-column-size">{{ formatSize(entry.size) }}</span>
            <span class="trash-column-actions trash-actions">
              <button class="trash-action-button" type="button" title="恢复" @click="restoreTrash(entry)">
                <IcIcon name="replay" :size="14" />
                <span>恢复</span>
              </button>
              <button class="trash-action-button danger" type="button" title="彻底删除" @click="deleteTrash(entry)">
                <IcIcon name="trash" :size="14" />
              </button>
            </span>
          </div>
        </div>
      </div>

      <div v-else-if="viewMode === 'list'" class="list-view">
        <div class="list-header" :style="{ gridTemplateColumns: listGridColumns }">
          <span v-if="isMultiSelecting" class="selection-column-header"></span>
          <span class="column-name">名称</span>
          <span class="column-modified">最后修改日期</span>
          <span class="column-ingested">入库日期</span>
          <span class="column-type">类型</span>
          <span class="column-size">大小</span>
          <span v-if="settingsStore.showPrivacyColumn" class="column-privacy">隐私状态</span>
          <span v-if="settingsStore.showFavoriteColumn" class="column-favorite">收藏</span>
          <span v-if="settingsStore.showIndexColumn" class="column-index">入库状态</span>
          <span v-if="settingsStore.showGraphColumn" class="column-graph">图谱状态</span>
        </div>
        <button
          v-for="(node, index) in visibleItems"
          :key="node.path"
          class="resource-row"
          :class="[
            gitStatusClass(node),
            { selected: workspaceStore.selectedTreePath === node.path || selectedPaths.has(node.path) },
          ]"
          :style="{
            gridTemplateColumns: listGridColumns,
            animationDelay: `${Math.min(index, 24) * 18}ms`,
          }"
          type="button"
          draggable="true"
          @click="handleItemClick(node, $event)"
          @dblclick="handleItemDblClick(node)"
          @dragenter.prevent="node.isDir && handleDragEnter(node.path)"
          @dragover.prevent="node.isDir && handleDragEnter(node.path)"
          @drop.prevent.stop="handleDrop($event, node)"
          @contextmenu.prevent.stop="openContextMenu(node, $event)"
        >
          <span v-if="isMultiSelecting" class="selection-check" :class="{ checked: selectedPaths.has(node.path) }">
            <IcIcon v-if="selectedPaths.has(node.path)" name="check" :size="12" />
          </span>
          <span class="column-name name-cell">
            <img class="material-file-icon" :src="materialFileIconForNode(node).src" alt="" aria-hidden="true" />
            <span class="file-name" :class="gitStatusClass(node)">{{ node.name }}</span>
          </span>
          <span class="column-modified">{{ displayMtime(node) }}</span>
          <span class="column-ingested">{{ displayIngestedAt(node) }}</span>
          <span class="column-type">{{ fileKind(node) }}</span>
          <span class="column-size">{{ formatSize(nodeSize(node)) }}</span>
          <span v-if="settingsStore.showPrivacyColumn" class="column-privacy favorite-cell">
            <PrivacyButton target-type="knowledge_path" :target-id="node.path" />
          </span>
          <span v-if="settingsStore.showFavoriteColumn" class="column-favorite favorite-cell">
            <FavoriteButton target-type="knowledge_path" :target-id="node.path" />
          </span>
          <span v-if="settingsStore.showIndexColumn" class="column-index index-status-cell" :class="indexStatusClass(node)">
            <IcIcon v-if="!node.isDir" :name="indexStatusIcon(node)" :size="13" />
            <span>{{ node.isDir ? '-' : indexStatusTitle(node) }}</span>
          </span>
          <span v-if="settingsStore.showGraphColumn" class="column-graph graph-status-cell" :class="graphStatusClass(node)">
            <IcIcon v-if="!node.isDir" :name="graphStatusIcon(node)" :size="13" />
            <span>{{ node.isDir ? '-' : graphStatusTitle(node) }}</span>
          </span>
        </button>
      </div>

      <div v-else-if="viewMode === 'content'" class="content-view">
        <div class="content-list">
          <button
            v-for="node in visibleItems"
            :key="node.path"
            class="content-item"
            :class="[
              gitStatusClass(node),
              { selected: workspaceStore.selectedTreePath === node.path || selectedPaths.has(node.path) },
            ]"
            type="button"
            @click="handleItemClick(node, $event)"
            @dblclick="handleItemDblClick(node)"
            @contextmenu.prevent.stop="openContextMenu(node, $event)"
          >
            <img class="material-file-icon material-file-icon-content" :src="materialFileIconForNode(node).src" alt="" aria-hidden="true" />
            <span class="content-text">
              <strong :class="gitStatusClass(node)">{{ node.name }}</strong>
              <small>{{ previewSummary(node) }}</small>
            </span>
            <FavoriteButton
              v-if="settingsStore.showFavoriteColumn"
              class="content-favorite"
              target-type="knowledge_path"
              :target-id="node.path"
            />
          </button>
        </div>
        <aside class="preview-pane">
          <div v-if="!selectedNode" class="preview-empty">选择一个文件查看内容</div>
          <div v-else-if="selectedNode.isDir" class="preview-empty">文件夹包含 {{ selectedNode.children?.length ?? 0 }} 项</div>
          <div v-else-if="previewLoading" class="preview-empty">正在加载内容</div>
          <div v-else-if="previewError" class="preview-empty">{{ previewError }}</div>
          <img
            v-else-if="selectedPreviewPayload?.data_url || selectedPreviewPayload?.raw_url"
            class="preview-image"
            :src="selectedPreviewPayload.data_url || selectedPreviewPayload.raw_url"
            :alt="selectedNode.name"
          />
          <div v-else-if="selectedPreviewPayload?.html" class="preview-html" v-html="selectedPreviewPayload.html"></div>
          <pre v-else class="preview-text">{{ selectedContent || selectedPreviewPayload?.message || '暂无可显示内容' }}</pre>
        </aside>
      </div>

      <div v-else class="icon-view" :class="`icon-${viewMode}`">
        <button
          v-for="node in visibleItems"
          :key="node.path"
          class="icon-tile"
          :class="[
            gitStatusClass(node),
            {
              selected: workspaceStore.selectedTreePath === node.path || selectedPaths.has(node.path),
              glass: viewMode === 'medium' || viewMode === 'large',
            },
          ]"
          type="button"
          @click="handleItemClick(node, $event)"
          @dblclick="handleItemDblClick(node)"
          @dragenter.prevent="node.isDir && handleDragEnter(node.path)"
          @dragover.prevent="node.isDir && handleDragEnter(node.path)"
          @drop.prevent.stop="handleDrop($event, node)"
          @contextmenu.prevent.stop="openContextMenu(node, $event)"
        >
          <span v-if="isMultiSelecting" class="selection-check tile-selection-check" :class="{ checked: selectedPaths.has(node.path) }">
            <IcIcon v-if="selectedPaths.has(node.path)" name="check" :size="12" />
          </span>
          <FavoriteButton
            v-if="settingsStore.showFavoriteColumn"
            class="tile-favorite"
            target-type="knowledge_path"
            :target-id="node.path"
           />
          <PrivacyButton
            v-if="settingsStore.showPrivacyColumn"
            class="tile-privacy"
            target-type="knowledge_path"
            :target-id="node.path"
          />
           <span class="tile-art">
             <AnimatedFolderIcon
               v-if="node.isDir && (viewMode === 'medium' || viewMode === 'large')"
               :size="viewMode"
               :open="workspaceStore.selectedTreePath === node.path || selectedPaths.has(node.path)"
             />
             <img
               v-else-if="viewMode === 'large' && isImageNode(node) && !privacyStore.loading && !privacyStore.isPrivate('knowledge_path', node.path) && imagePreviewUrls[node.path]"
               class="tile-image"
              :src="imagePreviewUrls[node.path]"
              :alt="node.name"
            />
            <img
              v-else
              class="material-file-icon"
              :class="{
                'material-file-icon-small': viewMode === 'small',
                'material-file-icon-medium': viewMode === 'medium',
                'material-file-icon-large': viewMode === 'large',
              }"
              :src="materialFileIconForNode(node).src"
              alt=""
              aria-hidden="true"
            />
          </span>
          <span class="tile-name" :class="gitStatusClass(node)">{{ node.name }}</span>
          <small v-if="viewMode !== 'small'">{{ formatSize(nodeSize(node)) }}</small>
        </button>
      </div>
    </div>

    <div v-if="dragging" class="drop-overlay" aria-live="polite">
      <div class="drop-box">
        <strong>拖拽到这里导入</strong>
        <span>目标: {{ dragTargetPath || currentDir || settingsStore.profile.knowledgeDir }}</span>
      </div>
    </div>
    <FileContextMenu
      v-if="contextMenu.open"
      ref="contextMenuRef"
      :node="contextMenu.node"
      :can-paste="canPaste"
      :menu-style="contextMenuStyle"
      :selection-count="contextSelectionCount"
      @create-file="createFileFromMenu"
      @create-folder="createFolderFromMenu"
      @copy="copyFromMenu"
      @cut="cutFromMenu"
      @copy-name="copyNameFromMenu"
      @copy-absolute-path="copyAbsolutePathFromMenu"
      @copy-relative-path="copyRelativePathFromMenu"
      @paste="pasteFromMenu"
      @rename="renameFromMenu"
      @show-in-folder="showInFolderFromMenu"
      @open-default="openWithDefaultFromMenu"
      @extract-graph="extractGraphFromMenu"
      @ask-agent="askAgentFromMenu"
      @html-visualize="htmlVisualizeFromMenu"
      @ingest="ingestFromMenu"
      @toggle-favorite="toggleFavoriteFromMenu"
      @toggle-privacy="togglePrivacyFromMenu"
      @toggle-ignore="toggleIgnoreFromMenu"
      @delete="deleteFromMenu"
    />
  </section>

  <!-- 模型阻断模态框 -->
  <Teleport to="body">
    <div v-if="modelModalVisible" class="model-modal-overlay" @click.self="closeModelModal">
      <div class="model-modal">
        <p class="model-modal-message">{{ modelModalMessage }}</p>
        <p class="model-modal-link">
          <a href="#" @click.prevent="goToStorageSettings">前往存储管理页面下载</a>
        </p>
        <div class="model-modal-actions">
          <button class="model-modal-btn close-btn" @click="closeModelModal">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style src="./FileResourceManager.css" scoped></style>
