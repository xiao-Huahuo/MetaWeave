<!--
  Daily activity heatmap dashboard card.

  Usage:
  Place inside the Dashboard planning area. The card loads the persisted yearly
  activity response, offers module-specific color filters, and fits the entire
  53-week grid into the card without internal scrolling.
-->

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'

import {
  fetchActivityHeatmap,
  type ActivityDay,
  type ActivityFilter,
  type ActivityHeatmapResponse,
  type ActivitySummary,
} from '@/api/activity'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'
import {
  ContributionGraph,
  ContributionGraphBlock,
  ContributionGraphGroup,
} from '@/components/ui/contribution-graph'
import { useSettingsStore } from '@/stores/settings'

defineOptions({ name: 'ActivityHeatmapCard' })

interface FilterConfig {
  key: ActivityFilter
  label: string
  color: string
}

interface CalendarDay {
  date: string
  future: boolean
  activity: ActivityDay | null
}

const filters: FilterConfig[] = [
  { key: 'all', label: '总览', color: '#27885b' },
  { key: 'library', label: '图书馆', color: '#eb2463' },
  { key: 'documents', label: '文档', color: '#1485d1' },
  { key: 'knowledge', label: '知识', color: '#7657dc' },
  { key: 'agent', label: 'Agent', color: '#c98516' },
  { key: 'tasks', label: '任务', color: '#27885b' },
  { key: 'other', label: '其他', color: '#687a92' },
]

const emptySummary: ActivitySummary = {
  total_score: 0,
  active_days: 0,
  current_streak: 0,
  peak_score: 0,
}

const settingsStore = useSettingsStore()
const payload = ref<ActivityHeatmapResponse | null>(null)
const activeFilter = ref<ActivityFilter>('all')
const loading = ref(false)
const errorMessage = ref('')
const calendarPanelRef = ref<HTMLElement | null>(null)
const visibleWeekCount = ref(52)
let calendarResizeObserver: ResizeObserver | null = null
const calendarWeekPitch = 13
const calendarLabelWidth = 31
const filterRailRef = ref<HTMLElement | null>(null)
const filterSliderStyle = ref({ width: '0px', left: '0px' })
let filterResizeObserver: ResizeObserver | null = null

const userId = computed(() => settingsStore.profile.userId)
const activeFilterConfig = computed(() => filters.find((item) => item.key === activeFilter.value) ?? filters[0]!)
const activeFilterIndex = computed(() => filters.findIndex((item) => item.key === activeFilter.value))
const activeSummary = computed(() => payload.value?.summaries[activeFilter.value] ?? emptySummary)
const activityByDate = computed(() => new Map((payload.value?.days ?? []).map((day) => [day.date, day])))
const cardStyle = computed<CSSProperties>(() => ({
  '--heat-color': activeFilterConfig.value.color,
  '--contribution-color': activeFilterConfig.value.color,
  '--filter-index': activeFilterIndex.value,
}))

const calendarWeeks = computed<CalendarDay[][]>(() => {
  const endDate = parseDate(payload.value?.end_date || todayIso())
  const gridStart = addDays(endDate, -363)
  return Array.from({ length: 52 }, (_, weekIndex) => (
    Array.from({ length: 7 }, (_, dayIndex) => {
      const current = addDays(gridStart, weekIndex * 7 + dayIndex)
      const date = formatIsoDate(current)
      return { date, future: false, activity: activityByDate.value.get(date) ?? null }
    })
  ))
})

const visibleCalendarWeeks = computed(() => calendarWeeks.value.slice(-visibleWeekCount.value))
const monthTicks = computed(() => {
  let previousMonth = ''
  return visibleCalendarWeeks.value.reduce<Array<{ label: string; weekIndex: number }>>((ticks, week, weekIndex) => {
    const month = week[0]?.date.slice(0, 7) ?? ''
    if (month && month !== previousMonth) {
      ticks.push({ label: `${Number(month.slice(5))}月`, weekIndex })
      previousMonth = month
    }
    return ticks
  }, [])
})

const metricItems = computed(() => [
  { label: '活跃值', value: activeSummary.value.total_score },
  { label: '活跃天数', value: activeSummary.value.active_days },
  { label: '连续活跃', value: `${activeSummary.value.current_streak} 天` },
  { label: '单日峰值', value: activeSummary.value.peak_score },
])

watch(userId, () => void loadActivity(), { immediate: true })

watch(activeFilter, () => {
  void nextTick(updateFilterSlider)
})

