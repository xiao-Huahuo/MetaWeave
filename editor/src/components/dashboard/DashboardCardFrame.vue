<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  status?: string
  titleHint?: string
}>(), {
  status: '',
  titleHint: '',
})
</script>

<template>
  <div class="dashboard-card card-block">
    <div class="dashboard-card-label">
      <span :title="titleHint || title">{{ title }}</span>
      <span v-if="status" class="dashboard-card-status">{{ status }}</span>
    </div>

    <div class="dashboard-card-surface">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.dashboard-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  height: 100%;
  width: 100%;
  min-height: 0;
  min-width: 0;
}

.dashboard-card-label {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 18px;
  padding: 0 2px;
  font-family: var(--font-ui);
  color: var(--color-text-primary);
}

.dashboard-card-label > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
}

.dashboard-card-status {
  margin-left: auto;
  flex-shrink: 0;
  max-width: 48%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-tertiary);
}

.dashboard-card-surface {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  border: 0;
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: 0 0 0 4px var(--library-form-ring);
}
</style>
