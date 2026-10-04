<!--
  Root application shell.

  Usage:
  - Initializes the shared theme store once.
  - Renders the active route for the editor front-end.
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterView } from 'vue-router'

import AuthView from '@/views/AuthView.vue'
import FloatingAgentRoot from '@/components/floating/FloatingAgentRoot.vue'
import ModelLifecycleOverlay from '@/components/common/ModelLifecycleOverlay.vue'
import { initializeManagedModels } from '@/api/settings'
import { initializeDshCodingAgent } from '@/api/sdk'
import { isFloatingWindow } from '@/floating/isFloating'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { apiGet } from '@/api/client'

const settingsStore = useSettingsStore()
const auth = useAuthStore()
const backendReady = ref(false)
const startupAbort = new AbortController()

async function waitForBackend(maxRetries = 120): Promise<void> {
  for (let i = 0; i < maxRetries && !startupAbort.signal.aborted; i++) {
    try {
      await apiGet('/health', undefined, { timeoutMs: 1_500, signal: startupAbort.signal })
      return
    } catch { /* 后端未就绪 */ }
    await new Promise(r => setTimeout(r, 1000))
  }
}

const initializedUsers = new Set<string>()

/** Authentication loads the user's settings before entry; then start managed models without blocking the renderer. */
async function initializeUserModels(userId: string) {
  if (!userId || initializedUsers.has(userId) || isFloatingWindow) return
  initializedUsers.add(userId)
  try {
    if (settingsStore.profile.userId !== userId) {
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
  window.addEventListener('metaweave:session-expired', expireSession)
  unsubscribeSession = window.agentEditorDesktop?.auth?.onSession((state) => {
    // Main-window restore is adopted by AuthView after its minimum loader interval.
    if (!state) auth.clear()
    else if (isFloatingWindow) {
      auth.clear()
      const revision = auth.getRevision()
      void auth.adopt(state, revision).catch(() => { if (revision === auth.getRevision()) auth.clear() })
    }
  })
  if (isFloatingWindow) {
    unsubscribeProgress = window.agentEditorDesktop?.onWindowSync?.(({ type }) => {
      if (type === 'account-progress') void auth.refreshIdentity().catch(() => { /* A later visibility event can retry a transient read. */ })
    })
    document.addEventListener('visibilitychange', refreshFloatingIdentity)
  }
  await waitForBackend()
  if (startupAbort.signal.aborted) return
  backendReady.value = true
  if (isFloatingWindow) {
    const revision = auth.getRevision()
    const state = await window.agentEditorDesktop?.auth?.getSession()
    if (state && !startupAbort.signal.aborted && revision === auth.getRevision()) {
      await auth.adopt(state, revision)
      await auth.refreshIdentity()
    }
  }
  if (auth.canEnter) void initializeUserModels(settingsStore.profile.userId)
})

let unsubscribeSession: (() => void) | undefined
let unsubscribeProgress: (() => void) | undefined
/** A newly shown floating window re-reads durable progress even after a transient connection failure. */
function refreshFloatingIdentity() {
  if (document.visibilityState === 'visible') void auth.refreshIdentity().catch(() => { /* The existing session remains usable on transient failure. */ })
}
/** Backend rejection returns every renderer to its account gate without renewing remembered login. */
function expireSession() { initializedUsers.clear(); auth.clear() }
onBeforeUnmount(() => {
  startupAbort.abort()
  window.removeEventListener('metaweave:session-expired', expireSession)
  unsubscribeSession?.()
  unsubscribeProgress?.()
  document.removeEventListener('visibilitychange', refreshFloatingIdentity)
})

watch(
  () => auth.canEnter,
  (canEnter) => {
    if (backendReady.value && canEnter) void initializeUserModels(settingsStore.profile.userId)
    if (!canEnter) initializedUsers.clear()
  },
)
</script>

<template>
  <FloatingAgentRoot v-if="isFloatingWindow && auth.canEnter" />
  <template v-else-if="auth.canEnter">
    <RouterView />
    <ModelLifecycleOverlay :user-id="settingsStore.profile.userId" />
  </template>
  <AuthView v-else-if="!isFloatingWindow" :backend-ready="backendReady" />
</template>
