<!--
  Model runtime management block.

  Usage:
  StorageSettingsSection provides the current user id. This component loads
  backend-owned model details, starts downloads/loads, and renders only real
  byte progress or an honest indeterminate state when total size is unknown.
-->
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import {
  checkModelDisk,
  deleteManagedModel,
  downloadManagedModel,
  fetchModelManagement,
  loadManagedModel,
  type ManagedModelStatus,
} from '@/api/settings'

defineOptions({ name: 'ModelManagement' })

const props = defineProps<{ userId: string }>()
const emit = defineEmits<{ storageChanged: [] }>()

const models = ref<ManagedModelStatus[]>([])
const expanded = ref(new Set<string>())
const loading = ref(false)
const actionKey = ref('')
const feedback = ref('')
const lastRefreshFailed = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasActiveWork = computed(() => models.value.some((model) => (
  ['verifying', 'downloading', 'loading'].includes(model.status) || model.progress.status === 'downloading'
)))

/** Format actual model bytes using compact binary units. */
function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

/** Refresh disk truth before returning the aggregated management DTO. */
async function refresh({ checkDisk = false }: { checkDisk?: boolean } = {}) {
  if (!props.userId) return
  loading.value = true
  try {
    if (checkDisk) {
      try {
        await checkModelDisk()
      } catch {
        // Disk synchronization is advisory; management data may still be available.
      }
    }
    models.value = (await fetchModelManagement(props.userId)).models
    lastRefreshFailed.value = false
    feedback.value = ''
    if (hasActiveWork.value) ensurePolling()
  } catch (error: unknown) {
    lastRefreshFailed.value = true
    feedback.value = error instanceof TypeError
      ? '模型服务连接暂不可用，正在自动重试'
      : error instanceof Error ? error.message : '模型状态加载失败'
    ensurePolling()
  } finally {
    loading.value = false
  }
}

/** Poll only while a real backend download/load is active. */
function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await refresh()
    if (!lastRefreshFailed.value && !hasActiveWork.value && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
      emit('storageChanged')
    }
  }, 750)
}

/** Confirm potentially large downloads, then let the backend own all progress. */
async function startDownload(model: ManagedModelStatus) {
  if (!window.confirm(`确认下载 ${model.name}？下载大小由模型仓库决定。`)) return
  actionKey.value = model.key
  feedback.value = ''
  try {
    await downloadManagedModel(model.key, props.userId)
    await refresh()
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : '模型下载启动失败'
  } finally {
    actionKey.value = ''
  }
}

/** Delete only the selected managed model and suppress auto-download until next launch. */
async function removeModel(model: ManagedModelStatus) {
  if (!window.confirm(`确认删除 ${model.name}？下次启动前不会自动重新下载。`)) return
  actionKey.value = model.key
  feedback.value = ''
  try {
    await deleteManagedModel(model.key, props.userId)
    await refresh()
    emit('storageChanged')
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : '模型删除失败'
  } finally {
    actionKey.value = ''
  }
}

/** Load an existing local Qwen, embedding, or rerank model into the active process. */
async function startLoad(model: ManagedModelStatus) {
  if (model.key === 'paddleocr') return
  actionKey.value = model.key
  try {
    await loadManagedModel(model.key)
    await refresh()
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : '模型加载失败'
  } finally {
    actionKey.value = ''
  }
}

