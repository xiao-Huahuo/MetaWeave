<!--
  Completed thinking summary.

  Usage:
  Displays the elapsed thinking duration above a finalized Agent reply without
  inventing trace rows. Real trace details remain rendered by ThinkingInline.
-->
<script setup lang="ts">
const props = defineProps<{
  /** Server-reported thinking duration in seconds. */
  seconds: number
}>()
</script>

<template>
  <span class="thinking-summary">
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="var(--color-accent)">
      <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
    </svg>
    <span>思考了 {{ props.seconds.toFixed(1) }}s</span>
  </span>
</template>

<style scoped>
.thinking-summary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  min-height: 24px;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  font-weight: 500;
  white-space: nowrap;
  animation: thinking-summary-in 350ms ease-out both;
}

@keyframes thinking-summary-in {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
