<!--
  Todo sidebar panel.

  Usage:
  Renders inside the agent-col alongside AgentPanel. Shows ordinary TODO
  controls plus scheduler-aware automation status, pause, and safe deletion.
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, nextTick, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import CreativeCheckbox from '@/components/common/CreativeCheckbox.vue'
import { useTodoStore } from '@/stores/todo'

const todoStore = useTodoStore()

const newTodoText = ref('')
const newTodoDatetime = ref('')
const editingId = ref('')
const editingText = ref('')
const editingDate = ref('')
const deletingId = ref('')
const timeTick = ref(0)
const automationFormOpen = ref(false)
const newAutomationText = ref('')
const newAutomationPrompt = ref('')
const newAutomationRunAt = ref('')
const newAutomationFrequency = ref<'none' | 'daily' | 'weekly' | 'monthly'>('none')
const newAutomationAccessMode = ref<'readonly' | 'sandbox' | 'full_access'>('sandbox')
const automationSubmitting = ref(false)
const automationError = ref('')
const expandedAutomationId = ref('')
const confirmDeleteId = ref('')
const automationTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
const automationRunAtMin = ref(formatDatetimeLocalInput(new Date(Date.now() + 60_000)))

let tickTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  todoStore.refreshFromServer()
  tickTimer = setInterval(() => { timeTick.value = Date.now() }, 30000)
})

onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer)
})

function triggerPicker(target: 'new' | string) {
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>('#picker-' + target)
    if (el) {
      el.value = ''
      el.showPicker()
    }
  })
}

function onSharedPick(e: Event) {
  const el = e.target as HTMLInputElement
  const val = el.value
  const id = el.dataset.target
  if (!val || !id) return
  if (id === 'new') {
    newTodoDatetime.value = val
  } else {
    todoStore.setDueDate(id, val)
  }
}

function handleAdd() {
  const trimmed = newTodoText.value.trim()
  if (!trimmed) return
  todoStore.addTodo(trimmed, newTodoDatetime.value || undefined)
  newTodoText.value = ''
  newTodoDatetime.value = ''
}

async function handleAddAutomation() {
  const text = newAutomationText.value.trim()
  const prompt = newAutomationPrompt.value.trim()
  if (!text || !prompt || !newAutomationRunAt.value || automationSubmitting.value) return
  const runAt = new Date(newAutomationRunAt.value)
  if (Number.isNaN(runAt.getTime()) || runAt.getTime() <= Date.now()) {
    automationError.value = '首次执行时间必须晚于当前时间。'
    return
  }
  automationSubmitting.value = true
  automationError.value = ''
  const created = await todoStore.addAutomation(
    text,
    prompt,
    runAt.toISOString(),
    automationTimezone,
    { frequency: newAutomationFrequency.value, interval: 1 },
    newAutomationAccessMode.value,
  )
  automationSubmitting.value = false
  if (!created.success) {
    automationError.value = created.error || '自动化任务创建失败，请确认后端服务已重启并检查必填字段。'
    return
  }
  newAutomationText.value = ''
  newAutomationPrompt.value = ''
  newAutomationRunAt.value = ''
  newAutomationFrequency.value = 'none'
  newAutomationAccessMode.value = 'sandbox'
  automationError.value = ''
  automationFormOpen.value = false
}

/** Opens or closes the automation form and refreshes its native minimum time. */
function toggleAutomationForm(): void {
  automationFormOpen.value = !automationFormOpen.value
  if (automationFormOpen.value) {
    automationRunAtMin.value = formatDatetimeLocalInput(new Date(Date.now() + 60_000))
    automationError.value = ''
  }
}

function startEdit(id: string, text: string, dueDate?: string) {
  editingId.value = id
  editingText.value = text
  editingDate.value = dueDate || ''
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>(`.todo-edit-input[data-id="${id}"]`)
    el?.focus()
    el?.select()
  })
}

