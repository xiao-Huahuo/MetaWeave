<!--
  Scanner recent-history rail.

  Reuses the recent-file card density while replacing index/graph badges with
  reveal, favorite, and permanent-delete actions required by scanner history.
-->
<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import { useFavoritesStore } from '@/stores/favorites'
import { useSettingsStore } from '@/stores/settings'
import type { ScannerRecord } from '@/api/scanner'

const props = withDefaults(defineProps<{
  records: ScannerRecord[]
  activeId?: string
  favoritesOnly?: boolean
}>(), {
  activeId: '',
  favoritesOnly: false,
})

const emit = defineEmits<{
  select: [record: ScannerRecord]
  reveal: [record: ScannerRecord]
  remove: [record: ScannerRecord]
}>()

const favoritesStore = useFavoritesStore()
const settingsStore = useSettingsStore()
const visibleRecords = computed(() => props.favoritesOnly
  ? props.records.filter((record) => favoritesStore.isFavorite('scanner', record.scan_id, record.library_id))
  : props.records)

/** Format bytes for the compact secondary line. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes >= 10 * 1024 ? 0 : 1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}

/** Format upload time in the same compact shape as recent browsing. */
function formatTime(value: string): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

/** Toggle the persisted scanner favorite without selecting the card. */
async function toggleFavorite(record: ScannerRecord): Promise<void> {
  await favoritesStore.toggle('scanner', record.scan_id, record.library_id)
}

/** Load only scanner favorites while preserving other cached favorite types. */
onMounted(() => {
  const libraryId = props.records[0]?.library_id ?? favoritesStore.activeLibraryId()
  void favoritesStore.load(settingsStore.profile.userId, 'scanner', libraryId).catch(() => undefined)
})
watch(() => settingsStore.profile.userId, (userId) => {
  if (userId) void favoritesStore.load(userId, 'scanner', favoritesStore.activeLibraryId()).catch(() => undefined)
})
</script>

<template>
  <div class="scanner-history-list" :class="{ 'is-empty': visibleRecords.length === 0 }">
    <template v-for="(record, index) in visibleRecords" :key="record.scan_id">
      <article
        class="scanner-history-card"
        :class="{ active: record.scan_id === activeId }"
        :style="{ '--history-index': index }"
        role="button"
        tabindex="0"
        @click="emit('select', record)"
        @keydown.enter.prevent="emit('select', record)"
        @keydown.space.prevent="emit('select', record)"
      >
        <span class="scanner-file-icon" :class="{ running: record.status === 'queued' || record.status === 'running' }">
          <IcIcon name="document" :size="18" />
        </span>
        <span class="scanner-history-main">
          <span class="scanner-history-name" :title="record.source_name">{{ record.source_name }}</span>
          <span v-if="record.status === 'queued' || record.status === 'running'" class="scanner-history-status">解析中</span>
          <span v-else class="scanner-history-size">{{ formatSize(record.size) }}</span>
        </span>
        <span class="scanner-history-footer">
          <time :datetime="record.created_at">{{ formatTime(record.created_at) }}</time>
          <span class="scanner-history-actions">
            <button type="button" title="打开原文件所在位置" aria-label="打开原文件所在位置" @click.stop="emit('reveal', record)"><IcIcon name="folder-open" :size="14" /></button>
            <button
              type="button"
              :title="favoritesStore.isFavorite('scanner', record.scan_id, record.library_id) ? '取消收藏' : '收藏'"
              :aria-label="favoritesStore.isFavorite('scanner', record.scan_id, record.library_id) ? '取消收藏' : '收藏'"
              @click.stop="toggleFavorite(record)"
            ><IcIcon name="star" :size="14" :class="{ 'is-favorite': favoritesStore.isFavorite('scanner', record.scan_id, record.library_id) }" /></button>
            <button type="button" title="删除历史" aria-label="删除历史" :disabled="record.status === 'queued' || record.status === 'running'" @click.stop="emit('remove', record)"><IcIcon name="trash" :size="14" /></button>
          </span>
        </span>
      </article>
    </template>
    <p v-if="visibleRecords.length === 0" class="scanner-history-empty">{{ favoritesOnly ? '还没有收藏的扫描记录' : '还没有解析记录' }}</p>
  </div>
</template>

<style scoped>
.scanner-history-list { display: grid; align-content: start; gap: 8px; min-height: 0; overflow: auto; padding: 4px 8px 16px; }
.scanner-history-list.is-empty { place-items: center; align-content: center; }
.scanner-history-card { display: grid; grid-template-columns: 38px minmax(0, 1fr); gap: 8px; width: 100%; min-width: 0; padding: 9px; border: 1px solid var(--color-border); border-radius: 17px; outline: 0; background: var(--color-canvas); color: var(--color-text); font: inherit; text-align: left; cursor: pointer; animation: scanner-history-enter 240ms cubic-bezier(.23,1,.32,1) both; animation-delay: calc(var(--history-index) * 55ms); transition: border-color 180ms ease, background 180ms ease, transform 140ms ease; }
.scanner-history-card:hover { border-color: var(--color-border-strong); background: var(--color-bg-hover); }
.scanner-history-card:active { transform: scale(.985); }
.scanner-history-card.active { border-color: var(--color-primary); background: var(--color-primary-soft); }
.scanner-history-card:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.scanner-file-icon { position: relative; display: grid; place-items: center; width: 34px; height: 34px; color: var(--color-text-muted); }
.scanner-file-icon.running::after { position: absolute; inset: 0; border: 2px solid var(--color-border); border-top-color: var(--color-primary); border-radius: 50%; content: ''; animation: scanner-ring 850ms linear infinite; }
.scanner-history-main { display: flex; min-width: 0; flex-direction: column; justify-content: center; }
.scanner-history-name { overflow: hidden; font-size: calc(12px * var(--font-scale)); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.scanner-history-size,.scanner-history-status { margin-top: 2px; color: var(--color-text-muted); font-size: calc(10px * var(--font-scale)); }
.scanner-history-status { color: var(--color-primary); }
.scanner-history-footer { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; color: var(--color-text-muted); font-size: calc(9px * var(--font-scale)); }
.scanner-history-actions { display: inline-flex; align-items: center; gap: 2px; }
.scanner-history-actions button { display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--color-text-muted); transition: background 150ms ease, color 150ms ease, transform 120ms ease; }
.scanner-history-actions button:hover:not(:disabled) { background: var(--color-primary-softer); color: var(--color-primary); }
.scanner-history-actions button:active:not(:disabled) { transform: scale(.9); }
.scanner-history-actions .is-favorite { color: var(--color-primary); fill: currentColor; }
.scanner-history-actions button:disabled { opacity: .35; }
.scanner-history-empty { margin: 0; color: var(--color-text-muted); font-size: calc(12px * var(--font-scale)); text-align: center; }
@keyframes scanner-history-enter { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes scanner-ring { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .scanner-history-card { animation: none; } .scanner-history-card,.scanner-history-actions button { transition: none; } .scanner-file-icon.running::after { animation: none; } }
</style>
