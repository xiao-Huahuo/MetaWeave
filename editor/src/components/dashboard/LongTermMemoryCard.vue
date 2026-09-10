<!--
  LongTermMemoryCard —— 长期记忆真实召回卡片。
  展示后端真实返回的 ReRank 前候选与 ReRank 后结果,不再使用前端伪造切片。
-->

<script setup lang="ts">
import { computed, ref } from 'vue'
import DashboardCardFrame from '@/components/dashboard/DashboardCardFrame.vue'

/** 记忆召回条目 */
interface MemoryRecallItem {
  memory_id?: string
  memory_type?: string
  content?: string
  merged_score?: number
  final_score?: number
  vector_score?: number
  keyword_score?: number
  rerank_score?: number
  retrieval_channels?: string[]
  matched_terms?: string[]
}

/** 召回快照 */
interface RecallSnapshot {
  pre_rerank?: MemoryRecallItem[]
  post_rerank?: MemoryRecallItem[]
}

const props = withDefaults(defineProps<{
  recallSnapshot?: RecallSnapshot
  isLoading?: boolean
}>(), {
  recallSnapshot: () => ({ pre_rerank: [], post_rerank: [] }),
  isLoading: false,
})

const activeTab = ref<'pre' | 'post'>('pre')

const preItems = computed(() => props.recallSnapshot?.pre_rerank || [])
const postItems = computed(() => props.recallSnapshot?.post_rerank || [])
const currentItems = computed(() => (activeTab.value === 'pre' ? preItems.value : postItems.value))
const windowStatus = computed(() => (
  activeTab.value === 'pre' ? `${preItems.value.length} candidates` : `${postItems.value.length} selected`
))

function formatMemoryType(value: string | undefined): string {
  const map: Record<string, string> = {
    session_fact: 'SESSION FACT',
    important_fact_summary: 'IMPORTANT SUMMARY',
    session_summary: 'SESSION SUMMARY',
  }
  return map[value || ''] || String(value || 'MEMORY').replace(/_/g, ' ').toUpperCase()
}

function formatChannels(channels: string[] | undefined): string {
  return Array.isArray(channels) && channels.length > 0 ? channels.join(' + ') : '--'
}

function formatScore(value: number | undefined): string {
  return typeof value === 'number' ? value.toFixed(3) : '--'
}
</script>

<template>
  <DashboardCardFrame title="长期记忆召回" :status="windowStatus">
    <div class="card-body">
      <div class="chart-toolbar" :class="{ post: activeTab === 'post' }">
        <span class="chart-mode-slider" aria-hidden="true"></span>
        <button class="chart-mode-btn" :class="{ active: activeTab === 'pre' }" @click="activeTab = 'pre'">ReRank 前</button>
        <button class="chart-mode-btn" :class="{ active: activeTab === 'post' }" @click="activeTab = 'post'">ReRank 后</button>
      </div>

      <div v-if="isLoading" class="empty-state">
        <span class="placeholder-text">$ 正在加载真实召回快照</span>
      </div>

      <div v-else-if="currentItems.length > 0" class="memory-list">
        <div
          v-for="(item, index) in currentItems"
          :key="`${activeTab}-${item.memory_id || index}`"
          class="memory-item"
          :style="{ '--memory-accent': activeTab === 'pre' ? 'var(--color-blue)' : 'var(--color-accent)' }"
        >
          <div class="memory-header">
            <span class="memory-type">{{ formatMemoryType(item.memory_type) }}</span>
            <span class="memory-score">
              {{ activeTab === 'pre' ? `merge ${formatScore(item.merged_score)}` : `final ${formatScore(item.final_score)}` }}
            </span>
          </div>
          <div class="memory-meta">
            <span class="memory-meta-item">channel {{ formatChannels(item.retrieval_channels) }}</span>
            <span v-if="activeTab === 'pre'" class="memory-meta-item">vector {{ formatScore(item.vector_score) }}</span>
            <span v-if="activeTab === 'pre'" class="memory-meta-item">keyword {{ formatScore(item.keyword_score) }}</span>
            <span v-if="activeTab === 'post'" class="memory-meta-item">rerank {{ formatScore(item.rerank_score) }}</span>
          </div>
          <div v-if="activeTab === 'pre' && item.matched_terms && item.matched_terms.length > 0" class="memory-meta">
            <span class="memory-meta-item">terms {{ item.matched_terms.join(' / ') }}</span>
          </div>
          <p class="memory-text">{{ item.content }}</p>
        </div>
      </div>

      <div v-else class="empty-state">
        <span class="placeholder-text">$ 当前会话还没有长期记忆召回结果</span>
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
  overflow: auto;
  padding: var(--space-10);
}

.memory-type,
.memory-score,
.memory-meta-item,
.chart-mode-btn,
.placeholder-text {
  font-family: var(--font-ui);
}

.memory-text {
  font-family: var(--font-text);
}

.chart-toolbar {
  position: relative;
  display: flex;
  gap: 2px;
  align-self: flex-start;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  flex-shrink: 0;
}

.chart-mode-slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: calc(50% - 3px);
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-soft);
  transition: transform 250ms ease;
  pointer-events: none;
}

.chart-toolbar.post .chart-mode-slider { transform: translateX(calc(100% + 2px)); }

.chart-mode-btn {
  position: relative;
  z-index: 1;
  min-width: 72px;
  height: 28px;
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
  background: transparent;
  border: 0;
  border-radius: 999px;
  padding: 0 8px;
  cursor: pointer;
  transition: color var(--transition-fast), background var(--transition-fast), border-color var(--transition-fast);
}

.chart-mode-btn:hover {
  color: var(--color-primary);
}

.chart-mode-btn.active {
  color: var(--color-primary);
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.memory-item {
  border: 0;
  background: var(--color-surface-raised);
  border-radius: 18px;
  padding: var(--space-8);
}

.memory-header {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-6);
}

.memory-type {
  font-size: calc(12px * var(--font-scale));
  color: var(--memory-accent);
  text-transform: uppercase;
}

.memory-score {
  margin-left: auto;
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
}

.memory-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
  margin-bottom: var(--space-6);
}

.memory-meta-item {
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
}

.memory-text {
  margin: 0;
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
}

.placeholder-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-align: center;
}
</style>
