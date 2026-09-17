<!--
  Agent 工具注册表面板。

  使用说明:
  组件展示 Agent 最终运行时工具、设置分组和用户开关状态；布局规格与其他
  debug 注册表检查页共同读取 registry-panel.css。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import { fetchAgentTools, type AgentToolInfo } from '@/api/tools'
import {
  fetchAvailableTools,
  fetchDisabledTools,
  saveDisabledTools,
  type ToolGroup,
} from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

interface AugmentedTool extends AgentToolInfo {
  enabled: boolean
}

interface AugmentedGroup {
  category: string
  display_name: string
  tools: AugmentedTool[]
}

const agentTools = ref<AgentToolInfo[]>([])
const groupsFromApi = ref<ToolGroup[]>([])
const enabledMap = ref<Record<string, boolean>>({})
const loading = ref(false)
const errorText = ref('')
const query = ref('')
const selectedName = ref('')
const collapsedCategories = ref<Set<string>>(new Set())

/**
 * 以 Agent 最终运行时注册表为全集,设置分组只负责分类与开关状态。
 * 尚未进入设置分组的新内置工具或 MCP 工具会自动归入“运行时工具”,不会被交集过滤掉。
 */
const groupedTools = computed<AugmentedGroup[]>(() => {
  const agentMap = new Map(agentTools.value.map(t => [t.name, t]))
  const groupedNames = new Set<string>()
  const groups = groupsFromApi.value
    .map(g => ({
      category: g.category,
      display_name: g.display_name,
      tools: g.tools
      .map(t => {
        const info = agentMap.get(t.name)
        if (!info) return null
        groupedNames.add(t.name)
        return { ...info, enabled: enabledMap.value[t.name] ?? t.enabled }
      })
      .filter((t): t is AugmentedTool => t !== null),
    }))
    .filter(group => group.tools.length > 0)
  const runtimeTools = agentTools.value
    .filter(tool => !groupedNames.has(tool.name))
    .map(tool => ({ ...tool, enabled: enabledMap.value[tool.name] !== false }))
  if (runtimeTools.length > 0) {
    groups.push({
      category: 'RUNTIME',
      display_name: '运行时工具',
      tools: runtimeTools,
    })
  }
  return groups
})

const filteredGroups = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return groupedTools.value
  return groupedTools.value
    .map(g => {
      const filtered = g.tools.filter(t =>
        `${t.name} ${t.display_name} ${t.description}`.toLowerCase().includes(q)
      )
      return filtered.length ? { ...g, tools: filtered } : null
    })
    .filter((g): g is AugmentedGroup => g !== null)
})

const totalArguments = computed(() => {
  return agentTools.value.reduce((sum, t) => sum + t.argument_count, 0)
})

const selectedTool = computed(() => {
  for (const g of filteredGroups.value) {
    const found = g.tools.find(t => t.name === selectedName.value)
    if (found) return found
  }
  return filteredGroups.value[0]?.tools[0] ?? null
})

const requiredArgs = computed(() => {
  return new Set(selectedTool.value?.args_schema?.required ?? [])
})

const selectedProperties = computed(() => {
  const properties = selectedTool.value?.args_schema?.properties ?? {}
  return Object.entries(properties).map(([name, schema]) => ({
    name,
    type: (schema as { type?: string }).type || 'unknown',
    description: (schema as { description?: string }).description || '',
    required: requiredArgs.value.has(name),
  }))
})

function toggleCategory(category: string) {
  const next = new Set(collapsedCategories.value)
  if (next.has(category)) next.delete(category)
  else next.add(category)
  collapsedCategories.value = next
}

