<!--
  RagMetricsCard —— RAG 召回率、命中率、置信度展示卡片。
  可切换 donut(当前 Session 累计值) / line(全部历史 Session)。
  ECharts 渲染，弹性布局。
-->

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'
import { useObsData } from '@/composable/useObsData'
import {
  OBS_HISTORY_RANGE_OPTIONS,
  formatObsHistoryRange,
  useObsHistory,
  type ObsHistoryRange,
} from '@/composable/useObsHistory'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'
import DropdownSelect from '@/components/ui/dropdown-menu/DropdownSelect.vue'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

const obs = useObsData()
const history = useObsHistory()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const chartMode = ref<'donut' | 'line'>('donut')
const ragToggleRef = ref<HTMLElement | null>(null)
const ragSliderStyle = ref({ width: '0px', left: '0px' })

function updateRagSlider() {
  nextTick(() => {
    const el = ragToggleRef.value
    if (!el) return
    const a = el.querySelector('.rag-btn.active') as HTMLElement | null
    if (!a) return
    ragSliderStyle.value = { width: `${a.offsetWidth}px`, left: `${a.offsetLeft}px` }
  })
}

onMounted(updateRagSlider)
watch(chartMode, updateRagSlider)

const selectedRange = computed<ObsHistoryRange>({
  get: () => history.ragLimit.value,
  set: (value) => {
    history.ragLimit.value = value
  },
})

/** Load the selected range only after the user opens the RAG curve. */
async function loadSelectedRagRange(): Promise<void> {
  const userId = settingsStore.profile.userId
  if (!userId) return
  if (sessionStore.sessions.length === 0) await sessionStore.load(userId)
  await history.loadRag(userId, sessionStore.sessions, selectedRange.value)
}

watch(
  () => [chartMode.value, selectedRange.value, settingsStore.profile.userId],
  ([mode]) => {
    if (mode === 'line') void loadSelectedRagRange()
  },
)

const rangeStatus = computed(() => {
  const range = formatObsHistoryRange(selectedRange.value, '次', 'RAG')
  return `${range} · 已加载 ${history.ragHistory.value.length} 次 RAG`
})

const METRIC_TOOLTIP = 'fill rate：槽位填充率 = 返回条数 / 请求上限 × 100\navg relevance：平均相关性 = 各条目 final_score 均值 × 100\nconfidence：置信度，与 avg_relevance 同值'

const GREEN = '#6ee7b7'
const BLUE = '#4da6ff'
const ACCENT = '#d99178'
const BG_MUTED = 'rgba(255,255,255,0.06)'
const TXT_LABEL = '#777'
const BORDER = 'rgba(255,255,255,0.08)'

/** 指标配置 */
interface MetricConfig {
  key: string
  label: string
  color: string
}

const metricConfigs: MetricConfig[] = [
  { key: 'fillRate', label: 'fill rate', color: GREEN },
  { key: 'avgRelevance', label: 'avg relevance', color: BLUE },
  { key: 'confidence', label: 'confidence', color: ACCENT },
]

/** 三个环形指标 */
const gaugeOption = (value: number, color: string, label: string) => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    formatter: () => `${label}: <strong>${value}%</strong>`,
    backgroundColor: 'rgba(30,30,40,0.92)',
    borderColor: 'rgba(255,255,255,0.08)',
    borderWidth: 1,
    textStyle: { color: '#ccc', fontSize: 12 },
  },
  series: [
    {
      type: 'pie',
      radius: ['52%', '72%'],
      center: ['50%', '50%'],
      silent: false,
      emphasis: {
        scale: false,
        label: { show: false },
      },
      label: { show: false },
      labelLine: { show: false },
      data: [
        { value, itemStyle: { color } },
        { value: Math.max(0, 100 - value), itemStyle: { color: BG_MUTED } },
      ],
    },
  ],
})

/** 环形图项目 */
interface DonutItem extends MetricConfig {
  value: number
  option: ReturnType<typeof gaugeOption>
}

const donutItems = computed<DonutItem[]>(() => {
  const m = obs.ragMetrics.value
  return metricConfigs.map((item) => ({
    ...item,
    value: m[item.key as keyof typeof m] as number,
    option: gaugeOption(m[item.key as keyof typeof m] as number, item.color, item.label),
  }))
})

