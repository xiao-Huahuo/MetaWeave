<!--
  TokenUsageCard -- persisted token usage charts.

  Usage:
  Keeps the original dashboard card area and switches between three backend
  backed charts: per model call, fixed time bucket, and session total usage.
  Each tab provides its own filter controls.
-->

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'
import DropdownSelect from '@/components/ui/dropdown-menu/DropdownSelect.vue'
import { fetchTokenUsageStats } from '@/api/agent'
import type { TokenUsageInterval, TokenUsageStatsResponse } from '@/api/agent'
import { fetchLLMConfig } from '@/api/settings'
import { buildTokenViewTotals, displayedTokenSessions, formatTokenModelLabel } from '@/composable/useTokenUsageDisplay'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

type ChartKind = 'buckets' | 'calls' | 'sessions'
type ChartMode = 'bar' | 'line'
type SessionSort = 'time' | 'tokens'

const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()
const chatStore = useChatStore()

const chartKind = ref<ChartKind>('buckets')
const kindToggleRef = ref<HTMLElement | null>(null)
const kindSliderStyle = ref({ width: '0px', left: '0px' })
const sortToggleRef = ref<HTMLElement | null>(null)
const sortSliderStyle = ref({ width: '0px', left: '0px' })
const chartTypeToggleRef = ref<HTMLElement | null>(null)
const chartTypeSliderStyle = ref({ width: '0px', left: '0px' })
const chartModes = ref<Record<ChartKind, ChartMode>>({
  calls: 'line',
  buckets: 'bar',
  sessions: 'bar',
})

// --- per-tab filters ---
const interval = ref<TokenUsageInterval>('5m')
const lookback = ref<number>(24) // 小时
const callLimit = ref<number>(50)
const sessionSort = ref<SessionSort>('time')

const loading = ref(false)
const error = ref('')
const largeModelName = ref('')
const smallModelName = ref('')
const stats = ref<TokenUsageStatsResponse>({
  interval: '5m',
  calls: [],
  buckets: [],
  sessions: [],
})

const chartTabs: Array<{ value: ChartKind; label: string }> = [
  { value: 'buckets', label: '时间刻度' },
  { value: 'calls', label: '每次调用' },
  { value: 'sessions', label: 'Session 总量' },
]

const intervalOptions: Array<{ value: TokenUsageInterval; label: string }> = [
  { value: '1m', label: '1分' },
  { value: '3m', label: '3分' },
  { value: '5m', label: '5分' },
  { value: '10m', label: '10分' },
  { value: '30m', label: '30分' },
  { value: '1h', label: '1时' },
  { value: '2h', label: '2时' },
  { value: '3h', label: '3时' },
  { value: '6h', label: '6时' },
  { value: '12h', label: '12时' },
  { value: '24h', label: '24时' },
  { value: '3d', label: '3天' },
  { value: '10d', label: '10天' },
  { value: '15d', label: '15天' },
  { value: 'month', label: '月' },
]

const lookbackOptions: Array<{ value: number; label: string }> = [
  { value: 1, label: '最近1小时' },
  { value: 6, label: '最近6小时' },
  { value: 24, label: '最近1天' },
  { value: 72, label: '最近3天' },
  { value: 240, label: '最近10天' },
  { value: 360, label: '最近15天' },
  { value: 720, label: '最近30天' },
]

const callLimitOptions: Array<{ value: number; label: string }> = [
  { value: 5, label: '5次' },
  { value: 10, label: '10次' },
  { value: 30, label: '30次' },
  { value: 50, label: '50次' },
  { value: 100, label: '100次' },
  { value: 300, label: '300次' },
]

const sessionSortOptions: Array<{ value: SessionSort; label: string }> = [
  { value: 'time', label: '按时间' },
  { value: 'tokens', label: '按用量' },
]

const CURVE_COLORS = {
  large: '#4da6ff',
  small: '#6ee7b7',
  total: '#d99178',
}
const BORDER = 'rgba(255,255,255,0.08)'
const TXT_LABEL = '#777'

