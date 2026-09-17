<!--
  Uploaded file attachment blocks.

  Usage:
  Shows pending or sent Agent session attachments with file-type specific icons.
-->
<script setup lang="ts">
import { computed } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import type { AgentUploadedAttachment } from '@/stores/chat'

const props = withDefaults(defineProps<{
  attachments: AgentUploadedAttachment[]
  align?: 'left' | 'right' | 'center'
}>(), {
  align: 'left',
})

const emit = defineEmits<{
  remove: [attachment: AgentUploadedAttachment]
}>()

const visibleAttachments = computed(() => props.attachments.filter((item) => item.filename || item.stored_name))

function extensionOf(filename: string) {
  const parts = filename.toLowerCase().split('.')
  return parts.length > 1 ? parts.pop() || '' : ''
}

function iconFor(filename: string) {
  const ext = extensionOf(filename)
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'bmp', 'ico'].includes(ext)) return 'image'
  if (['xlsx', 'xls', 'csv', 'tsv'].includes(ext)) return 'table-chart'
  if (['docx', 'doc'].includes(ext)) return 'title'
  if (['md', 'markdown'].includes(ext)) return 'edit-note'
  if (['json', 'jsonl'].includes(ext)) return 'code'
  if (['html', 'htm', 'xml'].includes(ext)) return 'code'
  if (['cpp', 'cc', 'cxx', 'c', 'h', 'hpp', 'py', 'ts', 'tsx', 'js', 'jsx', 'vue', 'java', 'go', 'rs'].includes(ext)) return 'code'
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return 'archive'
  if (['pdf', 'txt', 'log'].includes(ext)) return 'file'
  return 'file'
}

function kindFor(filename: string) {
  const ext = extensionOf(filename)
  if (!ext) return 'FILE'
  return ext.slice(0, 5).toUpperCase()
}

function toneFor(filename: string) {
  const ext = extensionOf(filename)
  if (['pdf'].includes(ext)) return 'red'
  if (['md', 'markdown', 'txt', 'log'].includes(ext)) return 'blue'
  if (['docx', 'doc'].includes(ext)) return 'indigo'
  if (['html', 'htm', 'xml', 'json', 'jsonl'].includes(ext)) return 'violet'
  if (['cpp', 'cc', 'cxx', 'c', 'h', 'hpp', 'py', 'ts', 'tsx', 'js', 'jsx', 'vue', 'java', 'go', 'rs'].includes(ext)) return 'green'
  if (['xlsx', 'xls', 'csv', 'tsv'].includes(ext)) return 'emerald'
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'bmp', 'ico'].includes(ext)) return 'pink'
  return 'neutral'
}

function processingStatus(attachment: AgentUploadedAttachment): string {
  return String(attachment.metadata?.processing_status || 'completed')
}

function processingProgress(attachment: AgentUploadedAttachment): number {
  const value = Number(attachment.metadata?.processing_progress ?? 100)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
}

function isProcessing(attachment: AgentUploadedAttachment): boolean {
  return ['uploading', 'queued', 'processing'].includes(processingStatus(attachment))
}

function processingLabel(attachment: AgentUploadedAttachment): string {
  const status = processingStatus(attachment)
  const stage = String(attachment.metadata?.processing_stage || '')
  if (status === 'failed') return '失败'
  if (status === 'uploading') return '上传中'
  if (stage === 'ocr') return 'OCR'
  if (stage === 'vision') return '识图'
  if (status === 'queued') return '等待解析'
  if (status === 'processing') return '解析中'
  return ''
}
</script>

<template>
  <div v-if="visibleAttachments.length" class="attachment-blocks" :class="`align-${align}`">
    <div
      v-for="attachment in visibleAttachments"
      :key="attachment.attachment_id"
      class="attachment-item"
      :class="[`tone-${toneFor(attachment.filename || attachment.stored_name)}`, `status-${processingStatus(attachment)}`]"
      :title="attachment.filename || attachment.stored_name"
    >
      <div class="attachment-card">
        <div class="attachment-icon-box">
          <IcIcon :name="iconFor(attachment.filename || attachment.stored_name)" :size="24" />
          <span class="attachment-kind">{{ kindFor(attachment.filename || attachment.stored_name) }}</span>
        </div>
        <span class="attachment-name">{{ attachment.filename || attachment.stored_name }}</span>
        <button
          class="attachment-remove"
          type="button"
          title="Remove attachment"
          aria-label="Remove attachment"
          @click.stop="emit('remove', attachment)"
        >
          <IcIcon name="close" :size="15" />
        </button>
      </div>
      <div
        v-if="isProcessing(attachment) || processingStatus(attachment) === 'failed'"
        class="attachment-processing"
        :title="String(attachment.metadata?.processing_error || processingLabel(attachment))"
      >
        <span>{{ processingLabel(attachment) }}</span>
        <span class="attachment-progress-track" aria-hidden="true">
          <span :style="{ width: `${processingProgress(attachment)}%` }"></span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attachment-blocks {
  display: flex;
  align-items: flex-start;
  flex-wrap: nowrap;
  gap: var(--space-6);
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 2px 6px;
  scrollbar-width: thin;
  scroll-padding-inline: 2px;
}

