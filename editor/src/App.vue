<!--
  Root application shell.

  Usage:
  - Initializes the shared theme store once.
  - Renders the active route for the editor front-end.
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterView } from 'vue-router'

import WifiLoader from '@/components/common/WifiLoader.vue'
import AuthView from '@/views/AuthView.vue'
import FloatingAgentRoot from '@/components/floating/FloatingAgentRoot.vue'
import ModelLifecycleOverlay from '@/components/common/ModelLifecycleOverlay.vue'
import { initializeManagedModels } from '@/api/settings'
import { initializeDshCodingAgent } from '@/api/sdk'
import { isFloatingWindow } from '@/floating/isFloating'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const backendReady = ref(false)

async function waitForBackend(maxRetries = 120): Promise<void> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const r = await fetch('/health', { method: 'GET' })
      if (r.ok) return
    } catch { /* 后端未就绪 */ }
    await new Promise(r => setTimeout(r, 1000))
  }
}

const initializedUsers = new Set<string>()

/** Refresh user settings, then trigger model work without awaiting any model task. */
async function initializeUserModels(userId: string) {
  if (!userId || initializedUsers.has(userId) || isFloatingWindow) return
  initializedUsers.add(userId)
  try {
    const profile = await settingsStore.refreshUserProfile()
    if (!profile || settingsStore.profile.userId !== userId) {
      initializedUsers.delete(userId)
      return
    }
    await Promise.allSettled([
      initializeManagedModels(userId),
      initializeDshCodingAgent(userId),
    ])
    await window.agentEditorDesktop?.floatingSetVisible?.(Boolean(settingsStore.profile.floatingLaunchEnabled))
  } catch {
    initializedUsers.delete(userId)
  }
}

onMounted(async () => {
  settingsStore.initTheme()
  await waitForBackend()
  backendReady.value = true
  void initializeUserModels(settingsStore.profile.userId)
})

watch(
  () => settingsStore.profile.userId,
  (userId) => {
    if (backendReady.value) void initializeUserModels(userId)
  },
)
</script>

<template>
  <div v-if="!backendReady" class="app-loading">
    <WifiLoader />
  </div>
  <FloatingAgentRoot v-else-if="isFloatingWindow && settingsStore.hasUserId" />
  <template v-else-if="settingsStore.hasUserId">
    <RouterView />
    <ModelLifecycleOverlay :user-id="settingsStore.profile.userId" />
  </template>
  <AuthView v-else />
</template>

<style scoped>
.app-loading {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  background: var(--color-canvas);
}

</style>
