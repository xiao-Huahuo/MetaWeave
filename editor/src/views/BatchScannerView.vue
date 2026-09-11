<!--
  Persistent batch scanner queue page.

  Projects existing ScannerRecord tasks into the shared queue-board layout and
  creates every selected file or URL through the real asynchronous scanner API.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { createFileScan, createUrlScan, type ScannerRecord } from '@/api/scanner'
import BatchScannerTaskCard from '@/components/batch_scanner/BatchScannerTaskCard.vue'
import BatchScannerTaskDialog from '@/components/batch_scanner/BatchScannerTaskDialog.vue'
import { localDateKey, partitionFinishedScans } from '@/components/batch_scanner/batchScannerBuckets'
import { preferredScannerMarkdown, preferredScannerVariant, useScannerRecordActions } from '@/components/scanner_view/useScannerRecordActions'
import ScannerParsingSettingsMenu from '@/components/scanner_view/ScannerParsingSettingsMenu.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import QueueBoardShell from '@/components/common/QueueBoardShell.vue'
import { useScannerStore } from '@/stores/scanner'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

defineOptions({ name: 'BatchScannerView', inheritAttrs: false })

const scannerStore = useScannerStore()
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const scannerActions = useScannerRecordActions()
const historyMode = ref(false)
const dialogOpen = ref(false)
const selected = ref<ScannerRecord | null>(null)
const submitting = ref(false)
const submitError = ref('')
const ocrEnabled = ref(true)
const onlineEnabled = ref(Boolean(settingsStore.profile.vlmEnabled))
watch(() => settingsStore.profile.vlmEnabled, value => { onlineEnabled.value = Boolean(value) }, { immediate: true })
const handledFallbacks = new Set<string>()
watch(
  () => scannerStore.records.filter(record => record.parser_fallback_reason).map(record => `${record.scan_id}:${record.parser_fallback_reason}`),
  fallbacks => {
    const next = fallbacks.find(item => !handledFallbacks.has(item))
    if (!next) return
    handledFallbacks.add(next)
    onlineEnabled.value = false
    scannerStore.actionError = `${next.split(':').slice(1).join(':')}，后续任务已自动切换本地解析`
  },
)
const busyScanIds = ref<Set<string>>(new Set())
const batchAction = ref('')
let pollTimer: number | null = null
const currentLocalDay = ref(new Date())

const queued = computed(() => scannerStore.records.filter(record => record.status === 'queued'))
const running = computed(() => scannerStore.records.filter(record => ['running', 'cancelling'].includes(record.status)))
const finishedBuckets = computed(() => partitionFinishedScans(scannerStore.records, currentLocalDay.value))
const finished = computed(() => finishedBuckets.value.today)
const historicalFinished = computed(() => finishedBuckets.value.history)
const cancelled = computed(() => scannerStore.records.filter(record => record.status === 'cancelled'))
const failed = computed(() => scannerStore.records.filter(record => record.status === 'failed'))

/** Report whether one completed card is waiting for a save or export action. */
function isRecordBusy(record: ScannerRecord): boolean {
  return busyScanIds.value.has(record.scan_id)
}

/** Run one card action with an isolated busy marker. */
async function withRecordBusy(record: ScannerRecord, action: () => Promise<void>): Promise<void> {
  busyScanIds.value = new Set([...busyScanIds.value, record.scan_id])
  try {
    await action()
  } finally {
    const next = new Set(busyScanIds.value)
    next.delete(record.scan_id)
    busyScanIds.value = next
  }
}

/** Save one card's preferred Markdown variant into the active knowledge root. */
async function saveRecord(record: ScannerRecord): Promise<void> {
  await withRecordBusy(record, async () => { await scannerActions.saveToKnowledge(record, preferredScannerVariant(record)) })
}

/** Export one card using the same package contract as the full scanner page. */
async function exportRecord(record: ScannerRecord): Promise<void> {
  await withRecordBusy(record, async () => { await scannerActions.exportOutside(record, preferredScannerVariant(record)) })
}

/** Save today's completed records one Markdown projection at a time. */
async function saveCompletedBatch(): Promise<void> {
  if (!finished.value.length || batchAction.value) return
  batchAction.value = 'save'
  let saved = 0
  try {
    for (const record of finished.value) {
      if (await scannerActions.saveToKnowledge(record, preferredScannerVariant(record), false)) saved += 1
    }
    workspaceStore.showToast(`批量保存完成：${saved}/${finished.value.length}`)
  } finally {
    batchAction.value = ''
  }
}

/** Export today's completed records as the one server-built ZIP. */
async function exportCompletedBatch(): Promise<void> {
  if (!finished.value.length || batchAction.value) return
  batchAction.value = 'export'
  try {
    await scannerActions.exportBatchOutside(finished.value)
  } finally {
    batchAction.value = ''
  }
}

