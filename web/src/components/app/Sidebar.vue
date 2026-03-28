<template>
  <div class="icon-sidebar">
    <div
      v-for="item in menuItems"
      :key="item.name"
      :class="['icon-item', { active: $route.path === item.path }]"
      @click="navigateTo(item.path)"
      :title="item.meta?.title || item.name"
    >
      <svg v-if="item.path === '/'" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
      <svg v-else-if="item.path === '/discovery-home'" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"></circle>
        <path d="m21 21-4.35-4.35"></path>
      </svg>
      <svg v-else-if="item.path === '/admin'" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
        <path d="M2 17l10 5 10-5M2 12l10 5 10-5"></path>
      </svg>
      <svg v-else class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()

const menuItems = computed(() => {
  return router.getRoutes().filter(route => {
    if (route.meta?.guest || !route.name) return false
    if (route.meta?.requiresAdmin) return authStore.isAuthenticated && authStore.isAdmin
    return true
  })
})

const navigateTo = (path) => router.push(path)
</script>

<style scoped>
.icon-sidebar {
  width: 60px;
  background: #f6f8fa;
  border-right: 1px solid #d0d7de;
  display: flex;
  flex-direction: column;
  padding: 8px 0;
}

.icon-item {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  cursor: pointer;
  position: relative;
  color: #57606a;
}

.icon-item:hover {
  background: #eaeef2;
}

.icon-item.active {
  background: #ffffff;
  border-left: 2px solid #0969da;
  color: #0969da;
}

.icon {
  width: 24px;
  height: 24px;
}
</style>
