<!--
  Batch scanner create and detail dialog.

  Reuses ScannerUploadPanel for all creation input and loader states, then uses
  the existing scanner result editor for completed task inspection.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { ScannerRecord } from '@/api/scanner'
import IcIcon from '@/components/common/IcIcon.vue'
import QueueDialogShell from '@/components/common/QueueDialogShell.vue'
import ScannerResultPanel from '@/components/scanner_view/ScannerResultPanel.vue'
import ScannerUploadPanel from '@/components/scanner_view/ScannerUploadPanel.vue'
import { formatProgress } from '@/utils/progress'

const props = withDefaults(defineProps<{
  open: boolean
  record?: ScannerRecord | null
  submitting?: boolean
  submitError?: string
}>(), {
  record: null,
  submitting: false,
  submitError: '',
})

const emit = defineEmits<{
  close: []
  create: [files: File[], urls: string[], ocrEnabled: boolean]
  cancel: [record: ScannerRecord]
  remove: [record: ScannerRecord]
  updated: [record: ScannerRecord]
}>()

const ocrEnabled = ref(true)
const title = computed(() => !props.record ? '新建批量扫描' : props.record.status === 'finished' ? '扫描结果' : '扫描任务详情')

watch(() => props.open, (open) => {
  if (!open || props.record) return
  ocrEnabled.value = true
})
</script>

<template>
  <QueueDialogShell :open="open" :title="title" :wide="record?.status === 'finished'" :content-key="record ? `${record.scan_id}-${record.status}-${record.progress}` : `${submitting}-${submitError}`" @close="emit('close')">
    <ScannerResultPanel v-if="record?.status === 'finished'" class="batch-result-panel" :record="record" @back="emit('close')" @updated="emit('updated', $event)" />

    <section v-else-if="record" class="batch-task-detail">
      <div class="batch-detail-heading"><IcIcon :name="record.source_kind === 'url' ? 'language' : 'document'" :size="20" /><strong>{{ record.source_name }}</strong></div>
      <dl>
        <div><dt>状态</dt><dd>{{ record.stage_label }}</dd></div>
        <div><dt>OCR</dt><dd>{{ record.ocr_enabled ? '已开启' : '已关闭' }}</dd></div>
        <div><dt>创建时间</dt><dd>{{ new Date(record.created_at).toLocaleString() }}</dd></div>
      </dl>
      <div v-if="record.status === 'running' || record.status === 'cancelling'" class="batch-detail-progress" role="progressbar" :aria-valuenow="record.progress" aria-valuemin="0" aria-valuemax="100"><i :style="{ transform: `scaleX(${record.progress / 100})` }"></i></div>
      <p v-if="record.status === 'running'">{{ formatProgress(record.progress) }}%</p>
      <p v-if="record.error" class="batch-form-error">{{ record.error }}</p>
    </section>

    <ScannerUploadPanel v-else v-model:ocr-enabled="ocrEnabled" :running="null" batch embedded :busy="submitting" :error="submitError" @upload-batch="emit('create', $event, [], ocrEnabled)" @crawl-batch="emit('create', [], $event, ocrEnabled)" />

    <template v-if="record && record.status !== 'finished'" #footer>
      <button v-if="record && ['queued', 'running', 'cancelling'].includes(record.status)" class="danger-btn" type="button" @click="emit('cancel', record)">终止扫描</button>
      <button v-else-if="record" class="danger-btn" type="button" @click="emit('remove', record)">删除记录</button>
      <span></span>
      <div class="submit-actions"><button type="button" @click="emit('close')">取消</button></div>
    </template>
  </QueueDialogShell>
</template>

<style scoped>
.batch-task-detail { display:grid; gap:10px; padding:0 16px; }
.batch-form-error { margin:0; color:var(--color-danger); font-size:calc(12px * var(--font-scale)); }
.batch-detail-heading { display:flex; align-items:center; gap:8px; min-width:0; }.batch-detail-heading strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.batch-task-detail dl { display:grid; margin:0; border-top:1px solid var(--color-border); }.batch-task-detail dl div { display:grid; grid-template-columns:110px minmax(0,1fr); gap:12px; padding:9px 0; border-bottom:1px solid var(--color-border); }.batch-task-detail dt { color:var(--color-text-muted); }.batch-task-detail dd { margin:0; }
.batch-task-detail > p { margin:0; color:var(--color-text-muted); text-align:right; }
.batch-detail-progress { position:relative; height:5px; overflow:hidden; border-radius:999px; background:color-mix(in srgb,var(--color-success) 26%,transparent); }.batch-detail-progress i { position:absolute; inset:0; background:var(--color-success); transform-origin:left; transition:transform 260ms ease; }
.batch-result-panel { min-height:min(680px,72vh); border-top:1px solid var(--color-border); }
@media (max-width:480px) { .batch-task-detail { padding:0 12px; }.batch-task-detail dl div { grid-template-columns:88px minmax(0,1fr); }.batch-result-panel { min-height:calc(100dvh - 126px); } }
@media (prefers-reduced-motion:reduce) { .batch-detail-progress i { transition:none; } }
</style>
