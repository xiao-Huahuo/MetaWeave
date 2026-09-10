<!-- Create, inspect, and action one Agent queue task. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import QueueDialogShell from '@/components/common/QueueDialogShell.vue'
import AttachmentBlocks from '@/components/editor_workspace/agent_chat/AttachmentBlocks.vue'
import AgentPanel from '@/components/editor_workspace/AgentPanel.vue'
import { useSettingsStore } from '@/stores/settings'
import type { AgentQueuePriority, AgentQueueTask } from '@/api/agentQueue'
import type { AgentUploadedAttachment } from '@/stores/chat'
const props = defineProps<{ open: boolean; task?: AgentQueueTask | null; uploading?: boolean; attachments: AgentUploadedAttachment[] }>()
const emit = defineEmits<{ close: []; create: [prompt: string, priority: AgentQueuePriority]; update: [task: AgentQueueTask, prompt: string, priority: AgentQueuePriority]; continue: [task: AgentQueueTask, prompt: string]; removeTask: [task: AgentQueueTask]; upload: [files: File[]]; remove: [item: AgentUploadedAttachment]; terminate: [task: AgentQueueTask] }>()
const prompt = ref(''), priority = ref<AgentQueuePriority>('medium'), fileInput = ref<HTMLInputElement | null>(null)
const settingsStore = useSettingsStore()
const isNew = computed(() => !props.task)
const priorityOptions: { value: AgentQueuePriority; label: string }[] = [
  { value: 'whenever', label: '随便做' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'critical', label: '极高' },
]
const priorityIndex = computed(() => priorityOptions.findIndex((option) => option.value === priority.value))
const priorityLabel = computed(() => priorityOptions[priorityIndex.value]?.label ?? '')
const taskProgress = computed(() => {
  const items = props.task?.task_list?.items ?? []
  return { total: items.length, done: items.filter((item) => item.status === 'completed').length }
})
watch(() => props.open, open => { if (open && props.task) { prompt.value = props.task.status === 'review' ? '' : props.task.prompt; priority.value = props.task.priority } else if (open) { prompt.value = ''; priority.value = 'medium' } })
function submit() { if (!prompt.value.trim()) return; if (isNew.value) emit('create', prompt.value.trim(), priority.value); else if (props.task?.status === 'pending') emit('update', props.task, prompt.value.trim(), priority.value); else if (props.task?.status === 'review') emit('continue', props.task, prompt.value.trim()) }
/** 从 Prompt 输入框接收拖入的全部文件。 */
function uploadDroppedFiles(event: DragEvent) { const files = Array.from(event.dataTransfer?.files ?? []); if (files.length) emit('upload', files) }
/** 读取系统文件选择器中的全部文件并清空原生输入。 */
function uploadSelectedFiles(event: Event) { const input = event.target as HTMLInputElement; emit('upload', Array.from(input.files ?? [])); input.value = '' }
</script>
<template><QueueDialogShell :open="open" :title="isNew ? '新建任务' : task?.status === 'running' ? '任务执行中' : task?.status === 'review' ? '等待确认' : '编辑任务'" :wide="Boolean((task?.status === 'running' || task?.status === 'review') && task.session_id)" :content-key="`${task?.task_id ?? 'new'}-${task?.status ?? ''}-${attachments.length}`" @close="emit('close')">
  <section v-if="isNew || task?.status === 'pending'" class="task-form"><div class="field field-prompt"><span>Prompt</span><div class="prompt-input-wrap"><textarea v-model="prompt" placeholder="描述希望 Agent 独立完成的任务；也可将附件拖到这里" @dragover.prevent @drop.prevent="uploadDroppedFiles" /><button class="attachment-add-btn" type="button" :disabled="uploading" title="添加附件" @click="fileInput?.click()"><IcIcon name="add" :size="17" /></button><input ref="fileInput" type="file" multiple hidden @change="uploadSelectedFiles"></div></div><div class="task-form-tools"><div class="field"><span>优先级</span><div class="priority-stars" role="radiogroup" aria-label="任务优先级"><button v-for="(option, index) in priorityOptions" :key="option.value" type="button" :class="{ active: index <= priorityIndex }" :title="option.label" :aria-label="option.label" :aria-checked="option.value === priority" role="radio" @click="priority = option.value"><IcIcon name="star" :size="17" /></button><span class="priority-label">{{ priorityLabel }}</span></div></div></div></section>
  <section v-else class="task-summary"><p class="task-summary-prompt">{{ task?.prompt }}</p><p class="task-summary-priority">优先级：{{ priorityLabel }}</p></section>
  <AttachmentBlocks v-if="attachments.length && (isNew || task?.status === 'pending')" class="task-attachments" :attachments="attachments" @remove="emit('remove', $event)" />
  <section v-if="(task?.status === 'running' || task?.status === 'review') && task.session_id" class="running-task-detail"><p v-if="task?.status === 'review'" class="task-elapsed">总耗时：{{ task.finished_at || task.started_at }}</p><div class="task-session-view"><AgentPanel mode="page" :session-id="task.session_id" :live-sync="task.status === 'running'" /></div><div v-if="taskProgress.total" class="task-progress" :aria-label="`任务进度 ${taskProgress.done}/${taskProgress.total}`"><i v-for="index in taskProgress.total" :key="index" :class="{ done: index <= taskProgress.done }"></i></div><label v-if="task?.status === 'review'" class="field continuation-field"><span>继续执行</span><textarea v-model="prompt" placeholder="输入下一轮任务，保留当前 Agent 上下文" /></label></section><section v-else-if="!isNew && task?.status !== 'pending'" class="task-detail"><p v-if="task?.started_at">总耗时：{{ task.finished_at || task.status === 'running' ? '已开始执行' : '等待执行' }}</p></section>
  <template #footer><button v-if="task?.status === 'pending'" class="danger-btn" type="button" @click="emit('removeTask', task)">删除任务</button><button v-else-if="task && task.status !== 'confirmed' && task.status !== 'terminated'" class="danger-btn" type="button" @click="emit('terminate', task)">终止任务</button><span></span><div class="submit-actions"><button class="secondary-btn" type="button" @click="emit('close')">取消</button><button v-if="isNew" class="primary-btn" type="button" @click="submit"><IcIcon name="save" :size="14" />创建</button><button v-else-if="task?.status === 'pending'" class="primary-btn" type="button" @click="submit"><IcIcon name="save" :size="14" />保存</button><button v-else-if="task?.status === 'review'" class="primary-btn" type="button" @click="submit">继续</button></div></template>