watch(payload, async (value) => {
  if (!value) return
  await nextTick()
  observeCalendarPanel()
})

function observeCalendarPanel(): void {
  const panel = calendarPanelRef.value
  if (!panel || typeof ResizeObserver === 'undefined') return
  const updateVisibleWeeks = () => {
    const weeks = Math.floor((panel.clientWidth - calendarLabelWidth + 3) / calendarWeekPitch)
    visibleWeekCount.value = Math.max(4, Math.min(52, weeks))
  }
  updateVisibleWeeks()
  calendarResizeObserver?.disconnect()
  calendarResizeObserver = new ResizeObserver(updateVisibleWeeks)
  calendarResizeObserver.observe(panel)
}

function updateFilterSlider(): void {
  const rail = filterRailRef.value
  const activeButton = rail?.querySelector<HTMLElement>('.filter-button.active')
  if (!activeButton) return
  filterSliderStyle.value = {
    width: `${activeButton.offsetWidth}px`,
    left: `${activeButton.offsetLeft}px`,
  }
}

onMounted(() => {
  void nextTick(() => {
    updateFilterSlider()
    if (filterRailRef.value && typeof ResizeObserver !== 'undefined') {
      filterResizeObserver = new ResizeObserver(updateFilterSlider)
      filterResizeObserver.observe(filterRailRef.value)
    }
  })
})

onBeforeUnmount(() => {
  calendarResizeObserver?.disconnect()
  calendarResizeObserver = null
  filterResizeObserver?.disconnect()
  filterResizeObserver = null
})

/** Load one persisted dataset and keep the latest active day selected. */
async function loadActivity(): Promise<void> {
  if (!userId.value) {
    payload.value = null
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    payload.value = await fetchActivityHeatmap(userId.value)
  } catch {
    payload.value = null
    errorMessage.value = '活跃数据加载失败'
  } finally {
    loading.value = false
  }
}

/** Return the selected filter score for one day. */
function scoreForDay(day: ActivityDay | null): number {
  if (!day) return 0
  return activeFilter.value === 'all' ? day.score : day.modules[activeFilter.value]?.score ?? 0
}

/** Convert a score to the fixed seven-level contribution scale. */
function levelForScore(score: number): number {
  if (score <= 0) return 0
  if (score <= 3) return 1
  if (score <= 7) return 2
  if (score <= 12) return 3
  if (score <= 18) return 4
  if (score <= 27) return 5
  return 6
}

/** Build a concise accessible label for one heat cell. */
function cellLabel(day: CalendarDay): string {
  if (day.future) return `${day.date}，未来日期`
  const score = scoreForDay(day.activity)
  return `${formatDisplayDate(day.date)}，${activeFilterConfig.value.label}活跃值 ${score}`
}

