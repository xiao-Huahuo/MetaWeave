<!--
  Literature reading workspace.

  Usage:
  The library activity menu opens this page. It derives every document from a
  literature smart-form row, renders a wider reading list on the left, and
  reuses EditorPane for the selected real knowledge file on the right.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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

import { buildApiUrl } from '@/api/client'
import { addFavorite, deleteFavorite, listFavorites } from '@/api/favorites'
import { createKnowledgeFolder, deleteKnowledgePath, previewKnowledgeFile, uploadKnowledgeFile } from '@/api/knowledge'
import { deleteLiteratureRow, duplicateLiteratureRow, listLiteratureEntries, patchLiteratureRow, touchLiteratureEntry, type LiteratureEntry } from '@/api/literatureReading'
import { addPrivacy, deletePrivacy, listPrivacy } from '@/api/privacy'
import { generateStructuredFields, getSmartFormDb, listSmartFormsDb, saveSmartFormDb } from '@/api/smartForms'
import IcIcon from '@/components/common/IcIcon.vue'
import EditorPane from '@/components/editor_workspace/EditorPane.vue'
import LiteratureContextMenu from '@/components/literature_reading/LiteratureContextMenu.vue'
import LiteratureCreateDialog from '@/components/literature_reading/LiteratureCreateDialog.vue'
import LiteratureEntryCard from '@/components/literature_reading/LiteratureEntryCard.vue'
import SmartFormAddColumnMenu from '@/components/smart_forms/SmartFormAddColumnMenu.vue'
import { addColumn, createEmptyRow, extractMarkdownImages, type SmartColumn, type SmartLiteratureForm, type SmartRow } from '@/components/smart_forms/smartLiteratureTable'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

defineOptions({ name: 'LiteratureReadingView' })

type SortKey = 'title' | 'size' | 'entered' | 'viewed'

/** Active literature menu and its position relative to the owning card or field. */
interface LiteratureMenuState {
  open: boolean
  kind: 'row' | 'field'
  x: number
  y: number
  entry: LiteratureEntry | null
  columnId: string
  anchor: HTMLElement | null
  anchorOffsetX: number
  anchorOffsetY: number
}

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const entries = ref<LiteratureEntry[]>([])
const forms = ref<Array<{ form_id: string; title: string; asset_dir: string }>>([])
const formCache = ref<Record<string, SmartLiteratureForm>>({})
const formAssetDirs = ref<Record<string, string>>({})
const selectedFormId = ref('')
const selectedEntry = ref<LiteratureEntry | null>(null)
const query = ref('')
const searchOpen = ref(false)
const searchInput = ref<HTMLInputElement | null>(null)
const tagFilter = ref('')
const minRating = ref(0)
const sortKey = ref<SortKey>('entered')
const sortDirection = ref<'asc' | 'desc'>('desc')
const sortMenuOpen = ref(false)
const filterMenuOpen = ref(false)
const loading = ref(false)
const createOpen = ref(false)
const preparing = ref(false)
const draftRow = ref<SmartRow | null>(null)
const draftAssetPath = ref('')
const draftFormId = ref('')
const renamingKey = ref('')
const reuploadTarget = ref<LiteratureEntry | null>(null)
const reuploadInput = ref<HTMLInputElement | null>(null)
const addColumnMenu = ref({ open: false, x: 0, y: 0, formId: '' })
const favoriteTargets = ref(new Set<string>())
const privateTargets = ref(new Set<string>())
const pendingCellKeys = ref(new Set<string>())
const contextMenu = ref<LiteratureMenuState>({
  open: false,
  kind: 'row',
  x: 0,
  y: 0,
  entry: null,
  columnId: '',
  anchor: null,
  anchorOffsetX: 0,
  anchorOffsetY: 0,
})
const sortOptions = [
  { value: 'title', label: '标题', icon: 'title' },
  { value: 'size', label: '文献大小', icon: 'storage' },
  { value: 'entered', label: '入表时间', icon: 'calendar' },
  { value: 'viewed', label: '最近浏览', icon: 'history' },
]

