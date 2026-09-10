<!--
  TimeConsumptionPanel —— RAG 指标、Token 消耗与耗时观测页。
-->

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'

import { listLibraryItems } from '@/api/library'
import RagMetricsCard from '@/components/dashboard/RagMetricsCard.vue'
import TokenUsageCard from '@/components/dashboard/TokenUsageCard.vue'
import LatencyCard from '@/components/dashboard/LatencyCard.vue'
import ActivityHeatmapCard from '@/components/dashboard/ActivityHeatmapCard.vue'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { KnowledgeFileNode } from '@/types/knowledge'

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const libraryBookCount = ref(0)

const userId = computed(() => settingsStore.profile.userId)
const knowledgeFiles = computed(() => workspaceStore.flatNodes.filter((node) => !node.isDir))
const knowledgeFileCount = computed(() => knowledgeFiles.value.length)

const fileTypeSlices = computed(() => {
  const counts = new Map<string, number>()
  for (const node of knowledgeFiles.value) {
    const type = fileTypeOf(node)
    counts.set(type, (counts.get(type) ?? 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([label, value], index) => ({ label, value, color: pieColors[index % pieColors.length] }))
})

const typePieOption = computed(() => ({
  backgroundColor: 'transparent',
  color: pieColors,
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} 个 ({d}%)',
    backgroundColor: 'rgba(30,30,40,0.92)',
    borderColor: 'rgba(255,255,255,0.08)',
    borderWidth: 1,
    textStyle: { color: '#e5e7eb', fontSize: 12 },
  },
  legend: {
    show: false,
  },
  series: [
    {
      name: '文件类型',
      type: 'pie',
      radius: ['38%', '68%'],
      center: ['50%', '52%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 10,
        borderColor: 'transparent',
        borderWidth: 0,
      },
      label: {
        show: true,
        formatter: '{b}\n{c}',
        color: '#5f6673',
        fontSize: 12,
        fontWeight: 'bold',
        lineHeight: 14,
      },
      emphasis: {
        label: {
          show: true,
          fontSize: 12,
          fontWeight: 'bold',
          color: '#5f6673',
          formatter: '{b}\n{c}',
        },
      },
      labelLine: {
        show: true,
        length: 9,
        length2: 6,
        smooth: 0.2,
        lineStyle: {
          color: 'rgba(120,128,140,0.45)',
          width: 1,
        },
      },
      data: fileTypeSlices.value.length > 0
        ? fileTypeSlices.value.map((item) => ({ name: item.label, value: item.value }))
        : [{ name: '暂无文件', value: 0 }],
      animationType: 'scale',
      animationEasing: 'elasticOut',
      animationDelay: (index: number) => index * 80,
    },
  ],
}))

const pieColors = [
  '#4224eb',
  '#eb2463',
  '#26a269',
  '#e2a72e',
  '#f05d5e',
]

watch(userId, () => {
  void loadLibraryBookCount()
}, { immediate: true })

onMounted(() => {
  if (workspaceStore.flatNodes.length === 0) {
    void workspaceStore.loadKnowledgeTree()
  }
})

async function loadLibraryBookCount() {
  if (!userId.value) {
    libraryBookCount.value = 0
    return
  }
  const activeUserId = userId.value
  const queue = ['']
  let count = 0
  try {
    while (queue.length > 0) {
      const parentId = queue.shift() ?? ''
      const response = await listLibraryItems({ userId: activeUserId, parentId })
      for (const item of response.items) {
        if (item.item_type === 'book') count += 1
        if (item.item_type === 'collection') queue.push(item.item_id)
      }
    }
    if (userId.value === activeUserId) {
      libraryBookCount.value = count
    }
  } catch {
    libraryBookCount.value = 0
  }
}

function fileTypeOf(node: KnowledgeFileNode): string {
  const name = node.name || node.path
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex <= 0 || dotIndex === name.length - 1) return '无后缀'
  return name.slice(dotIndex + 1).toLowerCase()
}
</script>

