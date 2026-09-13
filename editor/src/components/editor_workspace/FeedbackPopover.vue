<!--
  Centered user feedback dialog.

  Usage:
  EditorWorkspace mounts this component as a modal overlay. Feedback is created,
  listed, edited, and deleted through the backend /feedback API only.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import { deleteFeedback, listFeedback, submitFeedback, updateFeedback, type FeedbackRecord } from '@/api/feedback'

defineOptions({ name: 'FeedbackPopover' })

const props = defineProps<{
  open: boolean
  userId: string
  page: string
}>()

const emit = defineEmits<{
  close: []
}>()

const content = ref('')
const feedbackItems = ref<FeedbackRecord[]>([])
const editingId = ref('')
const expandedFeedbackIds = ref<Set<string>>(new Set())
const loading = ref(false)
const submitting = ref(false)
const statusText = ref('')
const errorText = ref('')
const feedbackNotice = computed(() => errorText.value || statusText.value)
const canSubmit = computed(() => props.userId.trim().length > 0 && content.value.trim().length > 0 && !submitting.value)
const feedbackBodyWatchKey = computed(() => `${feedbackItems.value.length}:${editingId.value ? 'editing' : 'new'}:${loading.value ? 'loading' : 'ready'}:${expandedFeedbackIds.value.size}`)
const submitLabel = computed(() => {
  if (submitting.value) return '保存中'
  return editingId.value ? '保存修改' : '提交'
})

watch(
  () => props.open,
  (open) => {
    if (open) {
      statusText.value = ''
      errorText.value = ''
      void loadFeedback()
    } else {
      resetEditing()
    }
  },
)

watch(
  () => props.userId,
  () => {
    if (props.open) {
      void loadFeedback()
    }
  },
)

async function loadFeedback() {
  loading.value = true
  errorText.value = ''
  try {
    feedbackItems.value = await listFeedback(props.userId)
    errorText.value = ''
  } catch (error) {
    errorText.value = getFeedbackErrorMessage(error, '反馈读取失败')
  } finally {
    loading.value = false
  }
}

async function submit() {
  const trimmed = content.value.trim()
  if (!trimmed || submitting.value) return
  if (!props.userId.trim()) {
    errorText.value = '当前用户不可用'
    return
  }
  submitting.value = true
  statusText.value = ''
  errorText.value = ''
  try {
    if (editingId.value) {
      const updated = await updateFeedback(editingId.value, trimmed)
      feedbackItems.value = feedbackItems.value.map((item) =>
        item.feedback_id === updated.feedback_id ? updated : item,
      )
      errorText.value = ''
      statusText.value = '已修改'
    } else {
      const created = await submitFeedback({
        user_id: props.userId,
        content: trimmed,
        source: 'editor_activity_bar',
        page: props.page,
      })
      feedbackItems.value = [created, ...feedbackItems.value]
      errorText.value = ''
      statusText.value = '已保存'
    }
    content.value = ''
    editingId.value = ''
  } catch (error) {
    errorText.value = getFeedbackErrorMessage(error, '反馈保存失败')
  } finally {
    submitting.value = false
  }
}

function startEdit(item: FeedbackRecord) {
  editingId.value = item.feedback_id
  content.value = item.content
  statusText.value = '正在修改'
  errorText.value = ''
}

function toggleFeedbackExpanded(item: FeedbackRecord) {
  const next = new Set(expandedFeedbackIds.value)
  if (next.has(item.feedback_id)) {
    next.delete(item.feedback_id)
  } else {
    next.add(item.feedback_id)
  }
  expandedFeedbackIds.value = next
}

function isFeedbackExpanded(item: FeedbackRecord) {
  return expandedFeedbackIds.value.has(item.feedback_id)
}

function resetEditing() {
  editingId.value = ''
  content.value = ''
  statusText.value = ''
  errorText.value = ''
}

async function removeFeedback(item: FeedbackRecord) {
  errorText.value = ''
  statusText.value = ''
  try {
    await deleteFeedback(item.feedback_id)
    feedbackItems.value = feedbackItems.value.filter((entry) => entry.feedback_id !== item.feedback_id)
    const nextExpanded = new Set(expandedFeedbackIds.value)
    nextExpanded.delete(item.feedback_id)
    expandedFeedbackIds.value = nextExpanded
    if (editingId.value === item.feedback_id) {
      resetEditing()
    }
    errorText.value = ''
    statusText.value = '已删除'
  } catch (error) {
    errorText.value = getFeedbackErrorMessage(error, '反馈删除失败')
  }
}

function formatFeedbackTime(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getFeedbackErrorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : ''
  if (message.includes('非 JSON 响应') || message.includes('Content-Type: text/html')) {
    return '暂时无法读取反馈'
  }
  return message || fallback
}
</script>