const libraryId = computed(() => settingsStore.activeKnowledgeLibrary?.libraryId || settingsStore.profile.activeLibraryId)
const ratingFilter = computed({
  get: () => String(minRating.value),
  set: (value: string) => { minRating.value = Number(value) },
})
const hasActiveFilter = computed(() => Boolean(tagFilter.value || minRating.value || selectedFormId.value))
const tags = computed(() => [...new Set(entries.value.flatMap((entry) => entry.tags))].sort((a, b) => a.localeCompare(b)))
const visibleEntries = computed(() => {
  const normalized = query.value.trim().toLowerCase()
  const filtered = entries.value.filter((entry) => (
    (!selectedFormId.value || entry.form_id === selectedFormId.value)
    && (!normalized || `${entry.title} ${entry.file_name} ${entry.content_excerpt}`.toLowerCase().includes(normalized))
    && (!tagFilter.value || entry.tags.includes(tagFilter.value))
    && (!minRating.value || entry.rating >= minRating.value)
  ))
  const direction = sortDirection.value === 'asc' ? 1 : -1
  return filtered.sort((left, right) => {
    if (sortKey.value === 'title') return left.title.localeCompare(right.title) * direction
    if (sortKey.value === 'size') return (left.file_size - right.file_size) * direction
    const leftTime = Date.parse(sortKey.value === 'viewed' ? left.last_viewed_at : left.entered_at) || 0
    const rightTime = Date.parse(sortKey.value === 'viewed' ? right.last_viewed_at : right.entered_at) || 0
    return (leftTime - rightTime) * direction
  })
})
const groupedEntries = computed(() => forms.value
  .map((form) => ({ form, entries: visibleEntries.value.filter((entry) => entry.form_id === form.form_id) }))
  .filter((group) => group.entries.length))

function targetId(entry: LiteratureEntry): string {
  return `${entry.form_id}:${entry.row_id}`
}

function pendingColumnsFor(entry: LiteratureEntry): string[] {
  const prefix = `${targetId(entry)}:`
  return [...pendingCellKeys.value].filter((key) => key.startsWith(prefix)).map((key) => key.slice(prefix.length))
}

async function openSearch(): Promise<void> {
  searchOpen.value = true
  await nextTick()
  searchInput.value?.focus()
}

function closeSearch(): void {
  if (query.value) return
  searchOpen.value = false
}

/** Loads only literature forms and their lightweight row summaries for the active knowledge library. */
async function load(): Promise<void> {
  if (!settingsStore.profile.userId || !libraryId.value) return
  loading.value = true
  try {
    const [formItems, entryItems, favorites, privacy] = await Promise.all([
      listSmartFormsDb(settingsStore.profile.userId, libraryId.value, 'literature'),
      listLiteratureEntries(settingsStore.profile.userId, libraryId.value),
      listFavorites({ userId: settingsStore.profile.userId, libraryId: libraryId.value, targetType: 'smart_form_row' }),
      listPrivacy({ userId: settingsStore.profile.userId, libraryId: libraryId.value, targetType: 'smart_form_row' }),
    ])
    forms.value = formItems.map((item) => ({ form_id: item.form_id, title: item.title, asset_dir: item.asset_dir }))
    formAssetDirs.value = Object.fromEntries(formItems.map((item) => [item.form_id, item.asset_dir]))
    entries.value = entryItems
    favoriteTargets.value = new Set(favorites.favorites.map((item) => item.target_id))
    privateTargets.value = new Set(privacy.privacy.map((item) => item.target_id))
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '文献阅读加载失败')
  } finally {
    loading.value = false
  }
}

/** Lazily loads one complete form when a card expands or mutates. */
async function ensureForm(formId: string): Promise<SmartLiteratureForm> {
  if (formCache.value[formId]) return formCache.value[formId]
  const response = await getSmartFormDb(settingsStore.profile.userId, formId)
  formAssetDirs.value = { ...formAssetDirs.value, [formId]: response.asset_dir }
  formCache.value = { ...formCache.value, [formId]: response.form }
  return response.form
}

function rowFor(entry: LiteratureEntry): SmartRow | null {
  return formCache.value[entry.form_id]?.rows.find((row) => row.id === entry.row_id) ?? null
}

/** Selects the real asset in the shared EditorPane and persists row-level browsing time. */
async function selectEntry(entry: LiteratureEntry): Promise<void> {
  selectedEntry.value = entry
  await workspaceStore.selectFile({ name: entry.file_name, path: entry.asset_path, isDir: false, mtime: entry.updated_at, size: entry.file_size })
  const touched = await touchLiteratureEntry(settingsStore.profile.userId, libraryId.value, entry.form_id, entry.row_id)
  entry.last_viewed_at = touched.last_viewed_at
}