</QueueDialogShell></template>
<style scoped>
.queue-dialog-backdrop { position:fixed; inset:0; z-index:300; display:grid; place-items:center; background:rgba(0,0,0,.42); }.queue-dialog { display:grid; gap:14px; width:min(760px, calc(100vw - 32px)); max-height:calc(100vh - 32px); overflow:auto; border:1px solid var(--color-border); border-radius:28px; background:var(--color-surface); color:var(--color-text); font-size:calc(13px * var(--font-scale)); }.queue-dialog:has(.running-task-detail) { width:min(1280px, calc(100vw - 32px)); }.dialog-head { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:7px 16px; }.dialog-head h2 { margin:0; font-size:calc(15px * var(--font-scale)); }.icon-btn,.attachment-add-btn { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border:0; border-radius:50%; background:transparent; color:var(--color-text-muted); cursor:pointer; }.icon-btn:hover,.attachment-add-btn:hover { background:color-mix(in srgb, var(--color-text-secondary) 10%, transparent); color:var(--color-text); }.attachment-add-btn:disabled { cursor:wait; opacity:.62; }.task-form { display:grid; gap:14px; padding:0 16px; }.field { display:grid; gap:7px; min-width:0; color:var(--color-text-secondary); font-size:calc(12px * var(--font-scale)); }.prompt-input-wrap { position:relative; }.field textarea { width:100%; min-height:130px; border:1px solid var(--color-border); border-radius:28px; background:var(--color-canvas); color:var(--color-text); padding:10px 14px 42px; resize:vertical; font:inherit; outline:none; }.field textarea:focus { border-color:var(--color-primary); }.task-form-tools { display:flex; align-items:end; gap:8px; }.priority-stars { display:inline-flex; align-items:center; gap:2px; min-height:28px; }.priority-stars button { display:inline-flex; align-items:center; justify-content:center; width:24px; height:28px; border:0; background:transparent; color:var(--color-text-muted); cursor:pointer; }.priority-stars button.active { color:var(--color-primary); }.priority-stars button:disabled { cursor:default; }.priority-label { margin-left:var(--space-6); color:var(--color-text-secondary); font-size:calc(13px * var(--font-scale)); }.attachment-add-btn { position:absolute; bottom:10px; left:10px; border:1px solid var(--color-border); background:var(--color-surface-raised); }.task-attachments { margin:0 16px; }.task-detail,.running-task-detail { display:grid; gap:10px; padding:0 16px; color:var(--color-text-secondary); font-size:calc(12px * var(--font-scale)); }.task-detail p { margin:0; }.task-session-view { height:min(620px, 62vh); overflow:hidden; border:1px solid var(--color-border); border-radius:28px; background:var(--color-surface); }.task-progress { display:flex; gap:2px; width:100%; }.task-progress i { flex:1; height:4px; border-radius:999px; background:color-mix(in srgb, #22c55e 26%, transparent); }.task-progress i.done { background:#22c55e; }.dialog-actions { display:flex; align-items:center; gap:8px; padding:16px; }.dialog-actions>span { flex:1; }.submit-actions { display:inline-flex; align-items:center; gap:8px; }.secondary-btn,.primary-btn,.danger-btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:32px; border:1px solid var(--color-border); border-radius:999px; background:var(--color-surface-raised); color:var(--color-text); padding:0 16px; font:inherit; font-size:calc(13px * var(--font-scale)); cursor:pointer; }.primary-btn { border-color:var(--color-primary); background:var(--color-primary); color:#fff; }.danger-btn { border-color:var(--color-danger); color:var(--color-danger); }
.task-summary { display:grid; gap:6px; padding:0 16px; color:var(--color-text-secondary); }
.task-summary p { margin:0; }
.task-summary-prompt { color:var(--color-text); font-size:calc(14px * var(--font-scale)); line-height:1.6; white-space:pre-wrap; }
.task-summary-priority { font-size:calc(12px * var(--font-scale)); }
.task-elapsed { margin:0; color:var(--color-text-secondary); }
.continuation-field { padding-top:var(--space-4); }
.task-progress i { background:color-mix(in srgb, var(--color-success) 26%, transparent); }
.task-progress i.done { background:var(--color-success); }
</style>

<style scoped>
.queue-dialog {
  transition: height 280ms cubic-bezier(0.22, 1, 0.36, 1);
}

.queue-dialog .field textarea {
  border: 0 !important;
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-text) 6%) !important;
  transition: box-shadow var(--transition-fast);
}

.queue-dialog .field textarea:focus {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-border-strong) 50%, transparent) !important;
}
</style>
