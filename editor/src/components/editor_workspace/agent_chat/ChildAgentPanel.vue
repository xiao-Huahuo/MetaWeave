<!--
  主 Agent 会话内的子 Agent 控制区。

  用途：展示主 Agent 已召唤的子任务，按任务目标(goal)合并展示。折叠态只显示
  头像、名字、类别(英文)、前后台模式和状态，展开后才显示该目标下各次运行的
  详情。用户不能通过此组件创建子 Agent；子 Agent 只能由主 Agent 的运行时工具召唤。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import { fetchChildAgentDshWeb, fetchChildAgents, stopChildAgent } from '@/api/agent'
import type { ChildAgentRecord } from '@/api/agent'
import { getChildAgentAvatar } from '@/utils/childAgentAvatar'
import { preloadChildAgentConversations } from '@/components/editor_workspace/agent_chat/childAgentConversations'
import { useWorkspaceStore } from '@/stores/workspace'

const props = defineProps<{
  sessionId: string
  userId: string
}>()

const workspaceStore = useWorkspaceStore()

const emit = defineEmits<{
  close: []
  'open-conversation': [child: ChildAgentRecord]
  /** DSH Web 已交给浏览器侧栏，通知父组件收起旧 Agent 详情列。 */
  'open-dsh-web': []
  'children-update': [children: ChildAgentRecord[]]
}>()

const children = ref<ChildAgentRecord[]>([])
const error = ref('')
const expandedGoals = ref<Set<string>>(new Set())
const expandedRuns = ref<Set<string>>(new Set())
let timer: number | null = null

type GoalGroup = {
  goal: string
  runs: ChildAgentRecord[]
}

const goalGroups = computed<GoalGroup[]>(() => {
  const groups = new Map<string, ChildAgentRecord[]>()
  for (const child of children.value) {
    const key = child.goal || '(未命名目标)'
    const list = groups.get(key) || []
    list.push(child)
    groups.set(key, list)
  }
  return [...groups.entries()].map(([goal, runs]) => ({ goal, runs }))
})

const activeGroups = computed(() =>
  goalGroups.value.filter((group) => isChildActive(latestRun(group))),
)

function isChildActive(child: ChildAgentRecord) {
  return ['created', 'running'].includes(child.status)
}

function latestRun(group: GoalGroup): ChildAgentRecord {
  return group.runs[group.runs.length - 1]!
}

function isExpanded(group: GoalGroup) {
  return expandedGoals.value.has(group.goal)
}

function toggleExpanded(group: GoalGroup) {
  const next = new Set(expandedGoals.value)
  if (next.has(group.goal)) {
    next.delete(group.goal)
  } else {
    next.add(group.goal)
  }
  expandedGoals.value = next
}

function isRunExpanded(runId: string) {
  return expandedRuns.value.has(runId)
}

function toggleRun(runId: string) {
  const next = new Set(expandedRuns.value)
  if (next.has(runId)) {
    next.delete(runId)
  } else {
    next.add(runId)
  }
  expandedRuns.value = next
}

async function reload() {
  if (!props.sessionId) {
    children.value = []
    return
  }
  try {
    const response = await fetchChildAgents(props.sessionId)
    children.value = response.children
    emit('children-update', response.children)
    void preloadChildAgentConversations(response.children, props.userId)
    error.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '子 Agent 状态读取失败'
  }
}

async function stopChild(child: ChildAgentRecord) {
  try {
    await stopChildAgent(child.run_id)
    await reload()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '停止子 Agent 失败'
  }
}

/** 普通子 Agent 展开完整对话；DSH 在现有原生浏览器侧栏打开其受管 Web 会话。 */
async function openChild(child: ChildAgentRecord) {
  if (child.provider !== 'dsh') {
    emit('open-conversation', child)
    return
  }
  try {
    const response = await fetchChildAgentDshWeb(child.run_id, props.userId, props.sessionId)
    workspaceStore.openBrowserSidebar(response.url)
    emit('open-dsh-web')
    error.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'DSH Web 打开失败'
  }
}

function statusLabel(status: ChildAgentRecord['status']) {
  return {
    created: '已创建',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
  }[status]
}