/** Persists one expanded field and refreshes both cached detail and card summary. */
async function updateCell(entry: LiteratureEntry, columnId: string, value: string): Promise<void> {
  const response = await patchLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id, {
    [columnId]: { value, status: 'ready' },
  })
  formCache.value = { ...formCache.value, [entry.form_id]: response.form }
  await load()
}

async function download(entry: LiteratureEntry): Promise<void> {
  const preview = await previewKnowledgeFile(settingsStore.profile.userId, entry.asset_path)
  const source = preview.raw_url ? buildApiUrl(preview.raw_url) : preview.data_url
  if (!source) return
  const anchor = document.createElement('a')
  anchor.href = source
  anchor.download = entry.file_name
  anchor.click()
}

function absolutePath(entry: LiteratureEntry): string {
  return `${settingsStore.profile.knowledgeDir.replace(/[\\/]+$/u, '')}/${entry.asset_path}`.replace(/\//gu, '\\')
}

/** Closes the active row or field menu from any click outside the menu itself. */
function closeContextMenu(): void {
  contextMenu.value.open = false
}

/** Handles outside presses in capture phase so nested stop modifiers cannot leave the menu open. */
function handleDocumentPointerDown(event: PointerEvent): void {
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('.literature-context')) return
  closeContextMenu()
}

/** Keeps the fixed menu attached to its owning block while the sidebar scrolls. */
function updateContextMenuPosition(): void {
  const menu = contextMenu.value
  if (!menu.open || !menu.anchor) return
  if (!document.contains(menu.anchor)) {
    closeContextMenu()
    return
  }
  const rect = menu.anchor.getBoundingClientRect()
  const menuHeight = menu.kind === 'row' ? 440 : 130
  menu.x = Math.max(8, Math.min(rect.left + menu.anchorOffsetX, window.innerWidth - 252))
  menu.y = Math.max(8, Math.min(rect.top + menu.anchorOffsetY, window.innerHeight - menuHeight))
}

/** Opens one menu at the pointer while retaining the owning block as its anchor. */
function setContextMenu(kind: 'row' | 'field', entry: LiteratureEntry, columnId: string, event: MouseEvent): void {
  const selector = kind === 'row' ? '.literature-card' : '.literature-field'
  const anchor = (event.target as HTMLElement | null)?.closest<HTMLElement>(selector) ?? null
  const rect = anchor?.getBoundingClientRect()
  contextMenu.value = {
    open: true,
    kind,
    x: event.clientX,
    y: event.clientY,
    entry,
    columnId,
    anchor,
    anchorOffsetX: event.clientX - (rect?.left ?? event.clientX),
    anchorOffsetY: event.clientY - (rect?.top ?? event.clientY),
  }
  updateContextMenuPosition()
}

/** Opens the row menu anchored to the literature card. */
function openRowMenu(entry: LiteratureEntry, event: MouseEvent): void {
  setContextMenu('row', entry, '', event)
}

/** Opens the field menu anchored to the selected field block. */
function openFieldMenu(entry: LiteratureEntry, columnId: string, event: MouseEvent): void {
  setContextMenu('field', entry, columnId, event)
}

/** Calls the existing structured-generation contract for a complete row or one smart field. */
async function fill(entry: LiteratureEntry, onlyColumnId = ''): Promise<void> {
  const form = await ensureForm(entry.form_id)
  const row = rowFor(entry)
  if (!row) return
  const columns = form.columns.filter((column) => ['smart_text', 'smart_tag'].includes(column.type) && (!onlyColumnId || column.id === onlyColumnId))
  if (!columns.length) {
    workspaceStore.showToast('该字段不支持智能填充')
    return
  }
  const content = row.cells.literature_content?.value.trim() || ''
  if (!content) {
    workspaceStore.showToast('缺少文献内容，无法智能填充')
    return
  }
  const keys = columns.map((column) => `${targetId(entry)}:${column.id}`)
  pendingCellKeys.value = new Set([...pendingCellKeys.value, ...keys])
  try {
    const response = await generateStructuredFields({
      user_id: settingsStore.profile.userId,
      source: { kind: 'literature_document', content, metadata: { form_id: entry.form_id, row_id: entry.row_id } },
      fields: columns.map((column) => ({ id: column.id, title: column.title, type: column.type === 'smart_tag' ? 'tag' : 'text', description: column.description, options: column.options, required: true })),
      options: { language: 'zh', strict_json: true },
    })
    const cells = Object.fromEntries(response.results.map((result) => {
      const previous = row.cells[result.field_id]?.value || ''
      return [result.field_id, result.status === 'ready' && result.value.trim()
        ? { value: result.value.trim(), status: 'ready' }
        : { value: previous, status: previous.trim() ? 'ready' : 'failed' }]
    }))
    const saved = await patchLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id, cells)
    formCache.value = { ...formCache.value, [entry.form_id]: saved.form }
    await load()
  } finally {
    const next = new Set(pendingCellKeys.value)
    keys.forEach((key) => next.delete(key))
    pendingCellKeys.value = next
  }
}

