<!-- Username and global-password form; mode changes preserve only unsent page drafts. -->
<script setup lang="ts">
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import AuthField from './AuthField.vue'
import type { AuthDraft } from './authTypes'
const draft = defineModel<AuthDraft>('draft', { required: true })
const mode = defineModel<'login' | 'register'>('mode', { required: true })
</script>
<template>
  <section class="auth-step credentials-step">
    <h1>{{ mode === 'login' ? '登录' : '注册' }}</h1>
    <FormHeightTransition :watch-key="mode">
      <div class="auth-fields">
        <AuthField
          v-model="draft.username"
          label="用户名"
          placeholder="输入用户名"
          autocomplete="username"
          required
        />
        <AuthField
          v-model="draft.password"
          label="密码"
          type="password"
          placeholder="输入全局密码"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          required
        />
        <Transition name="auth-mode"
          ><AuthField
            v-if="mode === 'register'"
            v-model="draft.confirmation"
            label="确认密码"
            type="password"
            placeholder="再次输入密码"
            autocomplete="new-password"
            required
        /></Transition>
      </div>
    </FormHeightTransition>
    <p class="auth-mode-switch">
      {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
      <button type="button" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? '注册' : '登录' }}
      </button>
    </p>
  </section>
</template>
