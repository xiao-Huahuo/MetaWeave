/**
 * Scanner experience contract tests.
 *
 * Guards the scanner against drifting from the shared Agent, library, resource
 * manager, and editor interaction patterns requested by the product surface.
 */
import { describe, expect, it } from 'vitest'

import activityBarSource from '@/components/editor_workspace/ActivityBar.vue?raw'
import historySource from '@/components/scanner_view/ScannerHistoryList.vue?raw'
import resultSource from '@/components/scanner_view/ScannerResultPanel.vue?raw'
import uploadSource from '@/components/scanner_view/ScannerUploadPanel.vue?raw'
import scannerViewSource from '@/views/ScannerView.vue?raw'

describe('scanner experience contracts', () => {
  it('places the scanner directly after Agent with a scan-specific icon', () => {
    expect(activityBarSource).toMatch(/title="Agent"[\s\S]*?title="扫描器"/u)
    expect(activityBarSource).toContain('<IcIcon name="center-focus" :size="18" />')
  })

  it('matches the Agent drawer shell and provides matching collapse controls', () => {
    expect(scannerViewSource).toContain('<h1>扫描器</h1>')
    expect(scannerViewSource).toContain('<IcIcon name="cloud-upload" :size="16" />')
    expect(scannerViewSource).not.toContain('.scanner-new-button:hover { border-color: var(--color-accent)')
    expect(scannerViewSource).toContain('class="scanner-collapse-button"')
    expect(scannerViewSource).toContain('class="scanner-expand-button"')
    expect(scannerViewSource).toContain("border-radius: var(--workspace-card-radius)")
    expect(scannerViewSource).toContain('transform: translateX(calc(-100% + 10px))')
  })

  it('opens the native picker from the whole upload surface and never scrolls the upload page', () => {
    expect(uploadSource).toContain('@click="openPicker"')
    expect(uploadSource).toContain('拖拽或上传')
    expect(uploadSource).toContain('overflow: hidden')
    expect(uploadSource).not.toContain('.scanner-start { position: absolute; inset: 0; box-sizing: border-box; display: grid; align-content: start;')
  })

  it('uses the shared library form surface and a clipped responsive carousel', () => {
    expect(uploadSource).toContain('library-form-surface')
    expect(uploadSource).toContain('form-input-surface')
    expect(uploadSource).toContain('class="scanner-example-viewport"')
    expect(uploadSource).toContain('overflow: hidden')
    expect(uploadSource).not.toContain('overflow-x: auto')
  })

  it('stages history records and centers the empty state', () => {
    expect(historySource).toContain("'--history-index': index")
    expect(historySource).toContain('animation-delay: calc(var(--history-index) * 55ms)')
    expect(historySource).toContain("'is-empty': visibleRecords.length === 0")
  })

  it('places a red square stop action on each active history task', () => {
    expect(historySource).toContain('class="scanner-stop-button"')
    expect(historySource).toContain("emit('cancel', record)")
    expect(historySource).toContain('<IcIcon name="stop"')
    expect(historySource).toContain('background: var(--color-danger)')
    expect(historySource).toContain('border-radius: 50%')
  })

  it('reuses editor mode switches on both panes and moves OCR to the page toolbar', () => {
    expect(resultSource.match(/<EditorPaneToolbar/gu)).toHaveLength(2)
    expect(resultSource).toContain('settings-resource-page-switch')
    expect(resultSource).toContain('class="scanner-pane-divider"')
    expect(resultSource).toContain('@pointerdown="startPaneResize"')
    expect(resultSource).toContain('min-height: 44px')
    expect(resultSource).toContain('.scanner-variant-switch .settings-resource-page-button:hover { background: transparent !important; box-shadow: none !important; }')
  })

  it('renders OCR blocks only inside left or right preview surfaces', () => {
    expect(resultSource).toContain(`:blocks="sourceViewMode === 'preview' ? sourceOverlayBlocks : []"`)
    expect(resultSource).toContain(`v-if="viewMode === 'preview' || viewMode === 'split'"`)
    expect(resultSource).toContain(':blocks="previewBlocks"')
    expect(resultSource).not.toContain('<CodeEditor v-if="viewMode === \'edit\'" :blocks=')
  })

  it('uses the OCR-preprocessed image whenever source overlay boxes are visible', () => {
    expect(resultSource).toContain('const sourceOverlayBlocks = computed(() => props.record.ocr_preview_path ? previewBlocks.value : [])')
    expect(resultSource).toContain("variant.value === 'ocr' && props.record.ocr_preview_path")
    expect(resultSource).toContain("watch(() => [props.record.scan_id, variant.value]")
  })

  it('shows backend stage text and one-decimal progress without inventing client progress', () => {
    expect(uploadSource).toContain('{{ formatProgress(running.progress) }}%')
    expect(uploadSource).toContain('{{ running.stage_label }}')
    expect(uploadSource).not.toContain('setInterval(() => running.progress')
  })
})