/** Toggle one model's detailed configuration without changing backend state. */
function toggleDetails(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

/** Translate backend lifecycle into one concise user-facing status. */
function statusText(model: ManagedModelStatus): string {
  const labels: Record<string, string> = {
    ready: '使用中',
    verifying: '验证中',
    awaiting_download: '等待确认下载',
    loading: '加载中',
    downloading: '下载中',
    downloaded: '已下载',
    not_downloaded: '未下载',
    error: '异常',
  }
  return labels[model.status] || model.status
}

function statusClass(model: ManagedModelStatus): string {
  if (model.active) return 'ready'
  if (['verifying', 'loading', 'downloading'].includes(model.status)) return 'working'
  if (model.status === 'error') return 'error'
  if (model.downloaded) return 'downloaded'
  return 'missing'
}

/** Convert backend detail keys into stable user-facing labels. */
function detailLabel(key: string): string {
  const labels: Record<string, string> = {
    provider: '来源',
    repository: '模型仓库',
    model_type: '模型类型',
    language: '识别语言',
    device: '运行设备',
    detection_model: '检测模型',
    recognition_model: '识别模型',
    layout_model: '版面模型',
    ocr_models: '文字模型',
    table_models: '表格模型',
    formula_model: '公式模型',
    supporting_models: '辅助模型',
    preprocessing: '文档预处理',
    disabled_modules: '关闭模块',
    capabilities: '能力',
    fallback: '回退规则',
  }
  return labels[key] || key
}

function openPath(path: string) {
  window.agentEditorDesktop?.openPath?.(path)
}

watch(
  () => props.userId,
  (userId) => {
    if (userId) void refresh({ checkDisk: true })
  },
  { immediate: true },
)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <section class="management-block model-management" aria-labelledby="model-management-title">
    <header class="management-header">
      <h4 id="model-management-title">模型管理</h4>
      <button type="button" class="plain-icon-button" title="刷新模型状态" aria-label="刷新模型状态" :disabled="loading" @click="refresh({ checkDisk: true })">
        <IcIcon name="refresh" :size="15" :class="{ spinning: loading }" />
      </button>
    </header>

    <p v-if="feedback" class="management-feedback">{{ feedback }}</p>

    <div class="management-list">
      <article v-for="model in models" :key="model.key" class="management-item" :data-model="model.key">
        <div class="management-summary">
          <button
            type="button"
            class="details-toggle"
            :aria-expanded="expanded.has(model.key)"
            :aria-label="`${expanded.has(model.key) ? '收起' : '展开'} ${model.label}详情`"
            @click="toggleDetails(model.key)"
          >
            <IcIcon name="chevron-right" :size="14" :class="{ expanded: expanded.has(model.key) }" />
          </button>
          <div class="management-identity">
            <strong>{{ model.label }}</strong>
            <span>{{ model.name }}</span>
          </div>
          <div class="management-state">
            <span class="status-dot" :class="statusClass(model)"></span>
            <span>{{ statusText(model) }}</span>
          </div>
          <span class="enabled-state" :class="{ enabled: model.enabled }">{{ model.enabled ? '已启用' : '未启用' }}</span>
          <span class="management-size">{{ formatBytes(model.size_bytes) }}</span>
          <div class="management-actions">
            <button
              v-if="!model.downloaded || model.status === 'error'"
              type="button"
              class="text-button"
              :disabled="actionKey === model.key || model.progress.status === 'downloading'"
              @click="startDownload(model)"
            >{{ model.status === 'error' ? '重试' : '下载' }}</button>
            <button
              v-else-if="model.key !== 'paddleocr' && model.status === 'downloaded'"
              type="button"
              class="text-button"
              :disabled="actionKey === model.key"
              @click="startLoad(model)"
            >加载</button>
            <button
              v-if="model.downloaded"
              type="button"
              class="text-button danger-text-button"
              :disabled="actionKey === model.key || hasActiveWork"
              @click="removeModel(model)"
            >删除</button>
            <button type="button" class="plain-icon-button" title="打开模型位置" aria-label="打开模型位置" @click="openPath(model.path)">
              <IcIcon name="folder-open" :size="15" />
            </button>
          </div>
        </div>

        <div v-if="model.progress.status === 'downloading'" class="real-progress" role="status">
          <progress v-if="model.progress.percent !== null" :value="model.progress.percent" max="100"></progress>
          <progress v-else class="indeterminate-progress"></progress>
          <span>{{ model.progress.message }}</span>
          <span>
            {{ formatBytes(model.progress.downloaded_bytes) }}
            <template v-if="model.progress.total_bytes"> / {{ formatBytes(model.progress.total_bytes) }} · {{ model.progress.percent }}%</template>
          </span>
        </div>

        <div v-if="expanded.has(model.key)" class="management-details">
          <dl>
            <div><dt>用途</dt><dd>{{ model.role }}</dd></div>
            <div><dt>模型位置</dt><dd class="mono">{{ model.path }}</dd></div>
            <div><dt>文件数量</dt><dd>{{ model.file_count }}</dd></div>
            <div><dt>磁盘状态</dt><dd>{{ model.downloaded ? '完整' : '缺失' }}</dd></div>
            <div><dt>内存状态</dt><dd>{{ model.active ? '当前使用中' : '未加载' }}</dd></div>
            <div v-for="(value, key) in model.details" :key="key"><dt>{{ detailLabel(key) }}</dt><dd>{{ value }}</dd></div>
          </dl>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.management-block {
  container-type: inline-size;
  margin-top: var(--space-16);
  font-family: var(--font-ui);
}

.management-header {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--color-border);
}