<template>
  <div class="time-panel">
    <div class="row-upper">
      <div class="col-rag">
        <RagMetricsCard />
      </div>
      <div class="col-token">
        <TokenUsageCard />
      </div>
    </div>

    <div class="row-lower">
      <div class="col-planning">
        <div class="planning-left-column">
          <div class="planning-title"><span>全库数字总览</span></div>
          <div class="planning-left">
            <div class="planning-metrics">
              <div class="metric-row">
                <span class="metric-label">知识库文件</span>
                <span class="metric-value">{{ knowledgeFileCount }}</span>
              </div>
              <div class="metric-row">
                <span class="metric-label">图书馆图书</span>
                <span class="metric-value">{{ libraryBookCount }}</span>
              </div>
            </div>

            <div class="type-share-panel">
              <VChart class="type-pie-chart" :option="typePieOption" autoresize />
            </div>
          </div>
        </div>
        <div class="planning-right">
          <div class="planning-right-main">
            <ActivityHeatmapCard />
          </div>
        </div>
      </div>
      <div class="col-latency">
        <LatencyCard />
      </div>
    </div>
  </div>
</template>

<style scoped>
.time-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  overflow: hidden;
  padding: var(--space-10);
}

.row-upper {
  display: flex;
  gap: var(--space-10);
  min-height: 0;
  height: 240px;
  align-items: stretch;
}

.row-lower {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--space-10);
  flex: 1;
  min-height: 0;
}

.col-rag {
  flex: 0 0 auto;
  min-width: 200px;
  max-width: 340px;
  min-height: 0;
}

.col-token {
  width: 100%;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.col-planning,
.col-latency {
  width: 100%;
  min-width: 0;
  min-height: 0;
}

.col-planning {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(0, 2.4fr);
  gap: var(--space-10);
}

.planning-left-column {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-6);
}

.planning-title {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 18px;
  padding: 0 2px;
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
}

.planning-left {
  flex: 1 1 auto;
  border: 0;
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: 0 0 0 4px var(--library-form-ring);
}

.planning-right-main {
  display: flex;
  width: 100%;
  flex: 1 1 auto;
  align-items: flex-end;
  min-width: 0;
  min-height: 0;
}

.planning-right-main > * {
  width: 100%;
  height: auto;
  min-width: 0;
  min-height: 0;
}

.planning-left {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: var(--space-10);
}

.planning-metrics {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-8);
}

.metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  min-height: 58px;
  min-width: 0;
  border: 0;
  border-radius: 28px;
  padding: var(--space-10) var(--space-12);
  background: rgba(255, 255, 255, 0.02);
}

.metric-label {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-value {
  flex: 0 0 auto;
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
}

.type-share-panel {
  display: flex;
  width: 100%;
  aspect-ratio: 1;
  min-height: 0;
  margin-top: auto;
  background: transparent;
}

.type-pie-chart {
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 0;
}

.planning-right {
  display: flex;
  min-width: 0;
  min-height: 0;
}

.col-rag > *,
.col-token > *,
.col-latency > * {
  height: 100%;
  width: 100%;
  min-width: 0;
  min-height: 0;
}

@media (max-width: 1200px) {
  .time-panel {
    flex: 0 0 auto;
    min-height: 100%;
    overflow: visible;
  }

  .row-lower {
    grid-template-columns: minmax(0, 1fr);
    flex: none;
  }

  .row-upper {
    flex: none;
  }

  .col-planning {
    grid-template-columns: minmax(180px, 0.65fr) minmax(0, 1.35fr);
    min-height: 460px;
  }

  .col-latency {
    height: auto;
    min-height: 320px;
  }

  .col-latency > * {
    height: auto;
  }

  .planning-left {
    overflow: visible;
  }
}

@media (max-width: 768px) {
  .time-panel {
    flex: none;
    overflow: visible;
    padding: var(--space-8);
  }

  .row-upper,
  .row-lower {
    display: flex;
    flex: none;
    flex-direction: column;
  }

  .row-upper {
    height: auto;
  }

  .col-rag {
    flex: none;
    width: 100%;
    max-width: none;
    height: 220px;
    min-height: 220px;
  }

  .col-planning {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .planning-right {
    min-height: 420px;
  }

  .type-share-panel {
    flex: none;
    height: clamp(180px, 40vw, 260px);
    aspect-ratio: auto;
    margin-top: 0;
  }

  .col-token {
    flex: none;
    height: 320px;
  }

  .col-latency {
    flex: none;
    height: auto;
    min-height: 320px;
  }
}

@media (max-width: 560px) {
  .time-panel {
    gap: var(--space-8);
    padding: var(--space-8) var(--space-6);
  }
}
</style>
