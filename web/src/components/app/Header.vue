<template>
  <header class="header">
    <div class="logo">MetaWeave</div>
    <div class="right">
      <button v-if="!isAuthenticated" @click="goLogin">Login</button>
      <button v-else @click="logout">Logout</button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)
const router = useRouter()

const logout = () => {
  authStore.logout()
}

const goLogin = () => {
  router.push('/login')
}
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  background-color: #fff;
  border-bottom: 1px solid #ddd;
}

.logo {
  font-size: 24px;
  font-weight: bold;
}

.right button {
  padding: 8px 16px;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.right button:hover {
  background-color: #0056b3;
}
</style>