.management-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: calc(14px * var(--font-scale));
}

.management-list { border-bottom: 1px solid var(--color-border); }
.management-item { border-top: 1px solid var(--color-border); }
.management-item:first-child { border-top: 0; }

.management-summary {
  display: grid;
  min-height: 56px;
  grid-template-columns: 24px minmax(180px, 1.5fr) minmax(84px, auto) 72px 76px minmax(96px, auto);
  align-items: center;
  gap: var(--space-8);
}

.details-toggle,
.plain-icon-button,
.text-button {
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.details-toggle,
.plain-icon-button {
  display: inline-grid;
  width: 26px;
  height: 26px;
  place-items: center;
  padding: 0;
}

.details-toggle svg { transition: transform 160ms ease; }
.details-toggle svg.expanded { transform: rotate(90deg); }
.plain-icon-button:hover,
.text-button:hover { color: var(--color-primary); }
.plain-icon-button:disabled,
.text-button:disabled { cursor: default; opacity: 0.45; }

.management-identity {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.management-identity strong { font-size: calc(12px * var(--font-scale)); }
.management-identity span {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.management-state,
.enabled-state,
.management-size {
  color: var(--color-text-secondary);
  font-size: calc(11px * var(--font-scale));
  white-space: nowrap;
}

.management-state { display: inline-flex; align-items: center; gap: var(--space-6); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-text-muted); }
.status-dot.ready { background: var(--color-success, #26a269); }
.status-dot.working,
.status-dot.downloaded { background: var(--color-warning, #d79b20); }
.status-dot.error { background: var(--color-danger, #d64545); }
.enabled-state.enabled { color: var(--color-success, #26a269); }
.management-size { text-align: right; font-variant-numeric: tabular-nums; }
.management-actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-6); }
.text-button { color: var(--color-primary); font: inherit; font-size: calc(11px * var(--font-scale)); }
.danger-text-button { color: var(--color-danger, #d64545); }

.real-progress {
  display: grid;
  grid-template-columns: minmax(100px, 1fr) minmax(130px, auto) auto;
  align-items: center;
  gap: var(--space-10);
  padding: 0 0 var(--space-10) 32px;
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.real-progress progress { width: 100%; height: 6px; accent-color: var(--color-primary); }
.indeterminate-progress { accent-color: var(--color-primary); }

.management-details {
  padding: 0 0 var(--space-12) 32px;
  animation: details-in 150ms ease;
}

.management-details dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; gap: 1px var(--space-16); }
.management-details dl > div { display: grid; grid-template-columns: 92px minmax(0, 1fr); padding: var(--space-6) 0; }
.management-details dt { color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.management-details dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); }
.mono { font-family: var(--font-mono); }
.management-feedback { margin: var(--space-8) 0; color: var(--color-danger, #d64545); font-size: calc(11px * var(--font-scale)); }
.spinning { animation: spin 800ms linear infinite; }

@container (max-width: 760px) {
  .management-summary { grid-template-columns: 24px minmax(0, 1fr) auto auto; }
  .enabled-state,
  .management-size { display: none; }
  .management-details dl { grid-template-columns: 1fr; }
}

@container (max-width: 480px) {
  .management-summary { grid-template-columns: 24px minmax(0, 1fr) auto; grid-template-rows: auto auto; padding: var(--space-8) 0; }
  .management-state { grid-column: 2; }
  .management-actions { grid-column: 3; grid-row: 1 / span 2; }
  .real-progress { grid-template-columns: 1fr auto; padding-left: 0; }
  .real-progress span:first-of-type { grid-column: 1 / -1; }
  .management-details { padding-left: 0; }
  .management-details dl > div { grid-template-columns: 1fr; gap: 3px; }
}

@media (prefers-reduced-motion: reduce) {
  .details-toggle svg,
  .management-details { transition: none; animation: none; }
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes details-in { from { opacity: 0; transform: translateY(-4px); } }
</style>