async function clearInvalid(entry: LiteratureEntry): Promise<void> {
  await ensureForm(entry.form_id)
  const row = rowFor(entry)
  if (!row) return
  const cells = Object.fromEntries(Object.entries(row.cells)
    .filter(([, cell]) => cell.status === 'failed' && !cell.value.trim())
    .map(([columnId, cell]) => [columnId, { ...cell, status: undefined }]))
  if (!Object.keys(cells).length) {
    workspaceStore.showToast('本行没有空的失败字段')
    return
  }
  await patchLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id, cells)
  await load()
}

/** Adds one smart-form column and keeps every existing row connected to the new field. */
async function addField(column: SmartColumn): Promise<void> {
  const formId = addColumnMenu.value.formId
  if (!formId) return
  const form = await ensureForm(formId)
  const next = addColumn(form, column)
  const response = await saveSmartFormDb({ user_id: settingsStore.profile.userId, form_id: formId, library_id: libraryId.value, form_kind: 'literature', asset_dir: formAssetDirs.value[formId] ?? '', form: next })
  formCache.value = { ...formCache.value, [formId]: response.form }
  if (draftRow.value && draftFormId.value === formId) {
    response.form.columns.forEach((column) => {
      if (!draftRow.value?.cells[column.id]) draftRow.value!.cells[column.id] = { value: '', status: column.type.startsWith('smart_') ? 'idle' : undefined }
    })
    draftRow.value = { ...draftRow.value, cells: { ...draftRow.value.cells } }
  }
  addColumnMenu.value.open = false
  await load()
}

async function requestAddField(formId: string, event?: MouseEvent): Promise<void> {
  await ensureForm(formId)
  const target = event?.currentTarget instanceof HTMLElement ? event.currentTarget.getBoundingClientRect() : null
  const x = target ? target.right + 8 : contextMenu.value.x + 12
  const y = target ? Math.min(target.top, window.innerHeight - 640) : Math.min(contextMenu.value.y, window.innerHeight - 640)
  addColumnMenu.value = {
    open: true,
    formId,
    x: Math.max(8, Math.min(x, window.innerWidth - 308)),
    y: Math.max(8, y),
  }
}

async function toggleFavorite(entry: LiteratureEntry): Promise<void> {
  const id = targetId(entry)
  const payload = { user_id: settingsStore.profile.userId, library_id: libraryId.value, target_type: 'smart_form_row' as const, target_id: id }
  if (favoriteTargets.value.has(id)) {
    await deleteFavorite(payload)
    favoriteTargets.value.delete(id)
  } else {
    await addFavorite(payload)
    favoriteTargets.value.add(id)
  }
  favoriteTargets.value = new Set(favoriteTargets.value)
}

async function togglePrivacy(entry: LiteratureEntry): Promise<void> {
  const id = targetId(entry)
  const payload = { user_id: settingsStore.profile.userId, library_id: libraryId.value, target_type: 'smart_form_row' as const, target_id: id }
  if (privateTargets.value.has(id)) {
    await deletePrivacy(payload)
    privateTargets.value.delete(id)
  } else {
    await addPrivacy(payload)
    privateTargets.value.add(id)
  }
  privateTargets.value = new Set(privateTargets.value)
}

async function deleteEntry(entry: LiteratureEntry): Promise<void> {
  if (!window.confirm(`确定删除“${entry.title}”及真实文件吗？此操作不可撤销。`)) return
  await deleteLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id, true)
  if (selectedEntry.value?.row_id === entry.row_id) selectedEntry.value = null
  delete formCache.value[entry.form_id]
  await workspaceStore.loadKnowledgeTree()
  await load()
}

