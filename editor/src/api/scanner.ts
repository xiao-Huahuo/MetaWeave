/*
 * Scanner API client.
 *
 * Creates real file/URL tasks, persists editable drafts, saves results to the
 * knowledge library, and retrieves binary export payloads.
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPostForm, buildApiUrl } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

export type ScannerVariant = 'ocr' | 'no_ocr'
export type ScannerConflictStrategy = 'overwrite' | 'skip' | 'rename'

export interface ScannerOcrBlock {
  page: number
  type: string
  content: string
  bbox: number[]
  id: string | number | null
  order: number
  page_width?: number
  page_height?: number
}

export interface ScannerRecord {
  scan_id: string
  user_id: string
  library_id: string
  source_kind: string
  source_name: string
  source_path: string
  source_url: string
  size: number
  ocr_enabled: boolean
  online_enabled: boolean
  parser_engine: 'pending' | 'mineru' | 'local' | 'local-web'
  parser_fallback_reason: string
  status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'finished' | 'failed'
  stage: string
  stage_label: string
  progress: number
  no_ocr_markdown: string
  ocr_markdown: string
  ocr_blocks?: ScannerOcrBlock[]
  ocr_preview_path?: string
  assets: string[]
  error: string
  source_text: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

/** Persistent scanner records plus the normalized backend scheduler capacity. */
export interface ScannerListResponse {
  scans: ScannerRecord[]
  max_concurrency: number
}

/** Upload one selected or dropped file without restricting its extension. */
export function createFileScan(userId: string, file: File, ocrEnabled: boolean, onlineEnabled: boolean, sourceKind = 'file'): Promise<ScannerRecord> {
  const form = new FormData()
  form.set('user_id', userId)
  form.set('ocr_enabled', String(ocrEnabled))
  form.set('online_enabled', String(onlineEnabled))
  form.set('source_kind', sourceKind)
  form.set('file', file)
  return apiPostForm<ScannerRecord>(API_ROUTES.SCANNER_FILES, form)
}

/** Crawl one public webpage into a managed Markdown scanner record. */
export function createUrlScan(userId: string, url: string, ocrEnabled: boolean, onlineEnabled: boolean): Promise<ScannerRecord> {
  return apiPost<ScannerRecord>(API_ROUTES.SCANNER_URLS, { user_id: userId, url, ocr_enabled: ocrEnabled, online_enabled: onlineEnabled })
}

/** List scanner history in the active knowledge library. */
export function listScans(userId: string): Promise<ScannerListResponse> {
  return apiGet(API_ROUTES.SCANNER, { user_id: userId })
}

/** Load one scanner record including both editable Markdown drafts. */
export function getScan(userId: string, scanId: string): Promise<ScannerRecord> {
  return apiGet(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}`, { user_id: userId })
}

/** Persist one OCR or no-OCR Markdown draft. */
export function updateScanDraft(userId: string, scanId: string, variant: ScannerVariant, content: string): Promise<ScannerRecord> {
  return apiPatch(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}/draft`, { user_id: userId, variant, content })
}

/** Persist edits to a text original stored in the managed scanner directory. */
export function updateScanSource(userId: string, scanId: string, content: string): Promise<ScannerRecord> {
  return apiPatch(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}/source`, { user_id: userId, content })
}

/** Hard-stop one queued or running scanner task without affecting siblings. */
export function cancelScan(userId: string, scanId: string): Promise<ScannerRecord> {
  return apiPost(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}/cancel`, { user_id: userId })
}

/** Save one scanner projection into the active knowledge library. */
export function saveScanToKnowledge(userId: string, scanId: string, variant: ScannerVariant, conflictStrategy: ScannerConflictStrategy): Promise<{ ok: boolean; path: string; assets: string[] }> {
  return apiPost(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}/save`, {
    user_id: userId,
    variant,
    conflict_strategy: conflictStrategy,
  })
}

/** Download the Markdown or ZIP response as a Blob for native save-as. */
export async function fetchScanExport(userId: string, scanId: string, variant: ScannerVariant): Promise<{ filename: string; blob: Blob }> {
  const response = await fetch(buildApiUrl(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}/export`, { user_id: userId, variant }))
  if (!response.ok) throw new Error(`导出失败 (${response.status})`)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  return { filename: encodedName ? decodeURIComponent(encodedName) : `scanner.${variant === 'ocr' ? 'md' : 'zip'}`, blob: await response.blob() }
}

/** Request one server-built ZIP containing every selected scanner projection. */
export async function fetchScanBatchExport(userId: string, items: Array<{ scan_id: string; variant: ScannerVariant }>): Promise<{ filename: string; blob: Blob }> {
  const response = await fetch(buildApiUrl(`${API_ROUTES.SCANNER}/export-batch`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, items }),
  })
  if (!response.ok) throw new Error(`批量导出失败 (${response.status})`)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  return { filename: encodedName ? decodeURIComponent(encodedName) : 'scanner-batch.zip', blob: await response.blob() }
}

/** Permanently delete one terminal scanner record and its managed artifacts. */
export function deleteScan(userId: string, scanId: string): Promise<{ ok: boolean; deleted: boolean }> {
  return apiDelete(`${API_ROUTES.SCANNER}/${encodeURIComponent(scanId)}`, { user_id: userId })
}
