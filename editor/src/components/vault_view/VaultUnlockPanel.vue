<!--
  Password vault unlock panel.

  Usage:
  VaultView renders this component before a vault token exists. It emits setup
  or unlock requests without touching global application login state.
-->
<script setup lang="ts">
import { ref } from 'vue'

import FormHeightTransition from '@/components/common/FormHeightTransition.vue'

defineOptions({ name: 'VaultUnlockPanel' })

defineProps<{
  configured: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  unlock: [password: string]
  setup: [password: string]
}>()

const password = ref('')
const confirmPassword = ref('')
const localError = ref('')

function submit() {
  localError.value = ''
  if (password.value.length < 8) {
    localError.value = '主密码至少 8 位'
    return
  }
  emit('unlock', password.value)
}

function setup() {
  localError.value = ''
  if (password.value.length < 8) {
    localError.value = '主密码至少 8 位'
    return
  }
  if (password.value !== confirmPassword.value) {
    localError.value = '两次输入不一致'
    return
  }
  emit('setup', password.value)
}
</script>

<template>
  <section class="unlock-panel">
    <form class="unlock-card" @submit.prevent="configured ? submit() : setup()">
      <FormHeightTransition :watch-key="configured ? 'configured' : 'setup'">
        <div class="unlock-fields">
          <label for="vault-master-password">主密码</label>
          <div v-if="!configured" class="password-field">
            <input
              id="vault-master-password"
              v-model="password"
              class="vault-input form-input-surface"
              type="password"
              autocomplete="new-password"
              placeholder="主密码"
              @keydown.enter="setup"
            />
          </div>
          <div v-else class="input-row">
            <input
              id="vault-master-password"
              v-model="password"
              class="vault-input form-input-surface"
              type="password"
              autocomplete="current-password"
              placeholder="主密码"
              @keydown.enter="submit"
            />
            <button class="primary-btn" type="submit" :disabled="loading">解锁</button>
          </div>
          <template v-if="!configured">
            <label for="vault-confirm-password">确认主密码</label>
            <div class="input-row">
              <input
                id="vault-confirm-password"
                v-model="confirmPassword"
                class="vault-input form-input-surface"
                type="password"
                autocomplete="new-password"
                placeholder="再次输入主密码"
                @keydown.enter="setup"
              />
              <button class="primary-btn" type="submit" :disabled="loading">创建并解锁</button>
            </div>
          </template>
        </div>
      </FormHeightTransition>
      <p v-if="localError" class="error-text">{{ localError }}</p>
    </form>
  </section>
</template>

<style scoped>
.unlock-panel {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  background: var(--color-canvas);
}

.unlock-card {
  display: grid;
  gap: var(--space-12);
  width: min(420px, calc(100vw - 32px));
  padding: var(--space-20);
  border: 1px solid var(--color-border);
  border-radius: 28px;
  background: var(--color-surface);
  outline: 2px solid var(--workspace-panel-outline);
  outline-offset: 2px;
  box-shadow: 0 0 0 2px var(--library-form-ring);
  font-family: var(--font-ui);
  font-size: calc(14px * var(--font-scale));
}

label {
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
  font-weight: 650;
}

.input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-8);
  padding: var(--space-4);
}

.unlock-fields {
  display: grid;
  gap: var(--space-12);
}

.password-field {
  display: grid;
  padding: var(--space-4);
}

.vault-input {
  min-width: 0;
  height: 34px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas-soft);
  color: var(--color-text);
  padding: 0 var(--space-10);
  outline: 0;
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
}

.vault-input:focus {
  border-color: var(--color-primary);
}

.primary-btn {
  height: 34px;
  padding: 0 var(--space-12);
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary);
  color: white;
  font-size: calc(13px * var(--font-scale));
}

.primary-btn:disabled {
  cursor: default;
  opacity: 0.42;
}

.error-text {
  margin: 0;
  color: var(--color-danger);
  font-size: calc(12px * var(--font-scale));
}

@media (max-width: 520px) {
  .unlock-card {
    padding: var(--space-16);
  }

  .input-row {
    grid-template-columns: 1fr;
  }
}
</style>
