<!-- Authenticated server identity, shown at the lower left of settings and readable on narrow screens. -->
<script setup lang="ts">
defineProps<{ username: string; userId: string }>()
</script>
<template>
  <footer class="account-identity" aria-label="当前账号">
    <span class="account-username" :title="username">{{ username }}</span>
    <span class="account-user-id">{{ userId }}</span>
  </footer>
</template>
<style scoped>
.account-identity { display: flex; flex-direction: column; gap: 4px; padding: var(--space-12) var(--space-10) var(--space-4); color: var(--color-text-secondary); font-size: calc(12px * var(--font-scale)); min-width: 0; }
.account-username { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-user-id { font-family: var(--font-code); font-size: calc(11px * var(--font-scale)); color: var(--color-text-muted); user-select: text; }
@media (max-width: 600px) { .account-identity { flex-direction: row; align-items: center; gap: var(--space-10); padding-top: var(--space-6); } }
</style>