function commitEdit(id: string) {
  todoStore.editTodo(id, editingText.value)
  const item = todoStore.todos.find((todo) => todo.id === id)
  if (item?.category !== 'automation' && editingDate.value !== item?.dueDate) {
    todoStore.setDueDate(id, editingDate.value || undefined)
  }
  editingId.value = ''
  editingText.value = ''
  editingDate.value = ''
}

function cancelEdit() {
  editingId.value = ''
  editingText.value = ''
}

/** Starts a two-step automation deletion or immediately deletes an ordinary TODO. */
async function removeWithAnimation(id: string, confirmed = false): Promise<void> {
  if (deletingId.value) return
  const item = todoStore.todos.find((todo) => todo.id === id)
  if (item?.category === 'automation' && !confirmed) {
    confirmDeleteId.value = id
    expandedAutomationId.value = id
    return
  }
  deletingId.value = id
  const deleted = await todoStore.removeTodo(id)
  deletingId.value = ''
  if (deleted) {
    confirmDeleteId.value = ''
    if (expandedAutomationId.value === id) expandedAutomationId.value = ''
  }
}

/** Cancels the pending destructive confirmation without changing scheduler state. */
function cancelAutomationDelete(id: string): void {
  if (confirmDeleteId.value === id) confirmDeleteId.value = ''
}

/** Formats a local Date for the native datetime-local input value and min. */
function formatDatetimeLocalInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function formatDatetime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    if (iso.includes('T')) {
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      return `${y}-${m}-${day} ${hh}:${mm}`
    }
    return `${y}-${m}-${day}`
  } catch {
    return iso
  }
}

function isDatetimeExpired(iso: string): boolean {
  if (!iso) return false
  return new Date(iso).getTime() < Date.now()
}

function getAutomationNextRun(todoId: string): string | undefined {
  return getAutomation(todoId)?.nextRunAt
}

function getAutomation(todoId: string) {
  return todoStore.automations.find((item) => item.todoId === todoId)
}

/** Returns whether one automation mutation is currently awaiting the server. */
function isAutomationPending(todoId: string): boolean {
  return todoStore.automationPendingIds.has(todoId)
}

function formatAutomationState(todoId: string): string {
  const automation = getAutomation(todoId)
  if (!automation) return '状态待同步'
  if (automation.lastStatus === 'failed') return automation.enabled ? '上次失败' : '失败后暂停'
  if (automation.enabled) return '已启用'
  if (automation.recurrence.frequency === 'none' && automation.lastStatus === 'success') return '已完成'
  return '已暂停'
}

/** Maps scheduler state to the component's semantic status color. */
function automationStateKind(todoId: string): 'planned' | 'paused' | 'completed' | 'failed' | 'syncing' {
  const automation = getAutomation(todoId)
  if (!automation) return 'syncing'
  if (automation.lastStatus === 'failed') return 'failed'
  if (automation.recurrence.frequency === 'none' && automation.lastStatus === 'success' && !automation.enabled) {
    return 'completed'
  }
  return automation.enabled ? 'planned' : 'paused'
}

function formatAutomationLastRun(todoId: string): string {
  const automation = getAutomation(todoId)
  if (!automation?.lastRunAt) return '尚未执行'
  const labels: Record<string, string> = {
    success: '成功',
    failed: '失败',
    skipped: '已取消',
    running: '执行中',
  }
  return `${formatDatetime(automation.lastRunAt)} · ${labels[automation.lastStatus || ''] || '未知结果'}`
}

async function toggleAutomation(todoId: string): Promise<void> {
  const automation = getAutomation(todoId)
  if (!automation || isAutomationPending(todoId)) return
  await todoStore.setAutomationEnabled(todoId, !automation.enabled)
}

function toggleAutomationDetails(todoId: string) {
  expandedAutomationId.value = expandedAutomationId.value === todoId ? '' : todoId
}