function modeLabel(value: ChildAgentRecord['mode']) {
  return value === 'foreground' ? '前台' : '后台'
}

function accessModeLabel(value: ChildAgentRecord['access_mode']) {
  return {
    readonly: '只读',
    sandbox: '沙盒',
    full_access: '完整权限',
  }[value]
}

function childDisplayName(child: ChildAgentRecord) {
  return child.name?.trim() || '子Agent'
}

// 类别胶囊显示英文原文(预置类别首字母大写),不翻译成自造中文
const presetCategoryLabels: Record<string, string> = {
  agent: 'Agent',
  explore: 'Explore',
  plan: 'Plan',
}

function categoryBadge(child: ChildAgentRecord) {
  const category = child.category?.trim()
  if (!category) return ''
  return presetCategoryLabels[category] || category
}

function shortRunId(runId: string) {
  return runId.length > 8 ? runId.slice(0, 8) : runId
}

function resultText(result: unknown) {
  if (result === undefined || result === null) return ''
  if (typeof result === 'string') return result
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

watch([() => props.sessionId, () => props.userId], () => {
  void reload()
})

onMounted(() => {
  void reload()
  timer = window.setInterval(() => void reload(), 2000)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <aside class="child-agent-drawer" aria-label="子 Agent 任务">
    <header class="child-agent-header">
      <div class="child-agent-title">
        <IcIcon name="group" :size="16" />
        <span>子 Agent</span>
        <span class="child-agent-count">{{ activeGroups.length }} 个运行中</span>
      </div>
      <button class="child-agent-close" type="button" title="关闭子 Agent 侧栏" @click="emit('close')">
        <IcIcon name="close" :size="15" />
      </button>
    </header>

    <div class="child-agent-content">
      <div v-if="goalGroups.length" class="child-agent-tasks">
        <article v-for="group in goalGroups" :key="group.goal" class="child-agent-task">
          <div class="child-agent-task-head">
            <button
              class="child-agent-expand-button"
              type="button"
              :aria-label="isExpanded(group) ? '收起子 Agent 任务' : '展开子 Agent 任务'"
              :aria-expanded="isExpanded(group)"
              @click="toggleExpanded(group)"
            >
              <IcIcon name="chevron-down" class="child-agent-task-chevron" :class="{ expanded: isExpanded(group) }" :size="15" />
            </button>
            <img
              :src="getChildAgentAvatar(latestRun(group).run_id)"
              class="child-agent-avatar"
              alt=""
            />
            <button
              class="child-agent-name-link"
              type="button"
              :title="latestRun(group).provider === 'dsh' ? '在 DSH Web 中查看' : '查看子 Agent 对话'"
              @click="openChild(latestRun(group))"
            >
              {{ childDisplayName(latestRun(group)) }}
            </button>
            <span v-if="categoryBadge(latestRun(group))" class="child-agent-category">{{ categoryBadge(latestRun(group)) }}</span>
            <span class="child-agent-mode">{{ modeLabel(latestRun(group).mode) }}</span>
            <span class="child-agent-status" :data-status="latestRun(group).status">{{ statusLabel(latestRun(group).status) }}</span>
          </div>

          <div class="child-agent-detail" :class="{ expanded: isExpanded(group) }">
            <div class="child-agent-detail-inner">
              <section class="child-agent-section">
                <h4>任务目标</h4>
                <p>{{ group.goal }}</p>
              </section>

              <div v-for="run in group.runs" :key="run.run_id" class="child-agent-run">
                <div class="child-agent-run-head">
                  <span class="child-agent-run-dot" :data-status="run.status"></span>
                  <button class="child-agent-name-link run" type="button" :title="run.provider === 'dsh' ? '在 DSH Web 中查看' : '查看子 Agent 对话'" @click="openChild(run)">
                    {{ childDisplayName(run) }}
                  </button>
                  <span class="child-agent-status" :data-status="run.status">{{ statusLabel(run.status) }}</span>
                  <button
                    class="child-agent-expand-button"
                    type="button"
                    :aria-label="isRunExpanded(run.run_id) ? '收起运行信息' : '展开运行信息'"
                    :aria-expanded="isRunExpanded(run.run_id)"
                    @click="toggleRun(run.run_id)"
                  >
                    <IcIcon name="chevron-down" class="child-agent-run-chevron" :class="{ expanded: isRunExpanded(run.run_id) }" :size="14" />
                  </button>
                </div>

                <div class="child-agent-run-detail" :class="{ expanded: isRunExpanded(run.run_id) }">
                  <div class="child-agent-run-detail-inner">
                    <section class="child-agent-section-grid" aria-label="子 Agent 运行信息">
                      <div>
                        <span>类别</span>
                        <strong>{{ categoryBadge(run) || '通用' }}</strong>
                      </div>
                      <div>
                        <span>模式</span>
                        <strong>{{ modeLabel(run.mode) }}</strong>
                      </div>
                      <div>
                        <span>沙盒权限</span>
                        <strong>{{ accessModeLabel(run.access_mode) }}</strong>
                      </div>
                      <div>
                        <span>工具数量</span>
                        <strong>{{ run.allowed_tools.length }}</strong>
                      </div>
                    </section>

                    <section v-if="run.allowed_tools.length" class="child-agent-section">
                      <h4>工具范围</h4>
                      <p class="child-agent-tools">{{ run.allowed_tools.join(', ') }}</p>
                    </section>

                    <section v-if="run.summary" class="child-agent-section">
                      <h4>阶段摘要</h4>
                      <p>{{ run.summary }}</p>
                    </section>

                    <section v-if="resultText(run.result)" class="child-agent-section">
                      <h4>产出结果</h4>
                      <pre>{{ resultText(run.result) }}</pre>
                    </section>

                    <section v-if="run.error" class="child-agent-section">
                      <h4>错误信息</h4>
                      <p class="child-agent-error">{{ run.error }}</p>
                    </section>

                    <p class="child-agent-run-id">ID {{ shortRunId(run.run_id) }}</p>

                    <div v-if="isChildActive(run)" class="child-agent-actions">
                      <button type="button" @click.stop="stopChild(run)">停止</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
      <p v-if="error" class="child-agent-error">{{ error }}</p>
      <p v-if="!goalGroups.length && !error" class="child-agent-empty">暂无子 Agent 任务</p>
    </div>
  </aside>
</template>

<style scoped>
/* 作为融合侧边栏卡片的下分区:无边框、无独立背景,宽度与展开由外层卡片容器控制 */
.child-agent-drawer {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
}

.child-agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 40px;
  padding: 0 var(--space-12);
  border-bottom: 1px solid var(--color-border);
}

.child-agent-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-8);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  font-weight: 650;
}

