<!--
  Smart literature forms page.

  Usage:
  Provides a spreadsheet-like research literature table stored under the
  knowledge library .mw/forms/ directory. Users can edit typed columns, bind PDF
  assets, filter rows, and export CSV/Markdown without leaving the workspace.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { buildApiUrl } from '@/api/client'
import { createKnowledgeFolder, listKnowledgeFiles, previewKnowledgeFile, readKnowledgeFile, uploadKnowledgeFile } from '@/api/knowledge'
import { deleteSmartFormDb, generateStructuredFields, getSmartFormDb, listSmartFormsDb, saveSmartFormDb, type StructuredGenerationFieldResult } from '@/api/smartForms'
import IcIcon from '@/components/common/IcIcon.vue'
import PixelLoader from '@/components/common/PixelLoader.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { materialFileIconForNode } from '@/components/editor_workspace/materialFileIcons'
import { useSubmenuIntent } from '@/components/editor_workspace/submenuIntent'
import SmartMarkdownCell from '@/components/smart_forms/SmartMarkdownCell.vue'
import SmartFormAddColumnMenu from '@/components/smart_forms/SmartFormAddColumnMenu.vue'
import {
  SMART_COLUMN_TYPE_ICONS,
  smartColumnIcon,
  smartColumnTypeLabel,
} from '@/components/smart_forms/smartColumnPresentation'
import {
  BUILTIN_COLUMNS,
  DEFAULT_ROW_HEIGHT,
  MIN_ROW_HEIGHT,
  PLAIN_MAX_ROW_HEIGHT,
  PLAIN_ROW_HEIGHT,
  addColumn,
  createCustomColumn,
  createDefaultLiteratureForm,
  createDefaultPlainForm,
  createEmptyRow,
  exportCsv,
  exportMarkdown,
  extractMarkdownImages,
  filterRows,
  moveColumn,
  moveRow,
  joinTags,
  normalizeForm,
  removeColumn,
  resizeColumn,
  resizeRow,
  splitTags,
  uniqueTagValues,
  updateCell,
  type SmartColumn,
  type SmartColumnType,
  type SmartCell,
  type SmartLiteratureForm,
  type SmartRow,
} from '@/components/smart_forms/smartLiteratureTable'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

defineOptions({ name: 'SmartFormsView' })

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const props = withDefaults(defineProps<{
  /** Main-workspace mobile state measured outside the table's wide scroll content. */
  mobile?: boolean
  /** Main card width used for sub-mobile controls and table columns. */
  availableWidth?: number
}>(), {
  mobile: false,
  availableWidth: Number.POSITIVE_INFINITY,
})

interface SmartFormEntry {
  /** Database form id. */
  formId: string
  /** Display name. */
  name: string
  /** Attachment folder path relative to the knowledge root. */
  assetDir: string
}

const FORMS_ROOT_DIR = '.mw/forms'
/** 页面根容器，用于按容器宽度感知移动端断点（控制 Teleport 到 body 的菜单项）。 */
const smartFormsShell = ref<HTMLElement | null>(null)
/** 容器宽度是否已进入移动端（<=640px，与 @container 断点保持一致）。 */
const isMobileLayout = ref(false)
const form = ref<SmartLiteratureForm | null>(null)
const formEntries = ref<SmartFormEntry[]>([])
const activeFormId = ref('')
const activeFormDir = ref('')
const loading = ref(false)
const saving = ref(false)
const query = ref('')
const tagFilter = ref('')
const minRating = ref(0)
const newFormTitle = ref('')
const newFormKind = ref<'smart' | 'plain'>('smart')
const createFormOpen = ref(false)
/** Table-name field used to restore deterministic typing focus inside the creation dialog. */
const newFormTitleInput = ref<HTMLInputElement | null>(null)
const selectedCell = ref<{ rowId: string; columnId: string } | null>(null)
const customColumnTitle = ref('')
const customColumnDescription = ref('')
const uploadInputByRow = ref<Record<string, HTMLInputElement | null>>({})
const imagePreviewByPath = ref<Record<string, string>>({})
const tagEditorKey = ref('')
const tagDraft = ref('')
const dropdownOpen = ref('')
const tagFilterMenuOpen = ref(false)
const compactFiltersOpen = ref(false)
const ratingFilterMenuOpen = ref(false)
const swappedColumnId = ref('')
const swappedRowId = ref('')
const generationTokens = ref<Record<string, string>>({})
const tableContextSubmenuSide = ref<'right' | 'left'>('right')
const edgeColumnMenuOpen = ref(false)
const edgeColumnMenuStyle = ref<Record<string, string>>({ left: '0px', top: '0px' })
const editingColumnId = ref('')
const columnTitleDraft = ref('')
const expandedColumnDescriptions = ref(new Set<string>())
const editingColumnDescriptionId = ref('')
const columnDescriptionDraft = ref('')
const columnDescriptionInputById: Record<string, HTMLInputElement | null> = {}
const structuredGenerationQueue: Array<() => Promise<void>> = []
const structuredGenerationConcurrency = 2
let structuredGenerationActive = 0
let swapAnimationTimer: ReturnType<typeof setTimeout> | undefined
let columnDescriptionClickTimer: ReturnType<typeof setTimeout> | undefined
let tableResize: { kind: 'column' | 'row'; id: string; start: number; size: number } | null = null
let shellResizeObserver: ResizeObserver | null = null

type TableContextTarget =
  | { kind: 'table' }
  | { kind: 'column'; columnId: string }
  | { kind: 'row'; rowId: string }
  | { kind: 'cell'; rowId: string; columnId: string }
  | { kind: 'selection' }

interface CellCoord {
  rowId: string
  columnId: string
}

interface SmartFillResult {
  ready: number
  failed: number
}

type TableClipboard =
  | { kind: 'cell'; cell: SmartCell }
  | { kind: 'row'; cells: Record<string, SmartCell> }
  | { kind: 'column'; values: Record<string, SmartCell> }
  | { kind: 'selection'; cells: Record<string, SmartCell> }

const tableContextTarget = ref<TableContextTarget | null>(null)
const tableContextMenuStyle = ref<Record<string, string>>({ left: '0px', top: '0px' })
const tableContextSubmenu = ref('')
const tableContextSubmenuRefs: Record<string, HTMLElement | null> = {}
const tableClipboard = ref<TableClipboard | null>(null)
const selectedCellKeys = ref<string[]>([])
const selectedCellKeySet = computed(() => new Set(selectedCellKeys.value))
const dragAnchorCell = ref<CellCoord | null>(null)
const draggedColumnId = ref('')
const draggedRowId = ref('')
const expandedTextRowHeights = new Map<string, number>()
let autoSaveTimer: ReturnType<typeof setTimeout> | undefined
let literatureFileClickTimer: ReturnType<typeof setTimeout> | undefined
let formRevision = 0
const {
  openSubmenu: openTableSubmenu,
  keepSubmenuOpen: keepTableSubmenuOpen,
  scheduleSubmenuClose: scheduleTableSubmenuClose,
} = useSubmenuIntent(tableContextSubmenu)

const visibleRows = computed(() => form.value ? filterRows(form.value, query.value, tagFilter.value, minRating.value) : [])
const isCompressedLayout = computed(() => props.availableWidth <= 360)
const tagFilters = computed(() => form.value ? uniqueTagValues(form.value) : [])
const isLiteratureTable = computed(() => Boolean(form.value?.columns.some((column) => column.id === 'literature_file' || column.id === 'literature_content')))
const availableBuiltinColumns = computed(() => BUILTIN_COLUMNS.filter((builtin) => {
  if (builtin.id !== 'figures') return true
  return isLiteratureTable.value && !form.value?.columns.some((column) => column.id === builtin.id)
}))
const availableCustomColumnTypes = computed(() => customColumnTypes)
const activeFormStorageLabel = computed(() => activeFormId.value ? `SQLite: smart_forms/${activeFormId.value}` : '')
const activeFormCsvFile = computed(() => form.value ? `${form.value.title}.csv` : '')
const activeFormAssetDir = computed(() => activeFormDir.value ? `${activeFormDir.value}/assets` : '')
const updatedAtLabel = computed(() => form.value ? new Date(form.value.updatedAt).toLocaleString() : '')
const hasUserId = computed(() => Boolean(settingsStore.profile.userId))
const activeFormName = computed(() => formEntries.value.find((entry) => entry.formId === activeFormId.value)?.name || '切换表格')
const tagFilterOptions = computed(() => [{ value: '', label: '全部标签' }, ...tagFilters.value.map((tag) => ({ value: tag, label: tag }))])
const tagFilterLabel = computed(() => tagFilter.value || '全部标签')
const ratingFilterOptions = [
  { value: 0, label: '全部星级' },
  { value: 5, label: '5 星' },
  { value: 4, label: '4 星以上' },
  { value: 3, label: '3 星以上' },
]
const ratingFilterLabel = computed(() => ratingFilterOptions.find((option) => option.value === minRating.value)?.label || '全部星级')

/** Opens the creation dialog and focuses its dynamically teleported name field after mounting. */
async function openCreateForm(): Promise<void> {
  newFormKind.value = 'smart'
  createFormOpen.value = true
  await nextTick()
  newFormTitleInput.value?.focus()
}

/** Changes the table type without leaving subsequent keyboard input trapped on the type button. */
function selectNewFormKind(kind: 'smart' | 'plain'): void {
  newFormKind.value = kind
  newFormTitleInput.value?.focus()
}

const customColumnTypes: { value: SmartColumnType; label: string }[] = [
  { value: 'text', label: '文本' },
  { value: 'smart_text', label: '智能文本' },
  { value: 'tag', label: '标签' },
  { value: 'smart_tag', label: '智能标签' },
  { value: 'boolean', label: '是/否' },
  { value: 'star', label: '星级' },
  { value: 'date', label: '日期' },
]
const refreshingLiteraturePaths = new Set<string>()

/** 同步根容器宽度到移动端标记；初始即为窄屏时也立即生效。 */
function updateShellLayout(): void {
  isMobileLayout.value = props.mobile || props.availableWidth <= 640 || (smartFormsShell.value?.clientWidth ?? 0) <= 640
}

watch([() => props.mobile, () => props.availableWidth], updateShellLayout)

/** Shrinks the two leading literature columns so ultra-narrow views retain context. */
function responsiveColumnWidth(column: SmartColumn): number {
  if (!isMobileLayout.value || !Number.isFinite(props.availableWidth)) return column.width
  const halfContentWidth = Math.floor((props.availableWidth - 44) / 2)
  if (column.id === 'literature_file') return Math.min(column.width, Math.max(120, halfContentWidth))
  if (column.id === 'literature_content' || column.id === 'figures') return Math.min(column.width, Math.max(150, halfContentWidth))
  return column.width
}

/** Applies one responsive column width consistently to both header rows. */
function columnWidthStyle(column: SmartColumn): Record<string, string> {
  const width = responsiveColumnWidth(column)
  return { width: `${width}px`, minWidth: `${width}px`, maxWidth: `${width}px` }
}

onMounted(() => {
  window.addEventListener('mouseup', stopCellSelection)
  window.addEventListener('metaweave-knowledge-file-change', handleKnowledgeFileChange)
  updateShellLayout()
  shellResizeObserver = new ResizeObserver(updateShellLayout)
  if (smartFormsShell.value) shellResizeObserver.observe(smartFormsShell.value)
  void loadForm()
})

onBeforeUnmount(() => {
  window.removeEventListener('mouseup', stopCellSelection)
  window.removeEventListener('metaweave-knowledge-file-change', handleKnowledgeFileChange)
  shellResizeObserver?.disconnect()
  shellResizeObserver = null
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (swapAnimationTimer) clearTimeout(swapAnimationTimer)
  if (columnDescriptionClickTimer) clearTimeout(columnDescriptionClickTimer)
  if (literatureFileClickTimer) clearTimeout(literatureFileClickTimer)
  stopTableResize()
  closeTableContextMenu()
})

async function loadForm(): Promise<void> {
  if (!settingsStore.profile.userId) return
  loading.value = true
  try {
    let entries = await listSmartForms()
    if (!entries.length) {
      entries = await importLegacySmartForms()
    }
    formEntries.value = entries
    if (!entries.length) {
      form.value = null
      activeFormId.value = ''
      activeFormDir.value = ''
      selectedCell.value = null
      selectedCellKeys.value = []
      return
    }
    await openForm(entries[0]!)
  } catch (error) {
    workspaceStore.showToast(`读取智能表格失败 - ${errorMessage(error)}`)
  } finally {
    loading.value = false
  }
}

/** Loads user-created smart forms from the database. */
async function listSmartForms(): Promise<SmartFormEntry[]> {
  if (!settingsStore.profile.userId) return []
  const entries = await listSmartFormsDb(
    settingsStore.profile.userId,
    settingsStore.activeKnowledgeLibrary?.libraryId || settingsStore.profile.activeLibraryId,
  )
  return entries.map((entry) => ({
    formId: entry.form_id,
    name: entry.title,
    assetDir: entry.asset_dir,
  }))
}

/** Imports legacy smart-form JSON files once when the database is empty. */
async function importLegacySmartForms(): Promise<SmartFormEntry[]> {
  if (!settingsStore.profile.userId) return []
  const response = await listKnowledgeFiles(settingsStore.profile.userId)
  const formsRoot = response.tree.find((node) => node.isDir && node.path === FORMS_ROOT_DIR)
  const legacyDirs = (formsRoot?.children ?? []).filter((node) => node.isDir)
  if (!legacyDirs.length) return []
  for (const node of legacyDirs) {
    try {
      const legacy = await readKnowledgeFile(settingsStore.profile.userId, `${node.path}/form.json`)
      const legacyForm = normalizeForm(JSON.parse(legacy.content) as SmartLiteratureForm)
      await saveSmartFormDb({
        user_id: settingsStore.profile.userId,
        library_id: settingsStore.activeKnowledgeLibrary?.libraryId || settingsStore.profile.activeLibraryId,
        form_kind: 'literature',
        asset_dir: node.path,
        form: legacyForm,
      })
    } catch {
      // Ignore invalid legacy folders; database storage is the source of truth after import.
    }
  }
  return listSmartForms()
}

/** Opens an existing smart form from the database. */
async function openForm(entry: SmartFormEntry): Promise<void> {
  if (!settingsStore.profile.userId) return
  try {
    const response = await getSmartFormDb(settingsStore.profile.userId, entry.formId)
    form.value = normalizeForm(response.form)
    activeFormId.value = response.form_id
    activeFormDir.value = response.asset_dir || entry.assetDir
    selectedCell.value = null
    selectedCellKeys.value = []
    await loadImagePreviews()
  } catch (error) {
    workspaceStore.showToast(`打开表格失败 - ${errorMessage(error)}`)
  }
}

/** Opens a table selected from the database forms list. */
function openFormById(formId: string): void {
  const entry = formEntries.value.find((item) => item.formId === formId)
  if (entry) void openForm(entry)
}

function toggleDropdown(key: string): void {
  closeTableContextMenu()
  closeTagEditor()
  dropdownOpen.value = dropdownOpen.value === key ? '' : key
}

function closeDropdownMenus(): void {
  dropdownOpen.value = ''
}

function selectFormById(formId: string): void {
  openFormById(formId)
  closeDropdownMenus()
}

/** Deletes the active database table after explicit confirmation and opens the next table. */
async function deleteCurrentSmartForm(): Promise<void> {
  if (!settingsStore.profile.userId || !activeFormId.value || !form.value || saving.value) return
  if (!window.confirm(`确定删除表格“${form.value.title}”吗？此操作不可撤销。`)) return
  const deletedFormId = activeFormId.value
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = undefined
  }
  try {
    await deleteSmartFormDb(settingsStore.profile.userId, deletedFormId)
    formEntries.value = formEntries.value.filter((entry) => entry.formId !== deletedFormId)
    const nextForm = formEntries.value[0]
    if (nextForm) {
      await openForm(nextForm)
    } else {
      form.value = null
      activeFormId.value = ''
      activeFormDir.value = ''
      selectedCell.value = null
      selectedCellKeys.value = []
    }
    workspaceStore.showToast('表格已删除')
  } catch (error) {
    workspaceStore.showToast(`删除表格失败 - ${errorMessage(error)}`)
  }
}

/** Creates a user-named table and persists its initial state in the database. */
async function createSmartForm(): Promise<void> {
  if (!settingsStore.profile.userId) return
  const title = newFormTitle.value.trim()
  if (!title) {
    workspaceStore.showToast('请输入表名')
    return
  }
  const dir = uniqueFormDir(title)
  try {
    await createFolderIfMissing(FORMS_ROOT_DIR)
    await createFolderIfMissing(dir)
    if (newFormKind.value === 'smart') {
      await createFolderIfMissing(`${dir}/assets`)
    }
    form.value = newFormKind.value === 'smart'
      ? createDefaultLiteratureForm(title)
      : createDefaultPlainForm(title)
    activeFormId.value = ''
    activeFormDir.value = dir
    selectedCell.value = null
    selectedCellKeys.value = []
    await persistForm(false)
    formEntries.value = await listSmartForms()
    newFormTitle.value = ''
    newFormKind.value = 'smart'
    createFormOpen.value = false
    workspaceStore.showToast('表格已创建')
  } catch (error) {
    workspaceStore.showToast(`创建表格失败 - ${errorMessage(error)}`)
  }
}

