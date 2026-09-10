<!--
  Persistent batch scanner queue page.

  Projects existing ScannerRecord tasks into the shared queue-board layout and
  creates every selected file or URL through the real asynchronous scanner API.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { createFileScan, createUrlScan, type ScannerRecord } from '@/api/scanner'
import BatchScannerTaskCard from '@/components/batch_scanner/BatchScannerTaskCard.vue'
import BatchScannerTaskDialog from '@/components/batch_scanner/BatchScannerTaskDialog.vue'
import QueueBoardShell from '@/components/common/QueueBoardShell.vue'
import { useScannerStore } from '@/stores/scanner'
import { useSettingsStore } from '@/stores/settings'

defineOptions({ name: 'BatchScannerView', inheritAttrs: false })

const scannerStore = useScannerStore()
const settingsStore = useSettingsStore()
const historyMode = ref(false)
const dialogOpen = ref(false)
const selected = ref<ScannerRecord | null>(null)
const submitting = ref(false)
const submitError = ref('')
let pollTimer: number | null = null

const queued = computed(() => scannerStore.records.filter(record => record.status === 'queued'))
const running = computed(() => scannerStore.records.filter(record => ['running', 'cancelling'].includes(record.status)))
const finished = computed(() => scannerStore.records.filter(record => record.status === 'finished'))
const cancelled = computed(() => scannerStore.records.filter(record => record.status === 'cancelled'))
const failed = computed(() => scannerStore.records.filter(record => record.status === 'failed'))

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
async function createBatch(files: File[], urls: string[], ocrEnabled: boolean): Promise<void> {
  submitting.value = true
  submitError.value = ''
  scannerStore.actionError = ''
  const failures: string[] = []
  let createdCount = 0
  try {
    for (const file of files) {
      try {
        scannerStore.upsert(await createFileScan(settingsStore.profile.userId, file, ocrEnabled))
        createdCount += 1
      } catch {
        failures.push(file.name)
      }
    }
    for (const url of urls) {
      try {
        scannerStore.upsert(await createUrlScan(settingsStore.profile.userId, url, ocrEnabled))
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
  if (!scannerStore.hasRunning) return
  await scannerStore.load()
  if (selected.value) selected.value = scannerStore.records.find(record => record.scan_id === selected.value?.scan_id) ?? selected.value
}

onMounted(async () => {
  await scannerStore.load()
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
    @switch-page="historyMode = $event"
    @new-task="openNew"
  >
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
        <h2 class="queue-column-title review">扫描完成 <small>{{ finished.length }}</small></h2>
        <section><TransitionGroup name="queue-card" tag="div" class="queue-column"><BatchScannerTaskCard v-for="record in finished" :key="record.scan_id" :record="record" @select="openRecord" @cancel="cancel" @remove="remove" /><p v-if="!finished.length" class="queue-empty">完成的结果会出现在这里</p></TransitionGroup></section>
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
    </template>
  </QueueBoardShell>

  <BatchScannerTaskDialog :open="dialogOpen" :record="selected" :submitting="submitting" :submit-error="submitError" @close="closeDialog" @create="createBatch" @cancel="cancel" @remove="remove" @updated="updateRecord" />
  <p v-if="scannerStore.actionError" class="batch-scanner-error" role="alert">{{ scannerStore.actionError }}</p>
</template>

<style scoped>
.queue-empty { align-self:center; margin:auto; padding:28px 12px; color:var(--color-text-muted); font-size:calc(12px * var(--font-scale)); text-align:center; }
.batch-scanner-error { position:fixed; right:18px; bottom:18px; z-index:10; max-width:min(520px,calc(100% - 36px)); margin:0; padding:9px 12px; border:1px solid color-mix(in srgb,var(--color-danger) 45%,var(--color-border)); border-radius:8px; background:var(--color-surface); color:var(--color-danger); font-size:calc(11px * var(--font-scale)); }
</style>
