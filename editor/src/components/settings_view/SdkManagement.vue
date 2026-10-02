<!--
  SDK 与运行组件管理区块。

  用途：展示并管理 MetaWeave 固定的 DSH Windows Runtime。组件只消费真实后端
  状态，安装、取消、修复和卸载完成后通知存储页刷新磁盘统计。
-->
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import {
  cancelDshSdkInstall,
  fetchDshSdkManagement,
  installDshSdk,
  repairDshSdk,
  uninstallDshSdk,
  type DshSdkManagementStatus,
} from '@/api/sdk'

defineOptions({ name: 'SdkManagement' })

const props = defineProps<{ userId: string }>()
const emit = defineEmits<{ storageChanged: [] }>()
const sdk = ref<DshSdkManagementStatus | null>(null)
const expanded = ref(false)
const loading = ref(false)
const feedback = ref('')
const lastRefreshFailed = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const workingStates = new Set(['verifying', 'extracting', 'installing', 'repairing', 'cancelling', 'uninstalling'])

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

async function refresh() {
  if (!props.userId) return
  loading.value = true
  try {
    sdk.value = await fetchDshSdkManagement(props.userId)
    lastRefreshFailed.value = false
    feedback.value = ''
  } catch (error: unknown) {
    lastRefreshFailed.value = true
    feedback.value = error instanceof Error ? error.message : 'SDK 状态加载失败'
    syncPolling()
  } finally {
    loading.value = false
  }
}

function syncPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = lastRefreshFailed.value || (sdk.value && workingStates.has(sdk.value.status))
    ? setInterval(async () => {
        await refresh()
        if (lastRefreshFailed.value || !sdk.value || workingStates.has(sdk.value.status)) return
        if (pollTimer) clearInterval(pollTimer)
        pollTimer = null
        emit('storageChanged')
      }, 750)
    : null
}

async function install() {
  if (!props.userId || !sdk.value) return
  if (!sdk.value.configured) {
    feedback.value = '当前 MW 构建缺少内置 DSH Runtime SDK'
    return
  }
  if (!window.confirm(`将从 MW 内置资源解压并安装 ${sdk.value.label} ${sdk.value.version}，是否继续？`)) return
  try {
    sdk.value = await installDshSdk(props.userId)
    syncPolling()
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : 'SDK 安装启动失败'
  }
}

async function cancelInstall() {
  if (!props.userId) return
  sdk.value = await cancelDshSdkInstall(props.userId)
  syncPolling()
}

async function repair() {
  if (!props.userId || !window.confirm('将重新校验并解压内置 DSH Runtime，是否继续？')) return
  try {
    sdk.value = await repairDshSdk(props.userId)
    syncPolling()
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : 'SDK 修复启动失败'
  }
}

async function uninstall() {
  if (!props.userId || !window.confirm('确认卸载 DSH Runtime？子 Agent 对话历史会保留。')) return
  try {
    sdk.value = await uninstallDshSdk(props.userId)
    emit('storageChanged')
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : 'SDK 卸载失败'
  }
}

function statusText(): string {
  const labels: Record<string, string> = {
    missing: '未安装', verifying: '校验中', extracting: '解压中', installing: '安装中',
    ready: '可用', failed: '安装失败', repairing: '修复中', cancelling: '取消中', uninstalling: '卸载中',
  }
  return labels[sdk.value?.status || ''] || '检测中'
}

function statusClass(): string {
  if (sdk.value?.status === 'ready') return 'ready'
  if (workingStates.has(sdk.value?.status || '')) return 'working'
  if (sdk.value?.status === 'failed') return 'error'
  return 'missing'
}

function openPath() {
  if (sdk.value?.path) window.agentEditorDesktop?.openPath?.(sdk.value.path)
}

