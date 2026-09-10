<!--
  Shared queue-board page shell.

  Owns the toolbar, animated page switch, responsive lane grid, and list motion
  used by queue-style pages while domain components provide their own lanes.
-->
<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

import QueueDropdown from '@/components/agent_queue/QueueDropdown.vue'
import IcIcon from '@/components/common/IcIcon.vue'

interface QueueBoardOption {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  historyMode: boolean
  boardLabel: string
  historyLabel?: string
  newLabel: string
  concurrency: string
  concurrencyOptions?: QueueBoardOption[]
  historyColumns?: number
}>(), {
  historyLabel: '历史',
  concurrencyOptions: () => [],
  historyColumns: 2,
})

const emit = defineEmits<{
  switchPage: [historyMode: boolean]
  newTask: []
  updateConcurrency: [value: string]
}>()

const pageSwitchRef = ref<HTMLElement | null>(null)
const pageSliderStyle = ref({ width: '0px', left: '0px' })

/** Align the shared slider with the active button's rendered text width. */
function updatePageSlider(): void {
  nextTick(() => {
    const activeButton = pageSwitchRef.value?.querySelector('.queue-page-button.active') as HTMLElement | null
    if (!activeButton) return
    pageSliderStyle.value = { width: `${activeButton.offsetWidth}px`, left: `${activeButton.offsetLeft}px` }
  })
}

/** Emit one page-mode change and update the visual switch without owning data loading. */
function switchPage(historyMode: boolean): void {
  emit('switchPage', historyMode)
}

watch(() => props.historyMode, updatePageSlider)
onMounted(updatePageSlider)
</script>

<template>
  <section class="queue-page-shell">
    <header class="queue-topbar">
      <div ref="pageSwitchRef" class="queue-page-switch" aria-label="队列页面">
        <span class="queue-page-slider" :style="pageSliderStyle" aria-hidden="true"></span>
        <button class="queue-page-button" :class="{ active: !historyMode }" type="button" @click="switchPage(false)">
          <IcIcon name="checklist" :size="17" />
          <span>{{ boardLabel }}</span>
        </button>
        <button class="queue-page-button" :class="{ active: historyMode }" type="button" @click="switchPage(true)">
          <IcIcon name="history" :size="17" />
          <span>{{ historyLabel }}</span>
        </button>
      </div>
      <span class="queue-toolbar-separator" aria-hidden="true"></span>
      <div class="queue-toolbar-spacer"></div>
      <label class="queue-concurrency">
        <span>最大并行</span>
        <QueueDropdown
          v-if="concurrencyOptions.length"
          :model-value="concurrency"
          aria-label="最大并行任务数"
          :options="concurrencyOptions"
          @update:model-value="emit('updateConcurrency', $event)"
        />
        <strong v-else>{{ concurrency }}</strong>
      </label>
      <span class="queue-toolbar-separator" aria-hidden="true"></span>
      <button class="queue-new-task v1-icon-button" type="button" :title="newLabel" :aria-label="newLabel" @click="emit('newTask')">
        <IcIcon name="add" :size="17" />
      </button>
    </header>

    <Transition name="queue-switch" mode="out-in">
      <main :key="historyMode ? 'history' : 'board'" :class="historyMode ? `history-list history-columns-${historyColumns}` : 'queue-board'">
        <slot :name="historyMode ? 'history' : 'board'"></slot>
      </main>
    </Transition>
  </section>
</template>

