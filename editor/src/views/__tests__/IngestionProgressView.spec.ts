/** Single-file ingestion queue progress and cancellation UI tests. */

import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import IngestionProgressView from '@/views/IngestionProgressView.vue'

const cancelIngestionJob = vi.fn().mockResolvedValue(undefined)
const cancelGraphTask = vi.fn().mockResolvedValue(undefined)
const loadIngestionJobs = vi.fn().mockResolvedValue([])
const settingsStore = {
  profile: { knowledgeDir: 'D:/Knowledge' },
}
const workspaceStore = {
  ingestionViewTab: 'queue',
  mainView: 'ingestion',
  refreshing: false,
  ingestionQueue: [{
    id: 'ingest_1',
    jobId: 'ingest_1',
    name: 'paper.pdf',
    path: 'papers/paper.pdf',
    isDir: false,
    size: 2048,
    mtime: '2026-08-20 18:00',
    status: 'running',
    progress: 64.26,
    pipeline: 'pdf',
    stage: 'ocr_pages',
    stageLabel: '正在 OCR 扫描页',
    stageCurrent: 8,
    stageTotal: 20,
    queuedAt: '2026-08-20T10:00:00Z',
    message: '已识别第 8 / 20 页',
  }],
  graphQueue: [{
    id: 'graph_doc_notes/note.md',
    name: 'note.md',
    path: 'notes/note.md',
    isDir: false,
    status: 'running',
    progress: 35,
    stageLabel: '正在抽取实体',
    queuedAt: '2026-08-20T10:00:00Z',
  }],
  ingestionHistory: [],
  graphHistory: [],
  loadIngestionJobs,
  cancelIngestionJob,
  cancelGraphTask,
  clearIngestionHistory: vi.fn(),
  clearGraphHistory: vi.fn(),
  loadKnowledgeTree: vi.fn().mockResolvedValue(undefined),
  markIndexing: vi.fn(),
  startGraphRebuild: vi.fn(),
}

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => workspaceStore,
}))

vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => settingsStore,
}))

describe('IngestionProgressView', () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    workspaceStore.ingestionViewTab = 'queue'
  })

  it('shows real file pipeline detail and cancels that exact job', async () => {
    const wrapper = mount(IngestionProgressView, {
      global: { stubs: { IcIcon: true } },
    })

    expect(wrapper.text()).toContain('灌库进度')
    expect(wrapper.text()).toContain('paper.pdf')
    expect(wrapper.text()).toContain('64.3%')
    expect(wrapper.text()).toContain('正在 OCR 扫描页')
    expect(wrapper.text()).toContain('8 / 20')
    expect(wrapper.text()).toContain('所在位置绝对路径')
    expect(wrapper.text()).toContain('D:\\Knowledge\\papers\\paper.pdf')

    await wrapper.get('button[aria-label="中止 paper.pdf 灌库"]').trigger('click')

    expect(cancelIngestionJob).toHaveBeenCalledWith(workspaceStore.ingestionQueue[0])
  })

  it('shows the absolute location path for every graph extraction row', () => {
    workspaceStore.ingestionViewTab = 'graph-queue'
    const wrapper = mount(IngestionProgressView, {
      global: { stubs: { IcIcon: true } },
    })

    expect(wrapper.text()).toContain('所在位置绝对路径')
    expect(wrapper.text()).toContain('D:\\Knowledge\\notes\\note.md')
  })

  it('offers graph cancellation and targets the exact graph queue row', async () => {
    workspaceStore.ingestionViewTab = 'graph-queue'
    const wrapper = mount(IngestionProgressView, {
      global: { stubs: { IcIcon: true } },
    })

    await wrapper.get('button[aria-label="中止 note.md 图谱抽取"]').trigger('click')

    expect(cancelGraphTask).toHaveBeenCalledWith(workspaceStore.graphQueue[0])
  })
})
