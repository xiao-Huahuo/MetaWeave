<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoginForm from '../components/login_or_register/LoginForm.vue'
import RegisterForm from '../components/login_or_register/RegisterForm.vue'

const props = defineProps({
  defaultMode: {
    type: String,
    default: 'login',
  },
})

const route = useRoute()
const router = useRouter()
const mode = ref(props.defaultMode === 'register' ? 'register' : 'login')

const syncFromRoute = () => {
  mode.value = route.path === '/register' ? 'register' : 'login'
}

watch(() => route.path, syncFromRoute, { immediate: true })

const switchMode = (nextMode) => {
  const target = nextMode === 'register' ? '/register' : '/login'
  if (route.path !== target) {
    router.push(target)
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="panel">
      <div class="switch">
        <button
          type="button"
          class="switch-btn"
          :class="{ active: mode === 'login' }"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          class="switch-btn"
          :class="{ active: mode === 'register' }"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>
      <LoginForm v-if="mode === 'login'" @switch="switchMode" />
      <RegisterForm v-else @switch="switchMode" />
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: calc(100vh - 40px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: #f7f7f7;
}

.panel {
  width: 100%;
  max-width: 360px;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
}

.switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 16px;
}

.switch-btn {
  border: 1px solid #e6e6e6;
  background: #fafafa;
  color: #333;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.switch-btn.active {
  background: #111;
  color: #fff;
  border-color: #111;
}
</style>