/** 曲线图：会话级三率历史 */
const lineOption = computed(() => {
  const rows = history.ragHistory.value

  return {
    backgroundColor: 'transparent',
    grid: { top: 12, right: 16, bottom: 24, left: 36 },
    xAxis: {
      type: 'category',
      data: rows.map((r) => `R${r.turn}`),
      axisLine: { lineStyle: { color: BORDER } },
      axisTick: { show: false },
      axisLabel: { color: TXT_LABEL, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: BORDER, type: 'dashed' } },
      axisLabel: { color: TXT_LABEL, fontSize: 11 },
    },
    series: [
      {
        name: 'fill rate',
        type: 'line',
        data: rows.map((r) => r.fillRate),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: GREEN, width: 1.5 },
        itemStyle: { color: GREEN },
      },
      {
        name: 'avg relevance',
        type: 'line',
        data: rows.map((r) => r.avgRelevance),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: BLUE, width: 1.5 },
        itemStyle: { color: BLUE },
      },
      {
        name: 'confidence',
        type: 'line',
        data: rows.map((r) => r.confidence),
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { color: ACCENT, width: 1.8 },
        itemStyle: { color: ACCENT },
      },
    ],
    legend: {
      bottom: 0,
      textStyle: { color: TXT_LABEL, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 6,
      icon: 'roundRect',
    },
    tooltip: { trigger: 'axis' },
  }
})
</script>

<template>
  <DashboardCardFrame
    title="RAG 填充率 / 平均相关性 / 置信度"
    :title-hint="METRIC_TOOLTIP"
    :status="chartMode === 'donut' ? '当前 Session' : rangeStatus"
  >
    <div class="card-body">
      <div class="chart-toolbar">
        <div ref="ragToggleRef" class="capsule-toggle">
          <div class="capsule-slider" :style="ragSliderStyle"></div>
          <button class="rag-btn" :class="{ active: chartMode === 'donut' }" type="button" @click="chartMode = 'donut'">饼图</button>
          <button class="rag-btn" :class="{ active: chartMode === 'line' }" type="button" @click="chartMode = 'line'">曲线图</button>
        </div>
        <DropdownSelect
          v-if="chartMode === 'line'"
          v-model="selectedRange"
          class="range-select"
          aria-label="RAG 曲线范围"
          :options="OBS_HISTORY_RANGE_OPTIONS.map((range) => ({ value: range, label: formatObsHistoryRange(range, '次', 'RAG') }))"
        />
      </div>

      <!-- 三个 donut -->
      <div v-if="chartMode === 'donut'" class="gauges-row">
        <div v-for="item in donutItems" :key="item.key" class="gauge-item">
          <div class="gauge-chart-wrap">
            <v-chart :option="item.option" autoresize class="gauge-chart" />
          </div>
          <div class="gauge-meta">
            <span class="gauge-value" :style="{ color: item.color }">{{ item.value }}%</span>
            <span class="gauge-label">{{ item.label }}</span>
          </div>
        </div>
      </div>

      <!-- 曲线图 -->
      <div v-else class="line-chart-wrap">
        <div v-if="history.ragLoading.value" class="chart-state">加载中</div>
        <div v-else-if="history.ragError.value" class="chart-state">{{ history.ragError.value }}</div>
        <v-chart v-else :option="lineOption" autoresize class="line-chart" />
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

.capsule-toggle {
  position: relative;
  display: inline-flex;
  align-self: flex-start;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  flex-shrink: 0;
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  flex-shrink: 0;
}

:deep(.range-select.ui-dropdown-select-trigger) {
  min-width: 88px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  padding: 0 6px;
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

.rag-btn {
  position: relative;
  z-index: 1;
  font-family: var(--font-ui);
  height: 28px;
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
  background: transparent;
  border: none;
  border-radius: 999px;
  padding: 0 8px;
  cursor: pointer;
  outline: none;
}

.rag-btn:hover {
  color: var(--color-primary);
}

.rag-btn.active {
  color: var(--color-primary);
}

.gauges-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}

.gauge-item {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  align-items: stretch;
  justify-items: center;
  gap: var(--space-6);
  min-width: 0;
  min-height: 150px;
}

.gauge-chart-wrap {
  width: 100%;
  height: 100%;
}

.gauge-chart {
  width: 100%;
  height: 100%;
}

.gauge-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.gauge-value {
  font-family: var(--font-ui);
  font-size: calc(14px * var(--font-scale));
  line-height: 1;
}

.gauge-label {
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.3;
  color: var(--color-text-tertiary);
  text-transform: lowercase;
}

.line-chart-wrap {
  flex: 1;
  min-height: 0;
}

.line-chart {
  width: 100%;
  height: 100%;
}

.chart-state {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
}

@media (max-width: 760px) {
  .gauges-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-6);
  }

  .gauge-item {
    min-height: 112px;
    gap: var(--space-4);
  }

  .gauge-chart-wrap {
    width: 100%;
    max-width: 88px;
    justify-self: center;
  }

  .gauge-value {
    font-size: calc(12px * var(--font-scale));
  }

  .gauge-label {
    font-size: calc(11px * var(--font-scale));
  }
}
</style>
