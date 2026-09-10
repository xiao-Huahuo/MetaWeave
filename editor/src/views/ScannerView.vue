<!--
  Scanner page.

  Composes the persistent recent-history rail, upload/examples surface,
  progress state, and reusable split result editor.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import ScannerHistoryList from '@/components/scanner_view/ScannerHistoryList.vue'
import ScannerResultPanel from '@/components/scanner_view/ScannerResultPanel.vue'
import ScannerUploadPanel from '@/components/scanner_view/ScannerUploadPanel.vue'
import { useScannerStore } from '@/stores/scanner'
import { useSettingsStore } from '@/stores/settings'
import type { ScannerRecord } from '@/api/scanner'

defineOptions({ name: 'ScannerView' })

const scannerStore = useScannerStore()
const settingsStore = useSettingsStore()
const ocrEnabled = ref(true)
const submitting = ref(false)
const historyOpen = ref(window.innerWidth > 820)
const railPicker = ref<HTMLInputElement | null>(null)
const narrowLayout = window.matchMedia('(max-width: 820px)')
let pollTimer: number | null = null

const running = computed(() => {
  const active = scannerStore.active
  return active && (active.status === 'queued' || active.status === 'running') ? active : null
})
const finished = computed(() => scannerStore.active?.status === 'finished' ? scannerStore.active : null)
const failed = computed(() => scannerStore.active?.status === 'failed' ? scannerStore.active : null)

/** Resolve the absolute managed source path for native reveal actions. */
function absoluteSourcePath(record: ScannerRecord): string {
  const separator = window.agentEditorDesktop?.platform === 'win32' ? '\\' : '/'
  const root = settingsStore.profile.knowledgeDir.replace(/[\\/]+$/u, '')
  return `${root}${separator}${record.source_path.replace(/\//gu, separator)}`
}

/** Select any terminal or running record and refresh its latest detail. */
async function selectRecord(record: ScannerRecord): Promise<void> {
  scannerStore.activeId = record.scan_id
  await scannerStore.refreshActive()
}

/** Submit one file/example through the shared real backend task flow. */
async function upload(file: File, sourceKind = 'file'): Promise<void> {
  submitting.value = true
  scannerStore.actionError = ''
  try {
    await scannerStore.upload(file, ocrEnabled.value, sourceKind)
  } catch (error) {
    scannerStore.actionError = error instanceof Error ? error.message : '上传失败'
  } finally {
    submitting.value = false
  }
}

/** Open the system picker from the left-rail upload action. */
function openRailPicker(): void {
  scannerStore.activeId = ''
  railPicker.value?.click()
}

/** Forward a file selected from the left rail into the shared upload flow. */
function onRailPick(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void upload(file)
  input.value = ''
}

/** Submit one webpage URL through the scanner crawler. */
async function crawl(url: string): Promise<void> {
  submitting.value = true
  scannerStore.actionError = ''
  try {
    await scannerStore.crawl(url, ocrEnabled.value)
  } catch (error) {
    scannerStore.actionError = error instanceof Error ? error.message : '网页解析失败'
  } finally {
    submitting.value = false
  }
}

/** Reveal the managed source copy in the operating-system file manager. */
async function reveal(record: ScannerRecord): Promise<void> {
  if (record.source_path) await window.agentEditorDesktop?.showItemInFolder?.(absoluteSourcePath(record))
}

/** Confirm and permanently delete one history record plus managed artifacts. */
async function remove(record: ScannerRecord): Promise<void> {
  if (!window.confirm(`删除“${record.source_name}”的扫描历史和受管文件？此操作无法撤销。`)) return
  try {
    await scannerStore.remove(record.scan_id)
  } catch (error) {
    scannerStore.actionError = error instanceof Error ? error.message : '删除失败'
  }
}

/** Immediately terminate one queued or running task without confirmation delay. */
async function cancel(record: ScannerRecord): Promise<void> {
  try {
    await scannerStore.cancel(record.scan_id)
  } catch (error) {
    scannerStore.actionError = error instanceof Error ? error.message : '终止失败'
  }
}

/** Poll only while at least one scanner task remains active. */
async function poll(): Promise<void> {
  if (!scannerStore.hasRunning) return
  await scannerStore.load()
  if (scannerStore.activeId) await scannerStore.refreshActive()
}

/** Keep a desktop-open history rail from covering content after crossing into mobile. */
function handleNarrowLayout(event: MediaQueryListEvent | MediaQueryList): void {
  if (event.matches) historyOpen.value = false
}