.attachment-blocks.align-left {
  justify-content: flex-start;
}

.attachment-blocks.align-right {
  justify-content: flex-start;
  direction: rtl;
}

.attachment-blocks.align-center {
  justify-content: center;
}

/* 在 rtl 下附件内容需要重新 ltr，否则文件名会反向 */
.attachment-blocks.align-right .attachment-item {
  direction: ltr;
}

.attachment-item {
  --attachment-color: var(--color-text-secondary);
  display: flex;
  width: 70px;
  min-width: 70px;
  flex: 0 0 70px;
  flex-direction: column;
  align-self: flex-start;
  gap: var(--space-4);
}

.attachment-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 70px;
  width: 70px;
  height: 70px;
  gap: var(--space-4);
  padding: 7px 6px 6px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--color-border) 42%, transparent);
  border-radius: 16px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.34), rgba(255, 255, 255, 0.08) 48%, rgba(255, 255, 255, 0.2)),
    color-mix(in srgb, var(--color-surface) 44%, transparent);
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.45),
    inset 0 -1px 2px rgba(0, 0, 0, 0.08);
  -webkit-backdrop-filter: blur(18px) saturate(1.5);
  backdrop-filter: blur(18px) saturate(1.5);
  isolation: isolate;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast);
}

.attachment-card::before {
  position: absolute;
  inset: 1px;
  z-index: -1;
  pointer-events: none;
  content: "";
  border-radius: 15px;
  background:
    radial-gradient(circle at 22% 14%, rgba(255, 255, 255, 0.7), transparent 26%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.36), transparent 38%, rgba(255, 255, 255, 0.18) 76%, transparent);
  opacity: 0.72;
}

.attachment-card:hover {
  border-color: color-mix(in srgb, var(--attachment-color) 36%, var(--color-border));
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.55),
    inset 0 -1px 2px rgba(0, 0, 0, 0.1);
}

.attachment-remove {
  position: absolute;
  top: 4px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-muted);
  opacity: 0;
  cursor: pointer;
  transition:
    opacity var(--transition-fast),
    color var(--transition-fast),
    filter var(--transition-fast);
}

.attachment-card:hover .attachment-remove,
.attachment-remove:focus-visible {
  opacity: 1;
}

.attachment-remove:hover {
  background: transparent;
  color: #ef476f;
  filter:
    drop-shadow(0 0 1px var(--color-canvas))
    drop-shadow(0 0 3px rgba(239, 71, 111, 0.72));
}

.attachment-icon-box {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 31px;
  height: 31px;
  border-radius: 11px;
  background: transparent;
  color: var(--attachment-color);
}

.attachment-kind {
  position: absolute;
  right: 1px;
  bottom: 1px;
  max-width: 28px;
  overflow: hidden;
  color: var(--attachment-color);
  font-family: var(--font-ui);
  font-size: calc(6px * var(--font-scale));
  font-weight: 800;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-name {
  display: -webkit-box;
  width: 100%;
  overflow: hidden;
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: calc(8.5px * var(--font-scale));
  line-height: 1.18;
  text-align: center;
  text-overflow: ellipsis;
  word-break: break-all;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.attachment-processing {
  display: grid;
  width: 100%;
  gap: 2px;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(6px * var(--font-scale));
  line-height: 1;
  text-align: center;
}

.attachment-progress-track {
  display: block;
  width: 100%;
  height: 3px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--attachment-color) 18%, transparent);
}

.attachment-progress-track > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--attachment-color);
  transition: width 180ms ease;
}

.attachment-item.status-failed {
  --attachment-color: var(--color-danger);
}

:global(.dark) .attachment-card,
:global([data-theme="dark"]) .attachment-card {
  border-color: rgba(255, 255, 255, 0.12);
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0.035) 48%, rgba(255, 255, 255, 0.09)),
    rgba(12, 14, 18, 0.34);
  box-shadow:
    inset 0 1px 1px rgba(255, 255, 255, 0.18),
    inset 0 -1px 2px rgba(0, 0, 0, 0.28);
}

.tone-red { --attachment-color: #ef476f; }
.tone-blue { --attachment-color: #3b82f6; }
.tone-indigo { --attachment-color: #6366f1; }
.tone-violet { --attachment-color: #8b5cf6; }
.tone-green { --attachment-color: #22c55e; }
.tone-emerald { --attachment-color: #10b981; }
.tone-pink { --attachment-color: #ec4899; }
.tone-neutral { --attachment-color: var(--color-text-secondary); }
</style>
