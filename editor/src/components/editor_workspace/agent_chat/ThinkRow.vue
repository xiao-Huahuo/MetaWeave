<!--
  DeepSeek 模型思考文本( reasoning_content )的展示条,结构与交互借鉴 DSH 的
  ReasoningRow( Think 条): 图标 + 标题 + 折叠态摘要行 + 展开态全文。

  Usage:
  对话与工具模式的气泡共用本组件。流式期间(running)摘要跟随最新一行并在
  行尾扫光动画提示进行中;结束后摘要固定为第一行,点击整行可展开/收起全文。
-->
<script setup lang="ts">
import { ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'

const props = defineProps<{
  /** 完整或流式累积的思考文本。 */
  text: string
  /** 是否处于流式生成中。 */
  running?: boolean
}>()

const expanded = ref(false)
const summaryMaxChars = 300
const summary = ref('')
let processedTextLength = 0

/** Incrementally follows the latest line without rescanning the full reasoning text. */
watch(() => [props.text, props.running] as const, ([text, running]) => {
  if (!running) {
    const newline = text.indexOf('\n')
    summary.value = (newline === -1 ? text : text.slice(0, newline)).slice(0, summaryMaxChars)
    processedTextLength = text.length
    return
  }
  if (text.length < processedTextLength) {
    processedTextLength = 0
    summary.value = ''
  }
  const delta = text.slice(processedTextLength)
  const visibleTail = (summary.value + delta).trimEnd()
  const newline = visibleTail.lastIndexOf('\n')
  summary.value = (newline >= 0 ? visibleTail.slice(newline + 1) : visibleTail).slice(-summaryMaxChars)
  processedTextLength = text.length
}, { immediate: true })

function toggle() {
  expanded.value = !expanded.value
}
</script>

<template>
  <div class="think-row" data-variant="think" :data-state="running ? 'running' : 'ok'">
    <button
      class="think-row__trigger"
      type="button"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="think-row__leading" aria-hidden="true">
        <IcIcon name="psychology" :size="15" class="think-row__icon" />
      </span>
      <span class="think-row__title">思考</span>
      <span class="think-row__separator" aria-hidden="true"></span>
      <span class="think-row__summary" :data-follow-end="running || undefined">{{ summary }}</span>
      <IcIcon
        :name="expanded ? 'chevron-up' : 'chevron-down'"
        :size="15"
        morph
        class="think-row__chevron"
        aria-hidden="true"
      />
    </button>
    <div class="think-row__collapse" :class="{ expanded }" :aria-hidden="!expanded">
      <div class="think-row__collapse-inner">
        <div v-if="expanded" class="think-row__body">{{ text }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.think-row {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  margin-bottom: var(--space-6);
}

.think-row__trigger {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  min-width: 0;
  min-height: 24px;
  padding: 0;
  overflow: hidden;
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-normal);
  text-align: left;
  cursor: pointer;
}

.think-row__trigger:hover .think-row__title {
  color: var(--color-text-primary);
}

.think-row__leading {
  display: inline-flex;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
}

.think-row__icon {
  color: var(--color-accent);
}

.think-row__title {
  flex-shrink: 0;
  font-weight: 400;
}

.think-row__separator {
  flex: none;
  width: 2px;
  height: 2px;
  border-radius: 1px;
  background: var(--color-text-tertiary);
}

.think-row__summary {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  color: var(--color-text-tertiary);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-normal);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.think-row__summary[data-follow-end] {
  text-overflow: clip;
}

.think-row__chevron {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

/* 运行中的扫光动画: 借鉴 DSH ReasoningRow,提示思考仍在进行。 */
.think-row[data-state='running'] .think-row__trigger::after {
  content: '';
  position: absolute;
  inset-block: 0;
  left: 0;
  width: 300px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--color-canvas) 60%, transparent) 55%,
    transparent 100%
  );
  transform: translate3d(-100%, 0, 0);
  animation: mw-think-row-sweep 2.6s ease-out infinite;
  contain: paint;
  will-change: transform;
  pointer-events: none;
}

@keyframes mw-think-row-sweep {
  0% {
    transform: translate3d(-100%, 0, 0);
  }
  90%,
  100% {
    transform: translate3d(calc(100vw + 100%), 0, 0);
  }
}

.think-row__collapse {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 200ms cubic-bezier(0.23, 1, 0.32, 1);
}

.think-row__collapse.expanded {
  grid-template-rows: 1fr;
}

.think-row__collapse-inner {
  min-height: 0;
  overflow: hidden;
}

.think-row__body {
  padding: var(--space-2) 0 var(--space-2) 22px;
  color: var(--color-text-tertiary);
  font-family: var(--font-text);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-normal);
  opacity: 0;
  transform: translateY(-6px);
  transition:
    opacity 200ms cubic-bezier(0.23, 1, 0.32, 1),
    transform 200ms cubic-bezier(0.23, 1, 0.32, 1);
  white-space: pre-wrap;
  word-break: break-word;
}

.think-row__collapse.expanded .think-row__body {
  opacity: 1;
  transform: translateY(0);
}

@media (prefers-reduced-motion: reduce) {
  .think-row[data-state='running'] .think-row__trigger::after {
    animation: none;
  }

  .think-row__body {
    transform: none;
    transition: opacity 200ms cubic-bezier(0.23, 1, 0.32, 1);
  }
}
</style>