function formatAutomationRecurrence(todoId: string): string {
  const recurrence = todoStore.automations.find((item) => item.todoId === todoId)?.recurrence
  if (!recurrence || recurrence.frequency === 'none') return '执行一次'
  const labels: Record<'daily' | 'weekly' | 'monthly', { singular: string; interval: string }> = {
    daily: { singular: '每天', interval: '天' },
    weekly: { singular: '每周', interval: '周' },
    monthly: { singular: '每月', interval: '个月' },
  }
  const label = labels[recurrence.frequency]
  return recurrence.interval > 1 ? `每 ${recurrence.interval} ${label.interval}` : label.singular
}

function formatAutomationAccessMode(todoId: string): string {
  const accessMode = todoStore.automations.find((item) => item.todoId === todoId)?.accessMode
  const labels: Record<'readonly' | 'sandbox' | 'full_access', string> = {
    readonly: '只读权限',
    sandbox: '沙盒权限',
    full_access: '完全访问',
  }
  return accessMode ? labels[accessMode] : '未知权限'
}

function getAutomationPrompt(todoId: string): string {
  return todoStore.automations.find((item) => item.todoId === todoId)?.prompt || '暂无描述'
}
</script>

<template>
  <div class="todo-sidebar">
    <div class="todo-header">
      <span class="todo-title">待办</span>
      <div class="todo-header-actions">
        <label class="todo-hide-done" title="隐藏已完成">
          <input type="checkbox" :checked="todoStore.hideDone" @change="todoStore.toggleHideDone()" />
          <span class="todo-toggle-track">
            <span class="todo-toggle-thumb" />
          </span>
          <span>隐藏已完成</span>
        </label>
        <button
          class="todo-clear-done"
          type="button"
          :class="{ spinning: todoStore.pending.has('refresh') }"
          title="从服务器刷新"
          :disabled="todoStore.pending.has('refresh')"
          @click="todoStore.refreshFromServer()"
        >
          <IcIcon name="refresh" :size="12" />
        </button>
        <button
          class="todo-clear-done"
          type="button"
          title="清除已完成"
          :disabled="!todoStore.todos.some((t) => t.category !== 'automation' && t.done)"
          @click="todoStore.clearDone()"
        >
          <IcIcon name="trash" :size="12" />
        </button>
      </div>
    </div>

    <div class="todo-toolbar">
      <div class="todo-search">
        <IcIcon name="search" :size="12" class="todo-search-icon" />
        <input
          v-model="todoStore.searchQuery"
          class="todo-search-input"
          type="text"
          placeholder="搜索待办…"
          spellcheck="false"
        />
        <button
          v-if="todoStore.searchQuery"
          class="todo-search-clear"
          type="button"
          @click="todoStore.searchQuery = ''"
        >
          <IcIcon name="close" :size="10" />
        </button>
      </div>
    </div>

    <div class="todo-list" :data-tick="timeTick">
      <div
        v-for="item in todoStore.filteredTodos"
        :key="item.id"
        class="todo-item"
        :data-todo-id="item.id"
        :aria-busy="item.category === 'automation' && isAutomationPending(item.id) ? 'true' : 'false'"
        :class="{
          'todo-automation-item': item.category === 'automation',
          'todo-done': item.category !== 'automation' && item.done,
          'todo-overdue': item.category !== 'automation' && todoStore.overdueIds.has(item.id) && !item.done,
          'todo-deleting': deletingId === item.id,
        }"
      >
        <span v-if="item.category === 'automation'" class="todo-automation-icon" title="自动化任务">
          <IcIcon name="schedule" :size="16" />
        </span>
        <CreativeCheckbox v-else :model-value="item.done" :label="item.done ? '标记未完成' : '标记完成'"
          @update:model-value="todoStore.toggleTodo(item.id)" />

        <div class="todo-body">
          <div class="todo-title-row">
            <div v-if="editingId === item.id" class="todo-edit-wrap">
              <input
                :data-id="item.id"
                v-model="editingText"
                class="todo-edit-input"
                type="text"
                spellcheck="false"
                @blur="commitEdit(item.id)"
                @keydown.enter.prevent="commitEdit(item.id)"
                @keydown.escape.prevent="cancelEdit"
              />
            </div>
            <span
              v-else
              class="todo-text"
              :title="item.text"
              @dblclick="startEdit(item.id, item.text, item.category === 'automation' ? undefined : item.dueDate)"
            >
              {{ item.text }}
            </span>
            <span
              v-if="item.category === 'automation'"
              class="todo-automation-state"
              :data-status="automationStateKind(item.id)"
            >
              {{ formatAutomationState(item.id) }}
            </span>
            <button
              v-if="item.category === 'automation'"
              class="todo-automation-expand"
              type="button"
              :title="expandedAutomationId === item.id ? '收起自动化详情' : '展开自动化详情'"
              :aria-label="expandedAutomationId === item.id ? '收起自动化详情' : '展开自动化详情'"
              :aria-expanded="expandedAutomationId === item.id"
              @click.stop="toggleAutomationDetails(item.id)"
            >
              <IcIcon name="chevron-right" :size="12" :class="{ expanded: expandedAutomationId === item.id }" />
            </button>
          </div>
          <div v-if="item.category === 'automation'" class="todo-date-col todo-automation-next-run">
            <IcIcon name="schedule" :size="10" />
            <span
              class="todo-date"
              :class="{
                expired: !!getAutomation(item.id)?.enabled
                  && isDatetimeExpired(getAutomationNextRun(item.id) || ''),
              }"
            >
              {{ getAutomation(item.id)?.enabled ? '下次 ' : '计划时间 ' }}{{ formatDatetime(getAutomationNextRun(item.id) || '') || '待同步' }}
            </span>
          </div>
          <div v-else-if="item.dueDate" class="todo-date-col">
            <IcIcon name="calendar" :size="10" />
            <span class="todo-date" :class="{ expired: isDatetimeExpired(item.dueDate) && !item.done }">
              {{ formatDatetime(item.dueDate) }}
            </span>
            <button
              class="todo-date-clear"
              type="button"
              title="清除日期"
              @click="todoStore.setDueDate(item.id, undefined)"
            >
              <IcIcon name="close" :size="10" />
            </button>
          </div>
          <div
            v-if="item.category === 'automation' && expandedAutomationId === item.id"
            class="todo-automation-details"
          >
            <div class="todo-automation-detail-row">
              <span>状态</span>
              <strong>{{ formatAutomationState(item.id) }}</strong>
            </div>
            <div class="todo-automation-detail-row">
              <span>时间</span>
              <strong>{{ formatDatetime(getAutomationNextRun(item.id) || '') || '未设置' }}</strong>
            </div>
            <div class="todo-automation-detail-row">
              <span>时区</span>
              <strong>{{ getAutomation(item.id)?.timezone || '待同步' }}</strong>
            </div>
            <div class="todo-automation-detail-row">
              <span>权限</span>
              <strong>{{ formatAutomationAccessMode(item.id) }}</strong>
            </div>
            <div class="todo-automation-detail-row">
              <span>周期</span>
              <strong>{{ formatAutomationRecurrence(item.id) }}</strong>
            </div>
            <div class="todo-automation-detail-row">
              <span>最近结果</span>
              <strong>{{ formatAutomationLastRun(item.id) }}</strong>
            </div>
            <div v-if="getAutomation(item.id)?.lastError" class="todo-automation-detail-row todo-automation-last-error">
              <span>错误</span>
              <strong>{{ getAutomation(item.id)?.lastError }}</strong>
            </div>
            <div class="todo-automation-detail-row todo-automation-detail-description">
              <span>描述</span>
              <p>{{ getAutomationPrompt(item.id) }}</p>
            </div>
          </div>
          <p
            v-if="todoStore.automationActionErrors[item.id]"
            class="todo-automation-action-error"
            role="alert"
          >
            {{ todoStore.automationActionErrors[item.id] }}
          </p>
          <div
            v-if="item.category === 'automation' && confirmDeleteId === item.id"
            class="todo-automation-delete-confirm"
            role="group"
            :aria-label="`确认删除自动化：${item.text}`"
          >
            <p>将取消未来执行并删除运行记录，此操作不可撤销。</p>
            <div class="todo-automation-delete-actions">
              <button
                type="button"
                :aria-label="`取消删除自动化：${item.text}`"
                :disabled="isAutomationPending(item.id)"
                @click="cancelAutomationDelete(item.id)"
              >
                取消
              </button>
              <button
                type="button"
                class="danger"
                :aria-label="`确认删除自动化：${item.text}`"
                :disabled="isAutomationPending(item.id)"
                @click="removeWithAnimation(item.id, true)"
              >
                {{ isAutomationPending(item.id) ? '正在取消…' : '确认删除' }}
              </button>
            </div>
          </div>
        </div>

        <div class="todo-actions">
          <button
            class="todo-action-btn"
            type="button"
            title="编辑"
            :aria-label="`编辑任务：${item.text}`"
            :disabled="item.category === 'automation' && isAutomationPending(item.id)"
            @click="startEdit(item.id, item.text, item.category === 'automation' ? undefined : item.dueDate)"
          >
            <IcIcon name="edit" :size="11" />
          </button>
          <button
            v-if="item.category === 'automation'"
            class="todo-action-btn todo-automation-toggle-action"
            type="button"
            :title="getAutomation(item.id)?.enabled ? '暂停自动化' : '恢复自动化'"
            :aria-label="`${getAutomation(item.id)?.enabled ? '暂停' : '恢复'}自动化：${item.text}`"
            :disabled="isAutomationPending(item.id) || !getAutomation(item.id)"
            @click="toggleAutomation(item.id)"
          >
            <IcIcon :name="getAutomation(item.id)?.enabled ? 'pause' : 'play'" :size="11" morph />
          </button>
          <button
            v-else
            class="todo-action-btn"
            type="button"
            :title="item.dueDate ? '修改日期' : '添加日期'"
            :aria-label="`${item.dueDate ? '修改' : '添加'}任务日期：${item.text}`"
            @click="triggerPicker(item.id)"
          >
            <IcIcon name="calendar" :size="11" />
          </button>
          <input
            v-if="item.category !== 'automation'"
            :id="'picker-' + item.id"
            class="todo-inline-picker"
            type="datetime-local"
            :data-target="item.id"
            @change="onSharedPick"
          />
          <button
            class="todo-action-btn todo-action-remove"
            type="button"
            :title="item.category === 'automation' ? '删除自动化' : '删除'"
            :aria-label="item.category === 'automation' ? `删除自动化：${item.text}` : `删除任务：${item.text}`"
            :disabled="item.category === 'automation' && isAutomationPending(item.id)"
            @click="removeWithAnimation(item.id)"
          >
            <IcIcon name="trash" :size="11" />
          </button>
        </div>
      </div>

      <div v-if="todoStore.filteredTodos.length === 0" class="todo-empty">
        暂无待办
      </div>
    </div>

    <form v-if="automationFormOpen" class="todo-automation-form" @submit.prevent="handleAddAutomation">
      <div class="todo-automation-heading">
        <span>新建自动化任务</span>
        <button
          class="todo-automation-close"
          type="button"
          title="关闭"
          aria-label="关闭自动化任务表单"
          :disabled="automationSubmitting"
          @click="automationFormOpen = false"
        >
          <IcIcon name="close" :size="12" />
        </button>
      </div>
      <label class="todo-automation-field">
        <span>任务名称</span>
        <input
          v-model="newAutomationText"
          class="todo-automation-input"
          type="text"
          aria-label="自动化任务名称"
          placeholder="例如：生成每周总结"
          :disabled="automationSubmitting"
        />
      </label>
      <label class="todo-automation-field">
        <span>执行指令</span>
        <textarea
          v-model="newAutomationPrompt"
          class="todo-automation-input todo-automation-prompt"
          rows="2"
          aria-label="自动化执行指令"
          placeholder="到时间后让 Agent 做什么？"
          :disabled="automationSubmitting"
        />
      </label>
      <div class="todo-automation-row">
        <label class="todo-automation-field">
          <span>首次执行</span>
          <input
            v-model="newAutomationRunAt"
            class="todo-automation-input"
            type="datetime-local"
            aria-label="首次执行时间"
            :min="automationRunAtMin"
            :disabled="automationSubmitting"
            @input="automationError = ''"
          />
        </label>
        <label class="todo-automation-field">
          <span>重复</span>
          <select
            v-model="newAutomationFrequency"
            class="todo-automation-select"
            aria-label="重复周期"
            :disabled="automationSubmitting"
          >
            <option value="none">执行一次</option>
            <option value="daily">每天</option>
            <option value="weekly">每周</option>
            <option value="monthly">每月</option>
          </select>
        </label>
      </div>
      <p class="todo-automation-timezone">任务时区：{{ automationTimezone }}</p>
      <div class="todo-automation-row">
        <label class="todo-automation-field">
          <span>运行权限</span>
          <select
            v-model="newAutomationAccessMode"
            class="todo-automation-select"
            aria-label="运行权限"
            :disabled="automationSubmitting"
          >
            <option value="sandbox">沙盒权限</option>
            <option value="readonly">只读权限</option>
            <option value="full_access">完全访问</option>
          </select>
        </label>
        <button
          class="todo-add-btn todo-automation-submit"
          type="submit"
          aria-label="创建自动化任务"
          title="创建自动化任务"
          :disabled="automationSubmitting || !newAutomationText.trim() || !newAutomationPrompt.trim() || !newAutomationRunAt"
        >
          <IcIcon v-if="automationSubmitting" name="refresh" :size="14" class="todo-automation-spinner" />
          <IcIcon v-else name="add" :size="14" />
        </button>
      </div>
      <p v-if="newAutomationAccessMode === 'full_access'" class="todo-automation-warning" role="note">
        完全访问权限允许任务修改工作区文件并执行受支持的操作，请确认指令可信。
      </p>
      <p v-if="automationError" class="todo-automation-error" role="alert">{{ automationError }}</p>
    </form>

    <div class="todo-add-bar">
      <div class="todo-add-row">
        <button
          class="todo-add-automation-btn"
          type="button"
          :class="{ active: automationFormOpen }"
          title="新建自动化任务"
          aria-label="新建自动化任务"
          @click="toggleAutomationForm"
        >
          <IcIcon name="schedule" :size="14" />
        </button>
        <input
          v-model="newTodoText"
          class="todo-add-input"
          type="text"
          placeholder="添加新待办…"
          spellcheck="false"
          @keydown.enter.prevent="handleAdd"
        />
        <button
          class="todo-add-cal-btn"
          type="button"
          :title="newTodoDatetime ? '修改时间' : '添加时间'"
          :class="{ hasDate: !!newTodoDatetime }"
          @click="triggerPicker('new')"
        >
          <IcIcon name="calendar" :size="14" />
        </button>
        <input id="picker-new" class="todo-inline-picker" type="datetime-local" data-target="new" @change="onSharedPick" />
        <button
          class="todo-add-btn"
          :disabled="!newTodoText.trim()"
          type="button"
          title="添加"
          @click="handleAdd"
        >
          <IcIcon name="add" :size="14" />
        </button>
      </div>
      <div v-if="newTodoDatetime" class="todo-new-date-display">
        <IcIcon name="calendar" :size="10" />
        <span>{{ formatDatetime(newTodoDatetime) }}</span>
        <button
          class="todo-date-clear"
          type="button"
          title="清除日期"
          @click="newTodoDatetime = ''"
        >
          <IcIcon name="close" :size="10" />
        </button>
      </div>
    </div>
  </div>
</template>

<style src="./TodoSidebar.css" scoped></style>
