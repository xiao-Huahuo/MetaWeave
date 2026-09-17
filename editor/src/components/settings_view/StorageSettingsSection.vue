<!--
  存储管理设置区域组件。

  Usage:
    展示知识库与运行时目录树、ECharts 饼图和大小统计；仅知识库根目录可切换。
    <StorageSettingsSection />
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'
import IcIcon from '@/components/common/IcIcon.vue'
import CompilerManagement from '@/components/settings_view/CompilerManagement.vue'
import ModelManagement from '@/components/settings_view/ModelManagement.vue'
import SdkManagement from '@/components/settings_view/SdkManagement.vue'
import { saveModelPreferences } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'
import { API_ROUTES } from '@/router/api_routes'

interface StoragePathEntry {
  key: string
  label: string
  value: string
  size_bytes: number
  requires_restart: boolean
  can_clear: boolean
  parent: string | null
}

interface StorageConfigResponse {
  paths: StoragePathEntry[]
  knowledge_dir_total_bytes: number
  runtime_total_bytes: number
  managed_resource_distribution: Array<{ name: string; size_bytes: number }>
}

const settingsStore = useSettingsStore()

const paths = ref<StoragePathEntry[]>([])
const knowledgeDirTotal = ref(0)
const runtimeTotal = ref(0)
const managedResourceDistribution = ref<Array<{ name: string; value: number }>>([])
const loading = ref(false)
const clearing = ref<string | null>(null)
const savingKey = ref<string | null>(null)
const savingModelPreference = ref(false)
const feedback = ref('')
const knowledgeDirDraft = ref('')

/* ---- 颜色板：主色/点缀色/语义色 ---- */
const PIE_COLORS = [
  '#4224eb', '#eb2463', '#26a269', '#e2a72e', '#ef4444',
]

/* ---- 排序 ---- */
const ROOT_ORDER = [
  'knowledge_dir', 'managed_root', 'markdown_dir', 'frontmatter_dir', 'library_storage_dir', 'forms_dir', 'components_dir', 'latex_build_cache_dir', 'base_data_dir',
  'assets_dir', 'db_dir', 'relation_db_dir', 'vector_db_dir', 'sqlite_path', 'chroma_persist_dir',
  'log_dir', 'models_dir',
  'dsh_sdk_dir',
  'embedding_model_dir', 'paddleocr_model_dir', 'rerank_model_dir',
  'latex_runtime_dir', 'latex_distribution_dir', 'latex_repository_dir', 'latex_temp_dir',
  'trash_dir',
]

interface TreeItem {
  entry: StoragePathEntry
  depth: number
  hasChildren: boolean
}

const collapsedKeys = ref<Set<string>>(new Set())

function hasChild(key: string): boolean {
  return paths.value.some(p => p.parent === key)
}

function sortedChildren(parentKey: string): StoragePathEntry[] {
  return paths.value
    .filter(p => p.parent === parentKey)
    .sort((a, b) => ROOT_ORDER.indexOf(a.key) - ROOT_ORDER.indexOf(b.key))
}

const rootPaths = computed(() =>
  paths.value
    .filter(p => !p.parent)
    .sort((a, b) => ROOT_ORDER.indexOf(a.key) - ROOT_ORDER.indexOf(b.key))
)

const treeItems = computed(() => {
  const items: TreeItem[] = []
  function walk(parentKey: string, depth: number, parentCollapsed: boolean) {
    for (const child of sortedChildren(parentKey)) {
      if (parentCollapsed) return
      const hc = hasChild(child.key)
      const isCollapsed = collapsedKeys.value.has(child.key)
      items.push({ entry: child, depth, hasChildren: hc })
      walk(child.key, depth + 1, isCollapsed)
    }
  }
  for (const root of rootPaths.value) {
    const hc = hasChild(root.key)
    const isCollapsed = collapsedKeys.value.has(root.key)
    items.push({ entry: root, depth: 0, hasChildren: hc })
    walk(root.key, 1, isCollapsed)
  }
  return items
})

