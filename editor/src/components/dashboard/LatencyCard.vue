<!--
  LatencyCard —— 每次 message 思考耗时折线图。
  跨全部历史 Session 按时间铺开，点击数据点展开该 message 的步骤耗时占比。
  ECharts 渲染，弹性布局。
-->

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'
import {
  OBS_HISTORY_RANGE_OPTIONS,
  formatObsHistoryRange,
  useObsHistory,
  type ObsHistoryRange,
} from '@/composable/useObsHistory'
import { useObsData, type LatencyTurn } from '@/composable/useObsData'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'
import DropdownSelect from '@/components/ui/dropdown-menu/DropdownSelect.vue'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

const history = useObsHistory()
const obsData = useObsData()
const sessionStore = useSessionStore()
const settingsStore = useSettingsStore()
const selectedIdx = ref(-1)

const turns = computed<LatencyTurn[]>(() => {
  const sessionId = sessionStore.currentSessionId
  const liveTurns = obsData.latencyTurns.value
  if (!sessionId || liveTurns.length === 0) return history.latencyTurns.value
  const sessionName = sessionStore.currentSession?.session_name || sessionId
  const mergedTurns = [
    ...history.latencyTurns.value.filter((turn) => turn.sessionId !== sessionId),
    ...liveTurns.map((turn) => ({
      ...turn,
      id: `${sessionId}:live:${turn.id}`,
      sessionId,
      sessionName,
    })),
  ].sort((left, right) => {
    const leftTime = Date.parse(left.createdAt || '')
    const rightTime = Date.parse(right.createdAt || '')
    if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) return 0
    return leftTime - rightTime
  })
  let cumulativeSeconds = 0
  return mergedTurns.map((turn, index) => {
    cumulativeSeconds += turn.seconds
    return {
      ...turn,
      index: index + 1,
      cumulativeSeconds: Number(cumulativeSeconds.toFixed(2)),
    }
  })
})
const hasTurns = computed(() => turns.value.length > 0)
const selectedRange = computed<ObsHistoryRange>({
  get: () => history.latencyLimit.value,
  set: (value) => {
    history.latencyLimit.value = value
  },
})

/** Load only the currently selected latency range. */
async function loadSelectedLatencyRange(): Promise<void> {
  const userId = settingsStore.profile.userId
  if (!userId) return
  if (sessionStore.sessions.length === 0) await sessionStore.load(userId)
  await history.loadLatency(userId, sessionStore.sessions, selectedRange.value)
}

watch(
  () => [selectedRange.value, settingsStore.profile.userId],
  () => {
    void loadSelectedLatencyRange()
  },
  { immediate: true },
)

watch(turns, (val) => {
  if (val.length > 0) {
    selectedIdx.value = val.length - 1
  }
}, { immediate: true })

const summaryLabel = computed(() => {
  const range = formatObsHistoryRange(selectedRange.value, '条', 'message')
  if (turns.value.length === 0) return `${range} · no data`
  const total = turns.value.reduce((sum, turn) => sum + turn.seconds, 0)
  const average = Number((total / turns.value.length).toFixed(2))
  const maximum = Number(Math.max(...turns.value.map((turn) => turn.seconds)).toFixed(2))
  return `${range} · avg ${average}s · max ${maximum}s · ${turns.value.length} messages`
})

const emptyHint = computed(() => {
  if (history.latencyError.value) return `$ ${history.latencyError.value}`
  return `$ no latency data | sessions ${history.latencySessions.value.length} | messages ${history.latencyMessages.value.length}`
})

const selectedTurn = computed(() => {
  if (selectedIdx.value < 0 || selectedIdx.value >= turns.value.length) return null
  return turns.value[selectedIdx.value]
})

const selectedBreakdown = computed(() => {
  const turn = selectedTurn.value
  if (!turn) return []
  if (turn.nodeBreakdown.length > 0) return turn.nodeBreakdown
  return [{
    node: 'agent',
    count: 1,
    durationMs: turn.seconds * 1000,
    seconds: turn.seconds,
    share: 100,
  }]
})

const ACCENT = '#d99178'
const LINE_COLOR = '#e8a880'
const POINT_FILL = '#1a1a2e'
const ACTIVE_FILL = '#d99178'
const GRID_COLOR = 'rgba(255,255,255,0.10)'
const TXT_LABEL = '#888'
const NODE_COLORS = ['#4da6ff', '#d99178', '#6ee7b7', '#a78bfa', '#f59e0b', '#f472b6', '#94a3b8']

function nodeColor(i: number): string {
  return NODE_COLORS[i % NODE_COLORS.length] || NODE_COLORS[0] || '#888'
}