/** Creates a filesystem-safe, collision-resistant folder path for a user table name. */
function uniqueFormDir(title: string): string {
  const base = title
    .replace(/[\\/:*?"<>|#%&{}$!'@+`=\s]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64) || 'table'
  const existingDirs = new Set(formEntries.value.map((entry) => entry.assetDir))
  let candidate = `${FORMS_ROOT_DIR}/${base}`
  let index = 2
  while (existingDirs.has(candidate)) {
    candidate = `${FORMS_ROOT_DIR}/${base}-${index}`
    index += 1
  }
  return candidate
}

async function persistForm(showSuccessToast: boolean): Promise<void> {
  if (!settingsStore.profile.userId || !form.value || !activeFormDir.value) return
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = undefined
  }
  const saveRevision = formRevision
  saving.value = true
  try {
    await ensureFormFolders()
    const formToSave = { ...form.value, updatedAt: new Date().toISOString() }
    form.value = formToSave
    const response = await saveSmartFormDb({
      user_id: settingsStore.profile.userId,
      form_id: activeFormId.value || undefined,
      library_id: settingsStore.activeKnowledgeLibrary?.libraryId || settingsStore.profile.activeLibraryId,
      form_kind: isLiteratureTable.value ? 'literature' : 'plain',
      asset_dir: activeFormDir.value,
      form: formToSave,
    })
    activeFormId.value = response.form_id
    activeFormDir.value = response.asset_dir
    if (formRevision === saveRevision) {
      form.value = normalizeForm(response.form)
    }
    if (showSuccessToast) {
      workspaceStore.showToast('智能表格已保存')
    }
  } catch (error) {
    workspaceStore.showToast(`保存失败 - ${errorMessage(error)}`)
  } finally {
    saving.value = false
  }
}

function setForm(nextForm: SmartLiteratureForm, autosave = true): void {
  formRevision += 1
  form.value = nextForm
  if (autosave) scheduleAutoSave()
}

function scheduleAutoSave(): void {
  if (!settingsStore.profile.userId || !form.value || !activeFormDir.value) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => {
    autoSaveTimer = undefined
    void persistForm(false)
  }, 250)
}

async function ensureFormFolders(): Promise<void> {
  if (!settingsStore.profile.userId || !activeFormDir.value) return
  await createFolderIfMissing(FORMS_ROOT_DIR)
  await createFolderIfMissing(activeFormDir.value)
  await createFolderIfMissing(activeFormAssetDir.value)
}

async function createFolderIfMissing(path: string): Promise<void> {
  try {
    await createKnowledgeFolder(settingsStore.profile.userId, path)
  } catch {
    // Existing folders are fine; the backend returns an error instead of a no-op.
  }
}

function addRowAt(rowId: string | undefined, direction: -1 | 1): SmartRow | undefined {
  if (!form.value) return undefined
  const index = rowId ? form.value.rows.findIndex((row) => row.id === rowId) : form.value.rows.length - 1
  const insertionIndex = Math.max(0, index + (direction > 0 ? 1 : 0))
  const rows = [...form.value.rows]
  const row = createEmptyRow(form.value.columns)
  if (!isLiteratureTable.value) row.height = PLAIN_ROW_HEIGHT
  rows.splice(insertionIndex, 0, row)
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows,
  })
  return row
}

/** Opens the same field-type chooser used by the third-level context menu. */
function openEdgeColumnMenu(event: MouseEvent): void {
  closeFloatingMenus()
  const menuWidth = 280
  const edge = 8
  const viewportWidth = window.innerWidth || 1024
  const viewportHeight = window.innerHeight || 768
  edgeColumnMenuStyle.value = {
    left: `${Math.min(Math.max(event.clientX - menuWidth, edge), viewportWidth - menuWidth - edge)}px`,
    top: `${Math.min(Math.max(event.clientY, edge), Math.max(edge, viewportHeight - 520))}px`,
  }
  customColumnTitle.value = ''
  customColumnDescription.value = ''
  edgeColumnMenuOpen.value = true
}

function deleteRecord(rowId: string): void {
  if (!form.value) return
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.filter((row) => row.id !== rowId),
  })
}

function editCell(row: SmartRow, column: SmartColumn, value: string): void {
  if (!form.value) return
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.map((item) => item.id === row.id ? updateCell(item, column, value) : item),
  })
}

/** Grows an ordinary-table row to fit all content while its editor is active. */
function resizeEditingCell(row: SmartRow, height: number): void {
  if (!form.value || isLiteratureTable.value) return
  setForm(resizeRow(form.value, row.id, Math.max(PLAIN_ROW_HEIGHT, height), PLAIN_ROW_HEIGHT, PLAIN_MAX_ROW_HEIGHT))
}

/** Keeps empty and one-line ordinary rows at the current baseline even when stale heights remain in memory. */
function displayedRowHeight(row: SmartRow): number {
  if (isLiteratureTable.value) return row.height || DEFAULT_ROW_HEIGHT
  const isEmpty = Object.values(row.cells).every((cell) => !cell.value.trim())
  return isEmpty ? PLAIN_ROW_HEIGHT : Math.max(PLAIN_ROW_HEIGHT, row.height || PLAIN_ROW_HEIGHT)
}

/** Persists generic textarea edits and keeps their ordinary-table row fully visible. */
function handleCellTextareaInput(row: SmartRow, column: SmartColumn, event: Event): void {
  const target = event.target as HTMLTextAreaElement
  editCell(row, column, target.value)
  if (isLiteratureTable.value) return
  target.style.height = 'auto'
  const height = target.scrollHeight
  target.style.height = '100%'
  resizeEditingCell(row, height)
}

/** Starts resizing a column from its right table boundary. */
function startColumnResize(column: SmartColumn, event: PointerEvent): void {
  event.preventDefault()
  event.stopPropagation()
  tableResize = { kind: 'column', id: column.id, start: event.clientX, size: column.width }
  window.addEventListener('pointermove', continueTableResize)
  window.addEventListener('pointerup', stopTableResize)
}

/** Starts resizing a row from its bottom table boundary. */
function startRowResize(row: SmartRow, event: PointerEvent): void {
  event.preventDefault()
  event.stopPropagation()
  tableResize = { kind: 'row', id: row.id, start: event.clientY, size: row.height || DEFAULT_ROW_HEIGHT }
  window.addEventListener('pointermove', continueTableResize)
  window.addEventListener('pointerup', stopTableResize)
}

/** Applies the active table-boundary drag to the persisted form dimensions. */
function continueTableResize(event: PointerEvent): void {
  if (!tableResize || !form.value) return
  const delta = tableResize.kind === 'column' ? event.clientX - tableResize.start : event.clientY - tableResize.start
  setForm(tableResize.kind === 'column'
    ? resizeColumn(form.value, tableResize.id, tableResize.size + delta)
    : resizeRow(
      form.value,
      tableResize.id,
      tableResize.size + delta,
      isLiteratureTable.value ? MIN_ROW_HEIGHT : PLAIN_ROW_HEIGHT,
      isLiteratureTable.value ? Infinity : DEFAULT_ROW_HEIGHT,
    ))
}

/** Ends table resizing and removes global pointer listeners. */
function stopTableResize(): void {
  tableResize = null
  window.removeEventListener('pointermove', continueTableResize)
  window.removeEventListener('pointerup', stopTableResize)
}

/** Adjusts a row for an expanded Markdown cell and restores its previous height on collapse. */
function resizeExpandedTextCell(row: SmartRow, expanded: boolean, contentHeight: number): void {
  if (!form.value) return
  if (expanded) {
    if (!expandedTextRowHeights.has(row.id)) expandedTextRowHeights.set(row.id, row.height || DEFAULT_ROW_HEIGHT)
    setForm(resizeRow(form.value, row.id, Math.max(row.height || DEFAULT_ROW_HEIGHT, contentHeight)))
    return
  }
  const previousHeight = expandedTextRowHeights.get(row.id)
  expandedTextRowHeights.delete(row.id)
  setForm(resizeRow(form.value, row.id, previousHeight || DEFAULT_ROW_HEIGHT))
}

function setRating(row: SmartRow, column: SmartColumn, rating: number): void {
  editCell(row, column, String(rating))
}

function booleanDropdownKey(rowId: string, columnId: string): string {
  return `boolean:${rowId}:${columnId}`
}

function booleanCellLabel(row: SmartRow, column: SmartColumn): string {
  return row.cells[column.id]?.value || '未设置'
}

function selectBooleanValue(row: SmartRow, column: SmartColumn, value: string): void {
  editCell(row, column, value)
  closeDropdownMenus()
}

function addColumnAt(column: SmartColumn, direction: -1 | 1): void {
  if (!form.value) return
  if (form.value.columns.some((item) => item.id === column.id)) {
    workspaceStore.showToast('该内置列已存在')
    return
  }
  const targetColumnId = tableContextTarget.value && 'columnId' in tableContextTarget.value
    ? tableContextTarget.value.columnId
    : undefined
  const targetIndex = targetColumnId
    ? form.value.columns.findIndex((item) => item.id === targetColumnId)
    : form.value.columns.length
  const insertionIndex = Math.max(0, targetIndex + (direction > 0 ? 1 : 0))
  setForm(addColumn(form.value, { ...column }, insertionIndex))
}

function addCustomColumnAt(type: SmartColumnType, direction: -1 | 1): void {
  if (!form.value) return
  const targetColumnId = tableContextTarget.value && 'columnId' in tableContextTarget.value
    ? tableContextTarget.value.columnId
    : undefined
  const targetIndex = targetColumnId
    ? form.value.columns.findIndex((item) => item.id === targetColumnId)
    : form.value.columns.length
  setForm(addColumn(form.value, createCustomColumn(customColumnTitle.value, type, customColumnDescription.value), Math.max(0, targetIndex + (direction > 0 ? 1 : 0))))
  customColumnTitle.value = ''
  customColumnDescription.value = ''
}

function removeColumnById(columnId: string): void {
  if (!form.value) return
  removeColumnsFromTable([columnId])
}

/** Removes literature source columns together and downgrades smart fields for ordinary tables. */
function removeColumnsFromTable(columnIds: string[]): void {
  if (!form.value) return
  const removesLiterature = columnIds.some((columnId) => columnId === 'literature_file' || columnId === 'literature_content')
  const ids = removesLiterature
    ? [...new Set([...columnIds, 'literature_file', 'literature_content'])]
    : columnIds
  let nextForm = ids.reduce((currentForm, columnId) => removeColumn(currentForm, columnId), form.value)
  if (removesLiterature) {
    nextForm = {
      ...nextForm,
      columns: nextForm.columns.map((column) => column.type === 'smart_text'
        ? { ...column, type: 'text' as const }
        : column.type === 'smart_tag'
          ? { ...column, type: 'tag' as const }
          : column),
    }
  }
  setForm(nextForm)
}

function moveColumnById(columnId: string, direction: -1 | 1): void {
  if (!form.value) return
  setForm(moveColumn(form.value, columnId, direction))
}

/** Starts in-place editing for a user-created column header. */
function startColumnTitleEdit(column: SmartColumn): void {
  if (!column.id.startsWith('col_')) return
  editingColumnId.value = column.id
  columnTitleDraft.value = column.title
}

/** Commits a custom column title and lets the existing autosave persist it. */
function commitColumnTitleEdit(column: SmartColumn): void {
  if (!form.value || editingColumnId.value !== column.id) return
  const title = columnTitleDraft.value.trim()
  if (title) {
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      columns: form.value.columns.map((item) => item.id === column.id ? { ...item, title } : item),
    })
  }
  editingColumnId.value = ''
  columnTitleDraft.value = ''
}

/** Cancels custom column title editing without changing the stored title. */
function cancelColumnTitleEdit(): void {
  editingColumnId.value = ''
  columnTitleDraft.value = ''
}

/** Expands or collapses one non-index column's auxiliary description row. */
function toggleColumnDescription(column: SmartColumn): void {
  if (column.type === 'index') return
  const expanded = new Set(expandedColumnDescriptions.value)
  if (expanded.has(column.id)) expanded.delete(column.id)
  else expanded.add(column.id)
  expandedColumnDescriptions.value = expanded
}

/** Delays the single-click action so a double click can enter editing before layout moves the icon. */
function scheduleColumnDescriptionToggle(column: SmartColumn): void {
  if (columnDescriptionClickTimer) clearTimeout(columnDescriptionClickTimer)
  columnDescriptionClickTimer = setTimeout(() => {
    columnDescriptionClickTimer = undefined
    toggleColumnDescription(column)
  }, 220)
}

/** Cancels the pending single click and opens the exact column description editor. */
function handleColumnDescriptionDoubleClick(column: SmartColumn): void {
  if (columnDescriptionClickTimer) clearTimeout(columnDescriptionClickTimer)
  columnDescriptionClickTimer = undefined
  void startColumnDescriptionEdit(column)
}

/** Stores the rendered auxiliary-description input for deterministic focus. */
function setColumnDescriptionInputRef(columnId: string, element: unknown): void {
  columnDescriptionInputById[columnId] = element instanceof HTMLInputElement ? element : null
}

/** Opens direct auxiliary-description editing after a header-icon double click. */
async function startColumnDescriptionEdit(column: SmartColumn): Promise<void> {
  if (column.type === 'index') return
  expandedColumnDescriptions.value = new Set([...expandedColumnDescriptions.value, column.id])
  editingColumnDescriptionId.value = column.id
  columnDescriptionDraft.value = column.description ?? ''
  await nextTick()
  columnDescriptionInputById[column.id]?.focus()
}

/** Persists an edited auxiliary description through the table's existing autosave path. */
function commitColumnDescriptionEdit(column: SmartColumn): void {
  if (!form.value || editingColumnDescriptionId.value !== column.id) return
  const description = columnDescriptionDraft.value.trim()
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    columns: form.value.columns.map((item) => item.id === column.id
      ? { ...item, description: description || undefined }
      : item),
  })
  editingColumnDescriptionId.value = ''
  columnDescriptionDraft.value = ''
}

/** Leaves auxiliary-description editing without changing persisted column data. */
function cancelColumnDescriptionEdit(): void {
  editingColumnDescriptionId.value = ''
  columnDescriptionDraft.value = ''
}

function moveRowById(rowId: string, direction: -1 | 1): void {
  if (!form.value) return
  setForm(moveRow(form.value, rowId, direction))
}

/** Moves the row addressed by the current cell/row context target and closes the menu. */
function moveContextRow(direction: -1 | 1): void {
  const target = tableContextTarget.value
  if (!target || !('rowId' in target)) return
  moveRowById(target.rowId, direction)
  closeTableContextMenu()
}

/** Moves the column addressed by the current cell/column context target and closes the menu. */
function moveContextColumn(direction: -1 | 1): void {
  const target = tableContextTarget.value
  if (!target || !('columnId' in target)) return
  moveColumnById(target.columnId, direction)
  closeTableContextMenu()
}

function startColumnDrag(columnId: string, event: DragEvent): void {
  draggedColumnId.value = columnId
  event.dataTransfer?.setData('text/plain', columnId)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function dropColumn(columnId: string): void {
  if (!form.value || !draggedColumnId.value || draggedColumnId.value === columnId) return
  const sourceColumnId = draggedColumnId.value
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    columns: moveItemToTarget(form.value.columns, sourceColumnId, columnId, (column) => column.id),
  })
  markSwapAnimation(sourceColumnId, '')
  draggedColumnId.value = ''
}

function endColumnDrag(): void {
  draggedColumnId.value = ''
}

function startRowDrag(rowId: string, event: DragEvent): void {
  draggedRowId.value = rowId
  event.dataTransfer?.setData('text/plain', rowId)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function dropRow(rowId: string): void {
  if (!form.value || !draggedRowId.value || draggedRowId.value === rowId) return
  const sourceRowId = draggedRowId.value
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: moveItemToTarget(form.value.rows, sourceRowId, rowId, (row) => row.id),
  })
  markSwapAnimation('', sourceRowId)
  draggedRowId.value = ''
}

function endRowDrag(): void {
  draggedRowId.value = ''
}

