<template>
  <div class="sidebar">
    <nav>
      <ul>
        <li v-for="item in menuItems" :key="item.name">
          <a @click="navigateTo(item.path)" :class="{ active: $route.path === item.path }">
            {{ item.meta?.title || item.name }}
          </a>
        </li>
      </ul>
    </nav>
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
    if (route.meta?.guest || !route.name) {
      return false
    }

    if (route.meta?.requiresAdmin) {
      return authStore.isAuthenticated && authStore.isAdmin
    }

    return true
  })
})

const navigateTo = (path) => {
  router.push(path)
}
</script>

<style scoped>
.sidebar {
  width: 200px;
  background-color: #f4f4f4;
  padding: 20px;
  height: 100vh;
  border-right: 1px solid #ddd;
}

ul {
  list-style: none;
  padding: 0;
}

li {
  margin-bottom: 15px;
}

a {
  text-decoration: none;
  color: #666;
  cursor: pointer;
  display: block;
  padding: 8px 12px;
  border-radius: 4px;
  transition: all 0.3s;
}

a:hover {
  background-color: #e9ecef;
}

a.active {
  font-weight: bold;
  color: #fff;
  background-color: #007bff;
}
</style>