<template>
  <div v-if="open" class="feedback-backdrop" @click.self="emit('close')">
    <section class="feedback-popover library-form-surface" aria-label="用户反馈">
      <header class="feedback-header">
        <strong>用户反馈</strong>
        <button class="feedback-close" type="button" title="关闭" aria-label="关闭" @click="emit('close')">
          <IcIcon name="close" :size="15" />
        </button>
      </header>

      <FormHeightTransition :watch-key="feedbackBodyWatchKey">
        <div class="feedback-body">
          <form class="feedback-form" @submit.prevent="submit">
            <textarea
              class="form-input-surface"
              v-model="content"
              rows="6"
              maxlength="4000"
              placeholder="写下问题、建议或体验反馈"
              aria-label="反馈内容"
              @keydown.enter.exact.prevent="submit"
            ></textarea>
            <footer class="feedback-footer">
              <span class="feedback-status" :title="feedbackNotice">{{ feedbackNotice }}</span>
              <div class="feedback-actions">
                <button
                  v-if="editingId"
                  class="feedback-secondary"
                  type="button"
                  :disabled="submitting"
                  @click="resetEditing"
                >
                  取消
                </button>
                <button class="feedback-submit" type="submit" :disabled="!canSubmit">
                  <IcIcon name="send" :size="14" />
                  <span>{{ submitLabel }}</span>
                </button>
              </div>
            </footer>
          </form>

          <aside class="feedback-stack" :class="{ empty: !loading && feedbackItems.length === 0 }" aria-label="已提交反馈">
            <div v-if="loading" class="feedback-empty">读取中</div>
            <div v-else-if="feedbackItems.length === 0" class="feedback-empty">
              {{ errorText || '暂无反馈' }}
            </div>
            <template v-else>
              <article
                v-for="item in feedbackItems"
                :key="item.feedback_id"
                class="feedback-chip"
                :class="{ expanded: isFeedbackExpanded(item) }"
              >
                <button
                  class="feedback-chip-main"
                  type="button"
                  :aria-expanded="isFeedbackExpanded(item)"
                  @click="toggleFeedbackExpanded(item)"
                >
                  <span class="feedback-chip-line">
                    <span class="feedback-chip-content">{{ item.content }}</span>
                    <time>{{ formatFeedbackTime(item.created_at) }}</time>
                  </span>
                  <span v-if="isFeedbackExpanded(item)" class="feedback-chip-full">{{ item.content }}</span>
                </button>
                <div class="feedback-chip-actions">
                  <button type="button" title="修改" aria-label="修改" @click="startEdit(item)">
                    <IcIcon name="edit" :size="13" />
                  </button>
                  <button type="button" title="删除" aria-label="删除" @click="removeFeedback(item)">
                    <IcIcon name="trash" :size="13" />
                  </button>
                </div>
              </article>
            </template>
          </aside>
        </div>
      </FormHeightTransition>
    </section>
  </div>
</template>

<style scoped>
.feedback-backdrop {
  position: fixed;
  inset: 0;
  z-index: 220;
  display: grid;
  place-items: center;
  padding: var(--space-24);
  background: rgba(0, 0, 0, 0.42);
}

.feedback-popover {
  --feedback-panel-radius: 28px;
  --feedback-control-radius: 16px;
  --feedback-card-bg: var(--color-canvas);
  --feedback-card-text: var(--color-text);
  --feedback-card-muted: var(--color-text-muted);
  --feedback-card-subtle: color-mix(in srgb, var(--color-text-muted) 78%, transparent);
  --feedback-field-bg: var(--color-bg-app);
  --feedback-row-bg: color-mix(in srgb, var(--color-canvas) 92%, var(--color-text) 8%);
  --feedback-empty-bg: color-mix(in srgb, var(--color-canvas) 96%, var(--color-text) 4%);
  --feedback-soft-border: color-mix(in srgb, var(--color-border) 80%, transparent);

  display: grid;
  gap: var(--space-8);
  width: min(760px, calc(100vw - 32px));
  max-height: min(620px, calc(100vh - 48px));
  padding: var(--space-18, 18px);
  border: 1px solid var(--color-border);
  border-radius: var(--feedback-panel-radius);
  background: var(--feedback-card-bg);
  color: var(--feedback-card-text);
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
  font-family: var(--font-ui);
}

:global(:root[data-theme="dark"] .feedback-backdrop) {
  background: rgba(0, 0, 0, 0.52);
}

:global(:root[data-theme="dark"] .feedback-popover) {
  --feedback-card-bg: #0d1117;
  --feedback-card-text: #e6e6e6;
  --feedback-card-muted: rgba(230, 230, 230, 0.55);
  --feedback-card-subtle: rgba(230, 230, 230, 0.46);
  --feedback-field-bg: #111827;
  --feedback-row-bg: rgba(255, 255, 255, 0.045);
  --feedback-empty-bg: rgba(255, 255, 255, 0.035);
  --feedback-soft-border: rgba(230, 230, 230, 0.12);

  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.46);
}

