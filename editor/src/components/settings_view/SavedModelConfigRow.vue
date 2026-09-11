<!--
  Shared saved-model configuration row.

  Aligns LLM and VLM presets with the library list's horizontal structure:
  fixed visual mark, flexible metadata, and a right-aligned action rail.
-->
<script setup lang="ts">
import IcIcon from '@/components/common/IcIcon.vue'

defineOptions({ name: 'SavedModelConfigRow' })

defineProps<{
  title: string
  model: string
  endpoint: string
  detail?: string
  icon: string
}>()
</script>

<template>
  <article class="saved-config-row">
    <div class="saved-config-mark" aria-hidden="true">
      <IcIcon :name="icon" :size="20" />
      <span>{{ model || '—' }}</span>
    </div>
    <div class="saved-config-main">
      <strong :title="title">{{ title }}</strong>
      <span :title="model">{{ model || '未填写模型名称' }}</span>
      <small :title="endpoint">{{ endpoint || '未填写服务地址' }}</small>
      <small v-if="detail" :title="detail">{{ detail }}</small>
    </div>
    <div class="saved-config-actions">
      <slot name="actions"></slot>
    </div>
  </article>
</template>

<style scoped>
.saved-config-row {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr) auto;
  align-items: stretch;
  min-width: 0;
  min-height: 82px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
  color: var(--color-text);
  transition: border-color 160ms ease, background-color 160ms ease, transform 160ms cubic-bezier(.16,1,.3,1);
}
.saved-config-row:hover { border-color:color-mix(in srgb,var(--color-primary) 42%,var(--color-border)); background:var(--color-surface-raised); }
.saved-config-row:active { transform:scale(.997); }
.saved-config-mark { display:grid; place-items:center; align-content:center; gap:4px; margin:5px 0 5px 5px; overflow:hidden; border-radius:14px; background:var(--color-surface-raised); color:var(--color-text-muted); }
.saved-config-mark span { max-width:68px; overflow:hidden; font:600 calc(10px * var(--font-scale)) var(--font-mono); text-overflow:ellipsis; white-space:nowrap; }
.saved-config-main { display:grid; align-content:center; gap:2px; min-width:0; padding:10px 12px; }
.saved-config-main strong,.saved-config-main span,.saved-config-main small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.saved-config-main strong { font-size:calc(13px * var(--font-scale)); }
.saved-config-main span { font:500 calc(12px * var(--font-scale)) var(--font-mono); }
.saved-config-main small { color:var(--color-text-muted); font-size:calc(11px * var(--font-scale)); }
.saved-config-actions { display:flex; align-items:center; justify-content:flex-end; gap:6px; padding:10px 12px 10px 4px; }
.saved-config-actions :deep(button) { min-height:28px; padding:0 10px; border:1px solid var(--color-border); border-radius:var(--radius-sm); background:transparent; color:var(--color-text-secondary); font:500 calc(11px * var(--font-scale)) var(--font-ui); transition:border-color 150ms ease,color 150ms ease,background-color 150ms ease,transform 120ms ease; }
.saved-config-actions :deep(button:hover) { border-color:var(--color-primary); background:var(--color-primary-softer); color:var(--color-primary); }
.saved-config-actions :deep(button:active) { transform:scale(.97); }
.saved-config-actions :deep(button.danger:hover) { border-color:color-mix(in srgb,var(--color-danger) 52%,var(--color-border)); background:color-mix(in srgb,var(--color-danger) 8%,transparent); color:var(--color-danger); }
@media (max-width:768px) { .saved-config-row { grid-template-columns:68px minmax(0,1fr); }.saved-config-actions { grid-column:1 / -1; justify-content:flex-start; padding:0 10px 10px; }.saved-config-mark { grid-row:1; }.saved-config-main { grid-row:1; } }
@media (max-width:480px) { .saved-config-row { grid-template-columns:58px minmax(0,1fr); border-radius:14px; }.saved-config-mark { border-radius:10px; }.saved-config-actions { overflow-x:auto; }.saved-config-actions :deep(button) { flex:0 0 auto; } }
@media (prefers-reduced-motion:reduce) { .saved-config-row,.saved-config-actions :deep(button) { transition:none; } }
</style>