async function handleContextAction(action: string): Promise<void> {
  const { entry, columnId } = contextMenu.value
  contextMenu.value.open = false
  if (action === 'new') { openCreate(entry?.form_id); return }
  if (!entry) return
  if (action === 'add-field') { requestAddField(entry.form_id); return }
  if (action === 'duplicate') { await duplicateLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id); await load(); return }
  if (action === 'rename') { renamingKey.value = targetId(entry); return }
  if (action === 'fill') { await fill(entry); return }
  if (action === 'fill-field') { await fill(entry, columnId); return }
  if (action === 'clear-invalid') { await clearInvalid(entry); return }
  if (action === 'clear-field') { await updateCell(entry, columnId, ''); return }
  if (action === 'reupload') { reuploadTarget.value = entry; reuploadInput.value?.click(); return }
  if (action === 'reveal') { await window.agentEditorDesktop?.showItemInFolder?.(absolutePath(entry)); return }
  if (action === 'open-default') { await window.agentEditorDesktop?.openPath?.(absolutePath(entry)); return }
  if (action === 'favorite') { await toggleFavorite(entry); return }
  if (action === 'privacy') { await togglePrivacy(entry); return }
  if (action === 'delete') { await deleteEntry(entry); return }
  const copied = action === 'copy-name' ? entry.title : action === 'copy-relative' ? entry.asset_path : absolutePath(entry)
  await navigator.clipboard.writeText(copied)
}

function openCreate(formId = selectedFormId.value || forms.value[0]?.form_id || ''): void {
  if (!formId) {
    workspaceStore.showToast('请先创建智能文献表')
    return
  }
  draftFormId.value = formId
  draftRow.value = null
  draftAssetPath.value = ''
  createOpen.value = true
}

function updateDraftCell(columnId: string, value: string): void {
  if (!draftRow.value) return
  draftRow.value.cells[columnId] = { ...draftRow.value.cells[columnId], value }
  draftRow.value = { ...draftRow.value, cells: { ...draftRow.value.cells } }
}

/** Uploads and ingests one draft file, then previews generated table cells before final save. */
async function prepareDraft(file: File): Promise<void> {
  preparing.value = true
  try {
    const form = await ensureForm(draftFormId.value)
    const assetDir = `${formAssetDirs.value[draftFormId.value]}/assets`
    await createKnowledgeFolder(settingsStore.profile.userId, assetDir).catch(() => undefined)
    const uploaded = await uploadKnowledgeFile(settingsStore.profile.userId, file, assetDir, false, 'rename') as { uploaded_path?: string; knowledge_dir?: string }
    const root = (uploaded.knowledge_dir || settingsStore.profile.knowledgeDir).replace(/\\/gu, '/')
    const assetPath = String(uploaded.uploaded_path || '').replace(/\\/gu, '/').replace(`${root.replace(/\/+$/u, '')}/`, '')
    await workspaceStore.ingestFile({ name: file.name, path: assetPath, isDir: false, indexStatus: 'dirty' })
    const preview = await previewKnowledgeFile(settingsStore.profile.userId, assetPath)
    const content = [preview.semantic_markdown, preview.content, preview.render_content].find((item) => typeof item === 'string' && item.trim()) || ''
    const row = createEmptyRow(form.columns)
    row.cells.literature_file = { value: file.name, fileName: file.name, assetPath }
    row.cells.literature_content = { value: content, status: content ? 'ready' : 'failed' }
    row.cells.figures = { value: extractMarkdownImages(preview.semantic_markdown, preview.render_content), status: 'ready' }
    draftRow.value = row
    draftAssetPath.value = assetPath
    await fillDraftSmartFields(form, row)
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '文献提取失败')
  } finally {
    preparing.value = false
  }
}

async function fillDraftSmartFields(form: SmartLiteratureForm, row: SmartRow): Promise<void> {
  const content = row.cells.literature_content?.value || ''
  const columns = form.columns.filter((column) => ['smart_text', 'smart_tag'].includes(column.type))
  if (!content || !columns.length) return
  const response = await generateStructuredFields({
    user_id: settingsStore.profile.userId,
    source: { kind: 'literature_document', content },
    fields: columns.map((column) => ({ id: column.id, title: column.title, type: column.type === 'smart_tag' ? 'tag' : 'text', description: column.description, options: column.options })),
  })
  response.results.forEach((result) => {
    row.cells[result.field_id] = result.status === 'ready' ? { value: result.value, status: 'ready' } : { value: '', status: 'failed' }
  })
  draftRow.value = { ...row, cells: { ...row.cells } }
}

