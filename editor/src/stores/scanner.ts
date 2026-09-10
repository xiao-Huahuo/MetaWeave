/*
 * Scanner page state.
 *
 * Keeps a frontend cache only; all history, task state, and editable drafts are
 * persisted by the scanner backend API.
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  cancelScan,
  createFileScan,
  createUrlScan,
  deleteScan,
  getScan,
  listScans,
  updateScanDraft,
  updateScanSource,
  type ScannerRecord,
  type ScannerVariant,
} from '@/api/scanner'
import { useSettingsStore } from '@/stores/settings'

export const useScannerStore = defineStore('scanner', () => {
  const records = ref<ScannerRecord[]>([])
  const activeId = ref('')
  const loading = ref(false)
  const actionError = ref('')
  const maxConcurrency = ref(1)
  const active = computed(() => records.value.find((record) => record.scan_id === activeId.value) ?? null)
  const hasRunning = computed(() => records.value.some((record) => record.status === 'queued' || record.status === 'running'))

  /** Return the current user id shared by all scanner API calls. */
  function userId(): string {
    return useSettingsStore().profile.userId
  }

  /** Insert or replace one record while preserving chronological order. */
  function upsert(record: ScannerRecord): void {
    const next = records.value.filter((item) => item.scan_id !== record.scan_id)
    records.value = [record, ...next].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  }

  /** Refresh all current-library scanner history from the backend. */
  async function load(): Promise<void> {
    if (!userId()) return
    loading.value = true
    try {
      const previous = new Map(records.value.map((record) => [record.scan_id, record]))
      const response = await listScans(userId())
      maxConcurrency.value = Math.max(1, response.max_concurrency || 1)
      records.value = response.scans.map((record) => {
        const cached = previous.get(record.scan_id)
        if (!cached) return record
        return {
          ...record,
          no_ocr_markdown: record.no_ocr_markdown || cached.no_ocr_markdown,
          ocr_markdown: record.ocr_markdown || cached.ocr_markdown,
          source_text: record.source_text ?? cached.source_text,
        }
      })
    } finally {
      loading.value = false
    }
  }

  /** Create and select a real uploaded-file scanner task. */
  async function upload(file: File, ocrEnabled: boolean, sourceKind = 'file'): Promise<void> {
    actionError.value = ''
    const record = await createFileScan(userId(), file, ocrEnabled, sourceKind)
    upsert(record)
    activeId.value = record.scan_id
  }

  /** Create and select a real webpage scanner task. */
  async function crawl(url: string, ocrEnabled: boolean): Promise<void> {
    actionError.value = ''
    const record = await createUrlScan(userId(), url, ocrEnabled)
    upsert(record)
    activeId.value = record.scan_id
  }

  /** Reload a selected task so progress and terminal drafts stay current. */
  async function refreshActive(): Promise<void> {
    if (!activeId.value || !userId()) return
    upsert(await getScan(userId(), activeId.value))
  }

  /** Persist one Markdown variant and update the local record. */
  async function saveDraft(variant: ScannerVariant, content: string, scanId = activeId.value): Promise<void> {
    if (!scanId) return
    upsert(await updateScanDraft(userId(), scanId, variant, content))
  }

  /** Persist edits to a text original without changing parsed drafts. */
  async function saveSource(content: string, scanId = activeId.value): Promise<void> {
    if (!scanId) return
    upsert(await updateScanSource(userId(), scanId, content))
  }

  /** Permanently remove one terminal scanner history record. */
  async function remove(scanId: string): Promise<void> {
    await deleteScan(userId(), scanId)
    records.value = records.value.filter((record) => record.scan_id !== scanId)
    if (activeId.value === scanId) activeId.value = ''
  }

  /** Immediately terminate one task through its backend-owned process handle. */
  async function cancel(scanId: string): Promise<void> {
    actionError.value = ''
    upsert(await cancelScan(userId(), scanId))
  }

  return {
    records,
    activeId,
    active,
    loading,
    actionError,
    maxConcurrency,
    hasRunning,
    load,
    upload,
    crawl,
    refreshActive,
    saveDraft,
    saveSource,
    remove,
    cancel,
    upsert,
  }
})