function moveItemToTarget<T>(items: T[], sourceId: string, targetId: string, getId: (item: T) => string): T[] {
  const nextItems = [...items]
  const sourceIndex = nextItems.findIndex((item) => getId(item) === sourceId)
  const targetIndex = nextItems.findIndex((item) => getId(item) === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return items
  const [source] = nextItems.splice(sourceIndex, 1)
  if (!source) return items
  nextItems.splice(targetIndex, 0, source)
  return nextItems
}

function markSwapAnimation(columnId: string, rowId: string): void {
  swappedColumnId.value = columnId
  swappedRowId.value = rowId
  if (swapAnimationTimer) clearTimeout(swapAnimationTimer)
  swapAnimationTimer = setTimeout(() => {
    swappedColumnId.value = ''
    swappedRowId.value = ''
  }, 360)
}

function setTableContextSubmenuRef(key: string, element: unknown): void {
  tableContextSubmenuRefs[key] = element instanceof HTMLElement ? element : null
}

function handleTableSubmenuLeave(key: string, event: MouseEvent): void {
  const parent = event.currentTarget
  if (parent instanceof HTMLElement) {
    scheduleTableSubmenuClose(key, event, parent, tableContextSubmenuRefs[key] ?? null)
  }
}

function openTableContextMenu(target: TableContextTarget, event: MouseEvent): void {
  closeTagEditor()
  tableContextTarget.value = target
  tableContextSubmenu.value = ''
  const edge = 8
  const menuWidth = 252
  const submenuWidth = 248
  const gap = 8
  const viewportWidth = window.innerWidth || 1024
  const rightOpeningLimit = viewportWidth - menuWidth - submenuWidth - gap - edge
  const opensLeft = event.clientX > rightOpeningLimit
  tableContextSubmenuSide.value = opensLeft ? 'left' : 'right'
  const left = opensLeft
    ? Math.min(Math.max(event.clientX, edge + submenuWidth + gap), viewportWidth - menuWidth - edge)
    : Math.min(Math.max(event.clientX, edge), rightOpeningLimit)
  tableContextMenuStyle.value = {
    left: `${Math.max(edge, left)}px`,
    top: `${Math.min(Math.max(event.clientY, edge), Math.max(edge, (window.innerHeight || 768) - 300))}px`,
  }
}

function closeTableContextMenu(): void {
  tableContextTarget.value = null
  tableContextSubmenu.value = ''
}

function closeFloatingMenus(): void {
  closeDropdownMenus()
  closeTableContextMenu()
  closeTagEditor()
  edgeColumnMenuOpen.value = false
}

function cellKey(rowId: string, columnId: string): string {
  return `${rowId}:${columnId}`
}

function isCellSelected(rowId: string, columnId: string): boolean {
  return selectedCellKeySet.value.has(cellKey(rowId, columnId))
}

/** Draws only the outside edges of a rectangular drag selection. */
function cellSelectionStyle(rowId: string, columnId: string): Record<string, string> {
  if (!form.value || !isCellSelected(rowId, columnId)) return {}
  const rowIds = visibleRows.value.map((row) => row.id)
  const columnIds = form.value.columns.map((column) => column.id)
  const rowIndex = rowIds.indexOf(rowId)
  const columnIndex = columnIds.indexOf(columnId)
  const shadows: string[] = []
  const color = 'var(--color-primary)'
  if (!selectedCellKeySet.value.has(cellKey(rowIds[rowIndex - 1] || '', columnId))) shadows.push(`inset 0 2px 0 ${color}`)
  if (!selectedCellKeySet.value.has(cellKey(rowIds[rowIndex + 1] || '', columnId))) shadows.push(`inset 0 -2px 0 ${color}`)
  if (!selectedCellKeySet.value.has(cellKey(rowId, columnIds[columnIndex - 1] || ''))) shadows.push(`inset 2px 0 0 ${color}`)
  if (!selectedCellKeySet.value.has(cellKey(rowId, columnIds[columnIndex + 1] || ''))) shadows.push(`inset -2px 0 0 ${color}`)
  return { '--cell-selection-shadow': shadows.join(', ') || 'none' }
}

function selectedCells(): CellCoord[] {
  return selectedCellKeys.value.map((key) => {
    const [rowId = '', columnId = ''] = key.split(':')
    return { rowId, columnId }
  }).filter((cell) => cell.rowId && cell.columnId)
}

function selectSingleCell(rowId: string, columnId: string): void {
  selectedCell.value = { rowId, columnId }
  selectedCellKeys.value = [cellKey(rowId, columnId)]
}

/** Keeps a clicked cell selected while allowing a double-click to enter editing. */
function handleCellClick(rowId: string, columnId: string): void {
  selectSingleCell(rowId, columnId)
}

function startCellSelection(rowId: string, columnId: string, event: MouseEvent): void {
  if (event.button !== 0) return
  closeFloatingMenus()
  dragAnchorCell.value = { rowId, columnId }
  selectSingleCell(rowId, columnId)
}

function extendCellSelection(rowId: string, columnId: string): void {
  if (!form.value || !dragAnchorCell.value) return
  const rowIds = visibleRows.value.map((row) => row.id)
  const columnIds = form.value.columns.map((column) => column.id)
  const rowStart = rowIds.indexOf(dragAnchorCell.value.rowId)
  const rowEnd = rowIds.indexOf(rowId)
  const columnStart = columnIds.indexOf(dragAnchorCell.value.columnId)
  const columnEnd = columnIds.indexOf(columnId)
  if (rowStart < 0 || rowEnd < 0 || columnStart < 0 || columnEnd < 0) return
  const [minRow, maxRow] = [Math.min(rowStart, rowEnd), Math.max(rowStart, rowEnd)]
  const [minColumn, maxColumn] = [Math.min(columnStart, columnEnd), Math.max(columnStart, columnEnd)]
  selectedCell.value = { rowId, columnId }
  selectedCellKeys.value = rowIds
    .slice(minRow, maxRow + 1)
    .flatMap((selectedRowId) => columnIds.slice(minColumn, maxColumn + 1).map((selectedColumnId) => cellKey(selectedRowId, selectedColumnId)))
}

function stopCellSelection(): void {
  dragAnchorCell.value = null
}

/** Prevents browser text selection during cell drag-selection while preserving input selection. */
function preventTableTextSelection(event: Event): void {
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return
  event.preventDefault()
}

function openCellContextMenu(row: SmartRow, column: SmartColumn, event: MouseEvent): void {
  if (!isCellSelected(row.id, column.id)) {
    selectSingleCell(row.id, column.id)
  }
  openTableContextMenu(selectedCellKeys.value.length > 1 ? { kind: 'selection' } : { kind: 'cell', rowId: row.id, columnId: column.id }, event)
}

function addNewRow(): SmartRow | undefined {
  return addRowAt(undefined, 1)
}

/** Adds a literature row and immediately delegates file selection to its native input. */
async function addLiteratureRowAndUpload(): Promise<void> {
  const row = addNewRow()
  if (!row) return
  await nextTick()
  openUpload(row.id)
}

const TAG_COLORS = Array.from({ length: 6 }, (_, index) => `var(--color-tag-${index + 1})`)

/** Stable tag color derived from the tag text, independent of the theme primary color. */
function tagColor(value: string): string {
  let hash = 0
  for (const ch of value) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0
  return TAG_COLORS[hash % TAG_COLORS.length]!
}

function tagPillStyle(value: string): Record<string, string> {
  const color = tagColor(value)
  return {
    background: `color-mix(in srgb, ${color} var(--tag-color-smart-strength), var(--color-surface-raised))`,
    color: 'var(--color-tag-pill-text)',
  }
}

function tagKey(rowId: string, columnId: string): string {
  return `${rowId}:${columnId}`
}

function isTagEditorOpen(rowId: string, columnId: string): boolean {
  return tagEditorKey.value === tagKey(rowId, columnId)
}

function openTagEditor(row: SmartRow, column: SmartColumn): void {
  const key = tagKey(row.id, column.id)
  if (tagEditorKey.value === key) {
    closeTagEditor()
    return
  }
  tagEditorKey.value = key
  tagDraft.value = ''
}

function closeTagEditor(): void {
  tagEditorKey.value = ''
  tagDraft.value = ''
}

function cellTags(row: SmartRow, column: SmartColumn): string[] {
  return splitTags(row.cells[column.id]?.value ?? '')
}

function updateTags(row: SmartRow, column: SmartColumn, tags: string[]): void {
  editCell(row, column, joinTags(tags))
}

function toggleTag(row: SmartRow, column: SmartColumn, tag: string): void {
  const tags = cellTags(row, column)
  updateTags(row, column, tags.includes(tag) ? tags.filter((item) => item !== tag) : [...tags, tag])
}

function removeTag(row: SmartRow, column: SmartColumn, tag: string): void {
  updateTags(row, column, cellTags(row, column).filter((item) => item !== tag))
}

function addTagFromDraft(row: SmartRow, column: SmartColumn): void {
  const draft = tagDraft.value.trim()
  if (!draft) return
  const tags = cellTags(row, column)
  if (!tags.includes(draft)) updateTags(row, column, [...tags, draft])
  tagDraft.value = ''
}

function isTagSelected(row: SmartRow, column: SmartColumn, tag: string): boolean {
  return cellTags(row, column).includes(tag)
}

function contextColumn(): SmartColumn | undefined {
  const target = tableContextTarget.value
  if (!form.value || !target || (target.kind !== 'column' && target.kind !== 'cell')) return undefined
  return form.value.columns.find((column) => column.id === target.columnId)
}

function contextRow(): SmartRow | undefined {
  const target = tableContextTarget.value
  if (!form.value || !target || (target.kind !== 'row' && target.kind !== 'cell')) return undefined
  return form.value.rows.find((row) => row.id === target.rowId)
}

function contextCell(): SmartCell | undefined {
  const target = tableContextTarget.value
  if (!target || target.kind !== 'cell') return undefined
  return contextRow()?.cells[target.columnId]
}

function contextRowId(): string | undefined {
  const target = tableContextTarget.value
  return target && (target.kind === 'row' || target.kind === 'cell') ? target.rowId : undefined
}

function contextColumnId(): string | undefined {
  const target = tableContextTarget.value
  return target && (target.kind === 'column' || target.kind === 'cell') ? target.columnId : undefined
}

function contextCells(): CellCoord[] {
  const target = tableContextTarget.value
  if (!target) return []
  if (target.kind === 'selection') return selectedCells()
  if (target.kind === 'cell') return [{ rowId: target.rowId, columnId: target.columnId }]
  return []
}

function contextRowIds(): string[] {
  const target = tableContextTarget.value
  if (!target) return []
  if (target.kind === 'selection') return [...new Set(selectedCells().map((cell) => cell.rowId))]
  const rowId = contextRowId()
  return rowId ? [rowId] : []
}

function contextColumnIds(): string[] {
  const target = tableContextTarget.value
  if (!target || !form.value) return []
  if (target.kind === 'selection') return [...new Set(selectedCells().map((cell) => cell.columnId))]
  const columnId = contextColumnId()
  return columnId ? [columnId] : []
}

function canSmartFillContext(): boolean {
  const target = tableContextTarget.value
  if (!form.value || !target) return false
  if (target.kind === 'selection') {
    return contextCells().some((cell) => ['smart_text', 'smart_tag'].includes(form.value!.columns.find((column) => column.id === cell.columnId)?.type ?? ''))
  }
  if (target.kind === 'cell') return ['smart_text', 'smart_tag'].includes(contextColumn()?.type ?? '')
  if (target.kind === 'column') return ['smart_text', 'smart_tag'].includes(contextColumn()?.type ?? '')
  return form.value.columns.some((column) => column.type === 'smart_text' || column.type === 'smart_tag')
}

function canDeleteContextColumn(): boolean {
  if (tableContextTarget.value?.kind === 'selection') {
    return contextColumnIds().some((columnId) => form.value?.columns.find((column) => column.id === columnId)?.removable)
  }
  const column = contextColumn()
  return Boolean(column?.removable)
}

function deleteContextRow(): void {
  const rowIds = new Set(contextRowIds())
  if (!form.value || !rowIds.size) return
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.filter((row) => !rowIds.has(row.id)),
  })
  selectedCellKeys.value = []
  closeTableContextMenu()
}

function deleteContextColumn(): void {
  if (!form.value) return
  const columnIds = contextColumnIds()
    .filter((columnId) => form.value?.columns.find((column) => column.id === columnId)?.removable)
  if (!columnIds.length) return
  removeColumnsFromTable(columnIds)
  selectedCellKeys.value = []
  closeTableContextMenu()
}

function copyTableContext(): void {
  const target = tableContextTarget.value
  if (!target) return
  if (target.kind === 'selection' && form.value) {
    tableClipboard.value = {
      kind: 'selection',
      cells: Object.fromEntries(contextCells().map((cell) => {
        const row = form.value!.rows.find((item) => item.id === cell.rowId)
        return [cellKey(cell.rowId, cell.columnId), structuredClone(row?.cells[cell.columnId] ?? { value: '' })]
      })),
    }
  } else if (target.kind === 'cell') {
    const cell = contextCell()
    if (cell) tableClipboard.value = { kind: 'cell', cell: { ...cell } }
  } else if (target.kind === 'row') {
    const row = contextRow()
    if (row) tableClipboard.value = { kind: 'row', cells: structuredClone(row.cells) }
  } else if (target.kind === 'column' && form.value) {
    tableClipboard.value = {
      kind: 'column',
      values: Object.fromEntries(form.value.rows.map((row) => [row.id, structuredClone(row.cells[target.columnId] ?? { value: '' })])),
    }
  }
  closeTableContextMenu()
}

function pasteTableContext(): void {
  const target = tableContextTarget.value
  const clipboard = tableClipboard.value
  if (!target || !clipboard || !form.value) return
  if (target.kind === 'selection' && clipboard.kind === 'cell') {
    pasteCellToSelection(clipboard.cell)
  } else if (target.kind === 'selection' && clipboard.kind === 'selection') {
    pasteSelectionClipboard(clipboard.cells)
  } else if (target.kind === 'cell' && clipboard.kind === 'cell') {
    editCell(contextRow()!, contextColumn()!, clipboard.cell.value)
  } else if (target.kind === 'row' && clipboard.kind === 'row') {
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      rows: form.value.rows.map((row) => row.id === target.rowId ? { ...row, cells: structuredClone(clipboard.cells) } : row),
    })
  } else if (target.kind === 'column' && clipboard.kind === 'column') {
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      rows: form.value.rows.map((row) => ({
        ...row,
        cells: { ...row.cells, [target.columnId]: structuredClone(clipboard.values[row.id] ?? { value: '' }) },
      })),
    })
  }
  closeTableContextMenu()
}

function pasteCellToSelection(cell: SmartCell): void {
  if (!form.value) return
  const cells = contextCells()
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.map((row) => ({
      ...row,
      cells: {
        ...row.cells,
        ...Object.fromEntries(cells.filter((item) => item.rowId === row.id).map((item) => [item.columnId, { ...row.cells[item.columnId], ...cell }])),
      },
    })),
  })
}

function pasteSelectionClipboard(cellsByKey: Record<string, SmartCell>): void {
  if (!form.value) return
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.map((row) => ({
      ...row,
      cells: {
        ...row.cells,
        ...Object.fromEntries(contextCells()
          .filter((cell) => cell.rowId === row.id && cellsByKey[cellKey(cell.rowId, cell.columnId)])
          .map((cell) => [cell.columnId, { ...row.cells[cell.columnId], ...cellsByKey[cellKey(cell.rowId, cell.columnId)] }])),
      },
    })),
  })
}

function clearTableContext(): void {
  const target = tableContextTarget.value
  if (!target || !form.value) return
  if (target.kind === 'selection') {
    const cells = contextCells()
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      rows: form.value.rows.map((row) => ({
        ...row,
        cells: {
          ...row.cells,
          ...Object.fromEntries(cells.filter((cell) => cell.rowId === row.id).map((cell) => [cell.columnId, { ...row.cells[cell.columnId], value: '' }])),
        },
      })),
    })
  } else if (target.kind === 'cell') {
    editCell(contextRow()!, contextColumn()!, '')
  } else if (target.kind === 'row') {
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      rows: form.value.rows.map((row) => row.id === target.rowId ? { ...row, cells: Object.fromEntries(form.value!.columns.map((column) => [column.id, { ...row.cells[column.id], value: '' }])) } : row),
    })
  } else if (target.kind === 'column') {
    setForm({
      ...form.value,
      updatedAt: new Date().toISOString(),
      rows: form.value.rows.map((row) => ({ ...row, cells: { ...row.cells, [target.columnId]: { ...row.cells[target.columnId], value: '' } } })),
    })
  }
  closeTableContextMenu()
}

/** Clears failure markers only from empty cells without touching retained content. */
function clearInvalidFields(): void {
  if (!form.value) return
  let clearedCount = 0
  const rows = form.value.rows.map((row) => ({
    ...row,
    cells: Object.fromEntries(form.value!.columns.map((column) => {
      const cell = row.cells[column.id] ?? { value: '' }
      const invalid = cell.status === 'failed' && !cell.value.trim()
      if (!invalid) return [column.id, cell]
      clearedCount += 1
      return [column.id, { ...cell, value: '', status: undefined } as SmartCell]
    })),
  }))
  if (!clearedCount) {
    workspaceStore.showToast('没有可清空的无效字段')
    return
  }
  setForm({ ...form.value, updatedAt: new Date().toISOString(), rows })
  workspaceStore.showToast(`已清空 ${clearedCount} 个无效字段`)
}

function smartFillTableContext(): void {
  const target = tableContextTarget.value
  if (!target || !form.value) return
  const selectionCells = target.kind === 'selection' ? contextCells() : []
  closeTableContextMenu()
  if (target.kind === 'selection') {
    void generateSmartCellsForSelection(selectionCells, true)
  } else if (target.kind === 'cell') {
    void generateSmartCellsForRows([target.rowId], [target.columnId], true)
  } else if (target.kind === 'column') {
    void generateSmartCellsForRows(form.value.rows.map((row) => row.id), [target.columnId], true)
  } else if (target.kind === 'row') {
    void generateSmartCellsForRows([target.rowId], undefined, true)
  } else {
    void generateSmartCellsForRows(form.value.rows.map((row) => row.id), undefined, true)
  }
}

async function generateSmartCellsForSelection(cells: CellCoord[], showSuccessToast = false): Promise<void> {
  if (!form.value) return
  const smartColumnIds = [...new Set(cells
    .map((cell) => form.value?.columns.find((item) => item.id === cell.columnId))
    .filter((column) => column?.type === 'smart_text' || column?.type === 'smart_tag')
    .map((column) => column!.id))]
  const rowIds = [...new Set(cells.map((cell) => cell.rowId))]
  if (!smartColumnIds.length || !rowIds.length) {
    if (showSuccessToast) showSmartFillToast({ ready: 0, failed: 0 })
    return
  }
  const result = await generateSmartCellsForRows(rowIds, smartColumnIds, false)
  if (showSuccessToast) showSmartFillToast(result)
}

function addContextColumn(column: SmartColumn, direction: -1 | 1): void {
  if (!isLiteratureTable.value && (column.type === 'smart_text' || column.type === 'smart_tag')) return
  addColumnAt(column, direction)
  closeTableContextMenu()
}

function addContextCustomColumn(type: SmartColumnType, direction: -1 | 1): void {
  if (!isLiteratureTable.value && (type === 'smart_text' || type === 'smart_tag')) return
  addCustomColumnAt(type, direction)
  closeTableContextMenu()
}

