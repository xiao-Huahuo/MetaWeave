<!--
  Virtual library page.

  Usage:
  Provides an explorer-like virtual library surface for user-curated books and
  collections. It stores virtual metadata through /library APIs and opens real
  knowledge files through the existing workspace editor.
-->
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import {
  createLibraryBook,
  createLibraryCollection,
  deleteLibraryItem,
  listLibraryItems,
  listLibraryTags,
  updateLibraryItem,
} from '@/api/library'
import { buildApiUrl } from '@/api/client'
import { uploadKnowledgeFile, writeKnowledgeFile } from '@/api/knowledge'
import LibraryBar from '@/components/library_view/LibraryBar.vue'
import LibraryCard from '@/components/library_view/LibraryCard.vue'
import LibraryCreateDialog from '@/components/library_view/LibraryCreateDialog.vue'
import LibraryItemDialog from '@/components/library_view/LibraryItemDialog.vue'
import { isLibrarySourceImage } from '@/components/library_view/librarySourceImage'
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
import { useFavoritesStore } from '@/stores/favorites'
import { usePrivacyStore } from '@/stores/privacy'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { LibraryBreadcrumb, LibraryItem, LibraryTag } from '@/types/knowledge'

defineOptions({ name: 'LibraryView' })

const props = withDefaults(defineProps<{
  favoritesOnlyLocked?: boolean
  privacyOnlyLocked?: boolean
}>(), {
  favoritesOnlyLocked: false,
  privacyOnlyLocked: false,
})

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const favoritesStore = useFavoritesStore()
const privacyStore = usePrivacyStore()

const items = ref<LibraryItem[]>([])
const tags = ref<LibraryTag[]>([])
const breadcrumbs = ref<LibraryBreadcrumb[]>([])
const currentParentId = ref('')
const loading = ref(false)
const query = ref('')
const selectedTag = ref('')
const selectedContentType = ref('')
const favoritesOnly = ref(false)
const privacyOnly = ref(false)
const filterMenuOpen = ref(false)
const TAGS_PER_PAGE = 10
const tagPage = ref(0)
const multiSelect = ref(false)
const viewMode = ref<'card' | 'bar'>('card')
const selectedIds = ref<Set<string>>(new Set())
const selectedItem = ref<LibraryItem | null>(null)
const detailOpen = ref(false)
const pendingAutoSelect = ref(false)
const drawerChildren = ref<LibraryItem[]>([])
const drawerChildrenLoading = ref(false)
const draggedItem = ref<LibraryItem | null>(null)
const editItem = ref<LibraryItem | null>(null)
const createDialogMode = ref<'book' | 'collection' | null>(null)
const backStack = ref<string[]>([])
const forwardStack = ref<string[]>([])
const contextMenuTarget = ref<LibraryItem | null>(null)
const contextMenuOpen = ref(false)
const contextMenuStyle = ref({ left: '0px', top: '0px' })
/** Page-level external file drag state; internal library-item drags do not enter this flow. */
const libraryFileDragDepth = ref(0)
const libraryFileDragActive = ref(false)
const libraryFileDropBusy = ref(false)

function sortItems(list: LibraryItem[]): LibraryItem[] {
  return [...list].sort((a, b) => {
    const aIsCollection = a.item_type === 'collection' ? 0 : 1
    const bIsCollection = b.item_type === 'collection' ? 0 : 1
    if (aIsCollection !== bIsCollection) return aIsCollection - bIsCollection
    const aTitle = (a.display_title || a.title || '').toLowerCase()
    const bTitle = (b.display_title || b.title || '').toLowerCase()
    return aTitle.localeCompare(bTitle)
  })
}

const selectedItems = computed(() => items.value.filter((item) => selectedIds.value.has(item.item_id)))
const effectiveFavoritesOnly = computed(() => props.favoritesOnlyLocked || favoritesOnly.value)
const effectivePrivacyOnly = computed(() => props.privacyOnlyLocked || privacyOnly.value)
const renderedItems = computed(() => {
  if (!privacyStore.hasLoaded('library_item')) return []
  const privateIds = privacyStore.idsFor('library_item')
  if (effectivePrivacyOnly.value) {
    return items.value.filter((item) => privateIds.has(item.item_id))
  }
  const visibleItems = items.value.filter((item) => !privateIds.has(item.item_id))
  if (effectiveFavoritesOnly.value) {
    const favoriteIds = favoritesStore.idsFor('library_item')
    return visibleItems.filter((item) => favoriteIds.has(item.item_id))
  }
  return visibleItems
})
const hasSelection = computed(() => selectedIds.value.size > 0)
const canGoUp = computed(() => Boolean(currentParentId.value))
const canGoBack = computed(() => backStack.value.length > 0)
const canGoForward = computed(() => forwardStack.value.length > 0)
const virtualPath = computed(() => ['图书馆', ...breadcrumbs.value.map((crumb) => crumb.title)].join(' / '))
const drawerOpen = computed(() => Boolean(selectedItem.value) && !multiSelect.value && detailOpen.value)
const selectedDate = computed(() => formatDate(selectedItem.value?.source_mtime || selectedItem.value?.updated_at || ''))
const tagPageCount = computed(() => Math.max(1, Math.ceil(tags.value.length / TAGS_PER_PAGE)))
const pagedTags = computed(() => tags.value.slice(tagPage.value * TAGS_PER_PAGE, (tagPage.value + 1) * TAGS_PER_PAGE))

watch(
  [query, selectedTag, selectedContentType, currentParentId],
  () => {
    void loadItems()
  },
)

watch(multiSelect, (enabled) => {
  if (enabled) {
    selectedItem.value = null
  } else {
    selectedIds.value = new Set()
  }
})

watch(tags, () => {
  if (tagPage.value >= tagPageCount.value) {
    tagPage.value = Math.max(0, tagPageCount.value - 1)
  }
})

watch(
  () => workspaceStore.pendingLibraryParentId,
  (parentId) => {
    if (!parentId) return
    navigateTo(parentId)
    workspaceStore.pendingLibraryParentId = ''
  },
  { immediate: true },
)

