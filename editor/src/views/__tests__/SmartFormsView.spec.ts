/*
 * Smart forms view smoke tests.
 *
 * Usage:
 * Mounts the literature table page with mocked knowledge-file APIs to verify
 * the first screen and core controls render without a backend process.
 */

import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import { deleteSmartFormDb, generateStructuredFields, getSmartFormDb, listSmartFormsDb, saveSmartFormDb } from '@/api/smartForms'
import { BUILTIN_COLUMNS, addColumn, createCustomColumn, createDefaultLiteratureForm, createEmptyRow, type SmartLiteratureForm } from '@/components/smart_forms/smartLiteratureTable'
import { previewKnowledgeFile, readKnowledgeFile, uploadKnowledgeFile } from '@/api/knowledge'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import SmartFormsView from '@/views/SmartFormsView.vue'
import smartFormsSource from '@/views/SmartFormsView.vue?raw'
import editorWorkspaceSource from '@/views/EditorWorkspace.vue?raw'

/** jsdom observer stub used by the responsive smart-table shell. */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

vi.mock('@/api/agent', () => ({
  updateCurrentDocumentContext: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/settings', () => ({
  rebuildKnowledgeRootStream: vi.fn(),
}))

vi.mock('@/api/smartForms', () => ({
  generateStructuredFields: vi.fn(),
  deleteSmartFormDb: vi.fn(),
  getSmartFormDb: vi.fn(),
  listSmartFormsDb: vi.fn(),
  saveSmartFormDb: vi.fn(),
}))

vi.mock('@/api/knowledge', () => ({
  buildKnowledgeEventsUrl: vi.fn(() => '/events'),
  copyKnowledgePath: vi.fn(),
  createKnowledgeFile: vi.fn(),
  createKnowledgeFolder: vi.fn().mockResolvedValue({}),
  deleteKnowledgePath: vi.fn(),
  deleteKnowledgeTrashEntry: vi.fn(),
  getKnowledgeGraphStatus: vi.fn(),
  ingestKnowledgeFileStream: vi.fn(),
  ingestKnowledgePathStream: vi.fn(),
  listKnowledgeFiles: vi.fn().mockResolvedValue({ tree: [] }),
  listKnowledgeTrash: vi.fn(),
  previewKnowledgeFile: vi.fn(),
  readKnowledgeFile: vi.fn().mockResolvedValue({
    path: 'forms/我的文献表/form.json',
    content: JSON.stringify(createDefaultLiteratureForm('我的文献表')),
    mtime: '2026-08-09T10:00:00',
    size: 100,
  }),
  rebuildKnowledgeGraph: vi.fn(),
  renameKnowledgePath: vi.fn(),
  restoreKnowledgeTrashEntry: vi.fn(),
  searchKnowledge: vi.fn(),
  uploadKnowledgeFile: vi.fn(),
  writeKnowledgeFile: vi.fn(),
}))