/** Format an ISO date for the compact detail heading. */
function formatDisplayDate(value: string): string {
  const parsed = parseDate(value)
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日`
}

/** Parse a date-only value without applying a UTC timezone shift. */
function parseDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year || 1970, (month || 1) - 1, day || 1)
}

/** Return a new local calendar date offset by a whole number of days. */
function addDays(value: Date, amount: number): Date {
  const result = new Date(value)
  result.setDate(result.getDate() + amount)
  return result
}

/** Serialize a local calendar date as YYYY-MM-DD. */
function formatIsoDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

/** Return today's local date for the pre-load calendar shell. */
function todayIso(): string {
  return formatIsoDate(new Date())
}
</script>

<template>
  <DashboardCardFrame
    title="每日活跃热力图"
    :status="payload ? `${payload.start_date.slice(0, 7)} — ${payload.end_date.slice(0, 7)}` : '最近一年'"
  >
    <section
      class="activity-card"
      :class="{ 'is-overview': activeFilter === 'all' }"
      :style="cardStyle"
      aria-labelledby="activity-heatmap-title"
    >
      <h2 id="activity-heatmap-title" class="sr-only">每日活跃热力图</h2>

      <div ref="filterRailRef" class="filter-rail" role="tablist" aria-label="活跃模块筛选">
        <span class="filter-slider" :style="filterSliderStyle" aria-hidden="true"></span>
        <button
          v-for="filter in filters"
          :key="filter.key"
          class="filter-button"
          :class="{ active: activeFilter === filter.key }"
          :data-filter="filter.key"
          type="button"
          role="tab"
          :aria-selected="activeFilter === filter.key"
          @click="activeFilter = filter.key"
        >
          <span>{{ filter.label }}</span>
          <small>{{ payload?.summaries[filter.key]?.total_score ?? 0 }}</small>
        </button>
      </div>

      <div class="metric-strip" aria-live="polite">
        <div v-for="metric in metricItems" :key="metric.label" class="metric-item">
          <span>{{ metric.label }}</span>
          <strong :key="`${activeFilter}-${metric.label}`">{{ metric.value }}</strong>
        </div>
      </div>

      <div v-if="loading" class="card-state" role="status">正在汇总有效活动…</div>
      <div v-else-if="errorMessage" class="card-state error" role="alert">
        <span>{{ errorMessage }}</span>
        <button type="button" @click="loadActivity">重试</button>
      </div>

      <div v-else class="heatmap-layout">
        <div ref="calendarPanelRef" class="calendar-panel">
          <div class="calendar-content">
            <div class="month-ticks" aria-hidden="true">
              <span
                v-for="tick in monthTicks"
                :key="`${tick.label}-${tick.weekIndex}`"
                class="month-tick"
                :style="{ left: `${calendarLabelWidth + tick.weekIndex * calendarWeekPitch}px` }"
              >{{ tick.label }}</span>
            </div>
            <div class="calendar-grid">
              <div class="weekday-labels" aria-hidden="true">
                <span></span>
                <span>一</span>
                <span></span>
                <span>三</span>
                <span></span>
                <span>五</span>
                <span></span>
              </div>
              <ContributionGraph class="activity-contribution-graph" :aria-label="`最近${visibleWeekCount}周每日活跃情况`">
                <ContributionGraphGroup v-for="(week, weekIndex) in visibleCalendarWeeks" :key="weekIndex">
                  <ContributionGraphBlock
                    v-for="day in week"
                    :key="day.date"
                    :level="day.future ? 0 : levelForScore(scoreForDay(day.activity))"
                    :title="cellLabel(day)"
                  />
                </ContributionGraphGroup>
              </ContributionGraph>
            </div>
            <div class="contribution-legend" aria-label="活跃程度图例：从少到多">
              <span>少</span>
              <i v-for="level in 7" :key="level" class="legend-cell" :data-level="level - 1"></i>
              <span>多</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </DashboardCardFrame>
</template>

<style scoped>
.activity-card {
  --heat-color: #4224eb;
  --filter-index: 0;
  --ease-out-strong: cubic-bezier(0.23, 1, 0.32, 1);
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: var(--space-8);
  min-width: 0;
  min-height: 0;
  padding: var(--space-8) var(--space-10) var(--space-10);
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  overflow: hidden;
}

:deep(.dashboard-card),
:deep(.dashboard-card-surface) {
  height: auto;
}

:deep(.dashboard-card-surface) {
  flex: 0 0 auto;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.filter-rail {
  position: relative;
  display: inline-flex;
  align-self: flex-start;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 2px;
  background: var(--color-surface);
}

.filter-slider {
  position: absolute;
  z-index: 0;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  transition:
    left 250ms ease,
    width 250ms ease;
  pointer-events: none;
}

.filter-button {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  border-radius: 999px;
  border: 0;
  height: 28px;
  padding: 0 8px;
  color: var(--color-text-tertiary);
  background: transparent;
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: color 140ms ease, transform 120ms var(--ease-out-strong);
}

.filter-button small {
  color: inherit;
  font-size: calc(11px * var(--font-scale));
  font-variant-numeric: tabular-nums;
  opacity: 0.62;
}

.filter-button.active {
  color: var(--heat-color);
  font-weight: var(--font-weight-semibold);
}

.filter-button:active {
  transform: scale(0.97);
}

.filter-button:focus-visible,
.heat-cell:focus-visible {
  outline: 2px solid var(--heat-color);
  outline-offset: 1px;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  flex: 0 0 auto;
  border-block: 1px solid var(--color-border);
}

.metric-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-6);
  min-width: 0;
  padding: 6px var(--space-8);
}

.metric-item + .metric-item {
  border-left: 1px solid var(--color-border);
}

.metric-item span {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-tertiary);
  font-size: calc(12px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-item strong {
  color: var(--heat-color);
  font-size: calc(14px * var(--font-scale));
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  animation: metric-in 160ms var(--ease-out-strong);
}

.heatmap-layout {
  display: flex;
  flex: 0 0 auto;
  min-width: 0;
  overflow: hidden;
}

.calendar-panel {
  display: flex;
  width: 100%;
  flex: 1 1 auto;
  align-items: center;
  justify-content: center;
  min-width: 0;
  overflow: hidden;
}

.calendar-content {
  width: max-content;
  max-width: 100%;
}

.month-ticks {
  position: relative;
  height: 13px;
  margin-bottom: 4px;
  color: var(--color-text-tertiary);
  font-size: calc(11px * var(--font-scale));
  line-height: 13px;
  white-space: nowrap;
}

.month-tick {
  position: absolute;
  top: 0;
}

.calendar-grid {
  display: flex;
  align-items: flex-start;
}

.weekday-labels {
  display: grid;
  grid-template-rows: repeat(7, 10px);
  gap: 3px;
  width: 31px;
  flex: 0 0 31px;
  color: var(--color-text-tertiary);
  font-size: calc(10px * var(--font-scale));
  line-height: 10px;
}

.contribution-legend {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
  min-height: 18px;
  margin-top: 7px;
  color: var(--color-text-tertiary);
  font-size: calc(10px * var(--font-scale));
  line-height: 10px;
}

.legend-cell,
.activity-contribution-graph :deep(.contribution-graph-block) {
  width: 10px;
  height: 10px;
  flex-basis: 10px;
  border-radius: 2px;
}

.legend-cell {
  box-sizing: border-box;
  display: inline-block;
  border: 0.5px solid color-mix(in srgb, var(--color-border) 30%, transparent);
  background: color-mix(in srgb, var(--color-text-tertiary) 10%, transparent);
}

.activity-contribution-graph,
.activity-contribution-graph :deep(.contribution-graph-group) {
  gap: 3px;
}

.legend-cell[data-level='1'] { background: color-mix(in srgb, var(--contribution-color) 23%, transparent); }
.legend-cell[data-level='2'] { background: color-mix(in srgb, var(--contribution-color) 38%, transparent); }
.legend-cell[data-level='3'] { background: color-mix(in srgb, var(--contribution-color) 54%, transparent); }
.legend-cell[data-level='4'] { background: color-mix(in srgb, var(--contribution-color) 69%, transparent); }
.legend-cell[data-level='5'] { background: color-mix(in srgb, var(--contribution-color) 84%, transparent); }
.legend-cell[data-level='6'] { background: var(--contribution-color); }

/* Match the contribution graph's green overview scale: gray zero, then six
   increasingly saturated greens instead of translucent theme mixing. */
.activity-card.is-overview :deep(.contribution-graph-block[data-level='0']) { background: #ebedf0; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='1']) { background: #d4f8dd; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='2']) { background: #a6edb5; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='3']) { background: #69db86; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='4']) { background: #40c463; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='5']) { background: #30a14e; }
.activity-card.is-overview :deep(.contribution-graph-block[data-level='6']) { background: #216e39; }
.activity-card.is-overview .legend-cell[data-level='0'] { background: #ebedf0; }
.activity-card.is-overview .legend-cell[data-level='1'] { background: #d4f8dd; }
.activity-card.is-overview .legend-cell[data-level='2'] { background: #a6edb5; }
.activity-card.is-overview .legend-cell[data-level='3'] { background: #69db86; }
.activity-card.is-overview .legend-cell[data-level='4'] { background: #40c463; }
.activity-card.is-overview .legend-cell[data-level='5'] { background: #30a14e; }
.activity-card.is-overview .legend-cell[data-level='6'] { background: #216e39; }

.activity-contribution-graph {
  flex: 0 0 auto;
}

.card-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-8);
  flex: 1;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
}

.card-state button {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 3px 8px;
  color: var(--color-primary);
  background: var(--color-surface);
  cursor: pointer;
}

@keyframes metric-in {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (hover: hover) and (pointer: fine) {
  .filter-button:hover { color: var(--heat-color); }
}

@media (prefers-reduced-motion: reduce) {
  .filter-slider,
  .filter-button {
    transition-duration: 120ms;
  }
  .metric-item strong {
    opacity: 1;
    transform: none;
    animation: none;
  }
}

@media (prefers-contrast: more) {
  .filter-rail,
  .metric-strip { border-color: var(--color-text-secondary); }
}

@media (max-width: 560px) {
  .filter-rail {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    width: 100%;
    border-radius: var(--radius-md);
  }

  .filter-slider {
    display: none;
  }

  .filter-button {
    padding: 4px;
  }

  .filter-button.active {
    background: color-mix(in srgb, var(--heat-color) 14%, transparent);
  }

  .metric-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-item:nth-child(3) {
    border-left: 0;
  }

  .metric-item:nth-child(n + 3) {
    border-top: 1px solid var(--color-border);
  }
}
</style>