watch(() => props.userId, async (userId) => {
  if (!userId) return
  await refresh()
  syncPolling()
}, { immediate: true })

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <section class="sdk-management settings-block-surface" aria-labelledby="sdk-management-title">
    <header class="management-header">
      <h4 id="sdk-management-title">SDK 与运行组件</h4>
      <button type="button" class="icon-action" title="刷新 SDK 状态" :disabled="loading" @click="refresh">
        <IcIcon name="refresh" :size="15" :class="{ spinning: loading }" />
      </button>
    </header>

    <p v-if="feedback" class="feedback">{{ feedback }}</p>

    <article v-if="sdk" class="management-item">
      <div class="management-summary">
        <button class="icon-action" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
          <IcIcon name="chevron-right" :size="14" :class="{ expanded }" />
        </button>
        <div class="identity">
          <strong>{{ sdk.label }}</strong>
          <span>{{ sdk.role }}</span>
        </div>
        <div class="state"><span class="status-dot" :class="statusClass()"></span>{{ statusText() }}</div>
        <span class="version">{{ sdk.version }}</span>
        <span class="size">{{ formatBytes(sdk.size_bytes || sdk.package_size_bytes) }}</span>
        <div class="actions">
          <button v-if="sdk.status === 'missing'" type="button" @click="install">安装</button>
          <button v-else-if="workingStates.has(sdk.status)" type="button" class="danger" @click="cancelInstall">取消</button>
          <button v-else-if="sdk.status === 'failed'" type="button" @click="repair">修复</button>
          <button v-else-if="sdk.status === 'ready'" type="button" class="danger" :disabled="sdk.in_use" @click="uninstall">卸载</button>
          <button class="icon-action" type="button" title="打开 SDK 位置" @click="openPath"><IcIcon name="folder-open" :size="15" /></button>
        </div>
      </div>

      <div v-if="workingStates.has(sdk.status)" class="progress-row" role="status">
        <progress v-if="sdk.progress !== null" :value="sdk.progress" max="100"></progress>
        <progress v-else></progress>
        <span>{{ sdk.message }}</span>
        <span>{{ formatBytes(sdk.processed_bytes) }}<template v-if="sdk.total_bytes"> / {{ formatBytes(sdk.total_bytes) }}</template></span>
      </div>

      <dl v-if="expanded" class="details">
        <div><dt>平台</dt><dd>{{ sdk.platform }}</dd></div>
        <div><dt>状态</dt><dd>{{ sdk.message }}</dd></div>
        <div><dt>安装位置</dt><dd class="mono">{{ sdk.path }}</dd></div>
        <div><dt>内置安装包</dt><dd>{{ formatBytes(sdk.package_size_bytes) }}</dd></div>
        <div><dt>文件数量</dt><dd>{{ sdk.file_count }}</dd></div>
      </dl>
    </article>
  </section>
</template>

<style scoped>
.sdk-management { container-type: inline-size; min-width: 0; margin-top: var(--space-16); padding: 14px; font-family: var(--font-ui); }
.management-header { display: flex; min-height: 34px; align-items: center; justify-content: space-between; }
.management-header h4 { margin: 0; color: var(--color-text); font-size: calc(14px * var(--font-scale)); }
.management-summary { display: grid; min-height: 56px; grid-template-columns: 24px minmax(180px, 1.5fr) auto 90px 70px minmax(120px, auto); align-items: center; gap: var(--space-8); }
.icon-action, .actions button { border: 0; background: transparent; color: var(--color-text-muted); cursor: pointer; }
.icon-action { display: inline-grid; width: 26px; height: 26px; place-items: center; padding: 0; }
.icon-action:hover, .actions button:hover { color: var(--color-primary); }
.icon-action:disabled, .actions button:disabled { opacity: .45; cursor: default; }
.icon-action svg { transition: transform 160ms ease; }
.icon-action svg.expanded { transform: rotate(90deg); }
.identity { display: grid; min-width: 0; gap: 2px; }
.identity strong { font-size: calc(12px * var(--font-scale)); }
.identity span, .state, .version, .size { color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); }
.identity span { overflow: hidden; color: var(--color-text-muted); text-overflow: ellipsis; white-space: nowrap; }
.state { display: inline-flex; align-items: center; gap: var(--space-6); white-space: nowrap; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-text-muted); }
.status-dot.ready { background: var(--color-success); }
.status-dot.working { background: var(--color-warning); }
.status-dot.error { background: var(--color-danger); }
.size { text-align: right; }
.actions { display: flex; justify-content: flex-end; gap: var(--space-6); }
.actions button { color: var(--color-primary); font: inherit; font-size: calc(11px * var(--font-scale)); }
.actions button.danger, .feedback { color: var(--color-danger); }
.progress-row { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(130px, auto) auto; gap: var(--space-10); align-items: center; padding: 0 0 var(--space-10) 32px; color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.progress-row progress { width: 100%; height: 6px; accent-color: var(--color-primary); }
.details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; padding: 0 0 var(--space-12) 32px; gap: 1px var(--space-16); }
.details div { display: grid; grid-template-columns: 88px minmax(0, 1fr); padding: var(--space-6) 0; }
.details dt { color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.details dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); }
.mono { font-family: var(--font-code); }
.feedback { margin: var(--space-8) 0; font-size: calc(11px * var(--font-scale)); }
.spinning { animation: spin 800ms linear infinite; }
@container (max-width: 760px) { .management-summary { grid-template-columns: 24px minmax(0, 1fr) auto auto; } .version, .size { display: none; } .details { grid-template-columns: 1fr; } }
@container (max-width: 480px) { .management-summary { grid-template-columns: 24px minmax(0, 1fr) auto; grid-template-rows: auto auto; padding: var(--space-8) 0; } .state { grid-column: 2; } .actions { grid-column: 3; grid-row: 1 / span 2; } .progress-row { grid-template-columns: 1fr auto; padding-left: 0; } .progress-row span:first-of-type { grid-column: 1 / -1; } .details { padding-left: 0; } .details div { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .icon-action svg { transition: none; } }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
