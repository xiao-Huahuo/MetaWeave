<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const emit = defineEmits(['switch'])

const uname = ref('')
const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const authStore = useAuthStore()
const router = useRouter()

const submit = async () => {
  errorMessage.value = ''
  successMessage.value = ''

  if (!uname.value.trim() || !email.value.trim() || !password.value.trim()) {
    errorMessage.value = '用户名、邮箱、密码不能为空'
    return
  }

  loading.value = true
  const result = await authStore.register({
    uname: uname.value.trim(),
    email: email.value.trim(),
    pwd: password.value,
  })

  if (result.success) {
    const loginResult = await authStore.login({
      uname: uname.value.trim(),
      password: password.value,
    })

    if (loginResult.success) {
      successMessage.value = result.message || '注册成功'
      router.push('/')
    } else {
      errorMessage.value = loginResult.error || '自动登录失败'
    }
  } else {
    errorMessage.value = result.error || 'Registration failed'
  }

  loading.value = false
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="title">注册</div>
    <label class="field">
      <span>用户名</span>
      <input v-model="uname" type="text" autocomplete="username" placeholder="请输入 uname" />
    </label>
    <label class="field">
      <span>邮箱</span>
      <input v-model="email" type="email" autocomplete="email" placeholder="请输入 email" />
    </label>
    <label class="field">
      <span>密码</span>
      <input v-model="password" type="password" autocomplete="new-password" placeholder="请输入 password" />
    </label>
    <button class="primary" type="submit" :disabled="loading">
      {{ loading ? '注册中...' : '注册' }}
    </button>
    <div v-if="errorMessage" class="error">{{ errorMessage }}</div>
    <div v-if="successMessage" class="success">{{ successMessage }}</div>
    <div class="hint">
      已有账号？
      <button type="button" class="link" @click="emit('switch', 'login')">去登录</button>
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

.success {
  color: #2e7d32;
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