async function createDraft(): Promise<void> {
  if (!draftRow.value) return
  const form = await ensureForm(draftFormId.value)
  const next = { ...form, rows: [...form.rows, draftRow.value] }
  const response = await saveSmartFormDb({ user_id: settingsStore.profile.userId, form_id: draftFormId.value, library_id: libraryId.value, form_kind: 'literature', asset_dir: formAssetDirs.value[draftFormId.value] ?? '', form: next })
  formCache.value = { ...formCache.value, [draftFormId.value]: response.form }
  createOpen.value = false
  draftRow.value = null
  await workspaceStore.loadKnowledgeTree()
  await load()
}

async function closeCreate(): Promise<void> {
  if (draftAssetPath.value && draftRow.value) await deleteKnowledgePath(settingsStore.profile.userId, draftAssetPath.value).catch(() => undefined)
  createOpen.value = false
  draftRow.value = null
  draftAssetPath.value = ''
}

async function handleReupload(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  const entry = reuploadTarget.value
  ;(event.target as HTMLInputElement).value = ''
  if (!file || !entry) return
  openCreate(entry.form_id)
  await prepareDraft(file)
  if (!draftRow.value) return
  const replacement = draftRow.value.cells
  const response = await patchLiteratureRow(settingsStore.profile.userId, entry.form_id, entry.row_id, replacement)
  await deleteKnowledgePath(settingsStore.profile.userId, entry.asset_path).catch(() => undefined)
  formCache.value = { ...formCache.value, [entry.form_id]: response.form }
  createOpen.value = false
  draftRow.value = null
  await workspaceStore.loadKnowledgeTree()
  await load()
}

onMounted(async () => {
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  window.addEventListener('resize', updateContextMenuPosition)
  window.addEventListener('scroll', updateContextMenuPosition, true)
  await load()
  const target = workspaceStore.consumePendingLiteratureEntry()
  if (!target) return
  selectedFormId.value = target.formId
  const entry = entries.value.find((item) => item.form_id === target.formId && item.row_id === target.rowId)
  if (!entry) {
    workspaceStore.showToast('未找到对应的智能表格文献行')
    return
  }
  await ensureForm(entry.form_id)
  await selectEntry(entry)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  window.removeEventListener('resize', updateContextMenuPosition)
  window.removeEventListener('scroll', updateContextMenuPosition, true)
})
</script>