watch(
  () => workspaceStore.pendingMainSearchResult,
  (result) => {
    if (result?.source !== 'library') return
    const item = result.item as unknown as LibraryItem
    navigateTo(item.parent_id || '')
    selectedItem.value = item
    detailOpen.value = true
    workspaceStore.pendingMainSearchResult = null
  },
  { immediate: true },
)

watch(selectedItem, (item) => {
  if (item?.item_type === 'collection') {
    void loadDrawerChildren(item.item_id)
  } else {
    drawerChildren.value = []
  }
})

onMounted(async () => {
  await Promise.all([
    loadItems(),
    loadTags(),
    workspaceStore.loadKnowledgeTree(),
    settingsStore.profile.userId
      ? favoritesStore.load(settingsStore.profile.userId, 'library_item', favoritesStore.activeLibraryId())
      : Promise.resolve(),
    settingsStore.profile.userId
      ? privacyStore.load(settingsStore.profile.userId, 'library_item', privacyStore.activeLibraryId())
      : Promise.resolve(),
  ])
  document.addEventListener('click', handleDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
})

/** Clear the active book and its detail popup when clicking outside library items. */
function handleDocumentClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element) || target.closest('.library-card, .library-bar, .context-menu')) {
    closeContextMenu()
    return
  }
  selectedItem.value = null
  detailOpen.value = false
  closeContextMenu()
}

async function loadItems() {
  if (!settingsStore.profile.userId) return
  loading.value = true
  try {
    const response = await listLibraryItems({
      userId: settingsStore.profile.userId,
      parentId: currentParentId.value,
      query: query.value,
      tag: selectedTag.value,
      contentType: selectedContentType.value,
      sort: 'updated_at',
      direction: 'desc',
    })
    items.value = sortItems(response.items)
    breadcrumbs.value = response.breadcrumbs
    selectedIds.value = new Set([...selectedIds.value].filter((id) => response.items.some((item) => item.item_id === id)))
    if (selectedItem.value) {
      selectedItem.value = response.items.find((item) => item.item_id === selectedItem.value?.item_id) ?? null
    }
    const firstItem = response.items[0]
    if (pendingAutoSelect.value && firstItem) {
      selectedItem.value = firstItem
      pendingAutoSelect.value = false
    }
  } finally {
    loading.value = false
    pendingAutoSelect.value = false
  }
}

async function loadTags() {
  if (!settingsStore.profile.userId) return
  const response = await listLibraryTags(settingsStore.profile.userId)
  tags.value = response.tags
}

async function loadDrawerChildren(parentId: string) {
  if (!settingsStore.profile.userId) return
  drawerChildrenLoading.value = true
  try {
    const response = await listLibraryItems({
      userId: settingsStore.profile.userId,
      parentId,
      sort: 'updated_at',
      direction: 'desc',
    })
    drawerChildren.value = sortItems(response.items)
  } finally {
    drawerChildrenLoading.value = false
  }
}

function navigateTo(parentId: string, recordHistory = true) {
  const nextParentId = parentId.trim()
  if (nextParentId === currentParentId.value) return
  if (recordHistory) {
    backStack.value = [...backStack.value, currentParentId.value]
    forwardStack.value = []
  }
  currentParentId.value = nextParentId
  selectedIds.value = new Set()
  selectedItem.value = null
}

function goBack() {
  const target = backStack.value[backStack.value.length - 1]
  if (target === undefined) return
  backStack.value = backStack.value.slice(0, -1)
  forwardStack.value = [...forwardStack.value, currentParentId.value]
  navigateTo(target, false)
}

function goForward() {
  const target = forwardStack.value[forwardStack.value.length - 1]
  if (target === undefined) return
  forwardStack.value = forwardStack.value.slice(0, -1)
  backStack.value = [...backStack.value, currentParentId.value]
  navigateTo(target, false)
}

function goUp() {
  if (!currentParentId.value) return
  const parent = breadcrumbs.value[breadcrumbs.value.length - 2]?.item_id ?? ''
  navigateTo(parent)
}

function refreshLibrary() {
  void Promise.all([
    loadItems(),
    loadTags(),
    selectedItem.value?.item_type === 'collection' ? loadDrawerChildren(selectedItem.value.item_id) : Promise.resolve(),
    workspaceStore.loadKnowledgeTree(),
    settingsStore.profile.userId
      ? favoritesStore.load(settingsStore.profile.userId, 'library_item', favoritesStore.activeLibraryId())
      : Promise.resolve(),
    settingsStore.profile.userId
      ? privacyStore.load(settingsStore.profile.userId, 'library_item', privacyStore.activeLibraryId())
      : Promise.resolve(),
  ])
}