.child-agent-close {
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.child-agent-close:hover {
  background: var(--color-primary-softer);
  color: var(--color-text);
}

.child-agent-content {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: var(--space-8);
  overflow-x: hidden;
  overflow-y: auto;
  padding: var(--space-10);
}

.child-agent-count,
.child-agent-mode {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.child-agent-task {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-8);
  border-radius: var(--radius-xl);
  background: var(--color-surface);
  transition: background-color 180ms ease;
}

.child-agent-task:hover {
  background: var(--color-surface-raised);
}

.child-agent-empty {
  margin: 0;
  padding: var(--space-8) 0;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.child-agent-task-head {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  min-width: 0;
  color: inherit;
  font-family: var(--font-ui);
  text-align: left;
}

.child-agent-expand-button:focus-visible,
.child-agent-name-link:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.child-agent-expand-button {
  display: inline-flex;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.child-agent-task-chevron {
  flex: 0 0 auto;
  color: var(--color-text-muted);
  transition: transform 180ms ease;
}

.child-agent-task-chevron.expanded {
  transform: rotate(180deg);
}

.child-agent-avatar {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: var(--color-canvas);
  object-fit: cover;
}

.child-agent-name-link {
  min-width: 0;
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  font-weight: 650;
  line-height: 1.35;
  cursor: pointer;
  text-overflow: ellipsis;
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--color-primary) 52%, transparent);
  text-underline-offset: 2px;
  white-space: nowrap;
}

.child-agent-name-link:hover { color: var(--color-primary); }
.child-agent-name-link.run { flex: 1; text-align: left; }

.child-agent-category {
  flex: 0 0 auto;
  padding: 0 var(--space-6);
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  color: var(--color-primary);
  font-size: calc(10px * var(--font-scale));
  font-weight: 600;
  line-height: 1.6;
  white-space: nowrap;
}

.child-agent-status {
  flex: 0 0 auto;
  margin-left: auto;
  font-size: calc(11px * var(--font-scale));
  font-weight: 600;
}

.child-agent-summary,
.child-agent-error {
  margin: 0;
  line-height: 1.45;
}

.child-agent-tasks {
  display: grid;
  gap: var(--space-6);
}

.child-agent-detail {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 220ms cubic-bezier(0.4, 0, 0.2, 1);
}

.child-agent-detail > .child-agent-detail-inner {
  overflow: hidden;
  min-height: 0;
}

.child-agent-detail.expanded {
  grid-template-rows: 1fr;
}

.child-agent-detail-inner {
  display: grid;
  gap: var(--space-8);
  padding-top: var(--space-8);
}

.child-agent-detail.expanded .child-agent-detail-inner {
  border-top: 1px solid var(--color-border);
}

.child-agent-run {
  display: flex;
  flex-direction: column;
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
}

.child-agent-run-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  min-width: 0;
  color: inherit;
  font-family: var(--font-ui);
  text-align: left;
}