<template>
  <section class="literature-reading" @click="addColumnMenu.open = false">
    <aside class="literature-sidebar">
      <header class="literature-toolbar">
        <div class="toolbar-row toolbar-primary-row">
          <label class="literature-search" :class="{ open: searchOpen || query }" @click.stop>
            <button class="toolbar-command" type="button" title="搜索" aria-label="搜索文献" @click="openSearch">
              <IcIcon name="search" :size="15" />
              <span>搜索</span>
            </button>
            <input ref="searchInput" v-model="query" type="search" placeholder="搜索文献" @focus="searchOpen = true" @blur="closeSearch" @keydown.esc="query = ''; searchOpen = false" />
            <button v-if="query" class="search-clear" type="button" title="清除搜索" @mousedown.prevent @click="query = ''"><IcIcon name="close" :size="12" /></button>
          </label>
          <div class="toolbar-actions">
            <DropdownMenu v-model:open="sortMenuOpen">
              <DropdownMenuTrigger as-child>
                <button class="toolbar-command menu-trigger" type="button" title="排序">
                  <IcIcon name="sort" :size="15" /><span>排序</span><IcIcon class="toolbar-chevron" name="chevron-down" :size="12" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuPortal>
                <DropdownMenuContent class="literature-toolbar-menu" align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>排序字段</DropdownMenuLabel>
                    <DropdownMenuRadioGroup v-model="sortKey">
                      <DropdownMenuRadioItem v-for="option in sortOptions" :key="option.value" :value="option.value">{{ option.label }}</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>排序方向</DropdownMenuLabel>
                    <DropdownMenuRadioGroup v-model="sortDirection">
                      <DropdownMenuRadioItem value="asc">升序</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="desc">降序</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenuPortal>
            </DropdownMenu>
            <DropdownMenu v-model:open="filterMenuOpen">
              <DropdownMenuTrigger as-child>
                <button class="toolbar-command menu-trigger" :class="{ active: hasActiveFilter }" type="button" title="筛选">
                  <IcIcon name="filter" :size="15" /><span>筛选</span><IcIcon class="toolbar-chevron" name="chevron-down" :size="12" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuPortal>
                <DropdownMenuContent class="literature-toolbar-menu literature-filter-menu" align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>标签</DropdownMenuLabel>
                    <DropdownMenuRadioGroup v-model="tagFilter">
                      <DropdownMenuRadioItem value="">全部标签</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem v-for="tag in tags" :key="tag" :value="tag">{{ tag }}</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>星级</DropdownMenuLabel>
                    <DropdownMenuRadioGroup v-model="ratingFilter">
                      <DropdownMenuRadioItem value="0">全部星级</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="3">3 星以上</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="4">4 星以上</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="5">5 星</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>表格</DropdownMenuLabel>
                    <DropdownMenuRadioGroup v-model="selectedFormId">
                      <DropdownMenuRadioItem value="">全部表格</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem v-for="form in forms" :key="form.form_id" :value="form.form_id">{{ form.title }}</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenuPortal>
            </DropdownMenu>
            <button class="toolbar-command icon-only v1-icon-button" type="button" title="刷新" aria-label="刷新文献库" @click="load"><IcIcon name="refresh" :size="15" /></button>
            <button class="toolbar-command icon-only v1-icon-button" type="button" title="新建" aria-label="新建文献" @click="openCreate()"><IcIcon name="add" :size="16" /></button>
          </div>
        </div>
      </header>
      <div class="literature-list">
        <section v-for="group in groupedEntries" :key="group.form.form_id" class="form-group">
          <h2>{{ group.form.title }}</h2>
          <LiteratureEntryCard
            v-for="entry in group.entries"
            :key="targetId(entry)"
            :entry="entry"
            :form="formCache[entry.form_id] ?? null"
            :row="rowFor(entry)"
            :selected="targetId(selectedEntry ?? entry) === targetId(entry) && Boolean(selectedEntry)"
            :renaming="renamingKey === targetId(entry)"
            :pending-column-ids="pendingColumnsFor(entry)"
            @select="selectEntry(entry)"
            @expand="ensureForm(entry.form_id)"
            @context-menu="openRowMenu(entry, $event)"
            @field-context-menu="(columnId, event) => openFieldMenu(entry, columnId, event)"
            @update-cell="(columnId, value) => updateCell(entry, columnId, value)"
            @download="download(entry)"
            @fill-field="fill(entry, $event)"
            @rename="updateCell(entry, 'title', $event); renamingKey = ''"
          />
        </section>
        <p v-if="!loading && !visibleEntries.length" class="empty-copy">当前知识库没有符合条件的智能表格文献</p>
      </div>
    </aside>
    <main class="literature-editor">
      <EditorPane v-if="selectedEntry" />
      <div v-else class="editor-empty"><IcIcon name="book" :size="34" /><p>从左侧选择一篇文献开始阅读</p></div>
    </main>
    <input ref="reuploadInput" class="hidden-input" type="file" @change="handleReupload" />
    <LiteratureContextMenu v-if="contextMenu.open" :kind="contextMenu.kind" :x="contextMenu.x" :y="contextMenu.y" @action="handleContextAction" />
    <LiteratureCreateDialog
      :open="createOpen"
      :preparing="preparing"
      :form="formCache[draftFormId] ?? null"
      :row="draftRow"
      :asset-path="draftAssetPath"
      @close="closeCreate"
      @file="prepareDraft"
      @create="createDraft"
      @add-field="requestAddField(draftFormId, $event)"
      @update-cell="updateDraftCell"
    />
    <Teleport to="body">
      <SmartFormAddColumnMenu
        v-if="addColumnMenu.open && formCache[addColumnMenu.formId]"
        class="literature-add-column-menu"
        :style="{ left: `${addColumnMenu.x}px`, top: `${addColumnMenu.y}px` }"
        :columns="formCache[addColumnMenu.formId]!.columns"
        :is-literature="true"
        @add="addField"
      />
    </Teleport>
  </section>
</template>