const statusText = computed(() => {
  if (loading.value) return '读取中'
  if (error.value) return '读取失败'
  const totals = buildTokenViewTotals(stats.value, chartKind.value)
  return [
    totals.large > 0 ? `${largeModelLabel.value} ${totals.large.toLocaleString('zh-CN')}` : '',
    totals.small > 0 ? `${smallModelLabel.value} ${totals.small.toLocaleString('zh-CN')}` : '',
  ].filter(Boolean).join(' · ')
})

const largeModelLabel = computed(() => formatTokenModelLabel(largeModelName.value, 'large'))
const smallModelLabel = computed(() => formatTokenModelLabel(smallModelName.value, 'small'))

const hasData = computed(() => {
  if (chartKind.value === 'calls') return stats.value.calls.length > 0
  if (chartKind.value === 'buckets') return stats.value.buckets.length > 0
  return stats.value.sessions.some((session) => session.total_tokens > 0)
})

const activeOption = computed(() => {
  if (chartKind.value === 'calls') return callOption.value
  if (chartKind.value === 'buckets') return bucketOption.value
  return sessionOption.value
})

const activeChartMode = computed({
  get: () => chartModes.value[chartKind.value],
  set: (value: ChartMode) => {
    chartModes.value = { ...chartModes.value, [chartKind.value]: value }
  },
})

const callOption = computed(() => {
  const items = stats.value.calls
  const mode = chartModes.value.calls
  return baseOption({
    xData: items.map((item) => formatShortTime(item.created_at)),
    series: [
      tokenSeries(largeModelLabel.value, items.map((item) => item.model_tier === 'large' ? item.total_tokens : 0), CURVE_COLORS.large, mode),
      tokenSeries(smallModelLabel.value, items.map((item) => item.model_tier === 'small' ? item.total_tokens : 0), CURVE_COLORS.small, mode),
    ],
  })
})

const bucketOption = computed(() => {
  const items = stats.value.buckets
  const mode = chartModes.value.buckets
  return baseOption({
    xData: items.map((item) => item.label),
    series: [
      tokenSeries(largeModelLabel.value, items.map((item) => item.large_tokens), CURVE_COLORS.large, mode),
      tokenSeries(smallModelLabel.value, items.map((item) => item.small_tokens), CURVE_COLORS.small, mode),
    ],
  })
})

const sessionOption = computed(() => {
  const items = displayedTokenSessions(stats.value.sessions)
  const mode = chartModes.value.sessions
  return baseOption({
    xData: items.map((item) => item.session_name || item.session_id),
    xRotate: items.length > 4 ? 25 : 0,
    series: [
      tokenSeries(largeModelLabel.value, items.map((item) => item.large_tokens), CURVE_COLORS.large, mode),
      tokenSeries(smallModelLabel.value, items.map((item) => item.small_tokens), CURVE_COLORS.small, mode),
    ],
  })
})

function tokenSeries(name: string, data: number[], color: string, mode: ChartMode) {
  if (mode === 'bar') {
    return {
      name,
      type: 'bar',
      stack: 'token',
      barMaxWidth: 18,
      data,
      itemStyle: {
        color,
        opacity: 0.82,
      },
      emphasis: {
        itemStyle: {
          opacity: 1,
        },
      },
    }
  }
  return {
    name,
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 5,
    data,
    lineStyle: {
      color,
      width: 1.8,
      shadowBlur: 10,
      shadowColor: `${color}99`,
    },
    itemStyle: {
      color,
      shadowBlur: 8,
      shadowColor: `${color}88`,
    },
    areaStyle: gradientArea(color),
    emphasis: {
      lineStyle: {
        width: 2.4,
        shadowBlur: 16,
      },
    },
  }
}