function goBreadcrumb(itemId: string) {
  navigateTo(itemId)
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

function selectItem(item: LibraryItem) {
  if (multiSelect.value) {
    toggleItem(item)
    return
  }
  // 单击仅做卡片高亮,不再呼出右侧边栏;边栏只能通过右键菜单"详细信息"打开
  selectedItem.value = item
  detailOpen.value = false
}

async function openItem(item: LibraryItem) {
  if (item.item_type === 'collection') {
    if (selectedItem.value) {
      // 侧边栏已打开时双击集锦导航，导航后自动选中新视图第一项以保持侧边栏开启
      pendingAutoSelect.value = true
    }
    selectedItem.value = null
    navigateTo(item.item_id)
    return
  }
  if (item.content_type === 'web_url' && item.source_url) {
    workspaceStore.openBrowserSidebar(item.source_url)
    return
  }
  if (item.source_path) {
    workspaceStore.setMainView('editor')
    await workspaceStore.selectFile({
      name: item.source_name || item.source_path.split('/').pop() || item.source_path,
      path: item.source_path,
      isDir: false,
      mtime: item.source_mtime,
      indexStatus: item.index_status === 'missing' ? undefined : item.index_status || undefined,
      graphStatus: item.graph_status || undefined,
    })
  }
}

async function openSource(item: LibraryItem) {
  if (item.content_type === 'web_url' && item.source_url) {
    workspaceStore.openBrowserSidebar(item.source_url)
    return
  }
  if (item.source_path) {
    await workspaceStore.openEditorSidebar({
      name: item.source_name || item.source_path.split('/').pop() || item.source_path,
      path: item.source_path,
      isDir: false,
      mtime: item.source_mtime,
      indexStatus: item.index_status === 'missing' ? undefined : item.index_status || undefined,
      graphStatus: item.graph_status || undefined,
    })
  }
}

async function openSourceFromEdit(item: LibraryItem) {
  editItem.value = null
  await openSource(item)
}

function openUrlFromEdit(url: string) {
  editItem.value = null
  workspaceStore.openBrowserSidebar(url)
}

function toggleItem(item: LibraryItem) {
  const next = new Set(selectedIds.value)
  if (next.has(item.item_id)) {
    next.delete(item.item_id)
  } else {
    next.add(item.item_id)
  }
  selectedIds.value = next
}

function cancelMultiSelect() {
  multiSelect.value = false
  selectedIds.value = new Set()
}

function openContextMenu(event: MouseEvent, item: LibraryItem) {
  contextMenuTarget.value = item
  contextMenuOpen.value = true
  const x = Math.min(event.clientX, window.innerWidth - 180)
  const y = Math.min(event.clientY, window.innerHeight - 240)
  contextMenuStyle.value = { left: `${x}px`, top: `${y}px` }
}

function closeContextMenu() {
  contextMenuOpen.value = false
  contextMenuTarget.value = null
}

function contextEdit() {
  if (!contextMenuTarget.value) return
  editItem.value = contextMenuTarget.value
  closeContextMenu()
}

function contextDetails() {
  const item = contextMenuTarget.value
  closeContextMenu()
  if (!item) return
  selectedItem.value = item
  detailOpen.value = true
}

function closeDetails() {
  selectedItem.value = null
  detailOpen.value = false
}

async function contextMoveToParent() {
  const item = contextMenuTarget.value
  closeContextMenu()
  if (!item || !currentParentId.value) return
  items.value = sortItems(items.value.filter((i) => i.item_id !== item.item_id))
  try {
    await updateLibraryItem(item.item_id, {
      user_id: settingsStore.profile.userId,
      parent_id: '',
    })
    workspaceStore.showToast(`已移动到根目录`)
    await loadItems()
  } catch (error) {
    workspaceStore.showToast(`移动失败 — ${errorMessage(error)}`)
    await loadItems()
  }
}

async function contextDelete() {
  const item = contextMenuTarget.value
  closeContextMenu()
  if (!item) return
  if (!window.confirm(`移出图书馆: ${item.display_title}? 真实文件不会被删除。`)) return
  items.value = sortItems(items.value.filter((i) => i.item_id !== item.item_id))
  selectedItem.value = null
  try {
    await deleteLibraryItem(settingsStore.profile.userId, item.item_id)
    await loadItems()
  } catch {
    await loadItems()
  }
}

function startDrag(item: LibraryItem) {
  draggedItem.value = item
}

async function dropOnItem(target: LibraryItem) {
  const source = draggedItem.value
  draggedItem.value = null
  if (!source || target.item_type !== 'collection' || source.item_id === target.item_id) return
  items.value = sortItems(items.value.filter((item) => item.item_id !== source.item_id))
  try {
    await updateLibraryItem(source.item_id, {
      user_id: settingsStore.profile.userId,
      parent_id: target.item_id,
    })
    workspaceStore.showToast(`已移动到 ${target.display_title}`)
    await loadItems()
  } catch (error) {
    workspaceStore.showToast(`移动失败 — ${errorMessage(error)}`)
    await loadItems()
  }
}

function openCreateBookDialog() {
  createDialogMode.value = 'book'
}

function openCreateCollectionDialog() {
  createDialogMode.value = 'collection'
}

/** Return whether one drag event carries operating-system files rather than an internal library item. */
function carriesExternalFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/** Show one page-level drop target while an external file crosses nested library elements. */
function handleLibraryFileDragEnter(event: DragEvent) {
  if (!carriesExternalFiles(event) || libraryFileDropBusy.value) return
  event.preventDefault()
  libraryFileDragDepth.value += 1
  libraryFileDragActive.value = true
}

/** Keep external file drops enabled without interfering with the existing internal item drag flow. */
function handleLibraryFileDragOver(event: DragEvent) {
  if (!carriesExternalFiles(event) || libraryFileDropBusy.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

/** Hide the page-level target only after the external drag leaves the complete library surface. */
function handleLibraryFileDragLeave(event: DragEvent) {
  if (!carriesExternalFiles(event)) return
  libraryFileDragDepth.value = Math.max(0, libraryFileDragDepth.value - 1)
  if (libraryFileDragDepth.value === 0) libraryFileDragActive.value = false
}

/** Upload one source file and persist its virtual book through the existing production APIs. */
async function createFileBook(sourceFile: File, payload: {
  title: string
  description: string
  tags: string[]
  cover_mode: LibraryItem['cover_mode']
  cover_asset_id: string
}): Promise<boolean> {
  const libraryStorageDir = settingsStore.activeKnowledgeLibrary?.libraryStorageDir || '.mw/library'
  const result = await uploadKnowledgeFile(settingsStore.profile.userId, sourceFile, libraryStorageDir, false, 'rename') as { uploaded_path?: string; knowledge_dir?: string }
  const relativePath = relativeUploadedPath(result.uploaded_path ?? '', result.knowledge_dir ?? settingsStore.profile.knowledgeDir)
  if (!relativePath) return false
  await createLibraryBook({
    user_id: settingsStore.profile.userId,
    parent_id: currentParentId.value,
    content_type: 'knowledge_file',
    source_path: relativePath,
    title: payload.title,
    description: payload.description,
    cover_mode: payload.cover_mode,
    cover_asset_id: payload.cover_asset_id,
    tags: payload.tags,
  })
  return true
}

/** Create a book immediately when one external file is dropped on the library page. */
async function handleLibraryFileDrop(event: DragEvent) {
  if (!carriesExternalFiles(event) || libraryFileDropBusy.value) return
  event.preventDefault()
  libraryFileDragDepth.value = 0
  libraryFileDragActive.value = false
  const sourceFile = event.dataTransfer?.files?.[0]
  if (!sourceFile) return
  libraryFileDropBusy.value = true
  try {
    const created = await createFileBook(sourceFile, {
      title: '',
      description: '',
      tags: [],
      cover_mode: isLibrarySourceImage(sourceFile.name, sourceFile.type) ? 'source_image' : 'title',
      cover_asset_id: '',
    })
    if (!created) {
      workspaceStore.showToast('上传完成但无法识别知识库相对路径')
      return
    }
    await workspaceStore.loadKnowledgeTree()
    await Promise.all([loadItems(), loadTags()])
    workspaceStore.showToast('已从拖入文件创建图书')
  } catch (error) {
    workspaceStore.showToast(`创建失败 — ${errorMessage(error)}`)
  } finally {
    libraryFileDropBusy.value = false
  }
}

async function createFromDialog(payload: {
  title: string
  description: string
  tags: string[]
  cover_mode: LibraryItem['cover_mode']
  cover_asset_id: string
  file: File | null
  source_mode: 'file' | 'text' | 'script' | 'url'
  text_content: string
  script_extension: string
  source_url: string
}) {
  const mode = createDialogMode.value
  if (!mode) return
  try {
    if (mode === 'collection') {
      await createLibraryCollection({
        user_id: settingsStore.profile.userId,
        parent_id: currentParentId.value,
        title: payload.title,
        description: payload.description,
        cover_mode: payload.cover_mode,
        cover_asset_id: payload.cover_asset_id,
        tags: payload.tags,
      })
      workspaceStore.showToast('已新增集锦')
    } else if (payload.source_mode === 'url') {
      if (!payload.source_url) {
        workspaceStore.showToast('请输入 URL')
        return
      }
      await createLibraryBook({
        user_id: settingsStore.profile.userId,
        parent_id: currentParentId.value,
        content_type: 'web_url',
        source_url: payload.source_url,
        title: payload.title,
        description: payload.description,
        cover_mode: payload.cover_mode,
        cover_asset_id: payload.cover_asset_id,
        tags: payload.tags,
      })
      workspaceStore.showToast('已新增网页并加入图书馆')
    } else {
      const sourceFile = payload.source_mode === 'text' || payload.source_mode === 'script'
        ? createTextSourceFile(payload.title, payload.text_content, payload.source_mode === 'script' ? payload.script_extension : '.md')
        : payload.file
      if (!sourceFile) {
        workspaceStore.showToast('请选择真实文件')
        return
      }
      if ((payload.source_mode === 'text' || payload.source_mode === 'script') && !payload.text_content.trim()) {
        workspaceStore.showToast('请输入文本内容')
        return
      }
      const created = await createFileBook(sourceFile, {
        title: payload.title,
        description: payload.description,
        cover_mode: payload.cover_mode,
        cover_asset_id: payload.cover_asset_id,
        tags: payload.tags,
      })
      if (!created) {
        workspaceStore.showToast('上传完成但无法识别知识库相对路径')
        return
      }
      await workspaceStore.loadKnowledgeTree()
      workspaceStore.showToast(payload.source_mode === 'script' ? '已保存脚本并加入图书馆' : payload.source_mode === 'text' ? '已保存文本并加入图书馆' : '已新增文件并加入图书馆')
    }
    createDialogMode.value = null
    await Promise.all([loadItems(), loadTags()])
  } catch (error) {
    workspaceStore.showToast(`创建失败 — ${errorMessage(error)}`)
  }
}

async function saveEdit(payload: {
  title: string
  description: string
  cover_mode: LibraryItem['cover_mode']
  cover_asset_id: string
  tags: string[]
  source_content?: string
}) {
  if (!editItem.value) return
  const item = editItem.value
  if (payload.source_content !== undefined && item.source_path) {
    await writeKnowledgeFile(settingsStore.profile.userId, item.source_path, payload.source_content)
    await workspaceStore.loadKnowledgeTree()
  }
  await updateLibraryItem(item.item_id, {
    user_id: settingsStore.profile.userId,
    title: payload.title,
    description: payload.description,
    cover_mode: payload.cover_mode,
    cover_asset_id: payload.cover_asset_id,
    tags: payload.tags,
  })
  editItem.value = null
  await Promise.all([loadItems(), loadTags()])
}

/** Persist one double-click inline title or description edit without opening the dialog. */
async function saveInlineEdit(item: LibraryItem, payload: { title?: string; description?: string }) {
  try {
    const response = await updateLibraryItem(item.item_id, {
      user_id: settingsStore.profile.userId,
      ...payload,
    })
    items.value = items.value.map((entry) => entry.item_id === item.item_id ? response.item : entry)
    if (selectedItem.value?.item_id === item.item_id) selectedItem.value = response.item
  } catch (error) {
    workspaceStore.showToast(`保存失败 — ${errorMessage(error)}`)
  }
}

async function removeSelected() {
  if (!hasSelection.value) return
  if (!window.confirm(`移出选中的 ${selectedIds.value.size} 项? 真实文件不会被删除。`)) return
  for (const item of selectedItems.value) {
    await deleteLibraryItem(settingsStore.profile.userId, item.item_id)
  }
  selectedIds.value = new Set()
  await loadItems()
}

function createTextSourceFile(title: string, content: string, extension: string): File {
  const baseName = sanitizeTextFileName(title) || `图书馆文本-${Date.now()}`
  const suffix = normalizeFileExtension(extension)
  const fileName = baseName.toLowerCase().endsWith(suffix) ? baseName : `${baseName}${suffix}`
  return new File([content], fileName, { type: suffix === '.md' ? 'text/markdown;charset=utf-8' : 'text/plain;charset=utf-8' })
}

/** Limit user-entered script suffixes to one safe filename extension. */
function normalizeFileExtension(value: string): string {
  const normalized = value.trim().replace(/^\.+/, '')
  return /^[a-z0-9][a-z0-9_-]{0,15}$/iu.test(normalized) ? `.${normalized}` : '.txt'
}

/** Download a book's real knowledge file, or its original URL resource. */
function downloadItem(item: LibraryItem): void {
  if (item.item_type === 'collection') return
  const url = item.source_path
    ? buildApiUrl('/knowledge/files/raw', { user_id: item.user_id, path: item.source_path, download: 'true' })
    : item.source_url
  if (!url) return
  triggerBrowserDownload(url, item.source_name || item.display_title)
}

/** Export an uploaded cover or the source file when it is the active cover. */
function downloadCover(item: LibraryItem): void {
  const url = item.cover_asset?.url || (item.cover_mode === 'source_image' && item.source_path
    ? buildApiUrl('/knowledge/files/raw', { user_id: item.user_id, path: item.source_path, download: 'true' })
    : '')
  if (!url) return
  triggerBrowserDownload(url, item.cover_asset?.file_name || `${item.display_title}-cover`)
}

function hasExportableCover(item: LibraryItem | null): boolean {
  return Boolean(item?.cover_asset?.url || (item?.cover_mode === 'source_image' && item.source_path))
}

function triggerBrowserDownload(url: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

function contextDownloadItem() {
  const item = contextMenuTarget.value
  closeContextMenu()
  if (item) downloadItem(item)
}

function contextDownloadCover() {
  const item = contextMenuTarget.value
  closeContextMenu()
  if (item) downloadCover(item)
}

function sanitizeTextFileName(rawTitle: string): string {
  return rawTitle
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '')
    .replace(/\s+/g, ' ')
    .slice(0, 80)
}

function relativeUploadedPath(uploadedPath: string, knowledgeDir: string): string {
  const normalizedRoot = knowledgeDir.replace(/\\/g, '/').replace(/\/+$/g, '')
  const normalizedPath = uploadedPath.replace(/\\/g, '/')
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1)
  }
  return normalizedPath.split('/').pop() ?? ''
}

function formatDate(raw: string): string {
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw.slice(0, 16)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请检查后端连接'
}
</script>

<template>
  <section
    class="library-view"
    @dragenter="handleLibraryFileDragEnter"
    @dragover="handleLibraryFileDragOver"
    @dragleave="handleLibraryFileDragLeave"
    @drop="handleLibraryFileDrop"
  >
    <div v-if="libraryFileDragActive || libraryFileDropBusy" class="library-file-drop-overlay" aria-live="polite">
      {{ libraryFileDropBusy ? '正在自动创建图书' : '松开文件即可自动创建图书；图片文件将直接作为封面' }}
    </div>
    <header class="library-toolbar">
      <div class="nav-row">
        <div class="nav-buttons">
          <button class="icon-toolbar-btn" type="button" title="回退" :disabled="!canGoBack" @click="goBack">
            <IcIcon name="arrow-left" :size="17" />
          </button>
          <button class="icon-toolbar-btn" type="button" title="反回退" :disabled="!canGoForward" @click="goForward">
            <IcIcon name="arrow-right" :size="17" />
          </button>
          <button class="icon-toolbar-btn" type="button" title="回到上级目录" :disabled="!canGoUp" @click="goUp">
            <IcIcon name="arrow-up" :size="17" />
          </button>
          <button class="icon-toolbar-btn" type="button" title="刷新" @click="refreshLibrary">
            <IcIcon name="refresh" :size="17" />
          </button>
        </div>
        <nav class="path-box" :title="virtualPath">
          <button class="path-segment" type="button" title="图书馆根目录" @click="goBreadcrumb('')">图书馆</button>
          <template v-for="crumb in breadcrumbs" :key="crumb.item_id">
            <span class="path-separator">/</span>
            <button class="path-segment" type="button" :title="crumb.title" @click="goBreadcrumb(crumb.item_id)">
              {{ crumb.title }}
            </button>
          </template>
        </nav>
        <label class="search-box">
          <IcIcon name="search" :size="14" />
          <input v-model="query" type="search" placeholder="查找" />
        </label>
        <DropdownMenu v-model:open="filterMenuOpen">
          <DropdownMenuTrigger as-child>
            <button
              class="filter-capsule-btn"
              :class="{ active: selectedContentType || selectedTag }"
              type="button"
              title="筛选"
            >
              <IcIcon name="filter" :size="17" />
              <span>筛选</span>
              <IcIcon class="filter-chevron" name="chevron-down" :size="14" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="library-filter-menu" align="end">
              <DropdownMenuGroup>
                <DropdownMenuLabel>类型</DropdownMenuLabel>
                <DropdownMenuRadioGroup v-model="selectedContentType">
                  <DropdownMenuRadioItem value="">全部</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="knowledge_file">知识库文件</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="web_url">网页</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem value="collection">集锦</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuLabel>标签</DropdownMenuLabel>
                <DropdownMenuRadioGroup v-model="selectedTag">
                  <DropdownMenuRadioItem value="">全部</DropdownMenuRadioItem>
                  <DropdownMenuRadioItem v-for="tag in pagedTags" :key="tag.name" :value="tag.name">
                    {{ tag.name }}
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
                <div v-if="tagPageCount > 1" class="filter-pagination">
                  <button
                    class="filter-page-btn"
                    type="button"
                    :disabled="tagPage <= 0"
                    @click.stop="tagPage -= 1"
                  >
                    上一页
                  </button>
                  <span class="filter-page-info">{{ tagPage + 1 }} / {{ tagPageCount }}</span>
                  <button
                    class="filter-page-btn"
                    type="button"
                    :disabled="tagPage >= tagPageCount - 1"
                    @click.stop="tagPage += 1"
                  >
                    下一页
                  </button>
                </div>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenu>
        <div class="library-actions" aria-label="图书馆操作">
          <button class="tool-button v1-icon-button" type="button" title="新增文件" @click="openCreateBookDialog">
            <IcIcon name="new-file" :size="17" />
          </button>
          <button
            class="tool-button v1-icon-button"
            :class="{ active: effectiveFavoritesOnly }"
            type="button"
            title="我的收藏"
            :aria-pressed="effectiveFavoritesOnly"
            :disabled="favoritesOnlyLocked"
            @click="toggleFavoritesOnly"
          >
            <IcIcon name="star" :size="17" />
          </button>
          <button
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
          <button class="tool-button v1-icon-button" type="button" title="新增集锦" @click="openCreateCollectionDialog">
            <IcIcon name="new-folder" :size="17" />
          </button>
          <button class="tool-button v1-icon-button" :class="{ active: multiSelect }" type="button" title="多选" @click="multiSelect = !multiSelect">
            <IcIcon name="label" :size="17" />
            <span v-if="multiSelect" class="multi-indicator">{{ selectedIds.size }}</span>
          </button>
          <button
            class="view-button"
            :class="{ active: viewMode === 'bar' }"
            type="button"
            :title="viewMode === 'card' ? '切换为条形' : '切换为卡片'"
            @click="viewMode = viewMode === 'card' ? 'bar' : 'card'"
          >
            <IcIcon v-if="viewMode === 'card'" name="view-stream" :size="17" />
            <IcIcon v-else name="grid-view" :size="17" />
            <span>{{ viewMode === 'card' ? '条形' : '卡片' }}</span>
          </button>
        </div>
      </div>
    </header>

    <section v-if="multiSelect" class="multi-banner">
      <span>已选择 {{ selectedIds.size }} 项</span>
      <div class="banner-actions">
        <button class="delete-btn" type="button" :disabled="!hasSelection" title="移出" @click="removeSelected">
          <svg viewBox="0 0 448 512" class="svgIcon"><path d="M135.2 17.7L128 32H32C14.3 32 0 46.3 0 64S14.3 96 32 96H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H320l-7.2-14.3C307.4 6.8 296.3 0 284.2 0H163.8c-12.1 0-23.2 6.8-28.6 17.7zM416 128H32L53.2 467c1.6 25.3 22.6 45 47.9 45H346.9c25.3 0 46.3-19.7 47.9-45L416 128z"></path></svg>
        </button>
        <button class="banner-close" type="button" title="取消多选" @click="cancelMultiSelect">
          <IcIcon name="close" :size="14" />
        </button>
      </div>
    </section>

    <section class="library-content">
      <main class="library-body">
        <div v-if="renderedItems.length === 0 && !loading" class="empty-hint">
          当前集锦为空。新增文件或创建集锦后会出现在这里。
        </div>
        <TransitionGroup
          v-else-if="renderedItems.length"
          appear
          :name="viewMode === 'card' ? 'card' : 'bar'"
          tag="div"
          :class="viewMode === 'card' ? 'library-grid' : 'library-list'"
        >
          <component
            :is="viewMode === 'card' ? LibraryCard : LibraryBar"
            v-for="(item, i) in renderedItems"
            :key="item.item_id"
            :style="{ '--i': i }"
            :item="item"
            :selected="multiSelect ? selectedIds.has(item.item_id) : selectedItem?.item_id === item.item_id"
            :multi-select="multiSelect"
            @open="openItem"
            @edit="editItem = $event"
            @contextmenu="openContextMenu"
            @download="downloadItem"
            @save="saveInlineEdit"
            @toggle="toggleItem"
            @select="selectItem"
            @drag-start="startDrag"
            @drop-on="dropOnItem"
          />
        </TransitionGroup>
      </main>

      <aside class="detail-drawer" :class="{ open: drawerOpen }">
        <template v-if="selectedItem">
          <header class="drawer-head">
            <div class="drawer-title" :title="selectedItem.display_title">{{ selectedItem.display_title }}</div>
            <button class="icon-toolbar-btn" type="button" title="关闭" @click="closeDetails">
              <IcIcon name="close" :size="15" />
            </button>
          </header>
          <div class="drawer-section">
            <div class="drawer-kv">
              <IcIcon v-if="selectedItem.item_type === 'collection'" name="folder-open" :size="15" />
              <IcIcon v-else-if="selectedItem.content_type === 'web_url'" name="link" :size="15" />
              <IcIcon v-else name="ingest" :size="15" />
              <span>{{ selectedItem.item_type === 'collection' ? '集锦' : selectedItem.source_name || selectedItem.source_path }}</span>
            </div>
            <div class="drawer-kv">
              <IcIcon name="event" :size="15" />
              <span>{{ selectedDate || '无日期' }}</span>
            </div>
            <div class="drawer-kv">
              <IcIcon name="ingest" :size="15" />
              <span>{{ selectedItem.item_type === 'collection' ? `${selectedItem.child_count} 项` : `${selectedItem.source_size || 0} bytes` }}</span>
            </div>
          </div>
          <div v-if="selectedItem.description" class="drawer-section">
            <div class="drawer-label">描述</div>
            <p class="drawer-description">{{ selectedItem.description }}</p>
          </div>
          <div v-if="selectedItem.tags.length" class="drawer-section">
            <div class="drawer-label">标签</div>
            <div class="drawer-tags">
              <span v-for="tag in selectedItem.tags" :key="tag" class="tag-pill">{{ tag }}</span>
            </div>
          </div>
          <div v-if="selectedItem.item_type === 'collection'" class="drawer-section drawer-section-grow">
            <div class="drawer-label">内容</div>
            <div v-if="drawerChildrenLoading" class="drawer-empty">正在读取</div>
            <div v-else-if="drawerChildren.length === 0" class="drawer-empty">空集锦</div>
            <template v-else>
              <button
                v-for="child in drawerChildren"
                :key="child.item_id"
                class="drawer-child"
                type="button"
                :title="child.display_title"
                @click="selectItem(child)"
                @dblclick.stop="openItem(child)"
              >
                <IcIcon v-if="child.item_type === 'collection'" name="folder-open" :size="14" />
                <IcIcon v-else-if="child.content_type === 'web_url'" name="link" :size="14" />
                <IcIcon v-else name="ingest" :size="14" />
                <span>{{ child.display_title }}</span>
              </button>
            </template>
          </div>
        </template>
      </aside>
    </section>

    <ul v-if="contextMenuOpen" class="context-menu" :style="contextMenuStyle" @click.stop>
      <li class="context-item" @click="openCreateBookDialog(); closeContextMenu()">
        <IcIcon name="new-file" :size="14" />
        <span>新增文件</span>
      </li>
      <li class="context-item" @click="openCreateCollectionDialog(); closeContextMenu()">
        <IcIcon name="new-folder" :size="14" />
        <span>新增集锦</span>
      </li>
      <li class="context-item" @click="contextDetails()">
        <IcIcon name="info" :size="14" />
        <span>详细信息</span>
      </li>
      <li class="context-item" @click="contextEdit()">
        <IcIcon name="edit" :size="14" />
        <span>编辑</span>
      </li>
      <li v-if="contextMenuTarget?.item_type === 'book'" class="context-item" @click="contextDownloadItem()">
        <IcIcon name="download" :size="14" />
        <span>导出真实文件</span>
      </li>
      <li
        v-if="contextMenuTarget?.item_type === 'book'"
        class="context-item"
        :class="{ disabled: !hasExportableCover(contextMenuTarget) }"
        :aria-disabled="!hasExportableCover(contextMenuTarget)"
        @click="contextDownloadCover()"
      >
        <IcIcon name="image" :size="14" />
        <span>导出封面</span>
      </li>
      <li class="context-item" @click="contextMoveToParent()">
        <IcIcon name="arrow-up" :size="14" />
        <span>移动到上一级集锦</span>
      </li>
      <hr class="context-sep" />
      <li class="context-item danger" @click="contextDelete()">
        <IcIcon name="trash" :size="14" />
        <span>删除</span>
      </li>
    </ul>
    <LibraryItemDialog
      :open="Boolean(editItem)"
      :item="editItem"
      :user-id="settingsStore.profile.userId"
      :available-tags="tags"
      @close="editItem = null"
      @save="saveEdit"
      @open-file="openSourceFromEdit"
      @open-url="openUrlFromEdit"
    />
    <LibraryCreateDialog
      :open="Boolean(createDialogMode)"
      :mode="createDialogMode ?? 'book'"
      :user-id="settingsStore.profile.userId"
      :available-tags="tags"
      @close="createDialogMode = null"
      @create="createFromDialog"
    />
  </section>
</template>

<style scoped>
.library-view {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  container-type: inline-size;
  background: var(--color-canvas);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
}

.library-file-drop-overlay {
  position: absolute;
  inset: 8px;
  z-index: 40;
  display: grid;
  place-items: center;
  pointer-events: none;
  border: 2px dashed var(--color-primary);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-surface) 88%, transparent);
  color: var(--color-primary);
  padding: 24px;
  text-align: center;
  font-size: calc(14px * var(--font-scale));
  font-weight: 700;
}

