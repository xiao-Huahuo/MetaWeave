/**
 * Shared scanner record actions.
 *
 * Keeps queue cards and the full scanner result page on the same persisted
 * favorite, source reveal, knowledge save, export, and clipboard behavior.
 */
import { fetchScanBatchExport, fetchScanExport, saveScanToKnowledge, type ScannerRecord, type ScannerVariant } from '@/api/scanner'
import { useFavoritesStore } from '@/stores/favorites'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

/** Choose the same useful result variant for cards that do not expose a variant switch. */
export function preferredScannerVariant(record: ScannerRecord): ScannerVariant {
  return record.ocr_enabled && Boolean(record.ocr_markdown) ? 'ocr' : 'no_ocr'
}

/** Return the Markdown represented by a scanner card's preferred variant. */
export function preferredScannerMarkdown(record: ScannerRecord): string {
  return preferredScannerVariant(record) === 'ocr' ? record.ocr_markdown : record.no_ocr_markdown
}

/** Provide the five scanner actions and the combined ZIP export to any scanner surface. */
export function useScannerRecordActions() {
  const settingsStore = useSettingsStore()
  const workspaceStore = useWorkspaceStore()
  const favoritesStore = useFavoritesStore()

  /** Reveal one managed original source in the operating-system file manager. */
  async function revealSource(record: ScannerRecord): Promise<void> {
    if (!record.source_path) return
    const separator = window.agentEditorDesktop?.platform === 'win32' ? '\\' : '/'
    const root = settingsStore.profile.knowledgeDir.replace(/[\\/]+$/u, '')
    await window.agentEditorDesktop?.showItemInFolder?.(`${root}${separator}${record.source_path.replace(/\//gu, separator)}`)
  }

  /** Toggle one scanner favorite through the shared backend-persisted store. */
  async function toggleFavorite(record: ScannerRecord): Promise<void> {
    try {
      await favoritesStore.toggle('scanner', record.scan_id, record.library_id)
      workspaceStore.showToast(favoritesStore.isFavorite('scanner', record.scan_id, record.library_id) ? '已收藏' : '已取消收藏')
    } catch (error) {
      workspaceStore.showToast(error instanceof Error ? error.message : '收藏操作失败', 5000)
    }
  }

  /** Save one selected Markdown projection after the existing conflict flow resolves. */
  async function saveToKnowledge(record: ScannerRecord, variant: ScannerVariant, notify = true): Promise<boolean> {
    try {
      await workspaceStore.loadKnowledgeTree()
      const filename = `${record.source_name.replace(/\.[^.]+$/u, '')}.md`
      const strategy = await workspaceStore.promptConflictStrategy('', [filename], 'scanner')
      if (!strategy) return false
      const result = await saveScanToKnowledge(settingsStore.profile.userId, record.scan_id, variant, strategy)
      await workspaceStore.loadKnowledgeTree()
      if (notify) workspaceStore.showToast(`已保存到 ${result.path}`)
      return true
    } catch (error) {
      workspaceStore.showToast(error instanceof Error ? error.message : '保存失败', 5000)
      return false
    }
  }

  /** Send one Blob through the desktop save dialog or browser download fallback. */
  async function downloadBlob(filename: string, blob: Blob): Promise<void> {
    if (window.agentEditorDesktop?.saveFileAs) {
      const saved = await window.agentEditorDesktop.saveFileAs({ filename, data: await blob.arrayBuffer() })
      if (saved) workspaceStore.showToast(`已导出到 ${saved}`)
      return
    }
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
    workspaceStore.showToast('已开始下载')
  }

  /** Export one scanner projection using the existing backend package contract. */
  async function exportOutside(record: ScannerRecord, variant: ScannerVariant): Promise<void> {
    try {
      const result = await fetchScanExport(settingsStore.profile.userId, record.scan_id, variant)
      await downloadBlob(result.filename, result.blob)
    } catch (error) {
      workspaceStore.showToast(error instanceof Error ? error.message : '导出失败', 5000)
    }
  }

  /** Export all records into the one ZIP returned by the scanner backend. */
  async function exportBatchOutside(records: ScannerRecord[]): Promise<void> {
    if (!records.length) return
    try {
      const result = await fetchScanBatchExport(settingsStore.profile.userId, records.map(record => ({
        scan_id: record.scan_id,
        variant: preferredScannerVariant(record),
      })))
      await downloadBlob(result.filename, result.blob)
    } catch (error) {
      workspaceStore.showToast(error instanceof Error ? error.message : '批量导出失败', 5000)
    }
  }

  /** Copy scanner text through the desktop bridge or secure browser clipboard. */
  async function copyText(value: string, label: string): Promise<void> {
    try {
      if (window.agentEditorDesktop?.writeClipboardText) await window.agentEditorDesktop.writeClipboardText(value)
      else await navigator.clipboard.writeText(value)
      workspaceStore.showToast(`已复制${label}`)
    } catch (error) {
      workspaceStore.showToast(error instanceof Error ? error.message : `复制${label}失败`, 5000)
    }
  }

  return { favoritesStore, revealSource, toggleFavorite, saveToKnowledge, exportOutside, exportBatchOutside, copyText }
}