function toggleCollapse(key: string) {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
}

function formatMB(bytes: number): string {
  if (bytes === 0) return '0 MB'
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(mb >= 100 ? 0 : 1)} MB`
}

/* ---- 饼图数据 ---- */
const totalPieOption = computed(() => ({
  tooltip: {
    trigger: 'item' as const,
    backgroundColor: 'rgba(30,30,40,0.92)',
    borderColor: 'rgba(255,255,255,0.08)',
    textStyle: { color: '#ccc', fontSize: 12 },
    formatter: (p: { name: string; value: number; percent: number }) =>
      `${p.name}: ${formatMB(p.value)} (${p.percent}%)`,
  },
  series: [{
    type: 'pie',
    radius: '65%',
    center: ['50%', '50%'],
    emphasis: { label: { fontWeight: 'bold' } },
    label: { show: false },
    data: [
      { name: '知识库', value: knowledgeDirTotal.value, itemStyle: { color: '#4224eb' } },
      { name: '运行时', value: runtimeTotal.value, itemStyle: { color: '#eb2463' } },
    ].filter(d => d.value > 0),
  }],
}))

const runtimePieData = computed(() => paths.value
  .filter(p => p.key !== 'knowledge_dir' && p.key !== 'base_data_dir' && p.parent === 'base_data_dir')
  .filter(p => p.size_bytes > 0)
  .map(p => ({ name: p.key === 'db_dir' ? '运行时' : p.label, value: p.size_bytes })))

/** 为运行时和受管资源分类复用相同的饼图交互与主题配置。 */
function createDistributionPieOption(data: Array<{ name: string; value: number }>) {
  return {
    tooltip: {
      trigger: 'item' as const,
      backgroundColor: 'rgba(30,30,40,0.92)',
      borderColor: 'rgba(255,255,255,0.08)',
      textStyle: { color: '#ccc', fontSize: 12 },
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}: ${formatMB(p.value)} (${p.percent}%)`,
    },
    series: [{
      type: 'pie',
      radius: '65%',
      center: ['50%', '50%'],
      emphasis: { label: { fontWeight: 'bold' } },
      label: { show: false },
      data: data.map((e, i) => ({
        name: e.name,
        value: e.value,
        itemStyle: { color: PIE_COLORS[i % PIE_COLORS.length] },
      })),
    }],
  }
}

const runtimePieOption = computed(() => createDistributionPieOption(runtimePieData.value))
const managedResourcePieOption = computed(() => createDistributionPieOption(managedResourceDistribution.value))

/* ---- 工具函数 ---- */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function openInExplorer(absPath: string) {
  window.agentEditorDesktop?.openPath?.(absPath)
}

function show(msg: string, ms = 2000) {
  feedback.value = msg
  setTimeout(() => { feedback.value = '' }, ms)
}

/** Persist the opt-in model auto-download setting in the backend user profile. */
async function handleModelAutoDownload(enabled: boolean) {
  if (!settingsStore.profile.userId || savingModelPreference.value) return
  const previous = Boolean(settingsStore.profile.modelAutoDownloadEnabled)
  settingsStore.updateProfile({ modelAutoDownloadEnabled: enabled })
  savingModelPreference.value = true
  try {
    const result = await saveModelPreferences(settingsStore.profile.userId, enabled)
    settingsStore.updateProfile({ modelAutoDownloadEnabled: result.auto_download_enabled })
  } catch (error: unknown) {
    settingsStore.updateProfile({ modelAutoDownloadEnabled: previous })
    show(error instanceof Error ? error.message : '自动下载设置保存失败')
  } finally {
    savingModelPreference.value = false
  }
}

/** Read the native checkbox value without embedding TypeScript casts in the template. */
function handleModelAutoDownloadChange(event: Event) {
  void handleModelAutoDownload((event.target as HTMLInputElement).checked)
}

