<!--
  Compiler runtime management block.

  Usage:
  StorageSettingsSection provides the user id. The component explains the
  active LaTeX distribution/source and owns managed MiKTeX install lifecycle.
-->
<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import {
  cancelLatexInstall,
  fetchLatexManagement,
  installLatexRuntime,
  uninstallLatexRuntime,
  type LatexManagementStatus,
} from '@/api/latex'

defineOptions({ name: 'CompilerManagement' })

const props = defineProps<{ userId: string }>()
const emit = defineEmits<{ storageChanged: [] }>()

const compiler = ref<LatexManagementStatus | null>(null)
const expanded = ref(false)
const loading = ref(false)
const feedback = ref('')
const lastRefreshFailed = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

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

async function refresh() {
  if (!props.userId) return
  loading.value = true
  try {
    compiler.value = await fetchLatexManagement(props.userId)
    lastRefreshFailed.value = false
    feedback.value = ''
  } catch (error: unknown) {
    lastRefreshFailed.value = true
    feedback.value = error instanceof Error ? error.message : '编译器状态加载失败'
    ensurePolling()
  } finally {
    loading.value = false
  }
}

function ensurePolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await refresh()
    const status = compiler.value?.status
    if (lastRefreshFailed.value || !status || ['downloading', 'installing', 'cancelling'].includes(status)) return
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
    emit('storageChanged')
  }, 750)
}

async function install() {
  if (!props.userId || !window.confirm('将从 MiKTeX 官网下载并安装当前用户范围的 LaTeX 环境，是否继续？')) return
  feedback.value = ''
  try {
    await installLatexRuntime(props.userId)
    await refresh()
    ensurePolling()
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : 'MiKTeX 安装启动失败'
  }
}

async function cancelInstall() {
  if (!props.userId) return
  await cancelLatexInstall(props.userId)
  await refresh()
  ensurePolling()
}

async function uninstall() {
  if (!props.userId || !window.confirm('确认卸载 MetaWeave 托管的 MiKTeX？系统安装不会受影响。')) return
  try {
    await uninstallLatexRuntime(props.userId)
    await refresh()
    emit('storageChanged')
  } catch (error: unknown) {
    feedback.value = error instanceof Error ? error.message : '卸载失败'
  }
}

function sourceText(): string {
  if (!compiler.value || compiler.value.status === 'missing') return '未安装'
  return compiler.value.source === 'managed' ? 'MetaWeave 托管' : '系统安装'
}

function statusText(): string {
  const status = compiler.value?.status
  const labels: Record<string, string> = {
    ready: '可用', downloading: '下载中', installing: '安装中', cancelling: '取消中', failed: '安装失败', missing: '未安装',
  }
  return labels[status || ''] || status || '检测中'
}

function statusClass(): string {
  const status = compiler.value?.status
  if (status === 'ready') return 'ready'
  if (['downloading', 'installing', 'cancelling'].includes(status || '')) return 'working'
  if (status === 'failed') return 'error'
  return 'missing'
}

function openPath(path: string) {
  window.agentEditorDesktop?.openPath?.(path)
}

watch(
  () => props.userId,
  (userId) => { if (userId) void refresh() },
  { immediate: true },
)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <section class="management-block compiler-management settings-block-surface" aria-labelledby="compiler-management-title">
    <header class="management-header">
      <h4 id="compiler-management-title">编译管理</h4>
      <button type="button" class="plain-icon-button" title="刷新编译器状态" aria-label="刷新编译器状态" :disabled="loading" @click="refresh">
        <IcIcon name="refresh" :size="15" :class="{ spinning: loading }" />
      </button>
    </header>

    <p v-if="feedback" class="management-feedback">{{ feedback }}</p>

    <article v-if="compiler" class="management-item">
      <div class="management-summary">
        <button type="button" class="details-toggle" :aria-expanded="expanded" :aria-label="`${expanded ? '收起' : '展开'} LaTeX 编译器详情`" @click="expanded = !expanded">
          <IcIcon name="chevron-right" :size="14" :class="{ expanded }" />
        </button>
        <div class="management-identity">
          <strong>{{ compiler.distribution || 'LaTeX 编译器' }}</strong>
          <span>{{ compiler.version || compiler.message }}</span>
        </div>
        <div class="management-state">
          <span class="status-dot" :class="statusClass()"></span>
          <span>{{ statusText() }}</span>
        </div>
        <span class="source-state">{{ sourceText() }}</span>
        <span class="management-size">{{ formatBytes(compiler.size_bytes) }}</span>
        <div class="management-actions">
          <button v-if="['missing', 'failed'].includes(compiler.status)" type="button" class="text-button" @click="install">{{ compiler.status === 'failed' ? '重试' : '安装 MiKTeX' }}</button>
          <button v-else-if="['downloading', 'installing'].includes(compiler.status)" type="button" class="text-button danger" @click="cancelInstall">取消</button>
          <button v-else-if="compiler.status === 'ready' && compiler.managed" type="button" class="text-button danger" @click="uninstall">卸载</button>
          <button v-if="compiler.distribution_path" type="button" class="plain-icon-button" title="打开编译器位置" aria-label="打开编译器位置" @click="openPath(compiler.distribution_path)">
            <IcIcon name="folder-open" :size="15" />
          </button>
        </div>
      </div>

      <div v-if="['downloading', 'installing', 'cancelling'].includes(compiler.status)" class="real-progress" role="status">
        <progress v-if="compiler.progress !== null" :value="compiler.progress" max="100"></progress>
        <progress v-else class="indeterminate-progress"></progress>
        <span>{{ compiler.message }}</span>
        <span>
          {{ formatBytes(compiler.downloaded_bytes || 0) }}
          <template v-if="compiler.total_bytes"> / {{ formatBytes(compiler.total_bytes) }} · {{ compiler.progress }}%</template>
        </span>
      </div>

      <div v-if="expanded" class="management-details">
        <dl>
          <div><dt>来源</dt><dd>{{ sourceText() }}</dd></div>
          <div><dt>默认引擎</dt><dd>{{ compiler.default_engine || '未选择' }}</dd></div>
          <div><dt>发行版位置</dt><dd class="mono">{{ compiler.distribution_path }}</dd></div>
          <div><dt>文件数量</dt><dd>{{ compiler.file_count }}</dd></div>
          <div><dt>latexmk</dt><dd class="mono">{{ compiler.latexmk_path || '不可用' }}</dd></div>
          <div><dt>托管运行时</dt><dd class="mono">{{ compiler.runtime_path }}</dd></div>
        </dl>
        <div class="engine-list">
          <div v-for="engine in compiler.engines" :key="engine.name" class="engine-row">
            <span class="status-dot" :class="engine.available ? 'ready' : 'missing'"></span>
            <strong>{{ engine.name }}</strong>
            <span>{{ engine.default ? '默认' : (engine.available ? '可用' : '未安装') }}</span>
            <code>{{ engine.path || '—' }}</code>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.management-block {
  container-type: inline-size;
  margin-top: var(--space-16);
  min-width: 0;
  padding: 14px;
  font-family: var(--font-ui);
}

