/** Batch scanner form, card, and shared-shell interaction contracts. */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ScannerRecord } from '@/api/scanner'
import BatchScannerTaskCard from '@/components/batch_scanner/BatchScannerTaskCard.vue'
import ScannerUploadPanel from '@/components/scanner_view/ScannerUploadPanel.vue'
import agentQueueSource from '@/views/AgentQueueView.vue?raw'
import batchScannerSource from '@/views/BatchScannerView.vue?raw'
import agentCardSource from '@/components/agent_queue/AgentQueueTaskCard.vue?raw'
import batchCardSource from '@/components/batch_scanner/BatchScannerTaskCard.vue?raw'
import batchDialogSource from '@/components/batch_scanner/BatchScannerTaskDialog.vue?raw'

/** Build one complete scanner record for card interaction checks. */
function scannerRecord(status: ScannerRecord['status'] = 'running'): ScannerRecord {
  return {
    scan_id: 'scan-1', user_id: 'u1', library_id: 'lib-1', source_kind: 'file', source_name: 'research-notes.pdf', source_path: '.mw/scan/scan-1/source/research-notes.pdf', source_url: '', size: 2048,
    ocr_enabled: true, status, stage: 'ocr', stage_label: '正在识别页面', progress: 42.6, no_ocr_markdown: '', ocr_markdown: '', assets: [], error: '', source_text: null, created_at: '2026-09-10T10:00:00Z', updated_at: '2026-09-10T10:01:00Z', finished_at: null,
  }
}

describe('batch scanner experience', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('ResizeObserver', class {
      observe(): void {}
      disconnect(): void {}
    })
  })

  it('uses the same queue board shell as the Agent task queue', () => {
    expect(agentQueueSource).toContain("import QueueBoardShell from '@/components/common/QueueBoardShell.vue'")
    expect(batchScannerSource).toContain("import QueueBoardShell from '@/components/common/QueueBoardShell.vue'")
  })

  it('renders the existing scanner upload surface instead of a batch-specific form', () => {
    expect(batchDialogSource).toContain('<ScannerUploadPanel')
    expect(batchDialogSource).not.toContain('batch-file-drop')
    expect(batchDialogSource).not.toContain('batch-source-list')
    expect(batchDialogSource).not.toContain('batch-scan-form')
  })

  it('emits every selected file from the scanner upload component batch mode', async () => {
    const wrapper = mount(ScannerUploadPanel, {
      props: { running: null, batch: true, ocrEnabled: true },
      global: { stubs: { IcIcon: true, PixelLoader: true, DropdownMenu: true, DropdownMenuContent: true, DropdownMenuItem: true, DropdownMenuPortal: true, DropdownMenuTrigger: true } },
    })
    const fileInput = wrapper.get('input[type="file"]')
    const selectedFiles = [new File(['alpha'], 'alpha.pdf'), new File(['beta'], 'beta.docx')]
    Object.defineProperty(fileInput.element, 'files', { configurable: true, value: selectedFiles })
    await fileInput.trigger('change')

    expect(wrapper.emitted('uploadBatch')?.[0]?.[0]).toEqual(selectedFiles)
  })

  it('emits newline-separated URLs from the same scanner upload component', async () => {
    const wrapper = mount(ScannerUploadPanel, {
      props: { running: null, batch: true, ocrEnabled: true },
      attachTo: document.body,
      global: { stubs: { IcIcon: true, PixelLoader: true, DropdownMenu: true, DropdownMenuContent: true, DropdownMenuItem: true, DropdownMenuPortal: true, DropdownMenuTrigger: true } },
    })
    const urlButton = wrapper.findAll('button').find(button => button.text().includes('网页链接'))
    await urlButton?.trigger('click')
    const textarea = document.body.querySelector<HTMLTextAreaElement>('.scanner-url-dialog textarea')
    const form = document.body.querySelector<HTMLFormElement>('.scanner-url-dialog')
    expect(textarea).not.toBeNull()
    expect(form).not.toBeNull()
    if (textarea && form) {
      textarea.value = 'https://example.com/a\nhttps://example.com/b'
      textarea.dispatchEvent(new Event('input', { bubbles: true }))
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await wrapper.vm.$nextTick()
    }

    expect(wrapper.emitted('crawlBatch')?.[0]?.[0]).toEqual(['https://example.com/a', 'https://example.com/b'])
    wrapper.unmount()
  })

  it('uses coordinated 20px task-card radii inside both 28px queue shells', () => {
    expect(agentCardSource).toMatch(/\.queue-task-card \{[^}]*border-radius:20px;/s)
    expect(batchCardSource).toMatch(/\.queue-task-card \{[^}]*border-radius:20px;/s)
  })

  it('exposes real progress and single-record cancellation from a running card', async () => {
    const record = scannerRecord()
    const wrapper = mount(BatchScannerTaskCard, { props: { record }, global: { stubs: { IcIcon: true } } })

    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('42.6')
    await wrapper.get('[aria-label="终止扫描"]').trigger('click')
    expect(wrapper.emitted('cancel')?.[0]?.[0]).toEqual(record)
  })
})