/** Open a clean batch form without replacing any persistent scanner state. */
function openNew(): void {
  selected.value = null
  submitError.value = ''
  dialogOpen.value = true
}

/** Open the selected record and bind the existing result editor to its id. */
function openRecord(record: ScannerRecord): void {
  scannerStore.activeId = record.scan_id
  selected.value = record
  dialogOpen.value = true
}

/** Close either form or detail surface while keeping all scanner tasks alive. */
function closeDialog(): void {
  dialogOpen.value = false
  selected.value = null
}

/** Create one durable scanner task per source; individual submission failures do not block siblings. */
async function createBatch(files: File[], urls: string[], taskOcrEnabled: boolean, taskOnlineEnabled: boolean): Promise<void> {
  if (!files.length && !urls.length) return
  submitting.value = true
  submitError.value = ''
  scannerStore.actionError = ''
  const failures: string[] = []
  let createdCount = 0
  try {
    for (const file of files) {
      try {
        scannerStore.upsert(await createFileScan(settingsStore.profile.userId, file, taskOcrEnabled, taskOnlineEnabled))
        createdCount += 1
      } catch {
        failures.push(file.name)
      }
    }
    for (const url of urls) {
      try {
        scannerStore.upsert(await createUrlScan(settingsStore.profile.userId, url, taskOcrEnabled, taskOnlineEnabled))
        createdCount += 1
      } catch {
        failures.push(url)
      }
    }
    const failureMessage = failures.length ? `${failures.length} 项未能创建：${failures.join('、')}` : ''
    if (createdCount) {
      closeDialog()
      scannerStore.actionError = failureMessage
    } else {
      submitError.value = failureMessage
    }
    await scannerStore.load()
  } finally {
    submitting.value = false
  }
}

/** Cancel exactly one queued or running scanner process through its backend owner. */
async function cancel(record: ScannerRecord): Promise<void> {
  await scannerStore.cancel(record.scan_id)
  if (selected.value?.scan_id === record.scan_id) selected.value = scannerStore.records.find(item => item.scan_id === record.scan_id) ?? record
}

/** Remove one terminal scanner record and close a matching detail dialog. */
async function remove(record: ScannerRecord): Promise<void> {
  if (!window.confirm(`删除“${record.source_name}”的扫描记录和受管文件？此操作无法撤销。`)) return
  await scannerStore.remove(record.scan_id)
  if (selected.value?.scan_id === record.scan_id) closeDialog()
}

/** Merge edits emitted by the shared result panel into both card and dialog state. */
function updateRecord(record: ScannerRecord): void {
  scannerStore.upsert(record)
  if (selected.value?.scan_id === record.scan_id) selected.value = record
}

/** Refresh persistent records only while backend work can still change them. */
async function poll(): Promise<void> {
  const now = new Date()
  if (localDateKey(now) !== localDateKey(currentLocalDay.value)) currentLocalDay.value = now
  if (!scannerStore.hasRunning) return
  await scannerStore.load()
  if (selected.value) selected.value = scannerStore.records.find(record => record.scan_id === selected.value?.scan_id) ?? selected.value
}

onMounted(async () => {
  await scannerStore.load()
  await scannerActions.favoritesStore.load(settingsStore.profile.userId, 'scanner')
  pollTimer = window.setInterval(() => { void poll().catch(() => undefined) }, 500)
})
onBeforeUnmount(() => { if (pollTimer !== null) window.clearInterval(pollTimer) })
</script>