.library-toolbar {
  display: flex;
  align-items: center;
  min-width: 0;
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
  border-bottom: 0;
  background: var(--color-surface-raised);
  font-size: calc(12px * var(--font-scale));
}

.nav-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex: 1 1 auto;
  min-width: 0;
  flex-wrap: nowrap;
}

.nav-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.library-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex: 0 0 auto;
}

.icon-toolbar-btn,
.path-segment,
.search-box {
  display: inline-flex;
  align-items: center;
  height: 28px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
}

.icon-toolbar-btn {
  position: relative;
  justify-content: center;
  width: 28px;
  padding: 0;
}

.tool-button,
.view-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0;
}

.tool-button:disabled {
  cursor: default;
  opacity: 0.35;
}

.view-button {
  overflow: hidden;
  flex: 0 0 auto;
  width: auto;
  min-width: 28px;
  gap: var(--space-4);
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  transition:
    background 180ms ease,
    border-color 180ms ease,
  color 180ms ease;
  white-space: nowrap;
}

.tool-button.active,
.tool-button:hover,
.view-button.active,
.view-button:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.icon-toolbar-btn:hover,
.path-segment:hover {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
}

.icon-toolbar-btn.active {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.icon-toolbar-btn.danger {
  color: var(--color-danger);
}

.icon-toolbar-btn:disabled {
  opacity: 0.38;
  pointer-events: none;
}

.path-box {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 160px;
  height: 28px;
  overflow: hidden;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-canvas);
  padding: 0 10px;
}

