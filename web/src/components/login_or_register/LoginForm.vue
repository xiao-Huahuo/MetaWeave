<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const emit = defineEmits(['switch'])

const uname = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

const router = useRouter()
const authStore = useAuthStore()

const submit = async () => {
  errorMessage.value = ''
  if (!uname.value.trim() || !password.value.trim()) {
    errorMessage.value = '用户名和密码不能为空'
    return
  }
  loading.value = true
  const result = await authStore.login({
    uname: uname.value.trim(),
    password: password.value,
  })
  loading.value = false

  if (result.success) {
    router.push('/')
  } else {
    errorMessage.value = result.error || 'Login failed'
  }
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="title">登录</div>
    <label class="field">
      <span>用户名</span>
      <input v-model="uname" type="text" autocomplete="username" placeholder="请输入 uname" />
    </label>
    <label class="field">
      <span>密码</span>
      <input v-model="password" type="password" autocomplete="current-password" placeholder="请输入 password" />
    </label>
    <button class="primary" type="submit" :disabled="loading">
      {{ loading ? '登录中...' : '登录' }}
    </button>
    <div v-if="errorMessage" class="error">{{ errorMessage }}</div>
    <div class="hint">
      没有账号？
      <button type="button" class="link" @click="emit('switch', 'register')">去注册</button>
    </div>
  </form>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.title {
  font-size: 18px;
  font-weight: 600;
  color: #111;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: #666;
}

.field input {
  border: 1px solid #e6e6e6;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
}

.field input:focus {
  border-color: #111;
}

.primary {
  border: 1px solid #111;
  background: #111;
  color: #fff;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
}

.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  color: #c0392b;
  font-size: 12px;
}

.hint {
  font-size: 12px;
  color: #666;
}

.link {
  border: none;
  background: transparent;
  color: #111;
  cursor: pointer;
  padding: 0;
}
</style>
