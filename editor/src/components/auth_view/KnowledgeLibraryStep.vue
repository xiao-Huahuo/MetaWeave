<!-- Knowledge-library fields; no directories or backend records are created by preview. -->
<script setup lang="ts">
import AuthField from './AuthField.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import { ref } from 'vue'
import type { AuthDraft } from './authTypes'
const draft = defineModel<AuthDraft>('draft', { required: true })
const error = ref('')
const choosing = ref(false)
/** Reuse the same desktop-native directory picker as basic settings. */
async function selectDirectory() {
  if (!window.agentEditorDesktop?.selectDirectory) {
    error.value = '本机目录选择需要在桌面应用中使用。'
    return
  }
  choosing.value = true
  error.value = ''
  try {
    const selected = await window.agentEditorDesktop.selectDirectory()
    if (selected) draft.value.knowledgeDir = selected
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '选择目录失败'
  } finally { choosing.value = false }
}
</script>
<template>
  <section class="auth-step">
    <h1>知识库选择</h1>
    <div class="auth-fields">
      <AuthField v-model="draft.libraryName" label="库名称" placeholder="知识库名称" />
      <div class="auth-directory-row">
        <AuthField v-model="draft.knowledgeDir" label="知识目录" placeholder="正在读取默认绝对路径" readonly />
        <button class="auth-directory-button" type="button" aria-label="选择知识目录" :disabled="choosing" @click="selectDirectory"><IcIcon name="folder" :size="20" /></button>
      </div>
      <p v-if="error" role="alert" class="auth-field-hint">{{ error }}</p>
    </div>
  </section>
</template>