function gradientArea(color: string) {
  return {
    color: {
      type: 'linear',
      x: 0,
      y: 0,
      x2: 0,
      y2: 1,
      colorStops: [
        { offset: 0, color: `${color}5c` },
        { offset: 0.45, color: `${color}24` },
        { offset: 1, color: `${color}02` },
      ],
    },
    shadowBlur: 18,
    shadowColor: `${color}66`,
  }
}

function baseOption({ xData, series, xRotate = 0 }: { xData: string[]; series: unknown[]; xRotate?: number }) {
  return {
    backgroundColor: 'transparent',
    grid: { top: 14, right: 16, bottom: 28, left: 42 },
    xAxis: {
      type: 'category',
      data: xData,
      axisLine: { lineStyle: { color: BORDER } },
      axisTick: { show: false },
      axisLabel: {
        color: TXT_LABEL,
        fontSize: 11,
        rotate: xRotate || (xData.length > 8 ? 30 : 0),
        overflow: 'truncate',
      },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: BORDER, type: 'dashed' } },
      axisLabel: { color: TXT_LABEL, fontSize: 11 },
    },
    series,
    legend: {
      bottom: 0,
      textStyle: { color: TXT_LABEL, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 6,
      icon: 'roundRect',
    },
    tooltip: { trigger: 'axis' },
  }
}

function updateKindSlider() {
  nextTick(() => {
    const el = kindToggleRef.value
    if (!el) return
    const a = el.querySelector('.kind-btn.active') as HTMLElement | null
    if (!a) return
    kindSliderStyle.value = { width: `${a.offsetWidth}px`, left: `${a.offsetLeft}px` }
  })
}
function updateSortSlider() {
  nextTick(() => {
    const el = sortToggleRef.value
    if (!el) return
    const a = el.querySelector('.sort-btn.active') as HTMLElement | null
    if (!a) return
    sortSliderStyle.value = { width: `${a.offsetWidth}px`, left: `${a.offsetLeft}px` }
  })
}
function updateChartTypeSlider() {
  nextTick(() => {
    const el = chartTypeToggleRef.value
    if (!el) return
    const a = el.querySelector('.chart-type-btn.active') as HTMLElement | null
    if (!a) return
    chartTypeSliderStyle.value = { width: `${a.offsetWidth}px`, left: `${a.offsetLeft}px` }
  })
}

function formatShortTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

async function loadStats() {
  const userId = settingsStore.profile.userId
  if (!userId) {
    stats.value = { interval: interval.value, calls: [], buckets: [], sessions: [] }
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params: Parameters<typeof fetchTokenUsageStats>[1] = {
      sessionId: sessionStore.currentSessionId,
    }
    if (chartKind.value === 'buckets') {
      params.interval = interval.value
      params.lookbackHours = lookback.value
    } else if (chartKind.value === 'calls') {
      params.limit = callLimit.value
    } else {
      params.interval = interval.value
      params.sessionSort = sessionSort.value
    }
    stats.value = await fetchTokenUsageStats(userId, params)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取 token 统计失败'
  } finally {
    loading.value = false
  }
}

/** Load the effective user model names used in chart legends and totals. */
async function loadModelNames() {
  const userId = settingsStore.profile.userId
  if (!userId) {
    largeModelName.value = ''
    smallModelName.value = ''
    return
  }
  try {
    const config = await fetchLLMConfig(userId)
    largeModelName.value = config.model_name || ''
    smallModelName.value = config.effective_small_model_name || config.small_model_name || ''
  } catch {
    largeModelName.value = ''
    smallModelName.value = ''
  }
}

onMounted(() => {
  void loadStats()
  void loadModelNames()
  nextTick(() => { updateKindSlider(); updateChartTypeSlider() })
})

watch(
  () => [settingsStore.profile.userId, sessionStore.currentSessionId] as const,
  () => void loadStats(),
)

watch(
  () => settingsStore.profile.userId,
  () => void loadModelNames(),
)

watch(
  () => [chartKind.value, interval.value, lookback.value, callLimit.value, sessionSort.value] as const,
  () => void loadStats(),
)