/** Appends a built-in field selected from the table's right-edge chooser. */
function addEdgeColumn(column: SmartColumn): void {
  if (!isLiteratureTable.value && (column.type === 'smart_text' || column.type === 'smart_tag')) return
  addColumnAt(column, 1)
  edgeColumnMenuOpen.value = false
}

function generateSmartCells(scope: 'selected' | 'all'): void {
  if (!form.value) return
  const target = selectedCell.value
  if (scope === 'selected') {
    const column = form.value.columns.find((item) => item.id === target?.columnId)
    if (!target || !column || (column.type !== 'smart_text' && column.type !== 'smart_tag')) {
      workspaceStore.showToast('请选择一个智能列单元格')
      return
    }
  }
  void generateSmartCellsForRows(
    scope === 'all' ? form.value.rows.map((row) => row.id) : [target!.rowId],
    scope === 'selected' ? [target!.columnId] : undefined,
    true,
  )
}

/** Regenerates a single smart cell from the row's extracted literature content. */
async function generateSmartCellsForRows(rowIds: string[], columnIds?: string[], showSuccessToast = false): Promise<SmartFillResult> {
  const result: SmartFillResult = { ready: 0, failed: 0 }
  if (!form.value) return result
  const currentForm = form.value
  const smartColumns = currentForm.columns.filter((column) => {
    const isSmart = column.type === 'smart_text' || column.type === 'smart_tag'
    return isSmart && (!columnIds || columnIds.includes(column.id))
  })
  if (!smartColumns.length || !settingsStore.profile.userId) return result
  const rowIdSet = new Set(rowIds)
  const tokensByCell = markSmartCellsPending(rowIdSet, smartColumns, currentForm)
  if (!Object.keys(tokensByCell).length) return result
  const results = await Promise.all(rowIds.map(async (rowId): Promise<SmartFillResult> => {
    const rowResult: SmartFillResult = { ready: 0, failed: 0 }
    const currentRow = form.value.rows.find((item) => item.id === rowId)
    if (!currentRow) return rowResult
    const literatureContent = currentRow.cells.literature_content?.value.trim() ?? ''
    if (!literatureContent) {
      const applied = patchStructuredGenerationResults(rowId, smartColumns, smartColumns.map((column) => ({
        field_id: column.id,
        status: 'failed',
        value: '',
        error: '缺少文献内容，无法生成',
      })), tokensByCell)
      rowResult.ready += applied.ready
      rowResult.failed += applied.failed
      return rowResult
    }
    try {
      const response = await enqueueStructuredGeneration(() => generateStructuredFields({
          user_id: settingsStore.profile.userId,
          source: {
            kind: 'literature_document',
            content: literatureContent,
            metadata: { form_id: activeFormId.value, row_id: rowId },
          },
          fields: smartColumns.map((column) => ({
            id: column.id,
            title: column.title,
            type: column.type === 'smart_tag' ? 'tag' : 'text',
            description: column.description?.trim() || undefined,
            options: column.options ?? [],
            required: true,
          })),
          options: { language: 'zh', strict_json: true },
        }))
      const applied = patchStructuredGenerationResults(rowId, smartColumns, response.results, tokensByCell)
      rowResult.ready += applied.ready
      rowResult.failed += applied.failed
    } catch (error) {
      const applied = patchStructuredGenerationResults(rowId, smartColumns, smartColumns.map((column) => ({
        field_id: column.id,
        status: 'failed',
        value: '',
        error: errorMessage(error),
      })), tokensByCell)
      rowResult.ready += applied.ready
      rowResult.failed += applied.failed
    }
    return rowResult
  }))
  result.ready = results.reduce((sum, item) => sum + item.ready, 0)
  result.failed = results.reduce((sum, item) => sum + item.failed, 0)
  await persistForm(false)
  if (showSuccessToast) showSmartFillToast(result)
  return result
}

/** Keeps table generation asynchronous while limiting pressure on the shared LLM scheduler. */
function enqueueStructuredGeneration<T>(job: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    structuredGenerationQueue.push(async () => {
      try {
        resolve(await job())
      } catch (error) {
        reject(error)
      }
    })
    void drainStructuredGenerationQueue()
  })
}

/** Starts at most two requests and leaves later requests queued until a slot is released. */
function drainStructuredGenerationQueue(): void {
  while (structuredGenerationActive < structuredGenerationConcurrency && structuredGenerationQueue.length) {
    const nextJob = structuredGenerationQueue.shift()
    if (!nextJob) return
    structuredGenerationActive += 1
    void nextJob().finally(() => {
      structuredGenerationActive -= 1
      drainStructuredGenerationQueue()
    })
  }
}

function markSmartCellsPending(rowIdSet: Set<string>, smartColumns: SmartColumn[], currentForm: SmartLiteratureForm): Record<string, string> {
  const nextTokens = { ...generationTokens.value }
  const tokensByCell: Record<string, string> = {}
  setForm({
    ...currentForm,
    updatedAt: new Date().toISOString(),
    rows: currentForm.rows.map((row) => ({
      ...row,
      cells: Object.fromEntries(currentForm.columns.map((column) => {
        const cell = row.cells[column.id] ?? { value: '' }
        const isTarget = rowIdSet.has(row.id) && smartColumns.some((item) => item.id === column.id)
        if (!isTarget) return [column.id, cell]
        const key = cellKey(row.id, column.id)
        const token = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
        nextTokens[key] = token
        tokensByCell[key] = token
        return [column.id, { ...cell, status: 'pending' }]
      })),
    })),
  }, false)
  generationTokens.value = nextTokens
  return tokensByCell
}

function patchStructuredGenerationResults(rowId: string, columns: SmartColumn[], results: StructuredGenerationFieldResult[], tokensByCell: Record<string, string>): SmartFillResult {
  if (!form.value) return { ready: 0, failed: 0 }
  let ready = 0
  let failed = 0
  const currentRow = form.value.rows.find((row) => row.id === rowId)
  const nextTokens = { ...generationTokens.value }
  const resultByColumn = new Map(results.map((item) => [item.field_id, item]))
  const generatedCells: Array<[string, SmartCell]> = []
  columns.forEach((column) => {
    const key = cellKey(rowId, column.id)
    if (generationTokens.value[key] !== tokensByCell[key]) return
    delete nextTokens[key]
    const result = resultByColumn.get(column.id)
    if (result?.status === 'ready' && result.value.trim()) {
      ready += 1
      generatedCells.push([column.id, { ...currentRow?.cells[column.id], value: result.value.trim(), status: 'ready' }])
      return
    }
    failed += 1
    const retainedValue = currentRow?.cells[column.id]?.value || ''
    generatedCells.push([column.id, {
      ...currentRow?.cells[column.id],
      value: retainedValue,
      status: retainedValue.trim() ? 'ready' : 'failed',
    }])
  })
  const cells = Object.fromEntries(generatedCells)
  generationTokens.value = nextTokens
  if (Object.keys(cells).length) patchRowCells(rowId, cells)
  return { ready, failed }
}

function sumSmartFillResults(results: SmartFillResult[]): SmartFillResult {
  return results.reduce((sum, item) => ({ ready: sum.ready + item.ready, failed: sum.failed + item.failed }), { ready: 0, failed: 0 })
}

function showSmartFillToast(result: SmartFillResult): void {
  if (result.ready && !result.failed) {
    workspaceStore.showToast(`智能列已生成 ${result.ready} 项`)
  } else if (result.ready && result.failed) {
    workspaceStore.showToast(`智能填充完成: ${result.ready} 项成功, ${result.failed} 项失败/为空`)
  } else if (result.failed) {
    workspaceStore.showToast(`智能填充失败或为空: ${result.failed} 项`)
  } else {
    workspaceStore.showToast('没有可生成的智能列')
  }
}

function setUploadRef(rowId: string, element: unknown): void {
  uploadInputByRow.value[rowId] = element instanceof HTMLInputElement ? element : null
}

function openUpload(rowId: string): void {
  uploadInputByRow.value[rowId]?.click()
}

/** Uploads one file into the active form's fixed assets directory. */
async function uploadFormAsset(file: File): Promise<string> {
  if (!settingsStore.profile.userId) return ''
  await ensureFormFolders()
  const result = await uploadKnowledgeFile(settingsStore.profile.userId, file, activeFormAssetDir.value, false, 'rename') as {
    uploaded_path?: string
    knowledge_dir?: string
  }
  return relativeUploadedPath(result.uploaded_path ?? '', result.knowledge_dir ?? settingsStore.profile.knowledgeDir)
}

/** Opens an uploaded literature source in the independent editor sidebar. */
async function openLiteratureFile(row: SmartRow): Promise<void> {
  const cell = row.cells.literature_file
  if (!cell?.assetPath) {
    openUpload(row.id)
    return
  }
  await workspaceStore.openEditorSidebar({
    name: cell.fileName || cell.value,
    path: cell.assetPath,
    isDir: false,
  })
}

/** Defers the single-click sidebar action so a double click can navigate instead. */
function scheduleOpenLiteratureFile(row: SmartRow): void {
  if (literatureFileClickTimer) clearTimeout(literatureFileClickTimer)
  literatureFileClickTimer = setTimeout(() => {
    literatureFileClickTimer = undefined
    void openLiteratureFile(row)
  }, 220)
}

/** Opens the literature reader at this exact table row without firing the sidebar action. */
function openLiteratureReader(row: SmartRow): void {
  if (literatureFileClickTimer) {
    clearTimeout(literatureFileClickTimer)
    literatureFileClickTimer = undefined
  }
  const cell = row.cells.literature_file
  if (!cell?.assetPath || !activeFormId.value) {
    openUpload(row.id)
    return
  }
  workspaceStore.openLiteratureEntry(activeFormId.value, row.id)
}

/** Downloads an uploaded source file without changing the selected workspace file. */
async function downloadLiteratureFile(row: SmartRow): Promise<void> {
  const cell = row.cells.literature_file
  if (!cell?.assetPath || !settingsStore.profile.userId) return
  try {
    const preview = await previewKnowledgeFile(settingsStore.profile.userId, cell.assetPath)
    const sourceUrl = preview.raw_url ? buildApiUrl(preview.raw_url) : preview.data_url
    if (!sourceUrl) throw new Error('原文件下载地址不可用')
    const downloadUrl = new URL(sourceUrl, window.location.origin)
    downloadUrl.searchParams.set('download', '1')
    const anchor = document.createElement('a')
    anchor.href = downloadUrl.toString()
    anchor.download = cell.fileName || cell.value || 'download'
    anchor.click()
  } catch (error) {
    workspaceStore.showToast(`下载失败 - ${errorMessage(error)}`)
  }
}

/** Uploads a pasted cell image and returns its form-relative Markdown path. */
async function uploadCellImage(file: File): Promise<{ name: string; relativePath: string }> {
  const assetPath = await uploadFormAsset(file)
  if (!assetPath) throw new Error('图片上传未返回文件路径')
  await workspaceStore.loadKnowledgeTree()
  const name = assetPath.split('/').pop() || file.name || 'image.png'
  const relativePath = assetPath.startsWith(`${activeFormDir.value}/`)
    ? assetPath.slice(activeFormDir.value.length + 1)
    : `assets/${name}`
  return { name, relativePath }
}

async function uploadLiterature(row: SmartRow, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !settingsStore.profile.userId || !form.value) return
  try {
    const assetPath = await uploadFormAsset(file)
    if (assetPath && isPreviewImageFile(file.name)) {
      await loadImagePreview(assetPath)
    }
    await refillLiteratureRow(row.id, assetPath, file.name)
    workspaceStore.showToast('文献已上传并完成内容回填')
  } catch (error) {
    patchRowCells(row.id, {
      literature_content: { value: `上传或灌库失败: ${errorMessage(error)}`, status: 'failed' },
      figures: { value: '', status: 'failed' },
    })
    workspaceStore.showToast(`上传失败 - ${errorMessage(error)}`)
  }
}

/** Re-ingests one row source, refreshes extracted content, and regenerates every smart field. */
async function refillLiteratureRow(rowId: string, assetPath: string, fileName?: string): Promise<void> {
  if (!assetPath) throw new Error('文献文件路径为空')
  const currentRow = form.value?.rows.find((row) => row.id === rowId)
  const resolvedName = fileName || currentRow?.cells.literature_file?.fileName || assetPath.split('/').pop() || assetPath
  patchRowCells(rowId, {
    ...(fileName ? { literature_file: { value: fileName, fileName, assetPath } } : {}),
    literature_content: { value: '正在灌库并提取文献内容...', status: 'pending' },
    figures: { value: '正在汇总 PDF 图表...', status: 'pending' },
  })
  await workspaceStore.ingestFile({ name: resolvedName, path: assetPath, isDir: false, indexStatus: 'dirty' })
  const extracted = await extractUploadedLiterature(assetPath)
  patchRowCells(rowId, {
    literature_content: extracted.content
      ? { value: extracted.content, status: 'ready' }
      : { value: '文献已入库，但暂未取得可显示文本。请检查文件是否为扫描件或 OCR 设置。', status: 'failed' },
    figures: { value: extracted.figures, status: 'ready' },
  })
  if (extracted.content) await generateSmartCellsForRows([rowId])
  await persistForm(false)
  await workspaceStore.loadKnowledgeTree()
}

/** Treats a sidebar editor save as a fresh upload for every matching literature row. */
async function handleKnowledgeFileChange(event: Event): Promise<void> {
  const assetPath = (event as CustomEvent<{ path?: string }>).detail?.path?.trim() || ''
  if (!assetPath || refreshingLiteraturePaths.has(assetPath)) return
  const rowIds = form.value?.rows
    .filter((row) => row.cells.literature_file?.assetPath === assetPath)
    .map((row) => row.id) ?? []
  if (!rowIds.length) return
  refreshingLiteraturePaths.add(assetPath)
  try {
    for (const rowId of rowIds) await refillLiteratureRow(rowId, assetPath)
    workspaceStore.showToast('文献修改已重新灌库并刷新智能列')
  } catch (error) {
    workspaceStore.showToast(`文献修改回填失败 - ${errorMessage(error)}`)
  } finally {
    refreshingLiteraturePaths.delete(assetPath)
  }
}

async function loadImagePreviews(): Promise<void> {
  const imagePaths = form.value?.rows
    .map((row) => row.cells.literature_file?.assetPath || '')
    .filter((path) => path && isPreviewImageFile(path) && imagePreviewByPath.value[path] === undefined) ?? []
  for (const path of imagePaths) {
    await loadImagePreview(path)
  }
}

async function loadImagePreview(path: string): Promise<void> {
  if (!settingsStore.profile.userId || imagePreviewByPath.value[path] !== undefined) return
  try {
    const preview = await previewKnowledgeFile(settingsStore.profile.userId, path)
    const previewUrl = preview.thumbnail_url || preview.data_url || preview.raw_url || ''
    imagePreviewByPath.value = { ...imagePreviewByPath.value, [path]: previewUrl ? buildApiUrl(previewUrl) : '' }
  } catch {
    imagePreviewByPath.value = { ...imagePreviewByPath.value, [path]: '' }
  }
}

function isImageFile(fileName: string): boolean {
  return /\.(avif|gif|jpe?g|png|webp)$/i.test(fileName)
}

function isPreviewImageFile(fileName: string): boolean {
  return isImageFile(fileName) || /\.pdf$/i.test(fileName)
}

function fileIconForCell(fileName: string) {
  return materialFileIconForNode({ name: fileName, path: fileName, isDir: false })
}

function patchRowCells(rowId: string, cells: Record<string, SmartCell>): void {
  if (!form.value) return
  setForm({
    ...form.value,
    updatedAt: new Date().toISOString(),
    rows: form.value.rows.map((item) => item.id === rowId ? {
      ...item,
      cells: {
        ...item.cells,
        ...Object.fromEntries(Object.entries(cells).map(([columnId, cell]) => [
          columnId,
          { ...item.cells[columnId], ...cell },
        ])),
      },
    } : item),
  })
}

/** Reads ingested literature text and concentrates its PDF image links for the built-in figure column. */
async function extractUploadedLiterature(assetPath: string): Promise<{ content: string; figures: string }> {
  if (!settingsStore.profile.userId) return { content: '', figures: '' }
  try {
    const preview = await previewKnowledgeFile(settingsStore.profile.userId, assetPath)
    const content = [preview.semantic_markdown, preview.content, preview.render_content]
      .find((value) => typeof value === 'string' && value.trim())
    const persistedFigures = extractMarkdownImages(preview.semantic_markdown)
    const figures = /\.pdf$/i.test(assetPath)
      ? persistedFigures || extractMarkdownImages(preview.render_content)
      : ''
    if (content) return { content: normalizeLiteratureContent(content), figures }
    const tableContent = preview.sheets
      ?.flatMap((sheet) => [sheet.name, ...sheet.rows.map((row) => row.join('\t'))])
      .join('\n')
    if (tableContent?.trim()) return { content: normalizeLiteratureContent(tableContent), figures }
    if (preview.html?.trim()) {
      const document = new DOMParser().parseFromString(preview.html, 'text/html')
      const htmlContent = document.body.textContent?.trim() ?? ''
      if (htmlContent) return { content: normalizeLiteratureContent(htmlContent), figures }
    }
  } catch {
    // Fall through to direct text read for editable text/markdown uploads.
  }
  try {
    const response = await readKnowledgeFile(settingsStore.profile.userId, assetPath)
    return { content: normalizeLiteratureContent(response.content), figures: '' }
  } catch {
    return { content: '', figures: '' }
  }
}

function normalizeLiteratureContent(content: string): string {
  return content.replace(/\r\n/g, '\n').trim().slice(0, 12000)
}

function downloadCsv(): void {
  if (!form.value) return
  downloadText(`${form.value.title}.csv`, exportCsv(form.value), 'text/csv;charset=utf-8')
}

