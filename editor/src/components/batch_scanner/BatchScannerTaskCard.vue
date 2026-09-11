<!--
  Batch scanner queue card.

  Presents one persistent ScannerRecord with the same compact card density and
  action placement as Agent queue cards while preserving scanner-specific data.
-->
<script setup lang="ts">
import { computed } from 'vue'

import type { ScannerRecord } from '@/api/scanner'
import IcIcon from '@/components/common/IcIcon.vue'
import { formatProgress } from '@/utils/progress'

const props = withDefaults(defineProps<{ record: ScannerRecord; favorite?: boolean; busy?: boolean }>(), {
  favorite: false,
  busy: false,
})
const emit = defineEmits<{
  select: [record: ScannerRecord]
  cancel: [record: ScannerRecord]
  remove: [record: ScannerRecord]
  favorite: [record: ScannerRecord]
  copy: [record: ScannerRecord]
  reveal: [record: ScannerRecord]
  save: [record: ScannerRecord]
  export: [record: ScannerRecord]
}>()

const active = computed(() => ['queued', 'running', 'cancelling'].includes(props.record.status))
const sourceLabel = computed(() => props.record.source_kind === 'url' ? '网页' : props.record.source_kind === 'example' ? '示例' : '文件')

/** Format byte counts without introducing a dependency for one compact label. */
function formatSize(size: number): string {
  if (!size) return sourceLabel.value
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <article class="queue-task-card" :class="`queue-task-card--${record.status}`">
    <button class="queue-task-open" type="button" @click="emit('select', record)">
      <div class="queue-task-title">
        <strong>{{ record.source_name }}</strong>
        <span>{{ sourceLabel }} · {{ formatSize(record.size) }} · {{ record.parser_engine === 'mineru' ? 'MinerU' : '本地' }} · OCR {{ record.ocr_enabled ? '开启' : '关闭' }}</span>
      </div>
      <div v-if="(record.status === 'running' || record.status === 'cancelling') && record.parser_engine !== 'mineru'" class="queue-progress" role="progressbar" :aria-valuenow="record.progress" aria-valuemin="0" aria-valuemax="100">
        <i :style="{ transform: `scaleX(${record.progress / 100})` }"></i>
      </div>
      <small :class="{ error: record.status === 'failed' }">{{ record.status === 'failed' ? record.error : record.stage_label }}<template v-if="record.status === 'running' && record.parser_engine !== 'mineru'"> · {{ formatProgress(record.progress) }}%</template></small>
    </button>
    <div v-if="record.status === 'finished'" class="queue-card-top-actions">
      <button class="queue-card-action" :class="{ favorite }" type="button" :title="favorite ? '取消收藏' : '收藏'" :aria-label="favorite ? '取消收藏' : '收藏'" :disabled="busy" @click="emit('favorite', record)"><IcIcon name="star" :size="16" /></button>
      <button class="queue-card-action" type="button" title="复制全文" aria-label="复制全文" :disabled="busy" @click="emit('copy', record)"><IcIcon name="copy" :size="16" /></button>
    </div>
    <div v-else class="queue-card-top-actions">
      <button class="queue-card-detail" type="button" title="查看详情" aria-label="查看详情" @click="emit('select', record)"><IcIcon name="info" :size="17" /></button>
      <button v-if="active" class="queue-card-action queue-card-terminate" type="button" title="终止扫描" aria-label="终止扫描" @click="emit('cancel', record)"><IcIcon name="stop" :size="16" /></button>
      <button v-else class="queue-card-action queue-card-remove" type="button" title="删除记录" aria-label="删除记录" @click="emit('remove', record)"><IcIcon name="trash" :size="16" /></button>
    </div>
    <div v-if="record.status === 'finished'" class="queue-card-bottom-actions">
      <button type="button" title="打开文件夹" aria-label="打开文件夹" :disabled="busy" @click="emit('reveal', record)"><IcIcon name="folder-open" :size="16" /></button>
      <button type="button" title="保存到知识库" aria-label="保存到知识库" :disabled="busy" @click="emit('save', record)"><IcIcon name="save" :size="16" /></button>
      <button type="button" title="导出" aria-label="导出" :disabled="busy" @click="emit('export', record)"><IcIcon name="download" :size="16" /></button>
    </div>
  </article>
</template>

<style scoped>
.queue-task-card { position:relative; width:100%; min-height:104px; border:1px solid var(--color-border); border-radius:20px; background:var(--color-surface); color:var(--color-text); transition:background var(--transition-fast),border-color var(--transition-fast),transform 180ms cubic-bezier(.16,1,.3,1); }
.queue-task-card:hover { border-color:color-mix(in srgb,var(--color-primary) 28%,var(--color-border)); background:var(--color-surface-raised); transform:translateY(-1px); }
.queue-task-open { display:grid; gap:10px; width:100%; min-height:102px; padding:14px; border:0; border-radius:inherit; background:transparent; color:inherit; text-align:left; cursor:pointer; }
.queue-task-card--finished .queue-task-open { padding-bottom:48px; }
.queue-task-title { display:grid; gap:4px; padding-right:66px; }
.queue-task-title strong { overflow:hidden; font:600 calc(13px * var(--font-scale))/1.45 var(--font-ui); text-overflow:ellipsis; white-space:nowrap; }
.queue-task-title span,.queue-task-open small { overflow:hidden; color:var(--color-text-muted); font-size:calc(11px * var(--font-scale)); text-overflow:ellipsis; white-space:nowrap; }
.queue-task-open small.error { color:var(--color-danger); }
.queue-progress { position:relative; width:100%; height:4px; overflow:hidden; border-radius:999px; background:color-mix(in srgb,var(--color-success) 26%,transparent); }
.queue-progress i { position:absolute; inset:0; background:var(--color-success); transform-origin:left; transition:transform 260ms ease; }
.queue-card-top-actions { position:absolute; top:7px; right:7px; z-index:1; display:flex; align-items:center; gap:4px; }
.queue-card-action,.queue-card-detail { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; padding:0; border:0; border-radius:50%; background:transparent; color:var(--color-text-secondary); cursor:pointer; }
.queue-card-detail:hover { background:var(--color-primary-softer); color:var(--color-primary); }
.queue-card-terminate { color:var(--color-danger); }
.queue-card-terminate:hover,.queue-card-remove:hover { background:color-mix(in srgb,var(--color-danger) 12%,transparent); color:var(--color-danger); }
.queue-card-action.favorite { color:var(--color-primary); }
.queue-card-bottom-actions { position:absolute; right:10px; bottom:9px; z-index:1; display:flex; align-items:center; gap:4px; }
.queue-card-bottom-actions button { display:grid; place-items:center; width:28px; height:28px; padding:0; border:0; border-radius:50%; background:transparent; color:var(--color-text-secondary); cursor:pointer; }
.queue-card-bottom-actions button:hover:not(:disabled),.queue-card-action:hover:not(:disabled) { background:var(--color-primary-softer); color:var(--color-primary); }
.queue-card-bottom-actions button:disabled,.queue-card-action:disabled { cursor:wait; opacity:.45; }
@media (prefers-reduced-motion:reduce) { .queue-task-card,.queue-progress i { transition:none; }.queue-task-card:hover { transform:none; } }
</style>