<template>
  <QueueBoardShell
    v-bind="$attrs"
    :history-mode="historyMode"
    board-label="扫描看板"
    new-label="新建批量扫描"
    :concurrency="String(scannerStore.maxConcurrency)"
    :history-columns="3"
    @switch-page="historyMode = $event"
    @new-task="openNew"
  >
    <template #toolbar-actions>
      <ScannerParsingSettingsMenu v-model:ocr-enabled="ocrEnabled" v-model:online-enabled="onlineEnabled" placement="toolbar" @error="scannerStore.actionError = $event" />
    </template>
    <template #board>
      <div class="queue-lane">
        <h2 class="queue-column-title pending">等待扫描 <small>{{ queued.length }}</small></h2>
        <section><TransitionGroup name="queue-card" tag="div" class="queue-column"><BatchScannerTaskCard v-for="record in queued" :key="record.scan_id" :record="record" @select="openRecord" @cancel="cancel" @remove="remove" /><p v-if="!queued.length" class="queue-empty">没有等待中的任务</p></TransitionGroup></section>
      </div>
      <div class="queue-lane">
        <h2 class="queue-column-title running">扫描中 <small>{{ running.length }}</small></h2>
        <section><TransitionGroup name="queue-card" tag="div" class="queue-column"><BatchScannerTaskCard v-for="record in running" :key="record.scan_id" :record="record" @select="openRecord" @cancel="cancel" @remove="remove" /><p v-if="!running.length" class="queue-empty">扫描器当前空闲</p></TransitionGroup></section>
      </div>
      <div class="queue-lane">
        <h2 class="queue-column-title review"><span>扫描完成</span><span class="queue-title-actions"><small>{{ finished.length }}</small><button type="button" title="批量保存到知识库" aria-label="批量保存到知识库" :disabled="!finished.length || Boolean(batchAction)" @click.stop="saveCompletedBatch"><IcIcon name="save" :size="15" /></button><button type="button" title="批量导出 ZIP" aria-label="批量导出 ZIP" :disabled="!finished.length || Boolean(batchAction)" @click.stop="exportCompletedBatch"><IcIcon name="download" :size="15" /></button></span></h2>
        <section><TransitionGroup name="queue-card" tag="div" class="queue-column"><BatchScannerTaskCard v-for="record in finished" :key="record.scan_id" :record="record" :favorite="scannerActions.favoritesStore.isFavorite('scanner', record.scan_id, record.library_id)" :busy="isRecordBusy(record)" @select="openRecord" @favorite="scannerActions.toggleFavorite" @copy="scannerActions.copyText(preferredScannerMarkdown($event), '全文')" @reveal="scannerActions.revealSource" @save="saveRecord" @export="exportRecord" /><p v-if="!finished.length" class="queue-empty">完成的结果会出现在这里</p></TransitionGroup></section>
      </div>
    </template>
    <template #history>
      <div class="queue-lane">
        <h2 class="queue-column-title confirmed">已终止 <small>{{ cancelled.length }}</small></h2>
        <section><div class="queue-column"><BatchScannerTaskCard v-for="record in cancelled" :key="record.scan_id" :record="record" @select="openRecord" @cancel="cancel" @remove="remove" /><p v-if="!cancelled.length" class="queue-empty">没有已终止任务</p></div></section>
      </div>
      <div class="queue-lane">
        <h2 class="queue-column-title terminated">失败 <small>{{ failed.length }}</small></h2>
        <section><div class="queue-column"><BatchScannerTaskCard v-for="record in failed" :key="record.scan_id" :record="record" @select="openRecord" @cancel="cancel" @remove="remove" /><p v-if="!failed.length" class="queue-empty">没有失败任务</p></div></section>
      </div>
      <div class="queue-lane">
        <h2 class="queue-column-title history">历史 <small>{{ historicalFinished.length }}</small></h2>
        <section><div class="queue-column"><BatchScannerTaskCard v-for="record in historicalFinished" :key="record.scan_id" :record="record" :favorite="scannerActions.favoritesStore.isFavorite('scanner', record.scan_id, record.library_id)" :busy="isRecordBusy(record)" @select="openRecord" @favorite="scannerActions.toggleFavorite" @copy="scannerActions.copyText(preferredScannerMarkdown($event), '全文')" @reveal="scannerActions.revealSource" @save="saveRecord" @export="exportRecord" /><p v-if="!historicalFinished.length" class="queue-empty">没有更早的扫描结果</p></div></section>
      </div>
    </template>
  </QueueBoardShell>

  <BatchScannerTaskDialog v-model:ocr-enabled="ocrEnabled" v-model:online-enabled="onlineEnabled" :open="dialogOpen" :record="selected" :submitting="submitting" :submit-error="submitError" @setting-error="submitError = $event" @close="closeDialog" @create="createBatch" @cancel="cancel" @remove="remove" @updated="updateRecord" />
  <p v-if="scannerStore.actionError" class="batch-scanner-error" role="alert">{{ scannerStore.actionError }}</p>
</template>

<style scoped>
.queue-empty { align-self:center; margin:auto; padding:28px 12px; color:var(--color-text-muted); font-size:calc(12px * var(--font-scale)); text-align:center; }
.batch-scanner-error { position:fixed; right:18px; bottom:18px; z-index:10; max-width:min(520px,calc(100% - 36px)); margin:0; padding:9px 12px; border:1px solid color-mix(in srgb,var(--color-danger) 45%,var(--color-border)); border-radius:8px; background:var(--color-surface); color:var(--color-danger); font-size:calc(11px * var(--font-scale)); }
.queue-title-actions { display:inline-flex; align-items:center; gap:4px; }
.queue-title-actions button { display:grid; place-items:center; width:26px; height:26px; padding:0; border:0; border-radius:50%; background:transparent; color:inherit; cursor:pointer; transition:background var(--transition-fast),transform 140ms ease; }
.queue-title-actions button:hover:not(:disabled) { background:color-mix(in srgb,currentColor 12%,transparent); }
.queue-title-actions button:active:not(:disabled) { transform:scale(.92); }
.queue-title-actions button:disabled { cursor:not-allowed; opacity:.38; }
</style>