function downloadMarkdown(): void {
  if (!form.value) return
  downloadText(`${form.value.title}.md`, exportMarkdown(form.value), 'text/markdown;charset=utf-8')
}

function downloadZip(): void {
  if (!form.value) return
  const baseName = safeExportFileName(form.value.title)
  downloadBlob(`${baseName}.zip`, createZipBlob([
    { name: `${baseName}.md`, content: exportMarkdown(form.value) },
    { name: `${baseName}.csv`, content: exportCsv(form.value) },
    { name: 'form.json', content: JSON.stringify(form.value, null, 2) },
  ]))
}

function downloadText(fileName: string, content: string, type: string): void {
  downloadBlob(fileName, new Blob([content], { type }))
}

function downloadBlob(fileName: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

interface ZipSourceFile {
  name: string
  content: string
}

function createZipBlob(files: ZipSourceFile[]): Blob {
  const encoder = new TextEncoder()
  const locals: BlobPart[] = []
  const centrals: BlobPart[] = []
  let offset = 0
  for (const file of files) {
    const name = encoder.encode(file.name)
    const data = encoder.encode(file.content)
    const crc = crc32(data)
    const local = zipLocalHeader(name, data.length, crc)
    const central = zipCentralHeader(name, data.length, crc, offset)
    locals.push(local, name, data)
    centrals.push(central, name)
    offset += local.byteLength + name.byteLength + data.byteLength
  }
  const centralSize = centrals.reduce((sum, part) => sum + (part instanceof Uint8Array ? part.byteLength : 0), 0)
  return new Blob([...locals, ...centrals, zipEndHeader(files.length, centralSize, offset)], { type: 'application/zip' })
}

function zipLocalHeader(fileName: Uint8Array, size: number, crc: number): Uint8Array {
  const header = new Uint8Array(30)
  const view = new DataView(header.buffer)
  view.setUint32(0, 0x04034b50, true)
  view.setUint16(4, 20, true)
  view.setUint16(6, 0x0800, true)
  view.setUint16(8, 0, true)
  view.setUint16(10, 0, true)
  view.setUint16(12, 0, true)
  view.setUint32(14, crc, true)
  view.setUint32(18, size, true)
  view.setUint32(22, size, true)
  view.setUint16(26, fileName.byteLength, true)
  return header
}

function zipCentralHeader(fileName: Uint8Array, size: number, crc: number, offset: number): Uint8Array {
  const header = new Uint8Array(46)
  const view = new DataView(header.buffer)
  view.setUint32(0, 0x02014b50, true)
  view.setUint16(4, 20, true)
  view.setUint16(6, 20, true)
  view.setUint16(8, 0x0800, true)
  view.setUint16(10, 0, true)
  view.setUint16(12, 0, true)
  view.setUint16(14, 0, true)
  view.setUint32(16, crc, true)
  view.setUint32(20, size, true)
  view.setUint32(24, size, true)
  view.setUint16(28, fileName.byteLength, true)
  view.setUint32(42, offset, true)
  return header
}

function zipEndHeader(fileCount: number, centralSize: number, centralOffset: number): Uint8Array {
  const header = new Uint8Array(22)
  const view = new DataView(header.buffer)
  view.setUint32(0, 0x06054b50, true)
  view.setUint16(8, fileCount, true)
  view.setUint16(10, fileCount, true)
  view.setUint32(12, centralSize, true)
  view.setUint32(16, centralOffset, true)
  return header
}

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of data) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function safeExportFileName(value: string): string {
  return value.replace(/[\\/:*?"<>|]+/g, '-').trim() || 'smart-form'
}

function relativeUploadedPath(uploadedPath: string, knowledgeDir: string): string {
  const normalizedRoot = knowledgeDir.replace(/\\/g, '/').replace(/\/+$/g, '')
  const normalizedPath = uploadedPath.replace(/\\/g, '/')
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1)
  }
  return normalizedPath
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请检查后端连接'
}
</script>