/* ---- API ---- */
async function loadStorageConfig() {
  if (!settingsStore.profile.userId) return
  loading.value = true
  try {
    const res = await fetch(`${API_ROUTES.SETTINGS_STORAGE_CONFIG}?user_id=${encodeURIComponent(settingsStore.profile.userId)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data: StorageConfigResponse = await res.json()
    paths.value = data.paths
    knowledgeDirTotal.value = data.knowledge_dir_total_bytes
    runtimeTotal.value = data.runtime_total_bytes
    managedResourceDistribution.value = (data.managed_resource_distribution ?? [])
      .filter(item => item.size_bytes > 0)
      .map(item => ({ name: item.name, value: item.size_bytes }))

    const kd = data.paths.find((p: StoragePathEntry) => p.key === 'knowledge_dir')
    if (kd) knowledgeDirDraft.value = kd.value
  } catch {
    show('加载失败')
  } finally {
    loading.value = false
  }
}

async function handleSaveKnowledgeDir() {
  if (savingKey.value) return
  savingKey.value = 'knowledge_dir'
  feedback.value = ''
  try {
    await settingsStore.switchKnowledgeRoot(knowledgeDirDraft.value)
    show('知识库路径已更新')
  } catch (e: unknown) {
    show(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingKey.value = null
    await loadStorageConfig()
  }
}

async function handleClear(pathKey: string, label: string) {
  const confirmed = window.confirm(`确认清空 "${label}"？此操作不可撤销。`)
  if (!confirmed) return
  clearing.value = pathKey
  feedback.value = ''
  try {
    const res = await fetch(API_ROUTES.SETTINGS_STORAGE_CLEAR, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: settingsStore.profile.userId, path_key: pathKey }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    show(`已清空，释放 ${formatBytes(data.freed_bytes)}`)
  } catch (e: unknown) {
    show(e instanceof Error ? e.message : '操作失败')
  } finally {
    clearing.value = null
    await loadStorageConfig()
  }
}

watch(
  () => settingsStore.profile.userId,
  (userId) => { if (userId) void loadStorageConfig() },
  { immediate: true },
)
</script>

<template>
  <div class="setting-section">
    <div class="section-header">
      <h3>存储管理</h3>
      <button class="icon-btn" :disabled="loading" title="刷新统计" @click="loadStorageConfig">
        <IcIcon name="refresh" :size="15" :class="{ spinning: loading }" />
      </button>
    </div>

    <label class="model-download-setting">
      <span>启用自动下载</span>
      <input
        type="checkbox"
        :checked="Boolean(settingsStore.profile.modelAutoDownloadEnabled)"
        :disabled="savingModelPreference"
        @change="handleModelAutoDownloadChange"
      />
    </label>

    <!-- 统计概览：左数字 / 右饼图 -->
    <div class="stats-row">
      <!-- 左侧：数字 -->
      <div class="stats-left">
        <div class="stat-card">
          <div class="stat-card-dot knowledge-dot"></div>
          <span class="stat-card-label">知识库</span>
          <span class="stat-card-value">{{ formatBytes(knowledgeDirTotal) }}</span>
        </div>
        <div class="stat-card">
          <div class="stat-card-dot runtime-dot"></div>
          <span class="stat-card-label">运行时</span>
          <span class="stat-card-value">{{ formatBytes(runtimeTotal) }}</span>
        </div>
      </div>

      <!-- 右侧：饼图 + 图例 -->
      <div v-if="paths.length > 0" class="stats-right">
        <div class="pie-charts">
          <div class="pie-chart-item">
            <VChart class="pie-canvas" :option="totalPieOption" autoresize />
            <span class="pie-title">知识库 / 运行时</span>
          </div>
          <div class="pie-chart-item">
            <VChart class="pie-canvas" :option="runtimePieOption" autoresize />
            <span class="pie-title">运行时分布</span>
            <div v-if="runtimePieData.length > 1" class="pie-legend">
              <span v-for="(item, i) in runtimePieData" :key="String(item.name)" class="legend-item">
                <span class="legend-dot" :style="{ background: PIE_COLORS[i % PIE_COLORS.length] }"></span>
                {{ item.name }}
              </span>
            </div>
          </div>
          <div class="pie-chart-item">
            <VChart v-if="managedResourceDistribution.length > 0" class="pie-canvas" :option="managedResourcePieOption" autoresize />
            <div v-else class="pie-canvas pie-empty">暂无数据</div>
            <span class="pie-title">受管资源分布</span>
            <div v-if="managedResourceDistribution.length > 1" class="pie-legend">
              <span v-for="(item, i) in managedResourceDistribution" :key="String(item.name)" class="legend-item">
                <span class="legend-dot" :style="{ background: PIE_COLORS[i % PIE_COLORS.length] }"></span>
                {{ item.name }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <p v-if="feedback" class="feedback">{{ feedback }}</p>

    <ModelManagement :user-id="settingsStore.profile.userId" @storage-changed="loadStorageConfig" />
    <CompilerManagement :user-id="settingsStore.profile.userId" @storage-changed="loadStorageConfig" />
    <SdkManagement :user-id="settingsStore.profile.userId" @storage-changed="loadStorageConfig" />

    <header class="storage-path-header">
      <h4>存储路径</h4>
    </header>

    <!-- 路径树 -->
    <div v-if="paths.length > 0" class="storage-tree">
      <div>
        <template v-for="item in treeItems" :key="item.entry.key">
          <div class="tree-row" :class="{ 'tree-child': item.depth > 0 }">
            <div class="tree-label-cell" :style="{ paddingLeft: `${item.depth * 20}px` }">
              <button
                v-if="item.hasChildren"
                class="tree-collapse-btn"
                @click="toggleCollapse(item.entry.key)"
              >
                <IcIcon name="chevron-right" :size="13" :class="{ rotated: !collapsedKeys.has(item.entry.key) }" />
              </button>
              <span v-else class="tree-spacer"></span>
              <span class="tree-name" :class="{ 'child-name': item.depth > 0 }">{{ item.entry.label }}</span>
            </div>
            <div class="tree-value-cell">
              <template v-if="item.depth === 0 && item.entry.key === 'knowledge_dir'">
                <input v-model="knowledgeDirDraft" type="text" class="tree-input" :disabled="savingKey === item.entry.key" />
                <button class="tree-explore-btn" title="在资源管理器中打开" @click="openInExplorer(item.entry.value)">
                  <IcIcon name="folder-open" :size="14" />
                </button>
                <button class="save-model-btn" :disabled="savingKey === item.entry.key || knowledgeDirDraft === item.entry.value" @click="handleSaveKnowledgeDir">
                  {{ savingKey === item.entry.key ? '...' : '保存' }}
                </button>
              </template>
              <template v-else>
                <span class="tree-value mono">{{ item.entry.value }}</span>
              </template>
            </div>
            <div class="tree-size-cell">{{ formatBytes(item.entry.size_bytes) }}</div>
            <div class="tree-action-cell">
              <button
                v-if="item.entry.can_clear"
                class="delete-btn"
                :disabled="clearing === item.entry.key"
                :title="`清空 ${item.entry.label}`"
                @click="handleClear(item.entry.key, item.entry.label)"
              >
                <svg viewBox="0 0 448 512" class="svgIcon"><path d="M135.2 17.7L128 32H32C14.3 32 0 46.3 0 64S14.3 96 32 96H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H320l-7.2-14.3C307.4 6.8 296.3 0 284.2 0H163.8c-12.1 0-23.2 6.8-28.6 17.7zM416 128H32L53.2 467c1.6 25.3 22.6 45 47.9 45H346.9c25.3 0 46.3-19.7 47.9-45L416 128z"></path></svg>
              </button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <p v-else-if="!loading" class="setting-hint">暂无存储路径数据</p>
  </div>
</template>

<style scoped>
/* ---- 页头：标题 + 刷新按钮 ---- */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-10);
}

.model-download-setting {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-12);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.model-download-setting input {
  accent-color: var(--color-primary);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.icon-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.icon-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.spinning {
  animation: spin 0.8s linear infinite;
}

/* ---- 统计概览：左右两栏 ---- */
.stats-row {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: var(--space-16);
  margin-bottom: var(--space-8);
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: 1fr;
  }
}

.stats-left {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-8);
}

.stats-right {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  gap: var(--space-6);
}

/* ---- 数字卡片 ---- */
.stat-card {
  display: grid;
  grid-template-columns: 10px 1fr auto;
  align-items: center;
  gap: var(--space-10);
  min-height: 58px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-10) var(--space-12);
  background: rgba(255, 255, 255, 0.02);
}

.stat-card-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.knowledge-dot {
  background: #4224eb;
}

.runtime-dot {
  background: #eb2463;
}

.stat-card-label {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-card-value {
  flex: 0 0 auto;
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
}

/* ---- 饼图 ---- */
.pie-charts {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-12);
}

.pie-chart-item {
  display: flex;
  flex: 1 1 180px;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  min-width: 0;
}

.pie-canvas {
  width: 180px;
  height: 180px;
  flex-shrink: 0;
}

.pie-title {
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
}

.pie-empty {
  display: grid;
  place-items: center;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

@media (max-width: 480px) {
  .pie-canvas {
    width: 128px;
    height: 128px;
  }
}

/* 图例 */
.pie-legend {
  display: flex;
  max-width: 220px;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-4) var(--space-10);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
  font-family: var(--font-ui);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ---- 路径树 ---- */
.storage-tree {
  position: relative;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.tree-row {
  display: grid;
  grid-template-columns: 200px 1fr 80px auto;
  align-items: center;
  gap: var(--space-10);
  padding: var(--space-6) var(--space-10);
  min-height: 44px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-canvas);
}

@media (max-width: 768px) {
  .tree-row {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }
}

.tree-row:last-child {
  border-bottom: none;
}

.tree-child {
  background: var(--color-surface);
}

.tree-label-cell {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  min-width: 0;
}

.tree-collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: color var(--transition-fast);
}

.tree-collapse-btn:hover {
  color: var(--color-primary);
}

@keyframes chevron-rotate-in {
  from { transform: rotate(-90deg); }
  to   { transform: rotate(0deg); }
}

.tree-collapse-btn .rotated {
  animation: chevron-rotate-in 0.2s ease forwards;
}

.tree-spacer {
  display: inline-block;
  width: 18px;
  flex-shrink: 0;
}

.tree-name {
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.child-name {
  color: var(--color-text-secondary);
}

.tree-value-cell {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  min-width: 0;
}

.tree-value {
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tree-value.mono {
  font-family: var(--font-mono);
}

.tree-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-mono);
  font-size: calc(11px * var(--font-scale));
  outline: none;
}

.tree-input:focus {
  border-color: var(--color-primary);
}

.tree-input:disabled {
  opacity: 0.5;
}

.tree-explore-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color var(--transition-fast), background var(--transition-fast), color var(--transition-fast);
}

.tree-explore-btn:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.tree-size-cell {
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-muted);
  text-align: right;
  white-space: nowrap;
}

.tree-action-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-6);
  flex-shrink: 0;
}

.storage-path-header {
  min-height: 34px;
  margin-top: var(--space-16);
  border-bottom: 1px solid var(--color-border);
}

.storage-path-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: calc(14px * var(--font-scale));
}
</style>

<style scoped>
.stat-card {
  min-height: 44px;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
</style>