.feedback-popover.library-form-surface {
  border-radius: 28px;
  box-shadow:
    0 0 0 2px var(--library-form-ring),
    0 24px 70px rgba(0, 0, 0, 0.28);
  animation: library-form-scan-in 420ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

.feedback-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  min-height: 22px;
}

.feedback-header strong {
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
}

.feedback-body {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(260px, 0.9fr) minmax(280px, 1fr);
  gap: var(--space-12);
}

.feedback-close,
.feedback-chip-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  background: transparent;
  color: var(--feedback-card-muted);
  cursor: pointer;
  transition:
    color 160ms ease,
    opacity 160ms ease,
    transform 180ms ease;
}

.feedback-close {
  width: 28px;
  height: 28px;
  border-radius: 50%;
}

.feedback-close:hover,
.feedback-chip-actions button:hover {
  color: var(--color-primary);
  transform: translateY(-1px);
}

.feedback-form {
  display: grid;
  gap: var(--space-8);
  align-content: start;
}

.feedback-form textarea {
  width: 100%;
  min-height: 178px;
  resize: vertical;
  padding: var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: var(--feedback-control-radius);
  outline: none;
  background: var(--feedback-field-bg);
  color: var(--feedback-card-text);
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  line-height: 1.5;
}

.feedback-form textarea:focus {
  border-color: var(--color-primary);
}

.feedback-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-8);
  min-height: 32px;
}

.feedback-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
}

.feedback-status {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.feedback-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  min-height: 32px;
  min-width: 82px;
  padding: 0 var(--space-14);
  border: 0;
  border-radius: 999px;
  background: var(--color-primary);
  color: #ffffff;
  cursor: pointer;
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
  white-space: nowrap;
  transition:
    background 180ms ease,
    box-shadow 180ms ease,
    opacity 160ms ease,
    transform 180ms ease;
}

.feedback-submit:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-primary) 88%, #ffffff 12%);
  transform: translateY(-1px);
}

.feedback-submit:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.feedback-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 0 var(--space-10);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--feedback-card-muted);
  cursor: pointer;
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  transition:
    color 160ms ease,
    transform 180ms ease;
}

.feedback-secondary:hover:not(:disabled) {
  color: var(--color-primary);
  transform: translateY(-1px);
}

.feedback-submit:disabled,
.feedback-secondary:disabled {
  cursor: default;
  opacity: 0.55;
}

.feedback-stack {
  min-height: 0;
  max-height: 430px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-8);
  padding: 0 var(--space-4) 0 0;
}

.feedback-stack.empty {
  min-height: 178px;
  display: grid;
  place-items: center;
  padding: 0;
}

.feedback-empty {
  display: grid;
  min-height: auto;
  place-items: center;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--feedback-card-subtle);
  font-size: calc(12px * var(--font-scale));
}

.feedback-chip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--space-8);
  min-height: 42px;
  padding: var(--space-8) var(--space-8) var(--space-8) var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: var(--feedback-control-radius);
  background: var(--feedback-row-bg);
  transition:
    background 160ms ease,
    border-color 160ms ease;
}

.feedback-chip:hover {
  border-color: color-mix(in srgb, var(--color-primary) 45%, var(--color-border) 55%);
  background: color-mix(in srgb, var(--feedback-row-bg) 88%, var(--color-primary) 12%);
}

.feedback-chip-main {
  min-width: 0;
  display: grid;
  gap: var(--space-6);
  border: 0;
  background: transparent;
  color: var(--feedback-card-text);
  text-align: left;
  cursor: pointer;
}

.feedback-chip-line {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-8);
}

.feedback-chip-content {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: calc(12px * var(--font-scale));
  line-height: 1.35;
}

.feedback-chip-main time {
  flex: 0 0 auto;
  color: var(--feedback-card-muted);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.2;
  white-space: nowrap;
}

.feedback-chip-full {
  min-width: 0;
  color: var(--feedback-card-text);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  animation: feedback-expand-in 140ms ease;
}

.feedback-chip-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
}

.feedback-chip-actions button {
  width: 26px;
  height: 26px;
  border-radius: 50%;
}

@keyframes feedback-expand-in {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 720px) {
  .feedback-backdrop {
    padding: var(--space-12);
  }

  .feedback-popover {
    max-height: calc(100vh - 24px);
    border-radius: 24px;
  }

  .feedback-body {
    grid-template-columns: 1fr;
  }

  .feedback-stack {
    max-height: 240px;
  }
}
</style>