<template>
  <section
    ref="smartFormsShell"
    class="smart-forms-view"
    :class="{ 'mobile-layout': props.mobile, 'compressed-layout': isCompressedLayout }"
    @click="closeFloatingMenus"
  >
    <header class="forms-header">
      <div class="forms-primary-row">
        <button
          v-if="form"
          class="new-row-btn"
          type="button"
          :title="isLiteratureTable ? '上传文献' : '新建行'"
          @click.stop="isLiteratureTable ? addLiteratureRowAndUpload() : addNewRow()"
        >
          <IcIcon :name="isLiteratureTable ? 'upload' : 'add'" :size="17" />
          <span>{{ isLiteratureTable ? '上传文献' : '新建行' }}</span>
        </button>
        <span v-else class="primary-icon-placeholder"></span>
        <div class="header-copy">
          <p class="forms-eyebrow">智能表格</p>
          <h1>{{ form?.title || '创建你的第一张表' }}</h1>
        </div>
        <label v-if="form" class="search-box">
          <IcIcon name="search" :size="15" />
          <input v-model="query" type="search" placeholder="搜索全表" />
        </label>
        <span v-else class="primary-search-placeholder"></span>
        <button class="primary-btn new-form-btn" type="button" title="新建表格" @click="openCreateForm">
          <IcIcon name="add" :size="17" />
          <span>新建表格</span>
        </button>
        <button
          v-if="form"
          class="delete-form-toolbar-btn mobile-hidden-action"
          type="button"
          title="删除表格"
          :disabled="!activeFormId || saving"
          @click="deleteCurrentSmartForm"
        >
          <IcIcon name="trash" :size="17" />
          <span>删除表格</span>
        </button>
      </div>

      <div v-if="form" class="forms-secondary-row">
        <div v-if="formEntries.length" class="smart-dropdown form-switch-control responsive-control-shell" @click.stop>
          <button class="smart-dropdown-trigger" type="button" title="切换表格" @click="toggleDropdown('forms')">
            <IcIcon name="table-chart" :size="17" />
            <span class="wide-control-label">{{ activeFormName }}</span>
            <span class="compact-control-label">切换表格</span>
            <IcIcon class="control-caret" name="chevron-down" :size="14" />
          </button>
          <div v-if="dropdownOpen === 'forms'" class="smart-dropdown-menu" @click.stop>
            <button
              v-for="(entry, index) in formEntries"
              :key="entry.formId"
              type="button"
              :style="{ '--item-index': index }"
              @click="selectFormById(entry.formId)"
            >
              <IcIcon v-if="activeFormId === entry.formId" name="check" :size="16" />
              <span v-else class="sort-check-placeholder"></span>
              <span>{{ entry.name }}</span>
            </button>
          </div>
        </div>
        <button v-if="isLiteratureTable" class="toolbar-btn bulk-action-capsule desktop-secondary-action" type="button" @click="generateSmartCells('all')">
          <IcIcon name="psychology" :size="17" />
          <span>全表智能填充</span>
        </button>
        <div class="filter-controls" :class="{ open: compactFiltersOpen }">
          <div class="responsive-control-shell filter-control-shell">
          <DropdownMenu v-model:open="tagFilterMenuOpen">
            <DropdownMenuTrigger as-child>
              <button class="smart-dropdown-trigger tag-filter-trigger" type="button" title="标签筛选">
                <IcIcon name="label" :size="17" />
                <span class="wide-control-label">{{ tagFilterLabel }}</span>
                <span class="compact-control-label">标签筛选</span>
                <IcIcon class="control-caret" name="chevron-down" :size="14" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuPortal>
              <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup v-model="tagFilter">
                  <DropdownMenuRadioItem v-for="option in tagFilterOptions" :key="option.value || 'all-tags'" :value="option.value">{{ option.label }}</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenuPortal>
          </DropdownMenu>
          </div>
          <div class="responsive-control-shell filter-control-shell">
          <DropdownMenu v-model:open="ratingFilterMenuOpen">
            <DropdownMenuTrigger as-child>
              <button class="smart-dropdown-trigger rating-filter-trigger" type="button" title="星级筛选">
                <IcIcon name="star" :size="17" />
                <span class="wide-control-label">{{ ratingFilterLabel }}</span>
                <span class="compact-control-label">星级筛选</span>
                <IcIcon class="control-caret" name="chevron-down" :size="14" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuPortal>
              <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup v-model="minRating">
                  <DropdownMenuRadioItem v-for="option in ratingFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenuPortal>
          </DropdownMenu>
          </div>
        </div>
        <div class="responsive-control-shell compact-filter-shell">
        <button
          class="smart-dropdown-trigger compact-filter-toggle"
          :class="{ active: compactFiltersOpen }"
          type="button"
          title="筛选"
          aria-label="筛选"
          :aria-expanded="compactFiltersOpen"
          @click.stop="compactFiltersOpen = !compactFiltersOpen"
        >
          <IcIcon name="filter" :size="17" />
          <span class="compact-control-label">筛选</span>
        </button>
        </div>
        <button class="toolbar-btn bulk-action-capsule clear-invalid-btn desktop-secondary-action" type="button" title="清除失败或空字段" @click="clearInvalidFields">
          <IcIcon name="trash" :size="17" />
          <span>清空无效字段</span>
        </button>
        <div class="smart-dropdown export-menu desktop-secondary-action" @click.stop>
          <button class="icon-btn v1-icon-button" type="button" title="导出表格" aria-label="导出表格" @click="toggleDropdown('export')"><IcIcon name="download" :size="17" /></button>
          <div v-if="dropdownOpen === 'export'" class="smart-dropdown-menu export-menu-panel">
            <button type="button" :style="{ '--item-index': 0 }" @click="downloadMarkdown">Markdown</button>
            <button type="button" :style="{ '--item-index': 1 }" @click="downloadCsv">CSV</button>
            <button type="button" :style="{ '--item-index': 2 }" @click="downloadZip">ZIP</button>
          </div>
        </div>
        <div class="responsive-control-shell compact-more-shell">
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <button class="smart-dropdown-trigger compact-more-trigger" type="button" title="其他操作">
              <IcIcon name="more-horiz" :size="17" />
              <span class="compact-control-label">其他</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent align="end">
              <DropdownMenuItem :disabled="!isLiteratureTable" @select="generateSmartCells('all')"><IcIcon name="psychology" :size="16" /><span>全表智能填充</span></DropdownMenuItem>
              <DropdownMenuItem @select="clearInvalidFields"><IcIcon name="trash" :size="16" /><span>清空无效字段</span></DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>导出</DropdownMenuLabel>
              <DropdownMenuItem @select="downloadMarkdown">Markdown</DropdownMenuItem>
              <DropdownMenuItem @select="downloadCsv">CSV</DropdownMenuItem>
              <DropdownMenuItem @select="downloadZip">ZIP</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem v-if="isMobileLayout" variant="destructive" :disabled="!activeFormId || saving" @select="deleteCurrentSmartForm"><IcIcon name="trash" :size="16" /><span>删除表格</span></DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenu>
        </div>
      </div>
    </header>

    <Teleport to="body">
      <div v-if="createFormOpen" class="form-dialog-backdrop" @click.self="createFormOpen = false">
        <form class="form-dialog library-form-surface" role="dialog" aria-modal="true" aria-labelledby="create-form-title" @submit.prevent="createSmartForm">
        <div class="form-dialog-header">
          <h2 id="create-form-title">创建表格</h2>
          <button class="dialog-close" type="button" title="关闭" aria-label="关闭" @click="createFormOpen = false">
            <IcIcon name="close" :size="18" />
          </button>
        </div>
        <label class="dialog-field">
          <span>表格名称</span>
          <input ref="newFormTitleInput" class="form-input-surface" v-model="newFormTitle" type="text" placeholder="例如：项目文献库" />
        </label>
        <div class="form-kind-picker" role="radiogroup" aria-label="表格类型">
          <button
            class="form-kind-pill"
            :class="{ active: newFormKind === 'smart' }"
            data-form-kind="smart"
            type="button"
            role="radio"
            :aria-checked="newFormKind === 'smart'"
            @click="selectNewFormKind('smart')"
          >智能表格(默认)</button>
          <button
            class="form-kind-pill"
            :class="{ active: newFormKind === 'plain' }"
            data-form-kind="plain"
            type="button"
            role="radio"
            :aria-checked="newFormKind === 'plain'"
            @click="selectNewFormKind('plain')"
          >普通表格</button>
        </div>
        <div class="form-dialog-actions">
          <button class="ghost-btn" type="button" @click="createFormOpen = false">取消</button>
          <button class="primary-btn" type="submit">创建表格</button>
        </div>
        </form>
      </div>
    </Teleport>

    <div v-if="!form" class="form-empty-state">
      <IcIcon name="table-chart" :size="32" />
      <p>还没有表格。输入表名后创建，数据会自动保存到数据库。</p>
    </div>

    <div v-if="form" class="table-frame" :class="{ loading, 'plain-table': !isLiteratureTable }" @mouseup="stopCellSelection" @contextmenu.prevent.stop="openTableContextMenu({ kind: 'table' }, $event)">
      <div class="smart-table-shell">
      <table class="smart-table" @selectstart="preventTableTextSelection">
        <thead>
          <tr class="table-column-drag-row">
            <th
              v-for="column in form.columns"
              :key="column.id"
              :class="{ 'sticky-literature-column': column.id === 'literature_file' }"
              :style="columnWidthStyle(column)"
            >
              <button
                class="table-edge-column-drag"
                type="button"
                draggable="true"
                title="拖动表格列"
                @dragstart.stop="startColumnDrag(column.id, $event)"
                @dragend.stop="endColumnDrag"
              ><IcIcon name="unfold" :size="10" /></button>
            </th>
          </tr>
          <tr>
            <th
              v-for="column in form.columns"
              :key="column.id"
              draggable="true"
              :data-column-id="column.id"
              :class="['tone-' + (column.tone || 'none'), { dragging: draggedColumnId === column.id, swapped: swappedColumnId === column.id, 'sticky-literature-column': column.id === 'literature_file' }]"
              :style="columnWidthStyle(column)"
              @dragstart="startColumnDrag(column.id, $event)"
              @dragover.prevent
              @drop.prevent="dropColumn(column.id)"
              @dragend="endColumnDrag"
              @contextmenu.prevent.stop="openTableContextMenu({ kind: 'column', columnId: column.id }, $event)"
            >
              <div class="column-header-block">
                <div class="column-head">
                <IcIcon v-if="column.type === 'index'" class="column-field-icon" :name="smartColumnIcon(column)" :size="15" />
                <button
                  v-else
                  class="column-description-toggle"
                  type="button"
                  :title="expandedColumnDescriptions.has(column.id) ? '收起辅助描述；双击编辑' : '展开辅助描述；双击编辑'"
                  :aria-expanded="expandedColumnDescriptions.has(column.id)"
                  draggable="false"
                  @pointerdown.stop
                  @dragstart.prevent
                  @click.stop="scheduleColumnDescriptionToggle(column)"
                  @dblclick.prevent.stop="handleColumnDescriptionDoubleClick(column)"
                >
                  <IcIcon class="column-field-icon" :name="smartColumnIcon(column)" :size="15" />
                </button>
                <span
                  v-if="editingColumnId !== column.id"
                  class="column-title-label"
                  :class="{ 'editable-column-title': column.id.startsWith('col_') }"
                  @click.stop="startColumnTitleEdit(column)"
                >{{ column.title }}</span>
                <input
                  v-else
                  v-model="columnTitleDraft"
                  class="column-title-input"
                  type="text"
                  @click.stop
                  @mousedown.stop
                  @keydown.enter.prevent="commitColumnTitleEdit(column)"
                  @keydown.esc.prevent="cancelColumnTitleEdit"
                  @blur="commitColumnTitleEdit(column)"
                />
                <span class="column-type-pill">{{ smartColumnTypeLabel(column.type) }}</span>
                <span v-if="column.type === 'smart_text' || column.type === 'smart_tag'" class="column-ai-pill">AI生成</span>
                <button
                  class="column-resize-handle"
                  type="button"
                  title="拖动调整列宽"
                  @pointerdown="startColumnResize(column, $event)"
                ></button>
                </div>
                <div
                  v-if="column.type !== 'index'"
                  class="column-description-panel"
                  :class="{ expanded: expandedColumnDescriptions.has(column.id) }"
                >
                  <div class="column-description-inner">
                    <input
                      v-if="editingColumnDescriptionId === column.id"
                      :ref="(element) => setColumnDescriptionInputRef(column.id, element)"
                      v-model="columnDescriptionDraft"
                      class="column-description-input"
                      :data-column-id="column.id"
                      type="text"
                      aria-label="辅助描述"
                      draggable="false"
                      @click.stop
                      @mousedown.stop
                      @pointerdown.stop
                      @dblclick.stop
                      @keydown.enter.prevent="commitColumnDescriptionEdit(column)"
                      @keydown.esc.prevent="cancelColumnDescriptionEdit"
                      @blur="commitColumnDescriptionEdit(column)"
                    />
                    <span
                      v-else
                      class="column-description-text"
                      title="双击编辑辅助描述"
                      @dblclick.prevent.stop="handleColumnDescriptionDoubleClick(column)"
                    >{{ column.description || '辅助描述' }}</span>
                  </div>
                </div>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in visibleRows" :key="row.id" :style="{ height: `${displayedRowHeight(row)}px` }">
            <td
              v-for="column in form.columns"
              :key="column.id"
              :style="{ height: `${displayedRowHeight(row)}px`, ...cellSelectionStyle(row.id, column.id) }"
              :data-row-id="row.id"
              :data-column-id="column.id"
              :draggable="column.type === 'index'"
              :class="['cell', 'tone-' + (column.tone || 'none'), { selected: isCellSelected(row.id, column.id), dragging: draggedRowId === row.id && column.type === 'index', 'row-swapped': swappedRowId === row.id, 'sticky-literature-column': column.id === 'literature_file' }]"
              @dragstart="column.type === 'index' && startRowDrag(row.id, $event)"
              @dragover.prevent="column.type === 'index'"
              @drop.prevent="column.type === 'index' && dropRow(row.id)"
              @dragend="endRowDrag"
              @mousedown.left="column.type !== 'index' && startCellSelection(row.id, column.id, $event)"
              @mouseenter="extendCellSelection(row.id, column.id)"
              @click="handleCellClick(row.id, column.id)"
              @contextmenu.prevent.stop="column.type === 'index' ? openTableContextMenu({ kind: 'row', rowId: row.id }, $event) : openCellContextMenu(row, column, $event)"
            >
              <span v-if="column.type === 'index'" class="row-index">
                {{ rowIndex + 1 }}
                <button
                  class="table-edge-row-drag"
                  type="button"
                  draggable="true"
                  title="拖动表格行"
                  @dragstart.stop="startRowDrag(row.id, $event)"
                  @dragend.stop="endRowDrag"
                ><IcIcon name="unfold" :size="10" /></button>
              </span>
              <div v-else-if="column.type === 'file'" class="file-cell">
                <button class="file-picker" type="button" @click.stop="scheduleOpenLiteratureFile(row)" @dblclick.prevent.stop="openLiteratureReader(row)">
                  <img
                    v-if="row.cells[column.id]?.assetPath && imagePreviewByPath[row.cells[column.id]?.assetPath || '']"
                    class="file-preview-image"
                    :src="imagePreviewByPath[row.cells[column.id]?.assetPath || '']"
                    :alt="row.cells[column.id]?.fileName || '文献首页预览'"
                  />
                  <img
                    v-else-if="row.cells[column.id]?.fileName || row.cells[column.id]?.value"
                    class="file-material-icon"
                    :src="fileIconForCell(row.cells[column.id]?.fileName || row.cells[column.id]?.value || '').src"
                    alt=""
                    aria-hidden="true"
                  />
                  <IcIcon v-else name="upload" :size="24" />
                  <span>{{ row.cells[column.id]?.fileName || row.cells[column.id]?.value || '添加文档' }}</span>
                </button>
                <div v-if="row.cells[column.id]?.assetPath" class="file-cell-actions">
                  <button type="button" title="下载原文件" @click.stop="downloadLiteratureFile(row)">
                    <IcIcon name="download" :size="13" />
                  </button>
                  <button type="button" title="重新上传" @click.stop="openUpload(row.id)">
                    <IcIcon name="upload" :size="13" />
                  </button>
                </div>
                <input
                  :ref="(el) => setUploadRef(row.id, el)"
                  class="hidden-input"
                  type="file"
                  @change="uploadLiterature(row, $event)"
                />
              </div>
              <div
                v-else-if="column.type === 'tag' || column.type === 'smart_tag'"
                class="tag-cell"
                @click.stop="openTagEditor(row, column)"
              >
                <span
                  v-for="tag in cellTags(row, column)"
                  :key="tag"
                  class="tag-pill"
                  :style="tagPillStyle(tag)"
                  @click.stop="openTagEditor(row, column)"
                >
                  <span class="tag-pill-label">{{ tag }}</span>
                  <button type="button" class="tag-pill-action danger" title="删除标签" @click.stop="removeTag(row, column, tag)">
                    <IcIcon name="close" :size="12" />
                  </button>
                </span>
                <button type="button" class="tag-add-button" @click.stop="openTagEditor(row, column)">
                  <IcIcon name="add" :size="13" />
                  <span>{{ cellTags(row, column).length ? '标签' : '添加标签' }}</span>
                </button>
                <div v-if="isTagEditorOpen(row.id, column.id)" class="tag-editor" @click.stop @mousedown.stop>
                  <div class="tag-editor-head">
                    <span>标签</span>
                    <button type="button" title="关闭标签编辑" @click.stop="closeTagEditor">
                      <IcIcon name="close" :size="12" />
                    </button>
                  </div>
                  <div v-if="cellTags(row, column).length" class="tag-editor-selected">
                    <button
                      v-for="tag in cellTags(row, column)"
                      :key="tag"
                      type="button"
                      class="tag-selected-pill"
                      :style="tagPillStyle(tag)"
                      title="移除标签"
                      @click="removeTag(row, column, tag)"
                    >
                      {{ tag }}
                      <IcIcon name="close" :size="10" />
                    </button>
                  </div>
                  <div v-if="column.options?.length" class="tag-option-list">
                    <button
                      v-for="(option, index) in column.options"
                      :key="option"
                      type="button"
                      class="tag-option-pill"
                      :class="{ selected: isTagSelected(row, column, option) }"
                      :style="{ ...tagPillStyle(option), '--item-index': index }"
                      @click="toggleTag(row, column, option)"
                    >
                      {{ option }}
                    </button>
                  </div>
                  <div class="tag-editor-input-row">
                    <input
                      v-model="tagDraft"
                      type="text"
                      placeholder="输入标签"
                      @keydown.enter.prevent="addTagFromDraft(row, column)"
                    />
                    <button type="button" title="添加标签" @click="addTagFromDraft(row, column)">
                      <IcIcon name="check" :size="13" />
                    </button>
                  </div>
                </div>
              </div>
              <div
                v-else-if="column.type === 'boolean'"
                class="cell-dropdown"
                @click.stop
              >
                <button class="cell-dropdown-trigger" type="button" @click="toggleDropdown(booleanDropdownKey(row.id, column.id))">
                  <span>{{ booleanCellLabel(row, column) }}</span>
                  <IcIcon name="chevron-down" :size="14" />
                </button>
                <div v-if="dropdownOpen === booleanDropdownKey(row.id, column.id)" class="smart-dropdown-menu cell-dropdown-menu">
                  <button type="button" :style="{ '--item-index': 0 }" @click="selectBooleanValue(row, column, '')">
                    <IcIcon v-if="!row.cells[column.id]?.value" name="check" :size="16" />
                    <span v-else class="sort-check-placeholder"></span>
                    <span>未设置</span>
                  </button>
                  <button
                    v-for="(option, index) in column.options || []"
                    :key="option"
                    type="button"
                    :style="{ '--item-index': index + 1 }"
                    @click="selectBooleanValue(row, column, option)"
                  >
                    <IcIcon v-if="row.cells[column.id]?.value === option" name="check" :size="16" />
                    <span v-else class="sort-check-placeholder"></span>
                    <span>{{ option }}</span>
                  </button>
                </div>
              </div>
              <div v-else-if="column.type === 'star'" class="star-cell">
                <button
                  v-for="rating in 5"
                  :key="rating"
                  type="button"
                  :class="{ active: Number(row.cells[column.id]?.value || 0) >= rating }"
                  @click="setRating(row, column, rating)"
                >
                  ★
                </button>
              </div>
              <input
                v-else-if="column.type === 'date'"
                type="datetime-local"
                :value="row.cells[column.id]?.value || ''"
                @input="editCell(row, column, ($event.target as HTMLInputElement).value)"
              />
              <SmartMarkdownCell
                v-else-if="column.type === 'text' || column.type === 'smart_text' || column.type === 'readonly_text'"
                :value="row.cells[column.id]?.value || ''"
                :path="`${activeFormDir}/table.md`"
                :editable="column.editable"
                :plain-when-collapsed="column.id === 'literature_content'"
                :inline-markdown-preview="column.id === 'figures' || column.id === 'formulas'"
                :upload-image="uploadCellImage"
                @update="editCell(row, column, $event)"
                @resize="(expanded, height) => resizeExpandedTextCell(row, expanded, height)"
                @edit-resize="(height) => resizeEditingCell(row, height)"
                @upload-error="workspaceStore.showToast(`图片上传失败 - ${errorMessage($event)}`)"
              />
              <textarea
                v-else
                :readonly="!column.editable"
                :value="row.cells[column.id]?.value || ''"
                :placeholder="row.cells[column.id]?.status === 'pending' ? '等待结构化 LLM 服务生成' : ''"
                @input="handleCellTextareaInput(row, column, $event)"
              ></textarea>
              <div
                v-if="(column.type === 'smart_text' || column.type === 'smart_tag') && row.cells[column.id]?.status === 'pending'"
                class="smart-cell-loading-mask"
                role="status"
                aria-label="正在生成智能字段"
              >
                <PixelLoader />
              </div>
              <span
                v-if="row.cells[column.id]?.status === 'failed' && !row.cells[column.id]?.value.trim()"
                class="status-dot"
                :class="row.cells[column.id]?.status"
              >
                失败/空
              </span>
              <button
                class="column-resize-handle cell-column-resize-handle"
                type="button"
                tabindex="-1"
                title="拖动调整列宽"
                aria-label="拖动调整列宽"
                @pointerdown="startColumnResize(column, $event)"
              ></button>
              <button
                class="row-resize-handle cell-row-resize-handle"
                type="button"
                tabindex="-1"
                title="拖动调整行高"
                aria-label="拖动调整行高"
                @pointerdown="startRowResize(row, $event)"
              ></button>
            </td>
          </tr>
        </tbody>
      </table>
      <button class="table-edge-add-row" type="button" title="添加空行" @click.stop="addRowAt(undefined, 1)">
        <IcIcon name="add" :size="10" />
      </button>
      <button class="table-edge-add-column" type="button" title="选择字段类型后添加列" @click.stop="openEdgeColumnMenu">
        <IcIcon name="add" :size="10" />
      </button>
      </div>
      <div v-if="!visibleRows.length" class="empty-state">
        <IcIcon name="table-chart" :size="28" />
        <p>没有符合条件的记录</p>
      </div>
    </div>

    <Teleport to="body">
      <SmartFormAddColumnMenu
        v-if="edgeColumnMenuOpen"
        class="edge-column-menu table-context-submenu-level-three"
        :style="edgeColumnMenuStyle"
        :columns="form?.columns ?? []"
        :is-literature="isLiteratureTable"
        @add="addEdgeColumn"
        @click.stop
      />
    </Teleport>

    <Teleport to="body">
      <div
        v-if="tableContextTarget"
        class="table-context-menu ui-floating-menu-surface"
        :class="{ dark: settingsStore.isDark, 'submenu-left': tableContextSubmenuSide === 'left' }"
        :style="tableContextMenuStyle"
        @click.stop
      >
      <div
        class="table-context-submenu-item"
        :class="{ active: tableContextSubmenu.startsWith('add-column') }"
        @mouseenter="openTableSubmenu('add-column')"
        @mouseleave="handleTableSubmenuLeave('add-column', $event)"
      >
        <button type="button"><IcIcon name="view-column" :size="15" /><span>添加列</span><IcIcon name="chevron-right" :size="15" /></button>
        <div
          v-show="tableContextSubmenu.startsWith('add-column')"
          :ref="(element) => setTableContextSubmenuRef('add-column', element)"
          class="table-context-submenu ui-floating-submenu-surface"
          :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
          @mouseenter="keepTableSubmenuOpen"
          @mouseleave="handleTableSubmenuLeave('add-column', $event)"
        >
          <div
            v-for="direction in [{ key: 'left', label: '左侧添加', value: -1 }, { key: 'right', label: '右侧添加', value: 1 }]"
            :key="direction.key"
            class="table-context-submenu-item table-context-submenu-level-two"
            :class="{ active: tableContextSubmenu === `add-column-${direction.key}` }"
            @mouseenter="openTableSubmenu(`add-column-${direction.key}`)"
            @mouseleave="handleTableSubmenuLeave(`add-column-${direction.key}`, $event)"
          >
            <button type="button"><IcIcon name="add" :size="15" /><span>{{ direction.label }}</span><IcIcon name="chevron-right" :size="15" /></button>
            <div
              v-show="tableContextSubmenu === `add-column-${direction.key}`"
              :ref="(element) => setTableContextSubmenuRef(`add-column-${direction.key}`, element)"
              class="table-context-submenu table-context-submenu-level-three ui-floating-submenu-surface"
              :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
              @mouseenter="keepTableSubmenuOpen"
              @mouseleave="handleTableSubmenuLeave(`add-column-${direction.key}`, $event)"
            >
              <span class="table-context-section-title">内置字段</span>
              <button
                v-for="column in availableBuiltinColumns"
                :key="column.id"
                type="button"
                :disabled="Boolean(form?.columns.some((item) => item.id === column.id)) || (!isLiteratureTable && (column.type === 'smart_text' || column.type === 'smart_tag'))"
                @click="addContextColumn(column, direction.value as -1 | 1)"
              >
                <IcIcon :name="smartColumnIcon(column)" :size="15" />
                <span>{{ column.title }}</span>
                <span class="menu-column-type-pill">{{ smartColumnTypeLabel(column.type) }}</span>
              </button>
              <hr class="table-context-separator" />
              <label class="table-context-input">
                <span>自定义字段名</span>
                <input v-model="customColumnTitle" class="form-input-surface" type="text" placeholder="例如：备注" @click.stop />
              </label>
              <label class="table-context-input">
                <span>辅助描述</span>
                <input v-model="customColumnDescription" class="form-input-surface" type="text" placeholder="例如：提取作者明确陈述的局限" @click.stop />
              </label>
              <span class="table-context-section-title">字段类型</span>
              <button
                v-for="type in availableCustomColumnTypes"
                :key="type.value"
                type="button"
                :disabled="!isLiteratureTable && (type.value === 'smart_text' || type.value === 'smart_tag')"
                @click="addContextCustomColumn(type.value, direction.value as -1 | 1)"
              >
                <IcIcon :name="SMART_COLUMN_TYPE_ICONS[type.value]" :size="15" /><span>{{ type.label }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div
        class="table-context-submenu-item"
        :class="{ active: tableContextSubmenu === 'add-row' }"
        @mouseenter="openTableSubmenu('add-row')"
        @mouseleave="handleTableSubmenuLeave('add-row', $event)"
      >
        <button type="button"><IcIcon name="add" :size="15" /><span>添加行</span><IcIcon name="chevron-right" :size="15" /></button>
        <div
          v-show="tableContextSubmenu === 'add-row'"
          :ref="(element) => setTableContextSubmenuRef('add-row', element)"
          class="table-context-submenu ui-floating-submenu-surface"
          :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
          @mouseenter="keepTableSubmenuOpen"
          @mouseleave="handleTableSubmenuLeave('add-row', $event)"
        >
          <button type="button" @click="addRowAt('rowId' in tableContextTarget ? tableContextTarget.rowId : undefined, -1); closeTableContextMenu()"><IcIcon name="arrow-up" :size="15" /><span>在上方添加</span></button>
          <button type="button" @click="addRowAt('rowId' in tableContextTarget ? tableContextTarget.rowId : undefined, 1); closeTableContextMenu()"><IcIcon name="arrow-down" :size="15" /><span>在下方添加</span></button>
        </div>
      </div>

      <div
        class="table-context-submenu-item"
        :class="{ active: tableContextSubmenu === 'delete' }"
        @mouseenter="openTableSubmenu('delete')"
        @mouseleave="handleTableSubmenuLeave('delete', $event)"
      >
        <button type="button"><IcIcon name="delete" :size="15" /><span>删除</span><IcIcon name="chevron-right" :size="15" /></button>
        <div
          v-show="tableContextSubmenu === 'delete'"
          :ref="(element) => setTableContextSubmenuRef('delete', element)"
          class="table-context-submenu ui-floating-submenu-surface"
          :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
          @mouseenter="keepTableSubmenuOpen"
          @mouseleave="handleTableSubmenuLeave('delete', $event)"
        >
          <button type="button" :disabled="!contextRowIds().length" class="danger-menu-item" @click="deleteContextRow"><IcIcon name="delete" :size="15" /><span>删除整行</span></button>
          <button type="button" :disabled="!canDeleteContextColumn()" class="danger-menu-item" @click="deleteContextColumn"><IcIcon name="delete" :size="15" /><span>删除整列</span></button>
        </div>
      </div>

      <div
        class="table-context-submenu-item"
        :class="{ active: tableContextSubmenu === 'move-row' }"
        @mouseenter="openTableSubmenu('move-row')"
        @mouseleave="handleTableSubmenuLeave('move-row', $event)"
      >
        <button type="button" :disabled="!('rowId' in tableContextTarget)"><IcIcon name="sort" :size="15" /><span>行移动</span><IcIcon name="chevron-right" :size="15" /></button>
        <div
          v-show="tableContextSubmenu === 'move-row'"
          :ref="(element) => setTableContextSubmenuRef('move-row', element)"
          class="table-context-submenu ui-floating-submenu-surface"
          :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
          @mouseenter="keepTableSubmenuOpen"
          @mouseleave="handleTableSubmenuLeave('move-row', $event)"
        >
          <button type="button" @click="moveContextRow(-1)"><IcIcon name="arrow-up" :size="15" /><span>行上移</span></button>
          <button type="button" @click="moveContextRow(1)"><IcIcon name="arrow-down" :size="15" /><span>行下移</span></button>
        </div>
      </div>

      <div
        class="table-context-submenu-item"
        :class="{ active: tableContextSubmenu === 'move-column' }"
        @mouseenter="openTableSubmenu('move-column')"
        @mouseleave="handleTableSubmenuLeave('move-column', $event)"
      >
        <button type="button" :disabled="!('columnId' in tableContextTarget)"><IcIcon name="view-column" :size="15" /><span>列移动</span><IcIcon name="chevron-right" :size="15" /></button>
        <div
          v-show="tableContextSubmenu === 'move-column'"
          :ref="(element) => setTableContextSubmenuRef('move-column', element)"
          class="table-context-submenu ui-floating-submenu-surface"
          :class="{ 'submenu-left': tableContextSubmenuSide === 'left' }"
          @mouseenter="keepTableSubmenuOpen"
          @mouseleave="handleTableSubmenuLeave('move-column', $event)"
        >
          <button type="button" @click="moveContextColumn(-1)"><IcIcon name="arrow-left" :size="15" /><span>列左移</span></button>
          <button type="button" @click="moveContextColumn(1)"><IcIcon name="arrow-right" :size="15" /><span>列右移</span></button>
        </div>
      </div>

      <hr class="table-context-separator" />
      <button type="button" :disabled="!canSmartFillContext()" @click="smartFillTableContext"><IcIcon name="psychology" :size="15" /><span>智能填充</span></button>
      <button type="button" :disabled="!['cell', 'row', 'column', 'selection'].includes(tableContextTarget.kind)" @click="copyTableContext"><IcIcon name="copy" :size="15" /><span>复制</span><kbd>Ctrl+C</kbd></button>
      <button type="button" :disabled="!tableClipboard" @click="pasteTableContext"><IcIcon name="paste" :size="15" /><span>粘贴</span><kbd>Ctrl+V</kbd></button>
      <button type="button" :disabled="tableContextTarget.kind === 'table'" @click="clearTableContext"><IcIcon name="remove" :size="15" /><span>清空</span></button>
      </div>
    </Teleport>

    <footer v-if="form" class="forms-footer">
      <span>存储: {{ activeFormStorageLabel }}</span>
      <span class="footer-export-info">导出: {{ activeFormCsvFile }}</span>
      <span>更新: {{ updatedAtLabel }}</span>
    </footer>
  </section>
</template>

<style scoped>
.smart-forms-view {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-height: 0;
  height: 100%;
  container-type: inline-size;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
}

.forms-header,
.forms-toolbar,
.forms-footer {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  border-bottom: 0;
  background: var(--color-surface-raised);
}

.forms-header {
  min-height: 44px;
  justify-content: space-between;
  padding: var(--space-8) var(--space-12);
  font-size: calc(12px * var(--font-scale));
}

.header-copy {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: var(--space-8);
  min-width: 0;
  min-height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  overflow: hidden;
}

.forms-eyebrow {
  margin: 0;
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
  white-space: nowrap;
}

.header-copy .forms-eyebrow::after {
  margin-left: var(--space-8);
  color: var(--color-text-muted);
  content: ">";
}

.forms-header h1 {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: inherit;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.forms-header .primary-btn,
.forms-header .new-row-btn,
.forms-header .icon-btn {
  font-size: inherit;
}

.forms-header .smart-dropdown-trigger {
  font: inherit;
}

.header-actions,
.column-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.primary-btn,
.ghost-btn,
.toolbar-btn,
.new-row-btn,
.view-tab,
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
}

.primary-btn {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
  padding: 0 var(--space-10);
}

.ghost-btn,
.toolbar-btn,
.new-row-btn {
  padding: 0 var(--space-8);
}

.bulk-action-capsule {
  border-radius: 999px;
}

.new-row-btn {
  width: auto;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary);
  color: #ffffff;
  padding: 0 var(--space-10);
}