describe('SmartFormsView', () => {
  function contextButton(label: string, includes = false): HTMLButtonElement | undefined {
    const menus = [...document.querySelectorAll<HTMLElement>('.table-context-menu')]
    const menu = menus[menus.length - 1]
    return [...(menu?.querySelectorAll<HTMLButtonElement>('button') ?? [])]
      .find((button) => includes ? button.textContent?.includes(label) : button.textContent === label)
  }

  async function hoverContextButton(label: string, includes = false): Promise<void> {
    contextButton(label, includes)?.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
    await nextTick()
  }

  async function clickContextButton(label: string, includes = false): Promise<void> {
    contextButton(label, includes)?.click()
    await nextTick()
  }

  function dbResponse(form: SmartLiteratureForm, formId = 'sf_demo') {
    return {
      form_id: formId,
      user_id: 'local-test',
      asset_dir: `.mw/forms/${form.title}`,
      form,
      updated_at: '2026-08-09T10:00:00',
    }
  }

  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    useSettingsStore().updateProfile({ userId: 'local-test', knowledgeDir: 'D:/Knowledge' })
    const defaultForm = createDefaultLiteratureForm('我的文献表')
    vi.mocked(listSmartFormsDb).mockResolvedValue([{
      form_id: 'sf_demo',
      title: '我的文献表',
      asset_dir: '.mw/forms/我的文献表',
      updated_at: '2026-08-09T10:00:00',
    }])
    vi.mocked(getSmartFormDb).mockResolvedValue(dbResponse(defaultForm))
    vi.mocked(saveSmartFormDb).mockImplementation(async (payload) => {
      return dbResponse(payload.form, payload.form_id || 'sf_saved')
    })
    vi.mocked(generateStructuredFields).mockResolvedValue({
      raw_output: '{"fields":[]}',
      results: [
        { field_id: 'title', status: 'ready', value: 'LLM extracted title' },
        { field_id: 'keywords', status: 'ready', value: 'ROS; signaling' },
        { field_id: 'paper_type', status: 'ready', value: '研究论文' },
        { field_id: 'journal', status: 'ready', value: 'Plant Cell' },
      ],
    })
    vi.mocked(deleteSmartFormDb).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('renders a user-created smart literature table from forms', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    expect(getSmartFormDb).toHaveBeenCalledWith('local-test', 'sf_demo')
    expect(wrapper.get('h1').text()).toBe('我的文献表')
    expect(wrapper.find('input[type="search"]').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('button').some((button) => button.text() === '保存')).toBe(false)
    expect(wrapper.text()).not.toContain('The missing link')
  })

  it('shows a field icon and a type pill beside every column name', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    const headers = wrapper.findAll('thead tr:nth-child(2) th')
    expect(headers).toHaveLength(5)
    expect(headers.every((header) => header.find('.column-field-icon').exists())).toBe(true)
    expect(headers.map((header) => header.get('.column-type-pill').text())).toEqual(['索引', '文件', '只读文本', '只读文本', '智能文本'])
    expect(headers[4]?.get('.column-ai-pill').text()).toBe('AI生成')
    expect(headers.every((header) => !header.find('.column-actions').exists())).toBe(true)
    expect(headers[0]?.attributes('style')).toContain('32px')
    expect(headers[1]?.classes()).toContain('sticky-literature-column')
  })

  it('expands and directly edits auxiliary descriptions from every non-index header icon', async () => {
    const storedForm = createDefaultLiteratureForm('我的文献表')
    storedForm.columns.find((column) => column.id === 'title')!.description = '提取论文正式标题'
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    expect(wrapper.find('th[data-column-id="row_index"] .column-description-toggle').exists()).toBe(false)
    const toggle = wrapper.get('th[data-column-id="title"] .column-description-toggle')
    await toggle.trigger('click')
    await new Promise((resolve) => window.setTimeout(resolve, 230))
    await nextTick()
    expect(wrapper.get('th[data-column-id="title"] .column-description-panel').classes()).toContain('expanded')
    expect(wrapper.get('th[data-column-id="title"] .column-description-text').text()).toBe('提取论文正式标题')

    await toggle.trigger('dblclick')
    const input = wrapper.get('th[data-column-id="title"] .column-description-input')
    await input.setValue('优先使用首页标题')
    await input.trigger('blur')
    await nextTick()
    expect(wrapper.get('th[data-column-id="title"] .column-description-text').text()).toBe('优先使用首页标题')
  })

  it('appends a column auxiliary description to structured AI generation', async () => {
    const storedForm = createDefaultLiteratureForm('我的文献表')
    storedForm.columns.find((column) => column.id === 'title')!.description = '优先使用首页的正式标题'
    storedForm.rows[0]!.cells.literature_content = { value: '论文正文', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('全表智能填充'))?.trigger('click')
    await flushPromises()

    expect(generateStructuredFields).toHaveBeenCalledWith(expect.objectContaining({
      fields: expect.arrayContaining([
        expect.objectContaining({ id: 'title', description: '优先使用首页的正式标题' }),
      ]),
    }))
  })

  it('opens uploaded literature in the editor sidebar and exposes file actions', async () => {
    const storedForm = createDefaultLiteratureForm('我的文献表')
    storedForm.rows[0]!.cells.literature_file = {
      value: 'paper.pdf',
      fileName: 'paper.pdf',
      assetPath: '.mw/forms/我的文献表/assets/paper.pdf',
    }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    const workspaceStore = useWorkspaceStore()
    const openEditorSidebar = vi.spyOn(workspaceStore, 'openEditorSidebar').mockResolvedValue(undefined)
    const openLiteratureEntry = vi.spyOn(workspaceStore, 'openLiteratureEntry')
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    vi.mocked(previewKnowledgeFile).mockResolvedValue({
      path: '.mw/forms/我的文献表/assets/paper.pdf',
      kind: 'pdf',
      raw_url: '/knowledge/raw/paper.pdf',
      thumbnail_url: '/knowledge/assets/pdf_preview/demo/page-1.png',
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.pdf',
      readonly: true,
    })
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    expect(wrapper.get('.file-preview-image').attributes('src')).toContain('/knowledge/assets/pdf_preview/demo/page-1.png')

    await wrapper.get('.file-picker').trigger('click')
    await new Promise((resolve) => window.setTimeout(resolve, 230))

    expect(openEditorSidebar).toHaveBeenCalledWith({
      name: 'paper.pdf',
      path: '.mw/forms/我的文献表/assets/paper.pdf',
      isDir: false,
    })
    openEditorSidebar.mockClear()
    await wrapper.get('.file-picker').trigger('click')
    await wrapper.get('.file-picker').trigger('dblclick')
    expect(openLiteratureEntry).toHaveBeenCalledWith('sf_demo', storedForm.rows[0]!.id)
    await new Promise((resolve) => window.setTimeout(resolve, 230))
    expect(openEditorSidebar).not.toHaveBeenCalled()
    expect(wrapper.find('button[title="下载原文件"]').exists()).toBe(true)
    expect(wrapper.find('button[title="重新上传"]').exists()).toBe(true)
    await wrapper.get('button[title="下载原文件"]').trigger('click')
    await flushPromises()
    expect(previewKnowledgeFile).toHaveBeenCalledWith('local-test', '.mw/forms/我的文献表/assets/paper.pdf')
    expect(anchorClick).toHaveBeenCalled()
    anchorClick.mockRestore()
  })

  it('treats a sidebar save as re-upload and regenerates the matching smart row', async () => {
    const storedForm = createDefaultLiteratureForm('我的文献表')
    storedForm.rows[0]!.cells.literature_file = {
      value: 'paper.md',
      fileName: 'paper.md',
      assetPath: '.mw/forms/我的文献表/assets/paper.md',
    }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    vi.mocked(previewKnowledgeFile).mockResolvedValue({
      path: '.mw/forms/我的文献表/assets/paper.md',
      kind: 'markdown',
      content: 'updated literature content',
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.md',
      readonly: false,
    })
    const workspaceStore = useWorkspaceStore()
    const ingestFile = vi.spyOn(workspaceStore, 'ingestFile').mockResolvedValue(undefined)
    vi.spyOn(workspaceStore, 'loadKnowledgeTree').mockResolvedValue(undefined)
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    window.dispatchEvent(new CustomEvent('metaweave-knowledge-file-change', {
      detail: { path: '.mw/forms/我的文献表/assets/paper.md' },
    }))
    await flushPromises()

    expect(ingestFile).toHaveBeenCalledWith({
      name: 'paper.md',
      path: '.mw/forms/我的文献表/assets/paper.md',
      isDir: false,
      indexStatus: 'dirty',
    })
    expect(generateStructuredFields).toHaveBeenCalled()
    expect(wrapper.text()).toContain('LLM extracted title')
  })

  it('resizes column and row boundaries with minimum dimensions', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const columnHandle = wrapper.get('th[data-column-id="title"] .column-resize-handle')
    const rowHandle = wrapper.get('.row-resize-handle')

    const pointerEvent = (type: string, clientX: number, clientY: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true })
      Object.defineProperties(event, { clientX: { value: clientX }, clientY: { value: clientY } })
      return event
    }
    columnHandle.element.dispatchEvent(pointerEvent('pointerdown', 200, 0))
    window.dispatchEvent(pointerEvent('pointermove', 260, 0))
    window.dispatchEvent(pointerEvent('pointerup', 0, 0))
    rowHandle.element.dispatchEvent(pointerEvent('pointerdown', 0, 200))
    window.dispatchEvent(pointerEvent('pointermove', 0, 250))
    window.dispatchEvent(pointerEvent('pointerup', 0, 0))
    await nextTick()

    expect(wrapper.get('th[data-column-id="title"]').attributes('style')).toContain('290px')
    expect(wrapper.get('tbody tr').attributes('style')).toContain('332px')
    expect(wrapper.get('tbody td[data-column-id="title"]').attributes('style')).toContain('332px')
  })

  it('inserts rows and opens a typed column chooser from table edge controls', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.get('.table-edge-add-row').trigger('click')
    await wrapper.get('.table-edge-add-column').trigger('click')

    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.findAll('thead tr:nth-child(2) th')).toHaveLength(5)
    const edgeMenu = document.querySelector('.edge-column-menu') as HTMLElement
    expect(edgeMenu).not.toBeNull()
    expect(edgeMenu.querySelectorAll('.menu-column-type-pill')).toHaveLength(BUILTIN_COLUMNS.length - 1)
    ;[...edgeMenu.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.includes('摘要'))?.click()
    await nextTick()
    expect(wrapper.findAll('thead tr:nth-child(2) th')).toHaveLength(6)
    expect(wrapper.findAll('.table-edge-column-drag')).toHaveLength(6)
    expect(wrapper.find('button[title="拖动表格行"]').exists()).toBe(true)
    expect(wrapper.find('button[title="拖动表格列"]').exists()).toBe(true)
  })

  it('opens context submenus toward the available viewport side', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu', { clientX: 900, clientY: 700 })
    await nextTick()

    const menu = document.querySelector('.table-context-menu') as HTMLElement | null
    expect(menu?.classList.contains('submenu-left')).toBe(true)
    expect(Number.parseInt(menu?.style.left || '0', 10)).toBeGreaterThan(0)

    await hoverContextButton('添加列')
    await hoverContextButton('左侧添加')
    const levelThree = document.querySelector('.table-context-submenu-level-three')
    expect(levelThree?.classList.contains('submenu-left')).toBe(true)
  })

  it('autosaves after table content changes', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    vi.mocked(saveSmartFormDb).mockClear()
    vi.useFakeTimers()

    await wrapper.find('td[data-column-id="title"] textarea').setValue('自动保存标题')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    vi.useRealTimers()

    expect(saveSmartFormDb).toHaveBeenCalledWith(expect.objectContaining({
      form_id: 'sf_demo',
      form: expect.objectContaining({
        rows: expect.arrayContaining([
          expect.objectContaining({
            cells: expect.objectContaining({
              title: expect.objectContaining({ value: '自动保存标题' }),
            }),
          }),
        ]),
      }),
    }))
  })

  it('exports the current form as a zip archive', async () => {
    const createObjectUrl = vi.fn((_blob: Blob) => 'blob:smart-form')
    const revokeObjectUrl = vi.fn()
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.get('button[title="导出表格"]').trigger('click')
    await wrapper.findAll('.smart-dropdown-menu button').find((button) => button.text() === 'ZIP')?.trigger('click')

    const blob = createObjectUrl.mock.calls[0]?.[0] as Blob
    expect(blob.type).toBe('application/zip')
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect(Array.from(bytes.slice(0, 4))).toEqual([0x50, 0x4b, 0x03, 0x04])
    expect(new TextDecoder().decode(bytes)).toContain('form.json')
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:smart-form')
    anchorClick.mockRestore()
  })

  it('shows a creation empty state instead of creating a fake default table', async () => {
    vi.mocked(listSmartFormsDb).mockResolvedValueOnce([])

    const wrapper = mount(SmartFormsView)
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('创建你的第一张表')
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
    expect(getSmartFormDb).not.toHaveBeenCalled()
  })

  it('adds a literature row and opens its file picker from the toolbar action', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const inputClick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)

    await wrapper.get('button[title="上传文献"]').trigger('click')
    await nextTick()

    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(inputClick).toHaveBeenCalledOnce()
    expect(wrapper.text()).not.toContain('新建列')
    inputClick.mockRestore()
  })

  it('clears only empty failed markers while preserving every existing value', async () => {
    const form = addColumn(addColumn(createDefaultLiteratureForm('我的文献表'), BUILTIN_COLUMNS.find((column) => column.id === 'keywords')!), BUILTIN_COLUMNS.find((column) => column.id === 'journal')!)
    form.rows[0]!.cells.title = { value: '生成失败: 模型错误', status: 'failed' }
    form.rows[0]!.cells.keywords = { value: '', status: 'idle' }
    form.rows[0]!.cells.journal = { value: 'Plant Cell', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('清空无效字段'))?.trigger('click')

    expect(wrapper.find('td[data-column-id="title"] textarea').element).toMatchObject({ value: '生成失败: 模型错误' })
    expect(wrapper.find('td[data-column-id="title"] .status-dot').exists()).toBe(false)
    expect(wrapper.find('td[data-column-id="keywords"] textarea').element).toMatchObject({ value: '' })
    expect(wrapper.find('td[data-column-id="journal"] textarea').element).toMatchObject({ value: 'Plant Cell' })
  })

  it('creates a user-named form under the knowledge forms folder', async () => {
    vi.mocked(listSmartFormsDb).mockResolvedValueOnce([])
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('button[title="新建表格"]').trigger('click')
    expect(wrapper.find('form[role="dialog"] .forms-eyebrow').exists()).toBe(false)
    const dialog = [...document.querySelectorAll<HTMLFormElement>('form[role="dialog"]')].at(-1)!
    const input = dialog.querySelector<HTMLInputElement>('input[placeholder="例如：项目文献库"]')!
    input.value = '项目阅读表'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    dialog.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    expect(saveSmartFormDb).toHaveBeenCalledWith(expect.objectContaining({
      user_id: 'local-test',
      asset_dir: '.mw/forms/项目阅读表',
      form: expect.objectContaining({ title: '项目阅读表' }),
    }))
  })

  it('keeps the table-name input focused when the creation dialog opens and its type changes', async () => {
    const wrapper = mount(SmartFormsView, { attachTo: document.body })
    await flushPromises()

    await wrapper.find('button[title="新建表格"]').trigger('click')
    await nextTick()
    const dialogs = [...document.querySelectorAll<HTMLElement>('form[role="dialog"]')]
    const dialog = dialogs[dialogs.length - 1]!
    const titleInput = dialog.querySelector<HTMLInputElement>('input[placeholder="例如：项目文献库"]')!
    expect(document.activeElement).toBe(titleInput)

    const plainType = dialog.querySelector<HTMLButtonElement>('button[data-form-kind="plain"]')!
    plainType.focus()
    plainType.click()
    await nextTick()

    expect(document.activeElement).toBe(titleInput)
    wrapper.unmount()
  })

  it('creates a plain 10 by 10 text table without upload, smart, or sequence columns', async () => {
    vi.mocked(listSmartFormsDb).mockResolvedValueOnce([])
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('button[title="新建表格"]').trigger('click')
    const dialog = [...document.querySelectorAll<HTMLFormElement>('form[role="dialog"]')].at(-1)!
    const smartType = dialog.querySelector<HTMLButtonElement>('button[data-form-kind="smart"]')!
    const plainType = dialog.querySelector<HTMLButtonElement>('button[data-form-kind="plain"]')!
    expect(smartType.classList).toContain('active')
    expect(plainType.classList).not.toContain('active')

    plainType.click()
    await nextTick()
    expect(smartType.classList).not.toContain('active')
    expect(plainType.classList).toContain('active')
    const input = dialog.querySelector<HTMLInputElement>('input[placeholder="例如：项目文献库"]')!
    input.value = '普通项目表'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    dialog.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()

    const savedForm = vi.mocked(saveSmartFormDb).mock.calls
      .find(([payload]) => payload.form.title === '普通项目表')?.[0].form
    expect(savedForm?.columns).toHaveLength(10)
    expect(savedForm?.columns.every((column) => column.type === 'text')).toBe(true)
    expect(savedForm?.rows).toHaveLength(10)
    expect(savedForm?.columns.some((column) => column.type === 'smart_text' || column.type === 'smart_tag')).toBe(false)
    expect(savedForm?.columns.some((column) => column.type === 'index' || column.id === 'row_index')).toBe(false)
    expect(wrapper.find('.table-frame.plain-table').exists()).toBe(true)
    expect(wrapper.findAll('thead th[data-column-id]')).toHaveLength(10)
    expect(wrapper.findAll('tbody tr')).toHaveLength(10)
    expect(wrapper.text()).not.toContain('序号')
    expect(wrapper.text()).not.toContain('全表智能填充')
  })

  it('renders every disabled context-menu action with the shared gray state', () => {
    expect(smartFormsSource).toMatch(/\.table-context-menu button:disabled\s*\{[^}]*color:\s*var\(--color-text-tertiary\);/)
    expect(smartFormsSource).toMatch(/\.table-context-menu button:disabled\s*\{[^}]*cursor:\s*not-allowed;/)
  })

  it('deletes the active table after confirmation and clears the workspace', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.get('button[title="删除表格"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith('确定删除表格“我的文献表”吗？此操作不可撤销。')
    expect(deleteSmartFormDb).toHaveBeenCalledWith('local-test', 'sf_demo')
    expect(wrapper.find('.form-empty-state').exists()).toBe(true)
    expect(wrapper.find('button[title="删除表格"]').exists()).toBe(false)
    confirm.mockRestore()
  })

  it('shares the workspace card radius and uses a capsule title input', () => {
    expect(editorWorkspaceSource).toContain('--workspace-card-radius: 28px;')
    expect(editorWorkspaceSource).toContain('border-radius: var(--workspace-card-radius);')
    expect(smartFormsSource).toContain('border-radius: var(--workspace-card-radius);')
    expect(smartFormsSource).toMatch(/\.dialog-field input \{[^}]*border-radius: 999px;/)
    expect(smartFormsSource).toMatch(/\.dialog-field input \{[^}]*width: 100%;[^}]*max-width: 100%;/)
    expect(smartFormsSource).toMatch(/\.new-form-btn \{[^}]*border-radius: 999px;[^}]*background: var\(--color-primary\);/)
  })

  it('adds rows and generates selected smart cells from literature content', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('tbody tr').trigger('contextmenu')
    await hoverContextButton('添加行', true)
    await clickContextButton('在下方添加', true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)

    vi.mocked(uploadKnowledgeFile).mockResolvedValueOnce({
      uploaded_path: 'D:/Knowledge/.mw/forms/我的文献表/assets/ros.md',
      knowledge_dir: 'D:/Knowledge',
    })
    vi.mocked(previewKnowledgeFile).mockResolvedValueOnce({
      path: '.mw/forms/我的文献表/assets/ros.md',
      kind: 'markdown',
      content: 'A paper about ROS receptor HPCA1 in systemic signaling.',
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.md',
      readonly: false,
    })
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', {
      value: [new File(['paper text'], 'ros.md', { type: 'text/markdown' })],
      configurable: true,
    })
    await wrapper.get('input[type="file"]').trigger('change')
    await flushPromises()

    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu')
    await clickContextButton('智能填充', true)
    await flushPromises()

    const textareaValues = wrapper.findAll('textarea').map((textarea) => {
      return (textarea.element as HTMLTextAreaElement).value
    })
    expect(textareaValues).toContain('LLM extracted title')
    expect(wrapper.text()).not.toContain('AI 生成')
  })

  it('deletes whole rows and removable columns from the table context menu', async () => {
    const paperTypeColumn = BUILTIN_COLUMNS.find((column) => column.id === 'paper_type')!
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(addColumn(createDefaultLiteratureForm('我的文献表'), paperTypeColumn)))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="paper_type"]').trigger('contextmenu')
    await hoverContextButton('删除')
    await clickContextButton('删除整列')
    expect(wrapper.find('td[data-column-id="paper_type"]').exists()).toBe(false)

    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu')
    await hoverContextButton('删除')
    await clickContextButton('删除整行')
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })

  it('moves rows and columns from dedicated context submenus', async () => {
    const keywordsColumn = BUILTIN_COLUMNS.find((column) => column.id === 'keywords')!
    const form = addColumn(createDefaultLiteratureForm('我的文献表'), keywordsColumn)
    const secondRow = createEmptyRow(form.columns)
    form.rows[0]!.cells.title = { value: '第一行' }
    secondRow.cells.title = { value: '第二行' }
    form.rows.push(secondRow)
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.findAll('td[data-column-id="title"]')[1]!.trigger('contextmenu')
    await hoverContextButton('行移动')
    await clickContextButton('行上移')
    expect(wrapper.findAll('td[data-column-id="title"] textarea').map((cell) => (cell.element as HTMLTextAreaElement).value)).toEqual(['第二行', '第一行'])

    const columnOrder = () => wrapper.findAll('thead th[data-column-id]').map((header) => header.attributes('data-column-id'))
    const before = columnOrder()
    await wrapper.find('th[data-column-id="keywords"]').trigger('contextmenu')
    await hoverContextButton('列移动')
    await clickContextButton('列左移')
    const after = columnOrder()
    expect(after.indexOf('keywords')).toBe(before.indexOf('keywords') - 1)
  })

  it('downgrades to a plain table when the literature source is deleted', async () => {
    const form = addColumn(addColumn(createDefaultLiteratureForm('我的文献表'), BUILTIN_COLUMNS.find((column) => column.id === 'paper_type')!), BUILTIN_COLUMNS.find((column) => column.id === 'keywords')!)
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('th[data-column-id="literature_file"]').trigger('contextmenu')
    await hoverContextButton('删除')
    await clickContextButton('删除整列')

    expect(wrapper.find('th[data-column-id="literature_file"]').exists()).toBe(false)
    expect(wrapper.find('th[data-column-id="literature_content"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text().includes('全表智能填充'))).toBe(false)

    await wrapper.find('th[data-column-id="title"]').trigger('contextmenu')
    await hoverContextButton('添加列')
    await hoverContextButton('左侧添加')
    expect(contextButton('关键词', true)?.disabled).toBe(true)
    expect(contextButton('重要性', true)?.disabled).toBe(false)
    await hoverContextButton('右侧添加')
    expect(contextButton('智能文本')?.disabled).toBe(true)
    expect(contextButton('文本')?.disabled).toBe(false)
  })

  it('drag-selects multiple cells and applies context actions to each selected item', async () => {
    const multiRowForm = createDefaultLiteratureForm('我的文献表')
    const secondRow = createEmptyRow(multiRowForm.columns)
    multiRowForm.rows = [
      {
        ...multiRowForm.rows[0]!,
        cells: {
          ...multiRowForm.rows[0]!.cells,
          title: { ...multiRowForm.rows[0]!.cells.title, value: '第一行标题' },
        },
      },
      {
        ...secondRow,
        cells: {
          ...secondRow.cells,
          title: { ...secondRow.cells.title, value: '第二行标题' },
        },
      },
    ]
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(multiRowForm))
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const titleCells = wrapper.findAll('td[data-column-id="title"]')

    await titleCells[0]!.trigger('mousedown', { button: 0 })
    await titleCells[1]!.trigger('mouseenter')
    await wrapper.find('.table-frame').trigger('mouseup')
    expect(wrapper.findAll('td.selected')).toHaveLength(2)
    expect(titleCells[0]!.attributes('style')).not.toContain('inset 0 -2px')
    expect(titleCells[1]!.attributes('style')).not.toContain('inset 0 2px')
    expect(titleCells[0]!.attributes('style')).toContain('inset 2px 0 0')
    expect(titleCells[1]!.attributes('style')).toContain('inset -2px 0 0')

    await wrapper.findAll('td[data-column-id="title"]')[1]!.trigger('contextmenu')
    await clickContextButton('清空')
    await flushPromises()
    expect(wrapper.findAll('td[data-column-id="title"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual(['', ''])

    await titleCells[1]!.trigger('contextmenu')
    await hoverContextButton('删除')
    await clickContextButton('删除整行')
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })

  it('fills every smart column in a multi-cell selection', async () => {
    const baseForm = createDefaultLiteratureForm('我的文献表')
    const form = addColumn(addColumn(baseForm, BUILTIN_COLUMNS.find((column) => column.id === 'keywords')!), BUILTIN_COLUMNS.find((column) => column.id === 'journal')!)
    const secondRow = createEmptyRow(form.columns)
    form.rows = [form.rows[0]!, secondRow]
    form.rows.forEach((row, index) => {
      row.cells.literature_content = { value: `文献内容 ${index + 1}`, status: 'ready' }
    })
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    vi.mocked(generateStructuredFields).mockImplementation(async (request) => ({
      raw_output: '{}',
      results: request.fields.map((field) => ({
        field_id: field.id,
        status: 'ready' as const,
        value: `${field.id}-${request.source.metadata?.row_id}`,
      })),
    }))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    const titleCells = wrapper.findAll('td[data-column-id="title"]')
    const journalCells = wrapper.findAll('td[data-column-id="journal"]')
    await titleCells[0]!.trigger('mousedown', { button: 0 })
    await journalCells[1]!.trigger('mouseenter')
    await wrapper.find('.table-frame').trigger('mouseup')
    await journalCells[1]!.trigger('contextmenu')
    await clickContextButton('智能填充', true)
    await flushPromises()

    expect(vi.mocked(generateStructuredFields)).toHaveBeenCalledTimes(2)
    expect(vi.mocked(generateStructuredFields).mock.calls.every(([request]) => request.fields.map((field) => field.id).sort().join(',') === 'journal,keywords,title')).toBe(true)
    expect(wrapper.findAll('td[data-column-id="title"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual([
      `title-${form.rows[0]!.id}`,
      `title-${form.rows[1]!.id}`,
    ])
    expect(wrapper.findAll('td[data-column-id="keywords"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual([
      `keywords-${form.rows[0]!.id}`,
      `keywords-${form.rows[1]!.id}`,
    ])
    expect(wrapper.findAll('td[data-column-id="journal"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual([
      `journal-${form.rows[0]!.id}`,
      `journal-${form.rows[1]!.id}`,
    ])
  })

  it('fills all rows and all smart columns from the whole-table action', async () => {
    const baseForm = createDefaultLiteratureForm('我的文献表')
    const form = addColumn(addColumn(baseForm, BUILTIN_COLUMNS.find((column) => column.id === 'keywords')!), BUILTIN_COLUMNS.find((column) => column.id === 'journal')!)
    const secondRow = createEmptyRow(form.columns)
    form.rows = [form.rows[0]!, secondRow]
    form.rows.forEach((row, index) => {
      row.cells.literature_content = { value: `文献内容 ${index + 1}`, status: 'ready' }
    })
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    vi.mocked(generateStructuredFields).mockImplementation(async (request) => ({
      raw_output: '{}',
      results: request.fields.map((field) => ({
        field_id: field.id,
        status: 'ready' as const,
        value: `${field.id}-${request.source.metadata?.row_id}`,
      })),
    }))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('全表智能填充'))?.trigger('click')
    await flushPromises()

    expect(vi.mocked(generateStructuredFields)).toHaveBeenCalledTimes(2)
    expect(vi.mocked(generateStructuredFields).mock.calls.every(([request]) => request.fields.map((field) => field.id).sort().join(',') === 'journal,keywords,title')).toBe(true)
    for (const columnId of ['title', 'keywords', 'journal']) {
      expect(wrapper.findAll(`td[data-column-id="${columnId}"] textarea`).map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual([
        `${columnId}-${form.rows[0]!.id}`,
        `${columnId}-${form.rows[1]!.id}`,
      ])
    }
  })

  it('reorders columns by dragging header cells', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    vi.mocked(saveSmartFormDb).mockClear()
    vi.useFakeTimers()
    const headers = () => wrapper.findAll('thead tr:nth-child(2) th').map((header) => header.get('.column-title-label').text())

    await wrapper.findAll('thead tr:nth-child(2) th')[4]!.trigger('dragstart')
    await wrapper.findAll('thead tr:nth-child(2) th')[2]!.trigger('drop')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(headers().slice(0, 5)).toEqual(['序号', '文献上传', '标题', '文献内容', '图表'])
    expect(saveSmartFormDb).toHaveBeenCalledWith(expect.objectContaining({
      form: expect.objectContaining({
        columns: expect.arrayContaining([
          expect.objectContaining({ id: 'title' }),
        ]),
      }),
    }))
  })

  it('edits a user-created column title in place and does not freeze columns', async () => {
    const form = addColumn(createDefaultLiteratureForm('我的文献表'), createCustomColumn('自定义字段', 'text'))
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    const customHeader = wrapper.find('th[data-column-id^="col_"]')
    await customHeader.find('.editable-column-title').trigger('click')
    await customHeader.find('.column-title-input').setValue('新的字段名')
    await customHeader.find('.column-title-input').trigger('keydown', { key: 'Enter' })

    expect(customHeader.text()).toContain('新的字段名')
    expect(wrapper.findAll('.sticky')).toHaveLength(0)
  })

  it('reorders whole rows by dragging the index column and recalculates row numbers', async () => {
    const multiRowForm = createDefaultLiteratureForm('我的文献表')
    const secondRow = createEmptyRow(multiRowForm.columns)
    multiRowForm.rows = [
      {
        ...multiRowForm.rows[0]!,
        cells: {
          ...multiRowForm.rows[0]!.cells,
          title: { ...multiRowForm.rows[0]!.cells.title, value: '第一行标题' },
        },
      },
      {
        ...secondRow,
        cells: {
          ...secondRow.cells,
          title: { ...secondRow.cells.title, value: '第二行标题' },
        },
      },
    ]
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(multiRowForm))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.findAll('td[data-column-id="row_index"]')[0]!.trigger('dragstart')
    await wrapper.findAll('td[data-column-id="row_index"]')[1]!.trigger('drop')
    await flushPromises()

    expect(wrapper.findAll('td[data-column-id="title"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual(['第二行标题', '第一行标题'])
    expect(wrapper.findAll('td[data-column-id="row_index"]').map((cell) => cell.text())).toEqual(['1', '2'])
  })

  it('closes the tag picker when clicking outside it', async () => {
    const paperTypeColumn = BUILTIN_COLUMNS.find((column) => column.id === 'paper_type')!
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(addColumn(createDefaultLiteratureForm('我的文献表'), paperTypeColumn)))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="paper_type"] .tag-add-button').trigger('click')
    expect(wrapper.find('.tag-editor').exists()).toBe(true)

    await wrapper.find('.tag-editor-input-row input').trigger('mousedown')
    await wrapper.find('.tag-editor-input-row input').trigger('click')
    expect(wrapper.find('.tag-editor').exists()).toBe(true)

    await wrapper.find('.tag-editor-head button').trigger('click')
    expect(wrapper.find('.tag-editor').exists()).toBe(false)

    await wrapper.find('td[data-column-id="paper_type"] .tag-add-button').trigger('click')

    await wrapper.find('.forms-header').trigger('click')
    expect(wrapper.find('.tag-editor').exists()).toBe(false)
  })

  it('prevents text selection on cell drag while preserving text input selection', async () => {
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const table = wrapper.find('.smart-table')
    const cellEvent = new Event('selectstart', { bubbles: true, cancelable: true })
    table.find('td[data-column-id="title"]').element.dispatchEvent(cellEvent)
    expect(cellEvent.defaultPrevented).toBe(true)
    const inputEvent = new Event('selectstart', { bubbles: true, cancelable: true })
    table.find('td[data-column-id="title"] textarea').element.dispatchEvent(inputEvent)
    expect(inputEvent.defaultPrevented).toBe(false)
  })

  it('adds multiple tags into one cell and toggles each off', async () => {
    const paperTypeColumn = BUILTIN_COLUMNS.find((column) => column.id === 'paper_type')!
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(addColumn(createDefaultLiteratureForm('我的文献表'), paperTypeColumn)))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    const cell = wrapper.find('td[data-column-id="paper_type"]')
    await cell.find('.tag-add-button').trigger('click')
    expect(wrapper.find('.tag-editor').exists()).toBe(true)

    await wrapper.findAll('.tag-option-pill').filter((pill) => pill.text().includes('研究论文'))[0]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.tag-option-pill').filter((pill) => pill.text().includes('综述论文'))[0]!.trigger('click')
    await flushPromises()

    const labelTexts = (): string[] => cell.findAll('.tag-pill-label').map((pill) => pill.text().trim())
    expect(labelTexts()).toEqual(expect.arrayContaining(['研究论文', '综述论文']))

    await wrapper.findAll('.tag-option-pill').filter((pill) => pill.text().includes('研究论文'))[0]!.trigger('click')
    await flushPromises()
    expect(labelTexts()).toEqual(['综述论文'])
  })

  it('adds a typed custom tag and renders it as a colored pill', async () => {
    const paperTypeColumn = BUILTIN_COLUMNS.find((column) => column.id === 'paper_type')!
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(addColumn(createDefaultLiteratureForm('我的文献表'), paperTypeColumn)))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    const cell = wrapper.find('td[data-column-id="paper_type"]')
    await cell.find('.tag-add-button').trigger('click')
    await cell.find('.tag-editor-input-row input').setValue('重点')
    await cell.find('.tag-editor-input-row button').trigger('click')
    await flushPromises()

    expect(cell.findAll('.tag-pill-label').map((pill) => pill.text().trim())).toEqual(['重点'])
    expect(cell.find('.tag-pill').attributes('style')).toContain('background')
  })

  it('marks smart fill as failed when structured generation returns failed results', async () => {
    vi.mocked(generateStructuredFields).mockResolvedValueOnce({
      raw_output: 'not json',
      results: [
        { field_id: 'title', status: 'failed', value: '', error: '模型未返回有效 JSON' },
      ],
    })
    const storedForm = createDefaultLiteratureForm('我的文献表')
    storedForm.rows[0]!.cells.title = { value: '原来的标题', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    vi.mocked(uploadKnowledgeFile).mockResolvedValueOnce({
      uploaded_path: 'D:/Knowledge/.mw/forms/我的文献表/assets/table.md',
      knowledge_dir: 'D:/Knowledge',
    })
    vi.mocked(previewKnowledgeFile).mockResolvedValueOnce({
      path: '.mw/forms/我的文献表/assets/table.md',
      kind: 'markdown',
      content: [
        '## 表格PDF',
        '摘要: 项目案例库用于演示智能表格抽取。',
        'Keywords: CRUD; archive; workspace',
        'DOI: 10.1234/metawave.demo',
        '2026',
      ].join('\n'),
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.md',
      readonly: false,
    })
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', {
      value: [new File(['paper text'], 'table.md', { type: 'text/markdown' })],
      configurable: true,
    })
    await wrapper.get('input[type="file"]').trigger('change')
    await flushPromises()
    expect(wrapper.find('td[data-column-id="literature_content"] textarea').element).toMatchObject({
      value: [
      '## 表格PDF',
      '摘要: 项目案例库用于演示智能表格抽取。',
      'Keywords: CRUD; archive; workspace',
      'DOI: 10.1234/metawave.demo',
      '2026',
    ].join('\n'),
    })
    await flushPromises()

    expect(wrapper.find('.status-dot.failed').exists()).toBe(false)
    expect(wrapper.find('td[data-column-id="title"] textarea').element).toMatchObject({
      value: '原来的标题',
    })
  })

  it('starts smart fill asynchronously so another cell can be selected while it runs', async () => {
    let resolveGeneration!: () => void
    const gate = new Promise<void>((resolve) => { resolveGeneration = resolve })
    vi.mocked(generateStructuredFields).mockImplementationOnce(async () => {
      await gate
      return {
        raw_output: '{"title":"晚到标题"}',
        results: [{ field_id: 'title', status: 'ready', value: '晚到标题' }],
      }
    })
    const form = createDefaultLiteratureForm('我的文献表')
    form.rows[0]!.cells.literature_content = { value: 'A real paper body for async extraction.', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu')
    await clickContextButton('智能填充', true)
    await wrapper.find('td[data-column-id="literature_content"]').trigger('click')

    expect(wrapper.find('td[data-column-id="title"] .smart-cell-loading-mask').exists()).toBe(true)
    expect(wrapper.find('td[data-column-id="title"] .pixel-loader i').exists()).toBe(true)
    expect(wrapper.find('td[data-column-id="literature_content"]').classes()).toContain('selected')

    resolveGeneration()
    await flushPromises()
    expect(wrapper.find('td[data-column-id="title"] textarea').element).toMatchObject({ value: '晚到标题' })
    expect(wrapper.find('td[data-column-id="title"] .smart-cell-loading-mask').exists()).toBe(false)
  })

  it('queues repeated smart fills from different rows without dropping later requests', async () => {
    const requests: Array<{ resolve: () => void }> = []
    vi.mocked(generateStructuredFields).mockImplementation((request) => new Promise((resolve) => {
      requests.push({ resolve: () => resolve({
        raw_output: '{}',
        results: [{ field_id: 'title', status: 'ready', value: `标题-${request.source.metadata?.row_id}` }],
      }) })
    }))
    const form = createDefaultLiteratureForm('我的文献表')
    form.rows.push(createEmptyRow(form.columns))
    form.rows.forEach((row) => { row.cells.literature_content = { value: 'paper content', status: 'ready' } })
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    for (const row of wrapper.findAll('td[data-column-id="title"]')) {
      await row.trigger('contextmenu')
      await clickContextButton('智能填充', true)
    }
    await nextTick()
    expect(vi.mocked(generateStructuredFields)).toHaveBeenCalledTimes(2)

    requests.shift()?.resolve()
    await flushPromises()
    expect(vi.mocked(generateStructuredFields)).toHaveBeenCalledTimes(2)
    requests.shift()?.resolve()
    await flushPromises()
    expect(wrapper.findAll('td[data-column-id="title"] .smart-cell-loading-mask').length).toBe(0)
    expect(wrapper.findAll('td[data-column-id="title"] textarea').every((textarea) => (textarea.element as HTMLTextAreaElement).value.startsWith('标题-'))).toBe(true)
  })

  it('does not let an older smart fill response overwrite a newer one for the same cell', async () => {
    let resolveFirst!: () => void
    let resolveSecond!: () => void
    const firstGate = new Promise<void>((resolve) => { resolveFirst = resolve })
    const secondGate = new Promise<void>((resolve) => { resolveSecond = resolve })
    vi.mocked(generateStructuredFields)
      .mockImplementationOnce(async () => {
        await firstGate
        return { raw_output: '{"title":"旧标题"}', results: [{ field_id: 'title', status: 'ready', value: '旧标题' }] }
      })
      .mockImplementationOnce(async () => {
        await secondGate
        return { raw_output: '{"title":"新标题"}', results: [{ field_id: 'title', status: 'ready', value: '新标题' }] }
      })
    const form = createDefaultLiteratureForm('我的文献表')
    form.rows[0]!.cells.literature_content = { value: 'A real paper body for async extraction.', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(form))
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu')
    await clickContextButton('智能填充', true)
    await wrapper.find('td[data-column-id="title"]').trigger('contextmenu')
    await clickContextButton('智能填充', true)

    resolveSecond()
    await flushPromises()
    expect(wrapper.find('td[data-column-id="title"] textarea').element).toMatchObject({ value: '新标题' })

    resolveFirst()
    await flushPromises()
    expect(wrapper.find('td[data-column-id="title"] textarea').element).toMatchObject({ value: '新标题' })
  })

  it('uploads literature assets without hidden auto ingest and submits stream ingestion', async () => {
    vi.mocked(uploadKnowledgeFile).mockResolvedValueOnce({
      uploaded_path: 'D:/Knowledge/.mw/forms/我的文献表/assets/paper.md',
      knowledge_dir: 'D:/Knowledge',
    })
    vi.mocked(previewKnowledgeFile).mockResolvedValueOnce({
      path: '.mw/forms/我的文献表/assets/paper.md',
      kind: 'markdown',
      content: '这是灌库后从文献中抽取出的真实正文。',
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.md',
      readonly: false,
    })
    const workspaceStore = useWorkspaceStore()
    const ingestFile = vi.spyOn(workspaceStore, 'ingestFile').mockResolvedValue(undefined)
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', {
      value: [new File(['paper text'], 'paper.md', { type: 'text/markdown' })],
      configurable: true,
    })

    await wrapper.get('input[type="file"]').trigger('change')
    await flushPromises()

    expect(uploadKnowledgeFile).toHaveBeenCalledWith(
      'local-test',
      expect.any(File),
      '.mw/forms/我的文献表/assets',
      false,
      'rename',
    )
    expect(ingestFile).toHaveBeenCalledWith({
      name: 'paper.md',
      path: '.mw/forms/我的文献表/assets/paper.md',
      isDir: false,
      indexStatus: 'dirty',
    })
    expect(previewKnowledgeFile).toHaveBeenCalledWith('local-test', '.mw/forms/我的文献表/assets/paper.md')
    const textareaValues = wrapper.findAll('textarea').map((textarea) => {
      return (textarea.element as HTMLTextAreaElement).value
    })
    expect(textareaValues).toContain('这是灌库后从文献中抽取出的真实正文。')
    expect(saveSmartFormDb).toHaveBeenCalledWith(expect.objectContaining({
      user_id: 'local-test',
      form_id: 'sf_demo',
      form: expect.objectContaining({
        rows: expect.arrayContaining([
          expect.objectContaining({
            cells: expect.objectContaining({
              literature_content: expect.objectContaining({ value: '这是灌库后从文献中抽取出的真实正文。' }),
            }),
          }),
        ]),
      }),
    }))
    expect(wrapper.find('.status-dot').exists()).toBe(false)
  })

  it('fills the built-in figure column from ingested PDF Markdown image links', async () => {
    vi.mocked(uploadKnowledgeFile).mockResolvedValueOnce({
      uploaded_path: 'D:/Knowledge/.mw/forms/我的文献表/assets/paper.pdf',
      knowledge_dir: 'D:/Knowledge',
    })
    vi.mocked(previewKnowledgeFile).mockResolvedValue({
      path: '.mw/forms/我的文献表/assets/paper.pdf',
      kind: 'document',
      semantic_markdown: [
        '# Paper',
        '![Figure 1](/.mw/assets/.mw/forms/我的文献表/assets/paper.pdf/image_0001.png)',
        '正文',
        '![Figure 2](/.mw/assets/.mw/forms/我的文献表/assets/paper.pdf/image_0002.png)',
      ].join('\n\n'),
      render_content: '![preview duplicate](/knowledge/assets/pdf_preview/demo/image_0001.png)',
      mtime: '2026-08-09T10:00:00',
      size: 128,
      extension: '.pdf',
      readonly: true,
    })
    vi.spyOn(useWorkspaceStore(), 'ingestFile').mockResolvedValue(undefined)
    const wrapper = mount(SmartFormsView)
    await flushPromises()
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', {
      value: [new File(['pdf'], 'paper.pdf', { type: 'application/pdf' })],
      configurable: true,
    })

    await wrapper.get('input[type="file"]').trigger('change')
    await flushPromises()

    const savedFigures = vi.mocked(saveSmartFormDb).mock.calls
      .map(([payload]) => payload.form.rows[0]?.cells.figures?.value)
      .filter(Boolean)
    expect(savedFigures).toContain([
      '![Figure 1](/.mw/assets/.mw/forms/我的文献表/assets/paper.pdf/image_0001.png)',
      '![Figure 2](/.mw/assets/.mw/forms/我的文献表/assets/paper.pdf/image_0002.png)',
    ].join('\n\n'))
    expect(savedFigures.some((value) => value?.includes('preview duplicate'))).toBe(false)
    expect(wrapper.find('td[data-column-id="figures"] .smart-markdown-cell').exists()).toBe(true)
    expect(wrapper.find('td[data-column-id="figures"] .smart-plain-text').exists()).toBe(false)
  })

  it('generates the optional formula column from literature content with its default prompt', async () => {
    const formulaColumn = BUILTIN_COLUMNS.find((column) => column.id === 'formulas')!
    const storedForm = addColumn(createDefaultLiteratureForm('公式表'), formulaColumn)
    storedForm.rows[0]!.cells.literature_content = { value: '正文包含能量方程和动量方程。', status: 'ready' }
    vi.mocked(getSmartFormDb).mockResolvedValueOnce(dbResponse(storedForm))
    vi.mocked(generateStructuredFields).mockResolvedValueOnce({
      raw_output: '{"formulas":"$$E = mc^2$$"}',
      results: [{ field_id: 'formulas', status: 'ready', value: '$$E = mc^2$$' }],
    })
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    await wrapper.find('td[data-column-id="formulas"]').trigger('contextmenu')
    await clickContextButton('智能填充', true)
    await flushPromises()

    expect(generateStructuredFields).toHaveBeenCalledWith(expect.objectContaining({
      source: expect.objectContaining({ content: '正文包含能量方程和动量方程。' }),
      fields: [expect.objectContaining({
        id: 'formulas',
        type: 'text',
        description: expect.stringContaining('$$...$$'),
      })],
    }))
    expect(wrapper.find('td[data-column-id="formulas"] .smart-plain-text').exists()).toBe(false)
  })

  it('uses structured table and document previews as literature text', async () => {
    vi.mocked(uploadKnowledgeFile).mockImplementation(async (_userId, file) => ({
      uploaded_path: `D:/Knowledge/.mw/forms/我的文献表/assets/${file.name}`,
      knowledge_dir: 'D:/Knowledge',
    }))
    vi.mocked(previewKnowledgeFile).mockImplementation(async (_userId, path) => {
      if (path.endsWith('.csv')) {
        return {
          path,
          kind: 'table',
          sheets: [{ name: 'csv', rows: [['标题', '作者'], ['表格论文', '作者甲']] }],
          mtime: '2026-08-09T10:00:00',
          size: 128,
          extension: '.csv',
          readonly: true,
        }
      }
      if (path.endsWith('.xlsx')) {
        return {
          path,
          kind: 'table',
          sheets: [{ name: 'Sheet 1', rows: [['年份', '期刊'], ['2026', 'Plant Cell']] }],
          mtime: '2026-08-09T10:00:00',
          size: 128,
          extension: '.xlsx',
          readonly: true,
        }
      }
      return {
        path,
        kind: 'document',
        html: '<h1>Word 标题</h1><p>Word 正文内容</p>',
        mtime: '2026-08-09T10:00:00',
        size: 128,
        extension: '.docx',
        readonly: true,
      }
    })
    const workspaceStore = useWorkspaceStore()
    vi.spyOn(workspaceStore, 'ingestFile').mockResolvedValue(undefined)
    const wrapper = mount(SmartFormsView)
    await flushPromises()

    for (const [index, fileName] of ['paper.csv', 'paper.xlsx', 'paper.docx'].entries()) {
      if (index > 0) {
        await wrapper.findAll('button').find((button) => button.text().includes('上传文献'))?.trigger('click')
        await flushPromises()
      }
      const input = wrapper.findAll('input[type="file"]')[index]!.element as HTMLInputElement
      Object.defineProperty(input, 'files', {
        value: [new File(['file'], fileName)],
        configurable: true,
      })
      await wrapper.findAll('input[type="file"]')[index]!.trigger('change')
      await flushPromises()
    }

    expect(wrapper.findAll('td[data-column-id="literature_content"] textarea').map((textarea) => (textarea.element as HTMLTextAreaElement).value)).toEqual([
      'csv\n标题\t作者\n表格论文\t作者甲',
      'Sheet 1\n年份\t期刊\n2026\tPlant Cell',
      'Word 标题Word 正文内容',
    ])
  })
})