.child-agent-run-head .child-agent-status {
  margin-left: 0;
}

.child-agent-run-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-text-muted);
}

.child-agent-run-dot[data-status='running'] {
  background: var(--color-primary);
}

.child-agent-run-dot[data-status='completed'] {
  background: var(--color-success);
}

.child-agent-run-dot[data-status='failed'],
.child-agent-run-dot[data-status='stopped'] {
  background: var(--color-danger);
}

.child-agent-run-chevron {
  flex: 0 0 auto;
  color: var(--color-text-muted);
  transition: transform 180ms ease;
}

.child-agent-run-chevron.expanded {
  transform: rotate(180deg);
}

.child-agent-run-detail {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 220ms cubic-bezier(0.4, 0, 0.2, 1);
}

.child-agent-run-detail > .child-agent-run-detail-inner {
  overflow: hidden;
  min-height: 0;
}

.child-agent-run-detail.expanded {
  grid-template-rows: 1fr;
}

.child-agent-run-detail-inner {
  display: grid;
  gap: var(--space-6);
  padding-top: var(--space-6);
}

.child-agent-run-id {
  margin: 0;
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
}

.child-agent-section,
.child-agent-section-grid {
  min-width: 0;
}

.child-agent-section {
  display: grid;
  gap: var(--space-4);
}

.child-agent-section h4 {
  margin: 0;
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
  font-weight: 600;
}

.child-agent-section p,
.child-agent-section pre {
  margin: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.5;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.child-agent-section pre {
  max-height: 220px;
  overflow: auto;
  padding: var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
  font-family: var(--font-code);
}

.child-agent-section-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-8);
}

.child-agent-section-grid div {
  display: grid;
  min-width: 0;
  gap: 2px;
  padding: var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-canvas);
}

.child-agent-section-grid span {
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
}

.child-agent-section-grid strong {
  min-width: 0;
  color: var(--color-text-primary);
  font-size: calc(12px * var(--font-scale));
  font-weight: 600;
  overflow-wrap: anywhere;
}

.child-agent-tools {
  max-height: 92px;
  overflow: auto;
}

.child-agent-actions {
  display: flex;
  justify-content: flex-end;
}

.child-agent-actions button {
  min-height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  cursor: pointer;
  transition:
    border-color 180ms ease,
    color 180ms ease,
    background-color 180ms ease;
}

.child-agent-actions button:hover {
  border-color: var(--color-danger);
  background: color-mix(in srgb, var(--color-danger) 12%, transparent);
  color: var(--color-danger);
}

.child-agent-status[data-status='completed'] { color: var(--color-success); }
.child-agent-status[data-status='failed'], .child-agent-error { color: var(--color-danger); }
.child-agent-status[data-status='running'] { color: var(--color-primary); }

@media (max-width: 640px) {
  .child-agent-section-grid { grid-template-columns: 1fr; }
}
</style>