.path-segment {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: transparent;
  box-shadow: none;
  padding: 0 7px;
}

.path-separator {
  color: var(--color-text-muted);
}

.search-box {
  flex: 0 1 220px;
  gap: 6px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
}

.search-box input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.library-filter-menu {
  width: 260px;
  max-height: min(520px, var(--reka-dropdown-menu-content-available-height));
  overflow-y: auto;
}

.filter-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px 2px;
  border-top: 1px solid var(--color-border);
  margin-top: 4px;
}

.filter-page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  height: 24px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
  padding: 0 8px;
}

.filter-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-page-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.filter-page-info {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  white-space: nowrap;
}

.multi-indicator {
  position: absolute;
  top: -4px;
  right: -4px;
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--color-primary);
  color: #fff;
  font-size: calc(10px * var(--font-scale));
  font-weight: 700;
  padding: 0 4px;
}

.multi-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 28px;
  padding: 0 10px;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-primary) 8%, transparent);
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.banner-close {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.banner-close:hover {
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger);
}

.delete-btn {
  width: 25px;
  height: 25px;
  border-radius: 50%;
  background-color: var(--color-canvas);
  border: 1px solid var(--color-border);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: none;
  cursor: pointer;
  transition-duration: .3s;
  overflow: hidden;
  position: relative;
  flex-shrink: 0;
  padding: 0;
}

