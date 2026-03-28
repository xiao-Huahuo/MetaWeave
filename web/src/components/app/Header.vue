<template>
  <header class="top-nav">
    <div class="nav-left">
      <span class="logo">MetaWeave</span>
    </div>
    <div class="nav-right">
      <span v-if="isAuthenticated" class="user-name">{{ userName }}</span>
      <button v-if="!isAuthenticated" @click="goLogin" class="btn">登录</button>
      <button v-else @click="logout" class="btn">退出</button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)
const userName = computed(() => JSON.parse(localStorage.getItem('user') || '{}').uname || 'User')
const router = useRouter()

const logout = () => authStore.logout()
const goLogin = () => router.push('/login')
</script>

<style scoped>
.top-nav {
  height: 48px;
  background: #ffffff;
  border-bottom: 1px solid #d0d7de;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}

.logo {
  font-weight: 600;
  font-size: 16px;
  color: #24292f;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-name {
  font-size: 14px;
  color: #57606a;
}

.btn {
  padding: 6px 12px;
  background: #f6f8fa;
  color: #24292f;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.btn:hover {
  background: #eaeef2;
}
</style>