<style scoped>
.literature-reading { display: grid; grid-template-columns: 384px minmax(0, 1fr); width: 100%; height: 100%; min-width: 0; min-height: 0; background: var(--color-bg-app); color: var(--color-text); }
.literature-add-column-menu { position: fixed; z-index: 1300; }
.literature-sidebar { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: var(--space-6); margin: var(--space-12); padding: var(--space-8); overflow: hidden; border: 0; border-radius: 28px; background: var(--color-surface); box-shadow: 0 0 0 4px var(--library-form-ring); animation: literature-sidebar-enter 220ms cubic-bezier(.23,1,.32,1) both; }
.literature-toolbar { display: grid; padding: 0; }
.toolbar-row { display: flex; align-items: center; min-width: 0; gap: var(--space-4); }
.toolbar-primary-row { justify-content: space-between; }
.toolbar-actions { display: inline-flex; align-items: center; gap: 2px; margin-left: auto; }
.toolbar-command { display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 28px; padding: 0 7px; border: 1px solid transparent; border-radius: 999px; background: transparent; color: var(--color-text-muted); font: inherit; font-size: calc(12px * var(--font-scale)); font-weight: 400; white-space: nowrap; cursor: pointer; }
.toolbar-command.icon-only { width: 28px; padding: 0; border-radius: 0; }
.toolbar-command:hover { color: var(--color-primary); }
.toolbar-command.menu-trigger { border-color: var(--color-border); background: var(--color-canvas); color: var(--color-text-secondary); }
.toolbar-command.menu-trigger:hover { border-color: color-mix(in srgb, var(--color-primary) 40%, transparent); color: var(--color-primary); }
.toolbar-command.menu-trigger.active,.toolbar-command.menu-trigger[data-state='open'] { border-color: color-mix(in srgb, var(--color-primary) 45%, transparent); background: var(--color-primary-soft); color: var(--color-primary); }
.toolbar-chevron { margin-right: -3px; opacity: .62; transition: transform var(--transition-fast); }
.toolbar-command[data-state='open'] .toolbar-chevron { transform: rotate(180deg); }
.literature-toolbar-menu { width: 236px; max-height: min(480px, var(--reka-dropdown-menu-content-available-height)); overflow-y: auto; }
.literature-filter-menu { width: 260px; }
.literature-search { display: flex; align-items: center; width: 61px; height: 28px; min-width: 0; overflow: hidden; border: 0; border-radius: 999px; background: transparent; transition: width 200ms ease-in-out, border-color 160ms ease, background 160ms ease; }
.literature-search.open { width: 112px; border: 1px solid var(--color-border); background: var(--color-canvas); }
.literature-search.open > .toolbar-command { padding-right: 2px; border: 0; }
.literature-search.open > .toolbar-command span { display: none; }
.literature-search input { width: 0; min-width: 0; flex: 1; opacity: 0; pointer-events: none; border: 0; outline: 0; background: transparent; color: var(--color-text); font: inherit; font-size: calc(12px * var(--font-scale)); transition: opacity 160ms ease; }
.literature-search.open input { width: auto; opacity: 1; pointer-events: auto; }
.search-clear { display: grid; width: 20px; height: 20px; flex: 0 0 20px; place-items: center; padding: 0; border: 0; background: transparent; color: var(--color-text-muted); }
.literature-list { flex: 1; min-height: 0; overflow: auto; padding: 8px; }.form-group { display: grid; gap: 7px; }.form-group + .form-group { margin-top: 14px; }.form-group h2 { margin: 0; padding: 5px 3px; color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.literature-editor { min-width: 0; min-height: 0; overflow: hidden; }.literature-editor :deep(.editor-panel) { height: 100%; }.editor-empty { display: grid; height: 100%; place-items: center; align-content: center; gap: 10px; color: var(--color-text-muted); }.editor-empty p { margin: 0; }.hidden-input { display: none; }.empty-copy { padding: 28px 16px; color: var(--color-text-muted); text-align: center; }
@keyframes literature-sidebar-enter { from { opacity: 0; transform: translateX(-8px) scale(.985); } to { opacity: 1; transform: none; } }
@media (max-width: 900px) { .literature-reading { grid-template-columns: 348px minmax(0, 1fr); } .toolbar-command { padding-inline: 5px; } .literature-search.open { width: 100px; } }
@media (max-width: 640px) { .literature-reading { grid-template-columns: 1fr; grid-template-rows: minmax(260px, 46%) minmax(0, 1fr); }.literature-sidebar { margin: var(--space-8); padding: var(--space-8); border-radius: 18px; }.toolbar-primary-row { flex-wrap: wrap; }.literature-search.open { width: min(160px, calc(100vw - 220px)); }.literature-list { padding-inline: 0; }.literature-editor { min-height: 0; } }
</style>