.delete-btn .svgIcon {
  width: 12px;
  transition-duration: .3s;
}

.delete-btn .svgIcon path {
  fill: rgb(255, 69, 69);
}

.delete-btn:hover {
  width: 70px;
  border-radius: 50px;
  transition-duration: .3s;
  background-color: rgb(255, 69, 69);
  border-color: rgb(255, 69, 69);
}

.delete-btn:hover .svgIcon {
  width: 25px;
  transition-duration: .3s;
  transform: translateY(60%);
}

.delete-btn:hover .svgIcon path {
  fill: white;
}

.delete-btn:disabled {
  opacity: 0.4;
  pointer-events: none;
}

.library-content {
  display: flex;
  flex-direction: row;
  align-items: stretch;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.library-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: auto;
  padding: 16px;
}

.library-grid {
  column-width: 248px;
  column-gap: 16px;
  position: relative;
}

.library-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
  gap: 10px;
  align-items: start;
  position: relative;
}

.card-move {
  transition: transform 400ms ease;
}

.card-enter-active {
  animation: card-in 350ms ease both;
  animation-delay: calc(var(--i, 0) * 40ms);
}

.card-leave-active {
  transition: opacity 300ms ease;
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: scale(0.92) translateY(12px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.card-leave-to {
  opacity: 0;
}

.bar-move {
  transition: transform 360ms ease;
}

.bar-enter-active {
  position: relative;
  animation: bar-scan-in 420ms ease both;
  animation-delay: calc(var(--i, 0) * 55ms);
}

.bar-enter-active::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--color-primary) 18%, transparent) 42%,
    transparent 78%
  );
  transform: translateX(-110%);
  animation: bar-scan-light 420ms ease both;
  animation-delay: calc(var(--i, 0) * 55ms);
}

