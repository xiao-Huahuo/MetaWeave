<!-- Page-level Kanban board for durable, independently running Agent tasks. -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AgentQueueTaskCard from '@/components/agent_queue/AgentQueueTaskCard.vue'
import AgentQueueTaskDialog from '@/components/agent_queue/AgentQueueTaskDialog.vue'
import { continueQueueTask, createQueueTask, deleteQueueTask, transitionQueueTask, updateQueueSettings, updateQueueTask, type AgentQueuePriority, type AgentQueueTask } from '@/api/agentQueue'
import { deleteAgentAttachment, uploadAgentAttachment } from '@/api/agent'
import { createSession, deleteSession } from '@/api/session'
import QueueBoardShell from '@/components/common/QueueBoardShell.vue'
import { useAgentQueueStore } from '@/stores/agentQueue'
import { useSettingsStore } from '@/stores/settings'
import type { AgentUploadedAttachment } from '@/stores/chat'

defineOptions({ name: 'AgentQueueView', inheritAttrs: false })

const settings = useSettingsStore(), queue = useAgentQueueStore()
const historyMode = ref(false), dialogOpen = ref(false), selected = ref<AgentQueueTask | null>(null), attachments = ref<AgentUploadedAttachment[]>([]), uploading = ref(false)
const concurrencyValue = ref('5')
const concurrencyOptions = Array.from({ length: 10 }, (_, index) => ({ value: String(index + 1), label: String(index + 1) }))
let pollId: number | null = null
const userId = () => settings.profile.userId
async function refresh() { await queue.load(userId(), historyMode.value); concurrencyValue.value = String(queue.maxConcurrency) }
/** Switch the shared queue shell and load the matching persistent task set. */
function switchPage(nextHistoryMode: boolean) { historyMode.value = nextHistoryMode; void refresh() }
function openNew() { selected.value = null; attachments.value = []; sessionForDraft.value = ''; dialogOpen.value = true }
function openTask(task: AgentQueueTask) { selected.value = task; attachments.value = task.attachments; dialogOpen.value = true }
async function upload(files: File[]) { if (!files.length) return; uploading.value = true; try { if (!sessionForDraft.value) sessionForDraft.value = (await createSession(userId(), '待执行任务')).session_id; for (const file of files) attachments.value.push((await uploadAgentAttachment(userId(), sessionForDraft.value, file)).attachment) } finally { uploading.value = false } }
const sessionForDraft = ref('')
async function create(prompt: string, priority: AgentQueuePriority) { let sessionId = sessionForDraft.value; if (!sessionId) sessionId = (await createSession(userId(), prompt.slice(0, 80))).session_id; await createQueueTask({ user_id: userId(), prompt, priority, attachments: attachments.value, session_id: sessionId }); sessionForDraft.value = ''; dialogOpen.value = false; await refresh() }
async function closeDialog() { if (!selected.value && sessionForDraft.value) await deleteSession(sessionForDraft.value); sessionForDraft.value = ''; dialogOpen.value = false }
async function removeAttachment(item: AgentUploadedAttachment) { const sessionId = selected.value?.session_id || sessionForDraft.value; if (sessionId) await deleteAgentAttachment(userId(), sessionId, item.attachment_id); attachments.value = attachments.value.filter(entry => entry.attachment_id !== item.attachment_id) }
async function transition(task: AgentQueueTask, status: 'confirmed' | 'terminated') { await transitionQueueTask(task.task_id, userId(), status); dialogOpen.value = false; await refresh() }
async function update(task: AgentQueueTask, prompt: string, priority: AgentQueuePriority) { await updateQueueTask(task.task_id, { user_id: userId(), prompt, priority, attachments: attachments.value }); dialogOpen.value = false; await refresh() }
async function removeTask(task: AgentQueueTask) { await deleteQueueTask(task.task_id, userId()); dialogOpen.value = false; await refresh() }
async function continueTask(task: AgentQueueTask, prompt: string) { await continueQueueTask(task.task_id, { user_id: userId(), prompt, attachments: attachments.value }); dialogOpen.value = false; await refresh() }
async function saveConcurrency(value: string) { await updateQueueSettings(userId(), Number(value)); await refresh() }
onMounted(() => { void refresh(); pollId = window.setInterval(() => void refresh(), 1500) })
onBeforeUnmount(() => { if (pollId !== null) window.clearInterval(pollId) })
</script>
<template>
  <QueueBoardShell
    v-bind="$attrs"
    :history-mode="historyMode"
    board-label="Issue 看板"
    new-label="新建任务"
    :concurrency="concurrencyValue"
    :concurrency-options="concurrencyOptions"
    @switch-page="switchPage"
    @new-task="openNew"
    @update-concurrency="saveConcurrency"
  >
    <template #board>
      <div class="queue-lane"><h2 class="queue-column-title pending">等待认领 <small>{{ queue.pending.length }}</small></h2><section><TransitionGroup name="queue-card" tag="div" class="queue-column"><AgentQueueTaskCard v-for="task in queue.pending" :key="task.task_id" :task="task" @select="openTask" @remove-task="removeTask" /></TransitionGroup></section></div>
      <div class="queue-lane"><h2 class="queue-column-title running">处理中 <small>{{ queue.running.length }}</small></h2><section><TransitionGroup name="queue-card" tag="div" class="queue-column"><AgentQueueTaskCard v-for="task in queue.running" :key="task.task_id" :task="task" @select="openTask" @terminate="transition($event, 'terminated')" /></TransitionGroup></section></div>
      <div class="queue-lane"><h2 class="queue-column-title review">等待确认 <small>{{ queue.review.length }}</small></h2><section><TransitionGroup name="queue-card" tag="div" class="queue-column"><AgentQueueTaskCard v-for="task in queue.review" :key="task.task_id" :task="task" @select="openTask" @confirm="transition($event, 'confirmed')" /></TransitionGroup></section></div>
    </template>
    <template #history>
      <div class="queue-lane"><h2 class="queue-column-title confirmed">已确认 <small>{{ queue.history.filter(item => item.status === 'confirmed').length }}</small></h2><section><div class="queue-column"><AgentQueueTaskCard v-for="task in queue.history.filter(item => item.status === 'confirmed')" :key="task.task_id" :task="task" @select="openTask" /></div></section></div>
      <div class="queue-lane"><h2 class="queue-column-title terminated">已终止 <small>{{ queue.history.filter(item => item.status === 'terminated').length }}</small></h2><section><div class="queue-column"><AgentQueueTaskCard v-for="task in queue.history.filter(item => item.status === 'terminated')" :key="task.task_id" :task="task" @select="openTask" /></div></section></div>
    </template>
  </QueueBoardShell>
  <AgentQueueTaskDialog :open="dialogOpen" :task="selected" :attachments="attachments" :uploading="uploading" @close="closeDialog" @upload="upload" @remove="removeAttachment" @create="create" @update="update" @continue="continueTask" @remove-task="removeTask" @terminate="transition($event, 'terminated')" />
</template>
