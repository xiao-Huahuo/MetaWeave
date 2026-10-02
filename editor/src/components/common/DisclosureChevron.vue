<!-- Shared ActivityBar management arrow. Offset preserves the original rail positioning and 180ms rotation. -->
<script setup lang="ts">
import IcIcon from '@/components/common/IcIcon.vue'
defineProps<{ open: boolean }>()
</script>
<template>
  <IcIcon class="disclosure-chevron" :class="{ 'is-open': open }" name="chevron-right" :size="14" />
</template>
<style scoped>
.disclosure-chevron {
  flex: 0 0 14px;
  width: 14px;
  height: 14px;
  transform: translateY(var(--disclosure-chevron-offset, 0)) rotate(0deg);
  transition: transform 180ms ease;
}
.disclosure-chevron.is-open { transform: translateY(var(--disclosure-chevron-offset, 0)) rotate(90deg); }
@media (prefers-reduced-motion: reduce) { .disclosure-chevron { transition: none; } }
</style>