.bar-leave-active {
  transition: opacity 220ms ease;
}

.bar-leave-to {
  opacity: 0;
}

@keyframes bar-scan-in {
  from {
    opacity: 0;
    clip-path: inset(0 100% 0 0);
    transform: translateX(-12px);
  }
  to {
    opacity: 1;
    clip-path: inset(0 0 0 0);
    transform: translateX(0);
  }
}

@keyframes bar-scan-light {
  from {
    transform: translateX(-110%);
  }
  to {
    transform: translateX(110%);
  }
}

.empty-hint {
  display: grid;
  place-items: center;
  min-height: 260px;
  color: var(--color-text-muted);
  font-size: calc(14px * var(--font-scale));
  text-align: center;
}

.detail-drawer {
  flex: 0 0 0px;
  width: 300px;
  min-width: 0;
  overflow: hidden;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
  transition:
    flex-basis 240ms ease,
    padding 240ms ease;
}

.detail-drawer.open {
  flex-basis: 300px;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--color-border);
}

.drawer-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: calc(14px * var(--font-scale));
  font-weight: 700;
}

.drawer-section {
  display: grid;
  gap: 8px;
  padding: 12px;
}

.drawer-section-grow {
  align-content: start;
  max-height: 50%;
  overflow: auto;
}

.drawer-kv {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.drawer-kv span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-label {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  font-weight: 700;
  text-transform: uppercase;
}

.drawer-description {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.55;
  white-space: pre-wrap;
}

.drawer-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.drawer-empty {
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.drawer-child {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  min-height: 28px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0 7px;
  text-align: left;
}

.drawer-child:hover {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.drawer-child span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  max-width: 180px;
  min-height: 23px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-tag-1) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
  padding: 0 8px;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-pill:nth-child(6n + 2) {
  background: color-mix(in srgb, var(--color-tag-2) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
}

.tag-pill:nth-child(6n + 3) {
  background: color-mix(in srgb, var(--color-tag-3) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
}
.tag-pill:nth-child(6n + 4) { background: color-mix(in srgb, var(--color-tag-4) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n + 5) { background: color-mix(in srgb, var(--color-tag-5) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n) { background: color-mix(in srgb, var(--color-tag-6) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }

.context-menu {
  position: fixed;
  z-index: 100;
  display: grid;
  min-width: 220px;
  padding: 6px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-canvas);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
  list-style: none;
  margin: 0;
}

.context-item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
  white-space: nowrap;
}

.context-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.context-item:hover {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-text);
}

.context-item.danger:hover {
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger);
}

.context-item.disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
  opacity: 0.42;
}

.context-item.disabled:hover {
  background: transparent;
  color: var(--color-text-muted);
}

.context-sep {
  width: 100%;
  margin: 4px 0;
  border: 0;
  border-top: 1px solid var(--color-border);
}

@container (max-width: 1040px) {
  .library-toolbar {
    align-items: stretch;
  }

  .nav-row {
    display: grid;
    grid-template-columns: auto minmax(180px, 1fr) minmax(140px, 220px) auto;
    align-items: center;
    gap: var(--space-6);
  }

  .nav-buttons {
    grid-column: 1;
    grid-row: 1;
  }

  .path-box {
    grid-column: 2;
    grid-row: 1;
    min-width: 180px;
  }

  .search-box {
    grid-column: 3;
    grid-row: 1;
    width: 100%;
  }

  .filter-capsule-btn {
    grid-column: 4;
    grid-row: 1;
  }

  .library-actions {
    grid-column: 1 / -1;
    grid-row: 2;
    justify-content: flex-end;
  }

  .library-grid {
    column-width: 220px;
  }

  .library-list {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-drawer.open {
    flex-basis: 260px;
  }
}

@container (max-width: 640px) {
  .library-toolbar {
    min-height: 0;
    padding: var(--space-6) var(--space-8);
  }

  .nav-row {
    grid-template-columns: minmax(0, 1fr) minmax(140px, 180px);
    gap: var(--space-4);
  }

  .nav-buttons {
    grid-column: 1;
    grid-row: 1;
  }

  .path-box {
    grid-column: 1 / -1;
    grid-row: 2;
    min-width: 0;
  }

  .search-box {
    grid-column: 2;
    grid-row: 1;
    min-width: 0;
    width: 100%;
  }

  .filter-capsule-btn {
    grid-column: 1;
    grid-row: 3;
    justify-self: start;
    width: 28px;
    padding: 0;
    justify-content: center;
  }

  .library-actions {
    grid-column: 2;
    grid-row: 3;
    width: max-content;
    justify-self: end;
    justify-content: flex-end;
  }

  .filter-capsule-btn span,
  .filter-chevron {
    display: none;
  }

  .library-body {
    padding: var(--space-8);
  }

  .library-grid {
    column-width: 160px;
    column-gap: var(--space-10);
  }

  .library-list {
    gap: var(--space-6);
  }

  .library-content {
    position: relative;
  }

  .detail-drawer,
  .detail-drawer.open {
    position: absolute;
    inset: 0 0 0 auto;
    z-index: 12;
    width: min(320px, 100%);
    flex-basis: auto;
    visibility: hidden;
    pointer-events: none;
    transform: translateX(100%);
    transition: transform 200ms ease, visibility 200ms;
  }

  .detail-drawer.open {
    visibility: visible;
    pointer-events: auto;
    transform: translateX(0);
  }
}
</style>