const lineOption = computed(() => {
  const items = turns.value as typeof turns.value
  const sel = selectedIdx.value

  return {
    backgroundColor: 'transparent',
    grid: { top: 14, right: 20, bottom: 24, left: 42 },
    xAxis: {
      type: 'category',
      data: items.map((t) => `M${t.index}`),
      axisLine: { lineStyle: { color: GRID_COLOR } },
      axisTick: { show: false },
      axisLabel: { color: TXT_LABEL, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '秒',
      min: 0,
      nameTextStyle: { color: TXT_LABEL, fontSize: 11 },
      splitLine: { lineStyle: { color: GRID_COLOR, type: 'dashed' } },
      axisLabel: { color: TXT_LABEL, fontSize: 11 },
    },
    series: [{
      type: 'line',
      data: items.map((t, i) => {
        const isSel = i === sel
        return {
          value: t.seconds,
          symbol: items.length === 1 ? 'pin' : 'circle',
          symbolSize: items.length === 1 ? 14 : (isSel ? 10 : 6),
          itemStyle: {
            color: isSel ? ACTIVE_FILL : POINT_FILL,
            borderColor: LINE_COLOR,
            borderWidth: 1.5,
          },
        }
      }),
      smooth: true,
      lineStyle: { color: LINE_COLOR, width: items.length === 1 ? 0 : 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: `${ACCENT}30` },
            { offset: 1, color: `${ACCENT}01` },
          ],
        },
      },
      emphasis: {
        scale: true,
        scaleSize: 3,
        focus: 'self',
      },
    }],
    tooltip: {
      trigger: 'axis',
      formatter: (params: { dataIndex: number; value: number }[]) => {
        const p = params[0]!
        const turn = items[p.dataIndex]
        return `${turn?.sessionName || turn?.sessionId || 'Session'}<br/>Message ${p.dataIndex + 1}<br/>${p.value}s`
      },
    },
  }
})

/** 纵向柱状图 — 选中轮次的节点占比 */
const barOption = computed(() => {
  const items = selectedBreakdown.value
  if (items.length === 0) return {}
  return {
    backgroundColor: 'transparent',
    grid: { top: 14, right: 8, bottom: 24, left: 30 },
    xAxis: {
      type: 'category',
      data: items.map((d) => d.node),
      axisLabel: { color: TXT_LABEL, fontSize: 11, rotate: items.length > 4 ? 30 : 0 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      max: 100,
      splitLine: { lineStyle: { color: GRID_COLOR, type: 'dashed' } },
      axisLabel: { color: TXT_LABEL, fontSize: 11, formatter: '{value}%' },
    },
    series: [{
      type: 'bar',
      data: items.map((d, i) => ({
        value: d.share,
        itemStyle: { color: nodeColor(i), borderRadius: [3, 3, 0, 0] },
      })),
      animationDuration: 800,
      animationEasing: 'cubicOut',
    }],
  }
})

/** 南丁格尔玫瑰图 — 选中轮次的节点占比 */
const roseOption = computed(() => {
  const items = selectedBreakdown.value
  if (items.length === 0) return {}
  return {
    backgroundColor: 'transparent',
    legend: {
      bottom: 0,
      textStyle: { color: TXT_LABEL, fontSize: 11 },
      itemWidth: 8,
      itemHeight: 6,
      icon: 'roundRect',
    },
    series: [{
      type: 'pie',
      radius: '65%',
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 2 },
      label: { show: false },
      data: items.map((d, i) => ({
        name: d.node,
        value: d.share,
        itemStyle: { color: nodeColor(i) },
      })),
      animationDuration: 800,
    }],
  }
})

function onLineClick(params: { componentType?: string; dataIndex?: number }): void {
  if (hasTurns.value && params.componentType === 'series') {
    const idx = params.dataIndex!
    selectedIdx.value = selectedIdx.value === idx ? -1 : idx
  }
}
</script>