watch(chartKind, () => nextTick(() => { updateKindSlider(); updateChartTypeSlider() }))
watch(sessionSort, updateSortSlider)
watch(activeChartMode, updateChartTypeSlider)

watch(
  () => chatStore.isStreaming,
  (streaming, wasStreaming) => {
    if (!streaming && wasStreaming) {
      void loadStats()
    }
  },
)
</script>

<template>
  <DashboardCardFrame title="Token 用量" :status="statusText">
    <div class="card-body">
      <div class="chart-toolbar">
        <div ref="kindToggleRef" class="capsule-toggle">
          <div class="capsule-slider" :style="kindSliderStyle"></div>
          <button
            v-for="tab in chartTabs"
            :key="tab.value"
            class="kind-btn"
            :class="{ active: chartKind === tab.value }"
            type="button"
            @click="chartKind = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- 时间刻度: 桶粒度 + 时间范围 -->
        <template v-if="chartKind === 'buckets'">
          <DropdownSelect v-model="interval" class="filter-select" aria-label="Token 时间粒度" :options="intervalOptions" />
          <DropdownSelect v-model="lookback" class="filter-select" aria-label="Token 时间范围" :options="lookbackOptions" />
        </template>

        <!-- 每次调用: 调用次数筛选 -->
        <template v-if="chartKind === 'calls'">
          <DropdownSelect v-model="callLimit" class="filter-select" aria-label="Token 调用次数" :options="callLimitOptions" />
        </template>

        <!-- Session 总量: 排序方式 -->
        <template v-if="chartKind === 'sessions'">
          <div ref="sortToggleRef" class="capsule-toggle">
            <div class="capsule-slider" :style="sortSliderStyle"></div>
            <button
              v-for="opt in sessionSortOptions"
              :key="opt.value"
              class="sort-btn"
              :class="{ active: sessionSort === opt.value }"
              type="button"
              @click="sessionSort = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>
        </template>

        <div ref="chartTypeToggleRef" class="capsule-toggle">
          <div class="capsule-slider" :style="chartTypeSliderStyle"></div>
          <button
            class="chart-type-btn"
            :class="{ active: activeChartMode === 'bar' }"
            type="button"
            @click="activeChartMode = 'bar'"
          >
            柱状图
          </button>
          <button
            class="chart-type-btn"
            :class="{ active: activeChartMode === 'line' }"
            type="button"
            @click="activeChartMode = 'line'"
          >
            曲线图
          </button>
        </div>
      </div>

      <div v-if="hasData" class="chart-area">
        <v-chart :option="activeOption" autoresize class="chart-box" />
      </div>
      <div v-else class="empty-state">
        <span class="placeholder-text">{{ error || '等待 token 统计' }}</span>
      </div>
    </div>
  </DashboardCardFrame>
</template>

<style scoped>
.card-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-10);
  overflow: hidden;
}

.chart-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.capsule-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 0;
  border-radius: 999px;
  background: var(--color-surface);
}

.capsule-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  transition: left 250ms ease, width 250ms ease;
  z-index: 0;
  pointer-events: none;
}

.kind-btn,
.sort-btn,
.chart-type-btn {
  position: relative;
  z-index: 1;
  height: 28px;
  padding: 0 8px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  outline: none;
}

.kind-btn:hover,
.sort-btn:hover,
.chart-type-btn:hover {
  color: var(--color-primary);
}

.kind-btn.active,
.sort-btn.active,
.chart-type-btn.active {
  color: var(--color-primary);
}

.filter-select {
  padding: 0 6px;
  border-color: var(--color-border);
  background: var(--color-surface);
}

:deep(.filter-select.ui-dropdown-select-trigger) {
  height: 28px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.chart-area {
  flex: 1;
  min-height: 0;
}

.chart-box {
  width: 100%;
  height: 100%;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
}

.placeholder-text {
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}
</style>