.icon-btn {
  width: 28px;
  padding: 0;
}

.new-form-btn {
  border-radius: 999px;
  background: var(--color-primary);
  color: #ffffff;
}

.toolbar-btn.strong {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.primary-btn:hover,
.ghost-btn:hover,
.toolbar-btn:hover,
.new-row-btn:hover,
.smart-dropdown-trigger:hover,
.cell-dropdown-trigger:hover,
.icon-btn:hover {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.new-row-btn:hover {
  background: var(--color-primary-hover, var(--color-primary));
  color: #ffffff;
}

.new-form-btn:hover {
  background: var(--color-primary-hover, var(--color-primary));
  color: #ffffff;
}

.forms-toolbar {
  position: relative;
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
  flex-wrap: wrap;
  font-size: calc(12px * var(--font-scale));
}

.forms-toolbar .toolbar-btn,
.forms-toolbar .delete-form-toolbar-btn {
  font-size: inherit;
}

.forms-toolbar .smart-dropdown-trigger {
  font: inherit;
}

.search-box {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  flex: 0 1 220px;
  width: 220px;
  min-width: 180px;
  max-width: 220px;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-muted);
}

.search-box input,
.cell-dropdown-trigger {
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.search-box input {
  width: 100%;
}

.new-form-input {
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0 var(--space-10);
  background: var(--color-canvas);
  color: var(--color-text-secondary);
}

.form-empty-state {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  min-height: 280px;
  padding: 24px;
  color: var(--color-text-muted);
  background: var(--color-canvas);
  text-align: center;
}

.smart-dropdown,
.export-menu {
  position: relative;
  display: inline-flex;
}

.smart-dropdown-trigger,
.cell-dropdown-trigger {
  display: inline-grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-6);
  height: 28px;
  min-width: 124px;
  max-width: 220px;
  padding: 0 var(--space-8);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.forms-header .smart-dropdown-trigger,
.forms-toolbar .smart-dropdown-trigger {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
}

.forms-header .smart-dropdown-trigger:hover,
.forms-toolbar .smart-dropdown-trigger:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.forms-toolbar .tag-filter-trigger,
.forms-toolbar .rating-filter-trigger {
  border-color: transparent;
  background: transparent;
}

.forms-toolbar .tag-filter-trigger:hover,
.forms-toolbar .rating-filter-trigger:hover {
  border-color: transparent;
}

.forms-toolbar .toolbar-btn {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  padding: 0 var(--space-10);
}

.forms-toolbar .toolbar-btn:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.forms-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: auto;
}

.delete-form-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  height: 28px;
  border: 1px solid var(--color-danger);
  border-radius: 999px;
  background: transparent;
  color: var(--color-danger);
  padding: 0 var(--space-10);
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
  transition: background 180ms ease, color 180ms ease, border-color 180ms ease;
}

.delete-form-toolbar-btn:hover:not(:disabled) {
  border-color: var(--color-danger);
  background: var(--color-danger);
  color: #fff;
}

.smart-dropdown-trigger span,
.cell-dropdown-trigger span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smart-dropdown-menu,
.export-menu-panel {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  min-width: 172px;
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  opacity: 1;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
  animation: smart-menu-pop 140ms ease-out both;
}

.smart-dropdown-menu button,
.export-menu-panel button {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-6);
  height: 30px;
  border: 0;
  padding: 0 var(--space-6);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  text-align: left;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-4px);
  animation: smart-menu-row-drop 150ms ease-out both;
  animation-delay: calc(20ms + var(--item-index, 0) * 18ms);
}

.smart-dropdown-menu button:hover,
.export-menu-panel button:hover {
  background: var(--color-selection-blue-soft);
  color: var(--color-text);
}

.form-dialog-backdrop {
  position: fixed;
  z-index: 1100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(0, 0, 0, 0.42);
}

.form-dialog {
  width: min(420px, 100%);
  padding: 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--workspace-card-radius);
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
}

.form-dialog.library-form-surface {
  border-radius: 28px;
  box-shadow:
    0 0 0 4px var(--library-form-ring),
    0 24px 70px rgba(0, 0, 0, 0.28);
}

.form-dialog-header,
.form-dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.form-dialog-header {
  margin-bottom: 20px;
}

.form-dialog h2 {
  margin: 0;
  font-size: var(--font-size-lg);
}

.dialog-close {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.dialog-field {
  display: grid;
  gap: 7px;
  min-width: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.dialog-field input {
  width: 100%;
  max-width: 100%;
  height: 36px;
  box-sizing: border-box;
  padding: 0 14px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text);
  font: inherit;
}

.form-kind-picker {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.form-kind-pill {
  min-height: 32px;
  padding: 0 14px;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font: inherit;
  cursor: pointer;
}

.form-kind-pill.active {
  background: var(--color-primary);
  color: #ffffff;
}

.form-kind-pill:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.form-dialog-actions {
  justify-content: flex-end;
  gap: 8px;
  margin-top: 24px;
}

.form-empty-state p {
  max-width: 420px;
  margin: 0;
}

.table-context-menu {
  position: fixed;
  z-index: 100000;
  display: grid;
  min-width: 252px;
  padding: var(--space-6);
}

.table-context-menu,
.table-context-submenu,
.edge-column-menu {
  color: var(--color-text-secondary);
}

.edge-column-menu {
  position: fixed;
  z-index: 100001;
  display: grid;
  width: 280px;
  box-sizing: border-box;
  padding: var(--space-6);
}

.table-context-submenu.submenu-left {
  right: calc(100% + var(--space-8));
  left: auto;
}

.table-context-submenu {
  position: absolute;
  top: calc(-1 * var(--space-6));
  left: calc(100% + var(--space-8));
  z-index: 1;
  display: grid;
  min-width: 248px;
  box-sizing: border-box;
  overflow: visible;
  padding: var(--space-6);
}

.table-context-menu button,
.edge-column-menu button {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--space-10);
  width: 100%;
  box-sizing: border-box;
  min-height: 30px;
  padding: 0 var(--space-8);
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  text-align: left;
}

.edge-column-menu button {
  cursor: pointer;
}

.edge-column-menu button:hover:not(:disabled) {
  background: var(--color-selection-blue-soft);
  color: var(--color-text);
}

.edge-column-menu button:disabled {
  color: var(--color-text-tertiary);
  cursor: not-allowed;
  opacity: 0.55;
}

.table-context-menu > button,
.table-context-menu > .table-context-submenu-item,
.table-context-submenu > button,
.table-context-submenu > .table-context-submenu-item {
  opacity: 0;
  transform: translateY(-4px);
  animation: smart-menu-row-drop 150ms ease-out both;
}

.table-context-menu > button:nth-of-type(1),
.table-context-menu > .table-context-submenu-item:nth-of-type(1),
.table-context-submenu > button:nth-of-type(1),
.table-context-submenu > .table-context-submenu-item:nth-of-type(1) { animation-delay: 20ms; }

.table-context-menu > button:nth-of-type(2),
.table-context-menu > .table-context-submenu-item:nth-of-type(2),
.table-context-submenu > button:nth-of-type(2),
.table-context-submenu > .table-context-submenu-item:nth-of-type(2) { animation-delay: 38ms; }

.table-context-menu > button:nth-of-type(3),
.table-context-menu > .table-context-submenu-item:nth-of-type(3),
.table-context-submenu > button:nth-of-type(3),
.table-context-submenu > .table-context-submenu-item:nth-of-type(3) { animation-delay: 56ms; }

.table-context-menu > button:nth-of-type(4),
.table-context-submenu > button:nth-of-type(4) { animation-delay: 74ms; }

.table-context-menu > button:nth-of-type(5),
.table-context-submenu > button:nth-of-type(5) { animation-delay: 92ms; }

.table-context-menu button:hover:not(:disabled),
.table-context-submenu-item.active > button {
  background: var(--color-selection-blue-soft);
  color: var(--color-text);
}

.table-context-menu .danger-menu-item:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-danger) 12%, var(--color-canvas));
  color: var(--color-danger);
}

.table-context-menu button:disabled {
  color: var(--color-text-tertiary);
  cursor: not-allowed;
  opacity: 0.55;
}

.table-context-submenu-item {
  position: relative;
}

.table-context-submenu-item > button {
  width: 100%;
}

.table-context-submenu-level-two {
  position: relative;
}

.table-context-submenu-level-three {
  min-width: 300px;
  max-height: min(620px, calc(100vh - 24px));
  overflow-x: hidden;
  overflow-y: auto;
}

.menu-column-type-pill,
.column-type-pill,
.column-ai-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  min-width: 0;
  height: 17px;
  box-sizing: border-box;
  padding: 0 6px;
  border: 0;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 30%, transparent);
  color: var(--color-tag-pill-text);
  font-size: calc(9px * var(--font-scale));
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.menu-column-type-pill {
  justify-self: end;
}

.column-ai-pill {
  background: color-mix(in srgb, var(--color-accent) 30%, transparent);
}

.table-context-menu kbd {
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
}

.table-context-section-title {
  display: block;
  padding: 4px var(--space-8);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.table-context-input {
  display: grid;
  gap: 4px;
  padding: 4px var(--space-8) var(--space-6);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.table-context-input input {
  width: 100%;
  height: 28px;
  box-sizing: border-box;
  padding: 0 var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  outline: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  font: inherit;
}

.table-context-separator {
  width: 100%;
  margin: var(--space-6) 0;
  border: 0;
  border-top: 1px solid var(--color-border);
}

.table-frame {
  position: relative;
  min-height: 0;
  margin: 0 var(--space-12);
  overflow: auto;
  border-radius: 18px;
  background: var(--color-canvas);
}

.plain-table .cell textarea,
.plain-table .cell select,
.plain-table .cell input {
  overflow: hidden;
  padding: 2px 6px;
}

.plain-table .smart-table {
  font-size: calc(13px * var(--font-scale));
}

.plain-table .cell select,
.plain-table .cell input {
  min-height: 0;
  height: 29px;
}

.plain-table :deep(.smart-markdown-source),
.plain-table :deep(.smart-plain-text),
.plain-table :deep(.markdown-body) {
  overflow: hidden;
  padding: 2px 6px;
  line-height: 1.35;
}

.plain-table .tag-cell,
.plain-table .cell-dropdown,
.plain-table .star-cell {
  box-sizing: border-box;
  min-height: 0;
  height: 29px;
  align-items: center;
  gap: 2px;
  padding: 2px 6px;
}

.plain-table .tag-pill,
.plain-table .tag-add-button {
  box-sizing: border-box;
  min-height: 22px;
  height: 22px;
  font-size: calc(12px * var(--font-scale));
}

.plain-table .star-cell button {
  box-sizing: border-box;
  height: 22px;
  padding: 0;
  font-size: 19px;
}

.plain-table .cell-dropdown-trigger {
  min-height: 0;
  height: 24px;
}

.plain-table .row-resize-handle {
  bottom: -2px;
  height: 4px;
}

.plain-table .row-resize-handle::after {
  bottom: 1px;
}

.smart-table-shell {
  position: relative;
  width: max-content;
  min-width: 0;
  padding: 0 9px 9px 0;
}

.smart-table {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: 0;
  table-layout: fixed;
  user-select: none;
}

.smart-table input,
.smart-table textarea {
  user-select: text;
}

th,
td {
  border-right: 0;
  border-bottom: 1px solid rgba(127, 127, 127, 0.12);
  vertical-align: top;
}

th {
  position: sticky;
  top: 0;
  z-index: 4;
  height: 34px;
  background: var(--color-canvas);
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
  font-weight: 500;
}

.table-column-drag-row th {
  top: 0;
  height: 10px;
  padding: 0;
  z-index: 6;
}

.smart-table thead tr:nth-child(2) th {
  top: 10px;
}

.smart-table tbody tr {
  transition: height 220ms ease;
}

th[draggable="true"],
td[draggable="true"] .row-index {
  cursor: grab;
}

th.dragging,
.cell.dragging {
  opacity: 0.55;
}

th.swapped,
.cell.row-swapped {
  animation: smart-swap-settle 320ms ease-out both;
}

.column-head {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-width: 0;
  min-height: 34px;
  padding: 0 var(--space-6);
}

.column-header-block {
  display: flex;
  min-height: 34px;
  flex-direction: column;
  justify-content: center;
}

.column-description-toggle {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 20px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.column-description-panel {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  transition: grid-template-rows 180ms ease, opacity 150ms ease;
}

.column-description-panel.expanded {
  grid-template-rows: 1fr;
  opacity: 1;
}

.column-description-inner {
  min-height: 0;
  overflow: hidden;
}

.column-description-text,
.column-description-input {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 0 var(--space-6) 6px 27px;
  overflow: hidden;
  color: var(--color-text-muted);
  font: inherit;
  font-size: calc(11px * var(--font-scale));
  line-height: 1.3;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.column-description-input {
  border: 0;
  border-bottom: 1px solid var(--color-primary);
  outline: 0;
  background: transparent;
  color: var(--color-text);
}

th[data-column-id="row_index"] .column-head {
  justify-content: center;
  padding: 0;
}

th[data-column-id="row_index"] .column-title-label,
th[data-column-id="row_index"] .column-type-pill {
  display: none;
}

.column-field-icon {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
}

.table-edge-column-drag,
.table-edge-row-drag,
.table-edge-add-row,
.table-edge-add-column {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 0;
  background: var(--color-surface-raised);
  color: var(--color-text-tertiary);
  cursor: pointer;
}

.table-edge-column-drag:hover,
.table-edge-row-drag:hover,
.table-edge-add-row:hover,
.table-edge-add-column:hover {
  border-color: color-mix(in srgb, var(--color-primary) 38%, var(--color-border));
  color: var(--color-primary);
}

.table-edge-column-drag {
  position: static;
  width: 100%;
  height: 10px;
  border-width: 0 0 1px;
  cursor: grab;
}

.table-edge-column-drag :deep(svg) {
  transform: rotate(90deg);
}

.table-edge-add-row {
  position: absolute;
  right: 9px;
  bottom: 0;
  left: 0;
  height: 9px;
  border: 0;
  transition: background-color 140ms ease, color 140ms ease;
}

.table-edge-add-column {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 9px;
  width: 9px;
  border: 0;
  transition: background-color 140ms ease, color 140ms ease;
}

.table-edge-add-row:hover,
.table-edge-add-column:hover {
  background: color-mix(in srgb, var(--color-primary) 16%, var(--color-surface-raised));
  color: var(--color-primary);
}

.column-resize-handle {
  position: absolute;
  top: 0;
  right: -6px;
  z-index: 20;
  width: 12px;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  touch-action: none;
}

.column-resize-handle::after {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 5px;
  width: 2px;
  content: '';
}

.column-resize-handle:hover::after {
  background: color-mix(in srgb, var(--color-primary) 45%, transparent);
}

.cell-column-resize-handle {
  right: 0;
}

.column-title-label {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.editable-column-title {
  cursor: text;
  border-bottom: 1px dashed var(--color-text-muted);
}

.column-title-input {
  min-width: 0;
  width: 100%;
  height: 24px;
  padding: 0 2px;
  border: 0;
  border-bottom: 1px solid var(--color-primary);
  outline: 0;
  background: transparent;
  color: inherit;
  font: inherit;
}

.cell {
  position: relative;
  /* Give each cell a definite viewport so child Markdown scroll areas can resolve 100% height. */
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
  background: transparent;
  overflow: hidden;
}

.cell-dropdown {
  position: relative;
  height: 100%;
  padding: 12px;
}

.cell-dropdown-trigger {
  width: 100%;
  max-width: none;
  background: var(--color-canvas);
}

.cell-dropdown-menu {
  top: 44px;
  left: 12px;
  right: auto;
  z-index: 18;
}

.cell:hover {
  /* Hover only the active cell; do not tint the whole row. */
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-primary) 38%, var(--color-border));
}

.cell.selected {
  box-shadow: var(--cell-selection-shadow, inset 0 0 0 2px var(--color-primary));
}

.sticky-literature-column {
  position: sticky;
  left: 0;
  z-index: 5;
  background: var(--color-canvas);
  box-shadow: 1px 0 0 var(--color-border);
}

th.sticky-literature-column {
  z-index: 8;
}

.row-index {
  position: relative;
  display: block;
  height: 100%;
  box-sizing: border-box;
  padding: 12px 0;
  color: var(--color-text-muted);
  text-align: center;
}

.table-edge-row-drag {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 8px;
  height: 100%;
  border-width: 0 1px 0 0;
  cursor: grab;
  opacity: 0;
}

.row-index:hover .table-edge-row-drag {
  opacity: 1;
}

.row-resize-handle {
  position: absolute;
  right: 0;
  bottom: -6px;
  left: 0;
  z-index: 19;
  width: 100%;
  height: 12px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: row-resize;
  touch-action: none;
}

.row-resize-handle::after {
  position: absolute;
  right: 0;
  bottom: 5px;
  left: 0;
  height: 2px;
  content: '';
}

.row-resize-handle:hover::after {
  background: color-mix(in srgb, var(--color-primary) 45%, transparent);
}

.cell-row-resize-handle {
  bottom: 0;
}

.cell textarea,
.cell select,
.cell input {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 0;
  resize: none;
  border: 0;
  outline: 0;
  padding: 11px;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  line-height: 1.35;
}

.cell select,
.cell input {
  min-height: 40px;
  height: 40px;
}

.tag-cell {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px;
  min-height: 100%;
  padding: 12px;
}

.tag-pill,
.tag-add-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 24px;
  border-radius: 999px;
  font-size: calc(12px * var(--font-scale));
}

.tag-pill {
  max-width: 100%;
  padding: 0 4px 0 10px;
  border: 0;
  background: var(--color-surface-active);
  color: var(--color-tag-pill-text);
}

.tag-pill-label {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-add-button {
  padding: 0 10px;
  border: 1px dashed var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.tag-add-button:hover {
  border-color: var(--color-border-strong);
  color: var(--color-text-secondary);
}

.tag-pill-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.tag-pill-action:hover {
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
}

.tag-pill-action.danger:hover {
  background: color-mix(in srgb, var(--color-danger) 14%, transparent);
  color: var(--color-danger);
}

.tag-editor {
  position: absolute;
  top: 42px;
  left: 8px;
  z-index: 12;
  display: grid;
  gap: 8px;
  min-width: 188px;
  max-width: 220px;
  padding: 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-lg);
  animation: smart-menu-pop 140ms ease-out both;
}

.tag-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 22px;
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.tag-editor-head button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.tag-editor-head button:hover {
  color: var(--color-danger);
}

.tag-editor-selected {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-border);
}

.tag-selected-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 24px;
  min-height: 24px;
  padding: 0 8px;
  border: 0;
  border-radius: 999px;
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.tag-editor-input-row {
  display: grid;
  grid-template-columns: 132px 24px;
  gap: 6px;
  justify-content: start;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}

.tag-editor-input-row input {
  width: 132px;
  height: 24px;
  min-height: 24px;
  box-sizing: border-box;
  padding: 0 12px;
  border: 0;
  border-radius: 999px;
  outline: 0;
  background: color-mix(in srgb, var(--color-primary) 6%, var(--color-canvas));
  color: var(--color-text);
  font: inherit;
}

.tag-editor-input-row button {
  width: 24px;
  height: 24px;
  min-height: 24px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: var(--color-primary-softer);
  color: var(--color-primary);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  text-align: left;
  cursor: pointer;
}

.tag-editor-input-row button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.tag-editor-input-row button:hover {
  background: var(--color-primary);
  color: #ffffff;
}

.tag-option-list {
  display: grid;
  grid-template-columns: repeat(2, max-content);
  align-items: start;
  justify-content: start;
  gap: 6px;
  max-height: 140px;
  overflow-x: hidden;
  overflow-y: auto;
}

.tag-option-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 24px;
  min-height: 24px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  background: var(--color-surface-active);
  color: var(--color-tag-pill-text);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  text-align: center;
  white-space: nowrap;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-4px);
  animation: smart-menu-row-drop 150ms ease-out both;
  animation-delay: calc(20ms + var(--item-index, 0) * 18ms);
}