<style scoped>
.queue-page-shell { display:flex; flex:1; min-height:0; flex-direction:column; overflow:auto; background:var(--color-canvas); }
.queue-topbar { display:flex; align-items:center; gap:var(--space-8); flex:0 0 auto; min-height:44px; padding:var(--space-8) var(--space-12); background:var(--color-panel-bg); font-size:calc(12px * var(--font-scale)); }
.queue-page-switch { position:relative; display:inline-grid; grid-template-columns:repeat(2, auto); align-items:center; gap:var(--space-2); padding:2px; border:1px solid var(--color-border); border-radius:999px; background:var(--color-canvas); }
.queue-page-slider { position:absolute; top:2px; height:calc(100% - 4px); border-radius:999px; background:var(--color-primary-softer); transition:left 250ms ease, width 250ms ease; pointer-events:none; }
.queue-page-button { position:relative; z-index:1; display:inline-flex; align-items:center; justify-content:center; gap:var(--space-6); height:28px; padding:0 var(--space-8); border:0; border-radius:999px; background:transparent; color:var(--color-text-secondary); font:inherit; font-size:calc(12px * var(--font-scale)); line-height:1; cursor:pointer; outline:none; }
.queue-page-button > span { display:block; line-height:1; }
.queue-page-button:hover,.queue-page-button.active { color:var(--color-primary); }
.queue-toolbar-separator { display:block; width:1px; height:22px; margin:0 var(--space-2); background:var(--color-border); }
.queue-toolbar-spacer { flex:1 1 auto; min-width:0; }
.queue-concurrency { display:inline-flex; align-items:center; gap:var(--space-6); min-height:28px; padding:0 var(--space-8); border:1px solid var(--color-border); border-radius:999px; background:var(--color-canvas); color:var(--color-text-secondary); font:inherit; font-size:calc(12px * var(--font-scale)); }
.queue-concurrency :deep(.queue-select) { width:30px; }
.queue-concurrency strong { min-width:16px; color:var(--color-text-primary); font:650 calc(12px * var(--font-scale)) var(--font-ui); text-align:center; }
.queue-new-task { display:inline-flex; align-items:center; justify-content:center; gap:var(--space-6); width:auto; height:28px; padding:0 var(--space-8); border:0; border-radius:var(--radius-sm); background:transparent; color:var(--color-text-secondary); font:inherit; font-size:calc(12px * var(--font-scale)); cursor:pointer; }
.queue-new-task:hover { background:var(--color-primary-softer); color:var(--color-primary); }
.queue-new-task:active { transform:scale(.98); }
.queue-board,.history-list { display:grid; flex:1 1 auto; min-height:0; margin:20px 24px 24px; }
.queue-board { grid-template-columns:repeat(3,minmax(220px,1fr)); gap:16px; }
.history-list { grid-template-columns:repeat(2,minmax(260px,1fr)); gap:16px; }
.history-list.history-columns-3 { grid-template-columns:repeat(3,minmax(220px,1fr)); }
:deep(.queue-lane) { display:flex; min-width:0; min-height:0; flex-direction:column; gap:var(--space-10); }
:deep(.queue-lane > section) { display:flex; min-height:0; flex:1 1 auto; flex-direction:column; padding:var(--space-8); border:0; border-radius:28px; background:var(--color-surface); box-shadow:0 0 0 4px var(--library-form-ring); }
:deep(.queue-column-title) { display:flex; flex:0 0 auto; align-items:center; justify-content:space-between; width:100%; min-height:32px; margin:0; padding:0 var(--space-12); border-radius:999px; font:650 calc(13px * var(--font-scale)) var(--font-ui); }
:deep(.queue-column-title small) { font:650 calc(11px * var(--font-scale)) var(--font-ui); opacity:.78; }
:deep(.queue-column-title.pending) { background:var(--color-primary-softer); color:var(--color-primary); }
:deep(.queue-column-title.running) { background:color-mix(in srgb,var(--color-warning) 18%,transparent); color:var(--color-warning); }
:deep(.queue-column-title.review),:deep(.queue-column-title.confirmed) { background:color-mix(in srgb,var(--color-success) 16%,transparent); color:var(--color-success); }
:deep(.queue-column-title.terminated) { background:color-mix(in srgb,var(--color-danger) 14%,transparent); color:var(--color-danger); }
:deep(.queue-column-title.history) { background:var(--color-primary-softer); color:var(--color-primary); }
:deep(.queue-column) { display:grid; flex:1 1 auto; min-height:0; align-content:start; gap:var(--space-12); padding:4px; margin:-4px; overflow:auto; }
:deep(.queue-card-enter-active),:deep(.queue-card-leave-active) { transition:opacity 180ms ease, transform 180ms ease; }
:deep(.queue-card-enter-from),:deep(.queue-card-leave-to) { opacity:0; transform:translateY(8px); }
.queue-switch-enter-active,.queue-switch-leave-active { transition:opacity 160ms ease; }
.queue-switch-enter-from,.queue-switch-leave-to { opacity:0; }
@media (max-width:1024px) { .queue-board { gap:12px; margin-right:16px; margin-left:16px; } }
@media (max-width:768px) { .queue-board,.history-list { grid-template-columns:1fr; margin:14px 12px 18px; }.queue-topbar { flex-wrap:wrap; }.queue-toolbar-spacer { display:none; }.queue-concurrency { margin-left:auto; } }
@media (max-width:480px) { .queue-topbar { gap:var(--space-4); padding:var(--space-6) var(--space-8); }.queue-toolbar-separator { display:none; }.queue-concurrency { order:3; margin-left:0; }.queue-new-task { margin-left:auto; }.queue-board,.history-list { margin:10px 8px 14px; } }
@media (prefers-reduced-motion:reduce) { .queue-page-slider,.queue-new-task,.queue-switch-enter-active,.queue-switch-leave-active,:deep(.queue-card-enter-active),:deep(.queue-card-leave-active) { transition:none; } }
</style>