<template>
  <DashboardCardFrame title="每次 message 思考耗时" :status="summaryLabel">
    <div class="card-body">
      <div class="chart-toolbar">
        <label class="range-label" for="latency-history-range">显示范围</label>
        <DropdownSelect
          id="latency-history-range"
          v-model="selectedRange"
          class="range-select"
          aria-label="思考耗时显示范围"
          :options="OBS_HISTORY_RANGE_OPTIONS.map((range) => ({ value: range, label: formatObsHistoryRange(range, '条', 'message') }))"
        />
      </div>

      <div class="line-chart-wrap">
        <div v-if="history.latencyLoading.value" class="chart-loading">加载中</div>
        <v-chart
          v-else-if="hasTurns"
          :option="lineOption"
          autoresize
          class="line-chart"
          @click="onLineClick"
        />
        <div v-else class="line-chart-skeleton" aria-hidden="true">
          <svg class="line-skeleton-svg" viewBox="0 0 100 60" preserveAspectRatio="none">
            <line x1="12" y1="6" x2="12" y2="50" class="axis-line" />
            <line x1="12" y1="50" x2="96" y2="50" class="axis-line" />
            <line x1="12" y1="16" x2="96" y2="16" class="grid-line" />
            <line x1="12" y1="28" x2="96" y2="28" class="grid-line" />
            <line x1="12" y1="40" x2="96" y2="40" class="grid-line" />
            <text x="2" y="17" class="axis-text">1</text>
            <text x="2" y="29" class="axis-text">0.5</text>
            <text x="5" y="41" class="axis-text">0</text>
            <text x="15" y="57" class="axis-text">M1</text>
            <text x="43" y="57" class="axis-text">M2</text>
            <text x="71" y="57" class="axis-text">M3</text>
            <polyline points="18,42 44,31 70,35 90,20" class="ghost-line" />
            <circle cx="18" cy="42" r="1.8" class="ghost-dot" />
            <circle cx="44" cy="31" r="1.8" class="ghost-dot" />
            <circle cx="70" cy="35" r="1.8" class="ghost-dot" />
            <circle cx="90" cy="20" r="1.8" class="ghost-dot" />
          </svg>
        </div>
      </div>

      <div v-if="selectedTurn" class="detail-panel">
        <div class="detail-summary">
          <span class="detail-title">{{ selectedTurn.sessionName || selectedTurn.sessionId }} · Message {{ selectedTurn.index }}</span>
          <span class="detail-time">{{ selectedTurn.seconds }}s{{ selectedTurn.estimated ? ' (est.)' : '' }}</span>
        </div>
        <div v-if="selectedBreakdown.length > 0" class="breakdown-charts">
          <div class="breakdown-col">
            <span class="col-label">步骤占比（柱状）</span>
            <v-chart :option="barOption" autoresize class="breakdown-chart" />
          </div>
          <div class="breakdown-col">
            <span class="col-label">步骤占比（玫瑰）</span>
            <v-chart :option="roseOption" autoresize class="breakdown-chart" />
          </div>
        </div>

        <p class="detail-prompt">{{ selectedTurn.userPrompt }}</p>
      </div>

      <div v-else-if="turns.length > 0" class="no-selection">
        <span class="placeholder-text">$ 点击上方数据点查看各步骤耗时占比</span>
      </div>

      <div v-else class="empty-state">
        <span class="placeholder-text">{{ emptyHint }}</span>
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
  overflow-y: auto;
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-6);
  flex-shrink: 0;
}

.range-label {
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

:deep(.range-select.ui-dropdown-select-trigger) {
  min-width: 96px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  padding: 0 var(--space-6);
}

/* ---- 折线图 ---- */
.line-chart-wrap {
  flex-shrink: 0;
  height: 150px;
  min-height: 150px;
  border-bottom: 1px solid var(--color-border);
}

.line-chart {
  width: 100%;
  height: 100%;
  min-height: 100px;
}

.chart-loading {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
}

.line-chart-skeleton {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: stretch;
}

.line-skeleton-svg {
  width: 100%;
  height: 100%;
}

.axis-line {
  stroke: var(--color-border-strong);
  stroke-width: 1;
}

.grid-line {
  stroke: var(--color-border);
  stroke-width: 1;
  stroke-dasharray: 2 2;
}

.axis-text {
  fill: var(--color-text-secondary);
  font-size: calc(4.5px * var(--font-scale));
  font-family: var(--font-ui);
}

.ghost-line {
  fill: none;
  stroke: rgba(217, 145, 120, 0.6);
  stroke-width: 1.5;
}

.ghost-dot {
  fill: rgba(217, 145, 120, 0.8);
}

/* ---- 明细面板 ---- */
.detail-panel {
  border-top: 1px solid var(--color-border-light);
  padding-top: var(--space-8);
  flex-shrink: 0;
  overflow: visible;
}

.detail-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
  margin-bottom: var(--space-4);
}

.detail-title {
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-primary);
  min-width: 0;
  overflow-wrap: anywhere;
}

.detail-time {
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  color: var(--color-accent);
  margin-left: auto;
}

.detail-prompt {
  font-family: var(--font-text);
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
  margin: var(--space-8) 0 0;
  overflow: visible;
}

/* ---- 步骤占比 ---- */
.breakdown-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-10);
  margin-top: var(--space-8);
  min-height: 142px;
}

@media (max-width: 1200px) {
  .card-body {
    overflow-y: visible;
  }
}

@media (max-width: 480px) {
  .breakdown-charts {
    grid-template-columns: 1fr;
  }
}

.breakdown-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.col-label {
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-4);
  flex-shrink: 0;
}

.breakdown-chart {
  width: 100%;
  height: 118px;
  min-height: 118px;
  flex-shrink: 0;
}

/* ---- 提示 / 空状态 ---- */
.no-selection {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-10);
  border: 1px dashed var(--color-border);
  flex: 1;
  min-height: 0;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--color-border);
  min-height: 72px;
}

.placeholder-text {
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  max-width: 100%;
  overflow-wrap: anywhere;
  text-align: center;
}
</style>
