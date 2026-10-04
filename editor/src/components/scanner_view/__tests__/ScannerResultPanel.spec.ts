/**
 * Scanner original-preview regression tests.
 * Mounts the result panel and simulates record replacement during progress polling.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ScannerResultPanel from '@/components/scanner_view/ScannerResultPanel.vue'
import { previewKnowledgeFile } from '@/api/knowledge'
import type { ScannerRecord } from '@/api/scanner'

vi.mock('@/api/knowledge', () => ({ previewKnowledgeFile: vi.fn() }))
vi.mock('@/stores/scanner', () => ({ useScannerStore: () => ({ saveDraft: vi.fn(), saveSource: vi.fn() }) }))
vi.mock('@/stores/settings', () => ({ useSettingsStore: () => ({ profile: { userId: 'preview-user' } }) }))
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => ({ showToast: vi.fn() }) }))
vi.mock('@/components/scanner_view/useScannerRecordActions', () => ({
  preferredScannerVariant: () => 'ocr',
  useScannerRecordActions: () => ({}),
}))

/** A finished image record selected while another scanner task is running. */
const record: ScannerRecord = {
  scan_id: 'history-image', user_id: 'preview-user', library_id: 'default',
  source_kind: 'file', source_name: '历史表格.png', source_path: 'history/source.png',
  source_url: '', size: 28, ocr_enabled: true, online_enabled: false,
  parser_engine: 'local', parser_fallback_reason: '', status: 'finished',
  stage: 'completed', stage_label: '解析完成', progress: 100,
  no_ocr_markdown: '', ocr_markdown: '', assets: [], error: '', source_text: null,
  created_at: '2026-10-02T06:00:00Z', updated_at: '2026-10-02T06:01:00Z',
  finished_at: '2026-10-02T06:01:00Z', ocr_preview_path: 'history/ocr.png',
}

/** Stub unrelated editor controls while exposing the original preview payload. */
function mountResult() {
  return mount(ScannerResultPanel, {
    props: { record: { ...record } },
    global: { stubs: {
      IcIcon: true, CodeEditor: true, CodePreview: true, EditorPaneToolbar: true,
      MarkdownPreview: true,
      MultimodalPreview: { name: 'MultimodalPreview', props: ['preview'], template: '<div>{{ preview?.path }}</div>' },
    } },
  })
}

let wrapper: ReturnType<typeof mountResult> | undefined
afterEach(() => { wrapper?.unmount(); vi.clearAllMocks() })

describe('scanner original preview', () => {
  it('retains the loaded preview across unchanged history polling responses', async () => {
    vi.mocked(previewKnowledgeFile).mockResolvedValue({ kind: 'image', path: record.ocr_preview_path!, mtime: '', size: 0, extension: '.png', readonly: true })
    wrapper = mountResult()
    await flushPromises()
    expect(previewKnowledgeFile).toHaveBeenCalledTimes(1)
    const preview = wrapper.findComponent({ name: 'MultimodalPreview' })
    const payload = preview.props('preview')
    for (let poll = 0; poll < 3; poll++) {
      await wrapper.setProps({ record: { ...record } })
      await flushPromises()
      expect(previewKnowledgeFile).toHaveBeenCalledTimes(1)
      expect(preview.props('preview')).toBe(payload)
    }
  })

  it('reloads when the OCR preview path or selected variant changes', async () => {
    vi.mocked(previewKnowledgeFile).mockResolvedValue({ kind: 'image', path: record.ocr_preview_path!, mtime: '', size: 0, extension: '.png', readonly: true })
    wrapper = mountResult()
    await flushPromises()
    await wrapper.setProps({ record: { ...record, ocr_preview_path: 'history/new-ocr.png' } })
    await flushPromises()
    expect(previewKnowledgeFile).toHaveBeenLastCalledWith('preview-user', 'history/new-ocr.png')
    await wrapper.get('.scanner-variant-switch button:last-child').trigger('click')
    await flushPromises()
    expect(previewKnowledgeFile).toHaveBeenLastCalledWith('preview-user', record.source_path)
  })
})