.management-header {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
}
.management-header h4 { margin: 0; color: var(--color-text); font-size: calc(14px * var(--font-scale)); }
.management-summary {
  display: grid;
  min-height: 56px;
  grid-template-columns: 24px minmax(180px, 1.5fr) minmax(72px, auto) 96px 76px minmax(96px, auto);
  align-items: center;
  gap: var(--space-8);
}
.details-toggle,
.plain-icon-button,
.text-button { border: 0; background: transparent; color: var(--color-text-muted); cursor: pointer; }
.details-toggle,
.plain-icon-button { display: inline-grid; width: 26px; height: 26px; place-items: center; padding: 0; }
.details-toggle svg { transition: transform 160ms ease; }
.details-toggle svg.expanded { transform: rotate(90deg); }
.plain-icon-button:hover,
.text-button:hover { color: var(--color-primary); }
.management-identity { display: grid; min-width: 0; gap: 2px; }
.management-identity strong { font-size: calc(12px * var(--font-scale)); }
.management-identity span { overflow: hidden; color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); text-overflow: ellipsis; white-space: nowrap; }
.management-state { display: inline-flex; align-items: center; gap: var(--space-6); }
.management-state,
.source-state,
.management-size { color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); white-space: nowrap; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-text-muted); }
.status-dot.ready { background: var(--color-success, #26a269); }
.status-dot.working { background: var(--color-warning, #d79b20); }
.status-dot.error { background: var(--color-danger, #d64545); }
.management-size { text-align: right; font-variant-numeric: tabular-nums; }
.management-actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-6); }
.text-button { color: var(--color-primary); font: inherit; font-size: calc(11px * var(--font-scale)); }
.text-button.danger { color: var(--color-danger, #d64545); }
.real-progress { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(130px, auto) auto; align-items: center; gap: var(--space-10); padding: 0 0 var(--space-10) 32px; color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.real-progress progress { width: 100%; height: 6px; accent-color: var(--color-primary); }
.management-details { padding: 0 0 var(--space-12) 32px; animation: details-in 150ms ease; }
.management-details dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; gap: 1px var(--space-16); }
.management-details dl > div { display: grid; grid-template-columns: 92px minmax(0, 1fr); padding: var(--space-6) 0; }
.management-details dt { color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.management-details dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); }
.engine-list { margin-top: var(--space-8); }
.engine-row { display: grid; grid-template-columns: 12px 80px 64px minmax(0, 1fr); align-items: center; gap: var(--space-8); min-height: 32px; color: var(--color-text-secondary); font-size: calc(11px * var(--font-scale)); }
.engine-row code { overflow: hidden; font-family: var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: var(--font-mono); }
.management-feedback { margin: var(--space-8) 0; color: var(--color-danger, #d64545); font-size: calc(11px * var(--font-scale)); }
.spinning { animation: spin 800ms linear infinite; }

@container (max-width: 760px) {
  .management-summary { grid-template-columns: 24px minmax(0, 1fr) auto auto; }
  .source-state,
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
  .engine-row { grid-template-columns: 12px 68px 52px minmax(0, 1fr); }
}

@media (prefers-reduced-motion: reduce) {
  .details-toggle svg,
  .management-details { transition: none; animation: none; }
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes details-in { from { opacity: 0; transform: translateY(-4px); } }
</style>
