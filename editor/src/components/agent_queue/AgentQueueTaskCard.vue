<!-- Compact task card shared by the three Agent queue columns. -->
<script setup lang="ts">
import { computed } from 'vue'
import type { AgentQueueTask } from '@/api/agentQueue'
import LoadingState from '@/components/common/LoadingState.vue'
import IcIcon from '@/components/common/IcIcon.vue'
const props = defineProps<{ task: AgentQueueTask }>()
const emit = defineEmits<{
  select: [task: AgentQueueTask]
  terminate: [task: AgentQueueTask]
  removeTask: [task: AgentQueueTask]
  confirm: [task: AgentQueueTask]
}>()
const progress = computed(() => {
  const items = props.task.task_list?.items || []
  return { done: items.filter(item => item.status === 'completed').length, total: items.length }
})
const priorityLabel = { critical: '极高', high: '高', medium: '中', low: '低', whenever: '随便做' }
</script>
<template>
  <article class="queue-task-card" :class="`queue-task-card--${task.status}`">
    <button class="queue-task-open" type="button" @click="emit('select', task)">
    <span v-if="task.status !== 'pending' && task.status !== 'running'" class="queue-priority" :class="`priority-${task.priority}`">{{ priorityLabel[task.priority] }}</span>
    <div class="queue-task-title">
      <strong>{{ task.prompt }}</strong>
      <LoadingState v-if="task.status === 'running'" label="Thinking" :show-elapsed="false" />
    </div>
    <div v-if="task.status === 'running' && progress.total" class="queue-progress" :aria-label="`任务进度 ${progress.done}/${progress.total}`">
      <i v-for="index in progress.total" :key="index" :class="{ done: index <= progress.done }"></i>
    </div>
    </button>
    <button v-if="task.status === 'running'" class="queue-card-action queue-card-terminate" type="button" title="终止任务" aria-label="终止任务" @click="emit('terminate', task)"><IcIcon name="stop" :size="17" /></button>
    <div v-if="task.status === 'pending'" class="queue-card-top-actions">
      <span class="queue-priority" :class="`priority-${task.priority}`">{{ priorityLabel[task.priority] }}</span>
      <button class="queue-card-detail" type="button" title="查看详情" aria-label="查看详情" @click="emit('select', task)"><IcIcon name="info" :size="17" /></button>
      <button class="queue-card-action queue-card-remove" type="button" title="删除任务" aria-label="删除任务" @click="emit('removeTask', task)"><IcIcon name="trash" :size="16" /></button>
    </div>
    <div v-if="task.status === 'running'" class="queue-card-top-actions">
      <button class="queue-card-detail" type="button" title="查看详情" aria-label="查看详情" @click="emit('select', task)"><IcIcon name="info" :size="17" /></button>
      <span class="queue-priority" :class="`priority-${task.priority}`">{{ priorityLabel[task.priority] }}</span>
    </div>
    <div v-if="task.status === 'review'" class="queue-card-review-actions">
      <button class="queue-card-detail" type="button" title="查看详情" aria-label="查看详情" @click="emit('select', task)"><IcIcon name="info" :size="17" /></button>
      <button class="queue-card-confirm" type="button" @click="emit('confirm', task)"><IcIcon name="check" :size="14" />确认</button>
    </div>
  </article>
</template>
<style scoped>
.queue-task-card { position:relative; width:100%; min-height:88px; border:1px solid var(--color-border); border-radius:20px; background:var(--color-surface); color:var(--color-text); transition:background var(--transition-fast), border-color var(--transition-fast); }
.queue-task-card:hover { background:var(--color-surface-raised); }
.queue-task-open { display:grid; gap:12px; width:100%; min-height:86px; padding:14px; border:0; border-radius:inherit; background:transparent; color:inherit; text-align:left; cursor:pointer; }
.queue-task-title { display:flex; align-items:flex-start; gap:8px; padding-right:44px; }.queue-task-title strong { flex:0 1 auto; min-width:0; font:600 calc(13px * var(--font-scale))/1.45 var(--font-ui); overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; }.queue-task-title .loading-state { flex:0 0 auto; margin-top:5px; gap:10px; }
.queue-task-card--pending .queue-task-title { padding-right:94px; }
.queue-task-card--running .queue-task-title { padding-right:76px; padding-left:26px; }
.queue-priority { position: absolute; top: 12px; right: 12px; font: 650 calc(10px * var(--font-scale))/1 var(--font-ui); color: var(--color-text-muted); }
.queue-card-top-actions { position:absolute; top:7px; right:7px; z-index:1; display:flex; align-items:center; gap:4px; }
.queue-card-top-actions .queue-priority { position:static; margin:0 2px; }
.priority-critical { color: #ef476f; }.priority-high { color: #d18b45; }.priority-medium { color: var(--color-primary); }.priority-low { color: #48a868; }
.queue-progress { display: flex; gap: 2px; width: 100%; }.queue-progress i { height: 4px; flex: 1; border-radius: 999px; background: color-mix(in srgb, #22c55e 26%, transparent); }.queue-progress i.done { background: #22c55e; }
.queue-card-action { display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px; padding:0; border:0; border-radius:50%; background:transparent; cursor:pointer; }
.queue-card-terminate { top:10px; left:10px; color:var(--color-danger); }.queue-card-terminate:hover { background:color-mix(in srgb, var(--color-danger) 12%, transparent); }
.queue-card-terminate { position:absolute; z-index:1; }
.queue-card-remove { color:var(--color-text-tertiary); }.queue-card-remove:hover { background:color-mix(in srgb, var(--color-danger) 12%, transparent); color:var(--color-danger); }
.queue-task-card--review .queue-task-open { padding-bottom:48px; }
.queue-card-detail,.queue-card-confirm { display:inline-flex; align-items:center; justify-content:center; min-height:28px; border-radius:999px; background:transparent; cursor:pointer; }
.queue-card-detail { width:28px; padding:0; border:0; color:var(--color-text-secondary); }
.queue-card-detail:hover { background:var(--color-primary-softer); color:var(--color-primary); }
.queue-card-review-actions { position:absolute; right:12px; bottom:10px; z-index:1; display:flex; align-items:center; gap:8px; }
.queue-card-confirm { gap:4px; padding:0 12px; border:1px solid var(--color-success); color:var(--color-success); font:600 calc(12px * var(--font-scale))/1 var(--font-ui); }
.queue-card-confirm:hover { background:color-mix(in srgb, var(--color-success) 10%, transparent); }
</style>