async function loadTools() {
  loading.value = true
  errorText.value = ''
  try {
    const [agentPayload, settingsPayload, disabledPayload] = await Promise.all([
      fetchAgentTools(),
      fetchAvailableTools(settingsStore.profile.userId || ''),
      fetchDisabledTools(settingsStore.profile.userId || ''),
    ])
    agentTools.value = agentPayload.tools
    groupsFromApi.value = settingsPayload.groups ?? []
    const disabledNames = new Set(disabledPayload.disabled_tools ?? [])
    const map: Record<string, boolean> = Object.fromEntries(
      agentPayload.tools.map(tool => [tool.name, !disabledNames.has(tool.name)]),
    )
    for (const g of settingsPayload.groups ?? []) {
      for (const t of g.tools) map[t.name] = t.enabled
    }
    enabledMap.value = map
    if (!selectedName.value && agentPayload.tools.length > 0) {
      selectedName.value = agentPayload.tools[0]!.name
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '工具注册表加载失败'
  } finally {
    loading.value = false
  }
}

async function handleToggleTool(toolName: string) {
  const wasEnabled = enabledMap.value[toolName] !== false
  enabledMap.value = { ...enabledMap.value, [toolName]: !wasEnabled }
  try {
    const userId = settingsStore.profile.userId
    if (!userId) return
    const disabled = Object.entries(enabledMap.value)
      .filter(([, enabled]) => !enabled)
      .map(([name]) => name)
    await saveDisabledTools(userId, disabled)
  } catch {
    enabledMap.value = { ...enabledMap.value, [toolName]: wasEnabled }
  }
}

function selectTool(tool: AugmentedTool) {
  selectedName.value = tool.name
}

onMounted(() => {
  void loadTools()
})
</script>

<template>
  <div class="tool-registry-panel registry-panel">
    <section class="registry-card">
      <div class="panel-heading registry-heading">
        <div class="title-summary">
          <h2>工具注册表</h2>
          <span>{{ agentTools.length }} tools</span>
          <span>{{ totalArguments }} args</span>
          <span>{{ filteredGroups.reduce((s, g) => s + g.tools.length, 0) }} visible</span>
        </div>
        <div class="registry-search">
          <IcIcon name="search" :size="14" />
          <input v-model="query" type="text" placeholder="搜索工具" />
        </div>
        <button class="icon-button" type="button" title="刷新" :disabled="loading" @click="loadTools">
          <IcIcon name="refresh" :size="15" />
        </button>
      </div>

      <div class="panel-surface">
        <p v-if="errorText" class="error-line">{{ errorText }}</p>

        <div class="registry-grid">
          <aside class="tool-list" aria-label="工具列表">
            <div v-if="loading" class="empty-state"><span>$ 正在读取</span></div>
            <template v-for="group in filteredGroups" :key="group.category">
              <div class="category-header" @click="toggleCategory(group.category)">
                <IcIcon
                  name="chevron-down"
                  :size="14"
                  class="collapse-icon"
                  :class="{ collapsed: collapsedCategories.has(group.category) }"
                />
                <span class="category-name">{{ group.display_name }}</span>
                <span class="category-count">{{ group.tools.length }}</span>
              </div>
              <div v-if="!collapsedCategories.has(group.category)" class="category-tools">
                <div
                  v-for="tool in group.tools"
                  :key="tool.name"
                  class="tool-list-item"
                  :class="{
                    active: selectedTool?.name === tool.name,
                    disabled: !tool.enabled,
                  }"
                >
                  <button class="tool-row" type="button" @click="selectTool(tool)">
                    <span class="tool-name">{{ tool.display_name || tool.name }}</span>
                    <span class="tool-meta">{{ tool.argument_count }} args</span>
                  </button>
                  <label
                    class="tool-toggle-label"
                    :class="{ managed: group.category === 'MEMORY' }"
                    :title="group.category === 'MEMORY' ? '由长期记忆总开关控制' : (tool.enabled ? '点击关闭' : '点击启用')"
                    @click.stop
                  >
                    <input
                      :checked="tool.enabled"
                      :disabled="group.category === 'MEMORY'"
                      type="checkbox"
                      @change="handleToggleTool(tool.name)"
                    />
                    <span class="toggle-bg"></span>
                    <span class="toggle-thumb"><span class="toggle-dot"></span></span>
                    <span v-if="!tool.enabled" class="disabled-badge">未启用</span>
                  </label>
                </div>
              </div>
            </template>
            <div v-if="!loading && filteredGroups.length === 0" class="empty-state">
              <span>$ 没有匹配的工具</span>
            </div>
          </aside>

          <main class="tool-detail">
            <div v-if="loading" class="empty-state"><span>$ 正在读取最终工具注册表</span></div>
            <template v-else-if="selectedTool">
              <div class="detail-title">
                <span class="detail-display">{{ selectedTool.display_name || selectedTool.name }}</span>
                <code>{{ selectedTool.name }}</code>
                <span v-if="!selectedTool.enabled" class="detail-disabled-badge">未启用</span>
              </div>
              <p class="detail-description">{{ selectedTool.description }}</p>
              <div class="arg-table">
                <div class="arg-row arg-head"><span>参数</span><span>类型</span><span>约束</span></div>
                <div v-for="arg in selectedProperties" :key="arg.name" class="arg-row">
                  <span class="arg-name">{{ arg.name }}</span>
                  <span>{{ arg.type }}</span>
                  <span>{{ arg.required ? 'required' : 'optional' }}</span>
                  <p class="arg-desc">{{ arg.description || '无说明' }}</p>
                </div>
              </div>
              <pre class="schema-block">{{ JSON.stringify(selectedTool.args_schema, null, 2) }}</pre>
            </template>
            <div v-else class="empty-state"><span>$ 工具注册表为空</span></div>
          </main>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped src="@/assets/registry-panel.css"></style>
