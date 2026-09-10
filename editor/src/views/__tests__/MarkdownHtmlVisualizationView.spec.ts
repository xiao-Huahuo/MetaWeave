/*
 * MD-HTML visualization page tests.
 *
 * Usage:
 * Verifies the page-facing name and explicit file-picker entry point without
 * starting the Agent visualization workflow.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import { useTaskListStore } from '@/stores/taskList'
import { useWorkspaceStore } from '@/stores/workspace'
import MarkdownHtmlVisualizationView from '@/views/MarkdownHtmlVisualizationView.vue'

vi.mock('@/api/agent', () => ({
  updateCurrentDocumentContext: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/settings', () => ({
  rebuildKnowledgeRootStream: vi.fn(),
}))

vi.mock('@/api/knowledge', () => ({
  buildKnowledgeEventsUrl: vi.fn(() => '/events'),
  copyKnowledgePath: vi.fn(),
  createKnowledgeFile: vi.fn(),
  createKnowledgeFolder: vi.fn(),
  deleteKnowledgePath: vi.fn(),
  deleteKnowledgeTrashEntry: vi.fn(),
  getKnowledgeGraphStatus: vi.fn(),
  ingestKnowledgeFileStream: vi.fn(),
  ingestKnowledgePathStream: vi.fn(),
  listKnowledgeFiles: vi.fn(),
  listKnowledgeTrash: vi.fn(),
  previewKnowledgeFile: vi.fn(),
  readKnowledgeFile: vi.fn(),
  rebuildKnowledgeGraph: vi.fn(),
  renameKnowledgePath: vi.fn(),
  restoreKnowledgeTrashEntry: vi.fn(),
  searchKnowledge: vi.fn(),
  uploadKnowledgeFile: vi.fn(),
  writeKnowledgeFile: vi.fn(),
}))

describe('MarkdownHtmlVisualizationView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('uses the MD-HTML page name and exposes file picker plus advanced options actions', async () => {
    const wrapper = mount(MarkdownHtmlVisualizationView, {
      global: {
        stubs: {
          Teleport: true,
          DropdownMenuPortal: { template: '<div><slot /></div>' },
        },
      },
    })

    expect(wrapper.find('.visualization-page').exists()).toBe(true)
    expect(wrapper.find('button[title="选择文件"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('高级选项')
    expect(wrapper.find('.advanced-popover').exists()).toBe(false)

    await wrapper.get('button[aria-haspopup="menu"]').trigger('click')

    expect(wrapper.text()).toContain('原结构模式')
    expect(wrapper.text()).toContain('AI提炼模式')
    expect(wrapper.text()).toContain('均衡展示')
    expect(wrapper.text()).toContain('视觉层级')
    expect(wrapper.findAll('.mode-pill .mode-button.active')).toHaveLength(1)
    expect(wrapper.findAll('.preset-grid button.active')).toHaveLength(1)
    expect(wrapper.findAll('.advanced-page-tabs button.active')).toHaveLength(1)
  })

  it('opens the centered file in the editor sidebar on double click', async () => {
    const workspaceStore = useWorkspaceStore()
    workspaceStore.tree = [{ name: 'notes.md', path: 'notes.md', isDir: false }]
    workspaceStore.selectedPath = 'notes.md'
    const openEditorSidebar = vi.spyOn(workspaceStore, 'openEditorSidebar').mockResolvedValue(undefined)
    const wrapper = mount(MarkdownHtmlVisualizationView, {
      global: { stubs: { Teleport: true } },
    })

    await wrapper.get('.selected-file-card').trigger('dblclick')

    expect(openEditorSidebar).toHaveBeenCalledWith({ name: 'notes.md', path: 'notes.md', isDir: false })
  })

  it('updates mode selection and custom requirement from advanced options', async () => {
    const workspaceStore = useWorkspaceStore()
    const wrapper = mount(MarkdownHtmlVisualizationView, {
      global: {
        stubs: {
          Teleport: true,
          DropdownMenuPortal: { template: '<div><slot /></div>' },
        },
      },
    })

    await wrapper.get('button[aria-haspopup="menu"]').trigger('click')

    const modeButtons = wrapper.findAll('.mode-pill .mode-button')
    await modeButtons[1].trigger('click')
    expect(workspaceStore.markdownHtmlVisualizationMode).toBe('insight')

    await modeButtons[0].trigger('click')
    expect(workspaceStore.markdownHtmlVisualizationMode).toBe('structure')

    await wrapper.get('.preset-grid button:nth-child(3)').trigger('click')
    expect(workspaceStore.markdownHtmlVisualizationPreset).toBe('dashboard')

    await wrapper.get('.advanced-page-tabs button:nth-child(3)').trigger('click')
    expect(wrapper.text()).toContain('强动效')

    await wrapper.get('.custom-requirement-field textarea').setValue('突出结论, 降低装饰密度')

    expect(workspaceStore.markdownHtmlVisualizationCustomRequirement).toBe('突出结论, 降低装饰密度')
  })

  it('shows task progress before HTML mounts and switches the action label after mount', async () => {
    const workspaceStore = useWorkspaceStore()
    const taskListStore = useTaskListStore()
    workspaceStore.tree = [{ name: 'notes.md', path: 'notes.md', isDir: false }]
    workspaceStore.selectedPath = 'notes.md'
    const wrapper = mount(MarkdownHtmlVisualizationView, {
      global: {
        stubs: {
          Teleport: true,
        },
      },
    })

    taskListStore.setTaskList({
      task_list_id: 'task_1',
      session_id: 'session_1',
      title: '生成 HTML 可视化',
      status: 'active',
      current_item_id: 'item_2',
      items: [
        { id: 'item_1', title: '读取文档', status: 'completed' },
        { id: 'item_2', title: '生成 HTML', status: 'in_progress' },
      ],
    }, { open: false })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('生成 HTML 可视化')
    expect(wrapper.text()).toContain('1/2')
    expect(wrapper.text()).toContain('生成 HTML')
    expect(wrapper.text()).toContain('一键可视化')
    expect(wrapper.find('.task-progress-list').exists()).toBe(false)

    await wrapper.get('.task-progress-toggle').trigger('click')

    expect(wrapper.find('.task-progress-list').exists()).toBe(true)
    expect(wrapper.text()).toContain('读取文档')
    expect(wrapper.text()).toContain('完成')
    expect(wrapper.text()).toContain('进行中')

    workspaceStore.showMarkdownHtmlVisualization({
      title: 'notes',
      filename: 'notes.html',
      path: 'runtime/visualizations/notes.html',
      url: '/visualizations/notes.html',
      source_path: 'notes.md',
      created_at: '2026-07-29T10:00:00',
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toContain('生成 HTML 可视化')
    expect(wrapper.text()).toContain('重新可视化')
  })

  it('hides task progress when the task list completion event arrives', async () => {
    const taskListStore = useTaskListStore()
    const wrapper = mount(MarkdownHtmlVisualizationView, {
      global: {
        stubs: {
          Teleport: true,
        },
      },
    })

    taskListStore.setTaskList({
      task_list_id: 'task_2',
      session_id: 'session_1',
      title: '生成 HTML 可视化',
      status: 'active',
      current_item_id: 'item_1',
      items: [
        { id: 'item_1', title: '生成 HTML', status: 'in_progress' },
      ],
    }, { open: false })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.task-progress-card').exists()).toBe(true)

    taskListStore.setTaskList({
      task_list_id: 'task_2',
      session_id: 'session_1',
      title: '生成 HTML 可视化',
      status: 'completed',
      current_item_id: null,
      items: [
        { id: 'item_1', title: '生成 HTML', status: 'completed' },
      ],
    }, { open: false })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.task-progress-card').exists()).toBe(false)
  })
})