.tag-option-pill.selected {
  filter: saturate(1.9) brightness(1.18);
}

.tag-option-pill:hover {
  filter: brightness(1.06);
}

.file-cell {
  position: relative;
  height: 100%;
  padding: 0;
}

.file-cell-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 3px;
  opacity: 0;
  transition: opacity 140ms ease;
}

.file-cell:hover .file-cell-actions,
.file-cell:focus-within .file-cell-actions {
  opacity: 1;
}

.file-cell-actions button {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: var(--color-surface-raised);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.file-cell-actions button:hover {
  border-color: color-mix(in srgb, var(--color-primary) 35%, var(--color-border));
  color: var(--color-primary);
}

.file-picker {
  display: grid;
  grid-template-rows: 1fr auto;
  align-items: center;
  justify-items: center;
  gap: 5px;
  width: 100%;
  height: 100%;
  padding: 10px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  overflow: hidden;
}

.file-picker:hover {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.file-picker span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.file-preview-image,
.file-material-icon {
  display: block;
  width: 52px;
  height: 52px;
  object-fit: contain;
}

.file-preview-image {
  width: 100%;
  height: 100%;
  min-height: 0;
  border-radius: var(--radius-sm);
  object-fit: contain;
}

.hidden-input {
  display: none;
}

.star-cell {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 12px;
}

.star-cell button {
  border: 0;
  background: transparent;
  color: color-mix(in srgb, var(--color-text-muted) 45%, transparent);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.star-cell button.active {
  color: #f3bd21;
}

.status-dot {
  position: absolute;
  right: 8px;
  bottom: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-primary-softer);
  color: var(--color-primary);
  font-size: 10px;
}

.status-dot.failed {
  background: color-mix(in srgb, var(--color-danger) 12%, var(--color-canvas));
  color: var(--color-danger);
}

.smart-cell-loading-mask {
  position: absolute;
  z-index: 12;
  inset: 0;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--color-canvas) 90%, transparent);
  backdrop-filter: blur(4px);
}

.tone-blue {
  background: color-mix(in srgb, var(--color-primary) 4%, transparent);
}

.tone-green {
  background: color-mix(in srgb, var(--color-success) 6%, transparent);
}

.tone-amber {
  background: color-mix(in srgb, var(--color-warning) 7%, transparent);
}

.tone-rose {
  background: color-mix(in srgb, var(--color-accent) 5%, transparent);
}

.tone-violet {
  background: color-mix(in srgb, var(--color-primary) 6%, transparent);
}

.empty-state {
  display: grid;
  place-items: center;
  gap: 8px;
  height: 260px;
  color: var(--color-text-muted);
}

.sort-check-placeholder {
  width: 16px;
  height: 16px;
}

.forms-footer {
  min-height: 32px;
  padding: 0 var(--space-12);
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

@keyframes smart-menu-pop {
  from {
    transform: translateY(-6px);
  }

  to {
    transform: translateY(0);
  }
}

@keyframes smart-menu-row-drop {
  from {
    transform: translateY(-6px);
    opacity: 0;
  }

  to {
    transform: translateY(0);
    opacity: 1;
  }
}

@keyframes smart-swap-settle {
  0% {
    transform: translateY(-4px);
    background: var(--color-primary-softer);
  }

  100% {
    transform: translateY(0);
  }
}

.forms-header {
  display: grid;
  align-items: stretch;
  justify-content: stretch;
  gap: 0;
  width: 100%;
  box-sizing: border-box;
  min-height: 0;
  padding: 0;
}

.forms-primary-row,
.forms-secondary-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  width: 100%;
  box-sizing: border-box;
  min-width: 0;
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
}

.forms-primary-row .header-copy {
  flex: 1 1 auto;
  min-width: 0;
}

.forms-primary-row .search-box {
  flex: 0 1 220px;
}

.forms-secondary-row {
  flex-wrap: wrap;
}

.forms-secondary-row .clear-invalid-btn {
  margin-left: auto;
}

.forms-secondary-row .filter-controls {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
}

.compact-control-label,
.compact-filter-toggle,
.compact-more-trigger {
  display: none;
}

.compact-filter-shell,
.compact-more-shell {
  display: none;
}

/* Secondary toolbar controls stay borderless except for the table selector. */
.smart-forms-view .forms-secondary-row .smart-dropdown-trigger {
  border: 0;
}

.smart-forms-view .forms-secondary-row .form-switch-control .smart-dropdown-trigger {
  border: 1px solid var(--color-border);
  border-radius: 999px;
}

.primary-icon-placeholder,
.primary-search-placeholder {
  display: none;
}

@container (max-width: 1040px) {
  .smart-forms-view .forms-header {
    display: grid;
    gap: var(--space-4);
    padding: var(--space-8) var(--space-10);
  }

  .smart-forms-view .forms-primary-row {
    display: grid;
    grid-template-columns: 28px minmax(100px, 1fr) 28px 28px;
    grid-template-rows: auto auto;
    gap: var(--space-4);
    min-height: 0;
    padding: 0;
  }

  .smart-forms-view .new-row-btn,
  .smart-forms-view .primary-icon-placeholder {
    grid-column: 1;
    grid-row: 1;
  }

  .smart-forms-view .search-box,
  .smart-forms-view .primary-search-placeholder {
    grid-column: 2;
    grid-row: 1;
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .smart-forms-view .new-form-btn {
    grid-column: 3;
    grid-row: 1;
  }

  .smart-forms-view .delete-form-toolbar-btn {
    grid-column: 4;
    grid-row: 1;
  }

  .smart-forms-view .new-row-btn,
  .smart-forms-view .new-form-btn,
  .smart-forms-view .delete-form-toolbar-btn {
    width: 28px;
    padding: 0;
    border-radius: 50%;
  }

  .smart-forms-view .new-row-btn span,
  .smart-forms-view .new-form-btn span,
  .smart-forms-view .delete-form-toolbar-btn span {
    display: none;
  }

  .smart-forms-view .forms-primary-row .header-copy {
    grid-column: 1 / -1;
    grid-row: 2;
    width: 100%;
    height: 28px;
    padding: 0 var(--space-10);
    border: 1px solid var(--color-border);
    border-radius: 999px;
  }

  .smart-forms-view .forms-primary-row .header-copy h1,
  .smart-forms-view .forms-primary-row .forms-eyebrow {
    display: inline;
    font-size: calc(12px * var(--font-scale));
    font-weight: 500;
  }

  .smart-forms-view .forms-primary-row .forms-eyebrow::after {
    display: inline;
    margin: 0 var(--space-6);
    content: '›';
  }

  .smart-forms-view .forms-secondary-row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-4);
    min-height: 0;
    padding: 0;
  }

  .smart-forms-view .form-switch-control,
  .smart-forms-view .compact-filter-shell,
  .smart-forms-view .compact-more-shell,
  .smart-forms-view .filter-control-shell {
    display: flex;
    justify-content: center;
    width: 100%;
    min-width: 0;
    max-width: 220px;
    justify-self: center;
    container-type: inline-size;
  }

  .smart-forms-view .form-switch-control,
  .smart-forms-view .filter-control-shell {
    container-name: smart-filter-control;
  }

  .smart-forms-view .compact-filter-shell,
  .smart-forms-view .compact-more-shell {
    container-name: smart-compact-action;
  }

  .smart-forms-view .compact-filter-toggle,
  .smart-forms-view .compact-more-trigger {
    display: inline-flex;
  }

  .smart-forms-view .form-switch-control {
    grid-column: 1;
    grid-row: 1;
  }

  .smart-forms-view .compact-filter-shell {
    grid-column: 2;
    grid-row: 1;
  }

  .smart-forms-view .compact-more-shell {
    grid-column: 3;
    grid-row: 1;
  }

  .smart-forms-view .forms-secondary-row .smart-dropdown-trigger {
    width: 100%;
    min-width: 0;
    max-width: 220px;
    justify-content: center;
    gap: var(--space-4);
    padding: 0 var(--space-6);
    white-space: nowrap;
  }

  .smart-forms-view .wide-control-label,
  .smart-forms-view .desktop-secondary-action {
    display: none;
  }

  .smart-forms-view .compact-control-label {
    display: inline;
  }

  .smart-forms-view .compact-filter-toggle.active {
    background: var(--color-primary-softer);
    color: var(--color-primary);
  }

  .smart-forms-view .forms-secondary-row .filter-controls {
    display: grid;
    grid-column: 1 / -1;
    grid-row: 2;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
    max-height: 0;
    overflow: hidden;
    opacity: 0;
    pointer-events: none;
    transition: max-height 180ms ease, opacity 150ms ease;
  }

  .smart-forms-view .forms-secondary-row .filter-controls.open {
    max-height: 32px;
    opacity: 1;
    pointer-events: auto;
  }

  .smart-forms-view .filter-controls .smart-dropdown-trigger {
    width: 100%;
    max-width: 220px;
  }
}

@container smart-filter-control (max-width: 112px) {
  .smart-forms-view .forms-secondary-row .smart-dropdown-trigger {
    width: 28px;
    max-width: 28px;
    gap: 0;
    padding: 0;
  }

  .smart-forms-view .compact-control-label,
  .smart-forms-view .control-caret {
    display: none;
  }
}

@container smart-compact-action (max-width: 88px) {
  .smart-forms-view .forms-secondary-row .smart-dropdown-trigger {
    width: 28px;
    max-width: 28px;
    gap: 0;
    padding: 0;
  }

  .smart-forms-view .compact-control-label {
    display: none;
  }
}

@container (max-width: 640px) {
  /* 移动端：页面骨架收紧，首行隐藏"删除表格"（危险操作移入"其他"菜单）。 */
  .smart-forms-view .forms-header {
    gap: var(--space-2);
    padding: var(--space-6) var(--space-8);
  }

  .smart-forms-view .forms-primary-row {
    grid-template-columns: 28px minmax(72px, 1fr) 28px;
  }

  .smart-forms-view .delete-form-toolbar-btn.mobile-hidden-action {
    display: none;
  }

  /* 移动端：表格留出横向滚动，固定左侧"行号"列，滚动时始终可见。 */
  .smart-forms-view .table-frame {
    margin: 0 var(--space-6);
  }

  .smart-forms-view th[data-column-id="row_index"],
  .smart-forms-view td[data-column-id="row_index"] {
    position: sticky;
    left: 0;
    z-index: 6;
    background: var(--color-canvas);
    box-shadow: 1px 0 0 var(--color-border);
  }

  .smart-forms-view th[data-column-id="row_index"] {
    z-index: 9;
  }

  /* 文献列紧跟行索引列右侧让位，避免两个固定列重叠。 */
  .smart-forms-view th.sticky-literature-column,
  .smart-forms-view td.sticky-literature-column {
    left: 32px;
  }

  /* 移动端：底部信息条精简，隐藏导出文件名。 */
  .smart-forms-view .forms-footer {
    min-height: 28px;
    padding: 0 var(--space-8);
    font-size: calc(11px * var(--font-scale));
  }

  .smart-forms-view .footer-export-info {
    display: none;
  }
}

/* The workspace owns the authoritative mobile width; wide table content must not override it. */
.smart-forms-view.mobile-layout .forms-primary-row {
  grid-template-columns: 28px minmax(0, 1fr) 28px;
}

.smart-forms-view.mobile-layout .search-box {
  min-width: 0;
  max-width: none;
}

.smart-forms-view.mobile-layout .new-form-btn {
  grid-column: 3;
  display: inline-flex;
}

.smart-forms-view.mobile-layout .delete-form-toolbar-btn.mobile-hidden-action {
  display: none;
}

.smart-forms-view.compressed-layout .forms-secondary-row .responsive-control-shell,
.smart-forms-view.compressed-layout .forms-secondary-row .smart-dropdown-trigger {
  width: 28px;
  max-width: 28px;
}

.smart-forms-view.compressed-layout .forms-secondary-row .smart-dropdown-trigger {
  gap: 0;
  padding: 0;
}

.smart-forms-view.compressed-layout .forms-secondary-row .compact-control-label,
.smart-forms-view.compressed-layout .forms-secondary-row .control-caret {
  display: none;
}

.smart-forms-view.compressed-layout .forms-footer {
  justify-content: flex-end;
}

.smart-forms-view.compressed-layout .forms-footer > span:first-child {
  display: none;
}
</style>