onMounted(async () => {
  narrowLayout.addEventListener('change', handleNarrowLayout)
  handleNarrowLayout(narrowLayout)
  await scannerStore.load()
  pollTimer = window.setInterval(() => { void poll().catch(() => undefined) }, 500)
})
onBeforeUnmount(() => {
  narrowLayout.removeEventListener('change', handleNarrowLayout)
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="scanner-view" :class="{ 'history-open': historyOpen }">
    <aside class="scanner-history-rail" :class="{ open: historyOpen }">
      <header class="scanner-rail-titlebar">
        <h1>扫描器</h1>
        <button class="scanner-collapse-button" type="button" title="收起侧边栏" aria-label="收起侧边栏" @click="historyOpen = false">
          <IcIcon name="arrow-left" :size="18" />
        </button>
      </header>
      <button class="scanner-new-button" type="button" :disabled="submitting" @click="openRailPicker">
        <IcIcon name="cloud-upload" :size="16" /><span>上传解析</span>
      </button>
      <input ref="railPicker" hidden type="file" @change="onRailPick" />
      <h2>最近解析</h2>
      <ScannerHistoryList
        :records="scannerStore.records"
        :active-id="scannerStore.activeId"
        @select="selectRecord"
        @reveal="reveal"
        @remove="remove"
        @cancel="cancel"
      />
    </aside>

    <main class="scanner-main">
      <button v-if="!historyOpen" class="scanner-expand-button" type="button" title="展开侧边栏" aria-label="展开侧边栏" @click="historyOpen = true">
        <IcIcon name="arrow-right" :size="18" />
      </button>
      <ScannerResultPanel v-if="finished" :key="finished.scan_id" :record="finished" @back="scannerStore.activeId = ''" @updated="scannerStore.upsert" />
      <section v-else-if="failed" class="scanner-failed">
        <IcIcon name="error-outline" :size="34" />
        <strong>解析失败</strong>
        <p>{{ failed.error }}</p>
        <button type="button" @click="scannerStore.activeId = ''">返回上传</button>
      </section>
      <ScannerUploadPanel v-else v-model:ocr-enabled="ocrEnabled" :running="running" @upload="upload" @crawl="crawl" />
      <p v-if="scannerStore.actionError" class="scanner-error">{{ scannerStore.actionError }}</p>
    </main>
  </section>
</template>

<style scoped>
.scanner-view { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; background: var(--color-bg-app); color: var(--color-text); font-family: var(--font-ui); }
.scanner-history-rail { position: absolute; top: 0; bottom: 0; left: 0; z-index: 4; display: grid; grid-template-rows: 64px auto auto minmax(0,1fr); width: 280px; max-width: min(280px,80vw); min-width: 0; min-height: 0; overflow: hidden; border: 0; border-radius: var(--workspace-card-radius); background: var(--color-chrome-rail-bg); opacity: 0; pointer-events: none; transform: translateX(calc(-100% + 10px)); transition: transform 200ms ease, opacity 160ms ease; }
.scanner-history-rail.open { opacity: 1; pointer-events: auto; transform: translateX(0); }
.scanner-rail-titlebar { display: flex; min-width: 0; min-height: 64px; align-items: center; justify-content: space-between; gap: var(--space-8); padding: 0 var(--space-20); }
.scanner-rail-titlebar h1 { margin: 0; overflow: hidden; color: var(--color-text-primary); font-size: calc(15px * var(--font-scale)); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.scanner-collapse-button,.scanner-expand-button { display: inline-flex; width: 28px; height: 28px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--color-text-secondary); cursor: pointer; transition: background var(--transition-fast), color var(--transition-fast); }
.scanner-collapse-button:hover,.scanner-expand-button:hover { background: var(--color-selection-blue-soft); color: var(--color-selection-blue); }
.scanner-expand-button { position: absolute; top: 12px; left: 12px; z-index: 3; }
.scanner-new-button { display: flex; width: calc(100% - 16px); min-height: 36px; align-items: center; justify-self: center; justify-content: center; gap: var(--space-6); margin: 0 0 var(--space-14); padding: 0 var(--space-12); border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-surface-raised); color: var(--color-text-primary); font: inherit; font-size: calc(13px * var(--font-scale)); font-weight: 600; transition: border-color 180ms ease, background 180ms ease, color 180ms ease, transform 180ms ease; }
.scanner-new-button:hover { border-color: var(--color-primary); background: var(--color-primary-softer); color: var(--color-primary); }
.scanner-new-button:active { transform: scale(.98); }
.scanner-history-rail > h2 { margin: 0 var(--space-20) var(--space-8); color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); font-weight: 650; }
.scanner-main { position: relative; height: 100%; min-width: 0; min-height: 0; margin-left: 0; overflow: hidden; border-radius: var(--workspace-card-radius); transition: margin-left 200ms ease; }
.scanner-view.history-open .scanner-main { margin-left: 280px; }
.scanner-main:has(.scanner-expand-button) :deep(.scanner-drop-title) { left: 54px; }
.scanner-main:has(.scanner-expand-button) :deep(.scanner-result-toolbar) { padding-left: 52px; }
.scanner-error { position: absolute; right: 18px; bottom: 18px; z-index: 10; max-width: min(520px,calc(100% - 36px)); margin: 0; padding: 9px 12px; border: 1px solid color-mix(in srgb,var(--color-danger) 45%,var(--color-border)); border-radius: 8px; background: var(--color-surface); color: var(--color-danger); font-size: calc(11px * var(--font-scale)); }
.scanner-failed { display: grid; place-items: center; align-content: center; min-height: 100%; padding: 24px; text-align: center; }
.scanner-failed :deep(svg) { color: var(--color-danger); }
.scanner-failed strong { margin-top: 12px; }
.scanner-failed p { max-width: 560px; color: var(--color-text-muted); font-size: calc(12px * var(--font-scale)); }
.scanner-failed button { min-height: 34px; padding: 0 14px; border: 0; border-radius: 8px; background: var(--color-primary); color: white; }
@media (max-width: 820px) { .scanner-view.history-open .scanner-main { margin-left: 0; } }
@media (prefers-reduced-motion: reduce) { .scanner-history-rail,.scanner-main,.scanner-new-button { transition: none; } }
</style>
