<!--
  Embedded browser workspace page.

  Usage:
  EditorWorkspace mounts this page for the browser activity. It resolves the
  persisted proxy fallback and coordinates BrowserChrome with Electron IPC.
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchWebSearchConfig } from '@/api/settings'
import BrowserChrome from '@/components/browser_view/BrowserChrome.vue'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

defineOptions({ name: 'BrowserPage' })

const props = withDefaults(defineProps<{
  activityOverlayOpen: boolean
  initialUrl?: string
  navigationRequestId?: number
  sidebar?: boolean
  visible?: boolean
}>(), {
  visible: true,
})

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const desktop = window.agentEditorDesktop
const desktopAvailable = Boolean(desktop?.isDesktop)
const address = ref('')
const proxyUrl = ref('')
const homeUrl = ref('https://www.google.com')
const configReady = ref(false)
const latestBounds = ref<BrowserViewBounds | null>(null)
const pendingUrl = ref(props.initialUrl?.trim() || '')
const browserState = ref<BrowserViewState>({
  url: '',
  title: '新标签页',
  canGoBack: false,
  canGoForward: false,
  loading: false,
})
let removeStateListener: (() => void) | undefined
let browserShown = false
let configFallbackTimer: number | undefined
let disposed = false

/** Show or reposition the native web surface after both config and bounds exist. */
async function syncNativeView() {
  if (!desktop || props.visible === false || props.activityOverlayOpen || !configReady.value || !latestBounds.value) return
  if (latestBounds.value.width < 1 || latestBounds.value.height < 1) return
  if (!browserShown) {
    browserShown = await desktop.browserShow({
      bounds: { ...latestBounds.value },
      proxyUrl: proxyUrl.value,
      homeUrl: homeUrl.value,
      themeMode: settingsStore.themeMode,
    })
    if (props.activityOverlayOpen) {
      browserShown = false
      await desktop.browserHide()
    } else {
      await navigatePendingUrl()
    }
    return
  }
  await desktop.browserSetBounds({ ...latestBounds.value })
}

/** Consume one externally requested URL after the shared native view is visible. */
async function navigatePendingUrl() {
  const url = pendingUrl.value.trim()
  if (!desktop || !browserShown || !url) return
  pendingUrl.value = ''
  // Native state supplies the display URL after removing managed DSH credentials.
  await desktop.browserNavigate(url)
}

/** Keep the native view clipped to the BrowserChrome content surface. */
function handleBounds(bounds: BrowserViewBounds) {
  latestBounds.value = bounds
  void syncNativeView()
}

/** Forward one navigation command to the isolated browser process. */
function handleCommand(command: 'back' | 'forward' | 'home' | 'reload' | 'stop' | 'external') {
  void desktop?.browserCommand(command)
}

/** Open a URL or search query entered in the omnibox. */
function handleNavigate(value: string) {
  void desktop?.browserNavigate(value)
}

/** Open the dedicated browser configuration tab in the existing settings page. */
function openBrowserSettings() {
  localStorage.setItem('agent_editor_settings_active_tab', 'browser')
  workspaceStore.setMainView('settings')
}

/** Yield the native Chromium layer to activity-bar DOM overlays, then restore it. */
watch(() => props.activityOverlayOpen, async (open) => {
  if (!desktop) return
  if (open) {
    browserShown = false
    await desktop.browserHide()
    return
  }
  await syncNativeView()
})

watch(() => props.visible, async (visible) => {
  if (!desktop) return
  if (visible === false) {
    browserShown = false
    latestBounds.value = null
    await desktop.browserHide()
    return
  }
  await syncNativeView()
})

/** Consume every library or citation click, including repeated identical URLs. */
watch(() => props.navigationRequestId, async () => {
  pendingUrl.value = props.initialUrl?.trim() || ''
  await navigatePendingUrl()
})

/** Propagate application/system theme changes to Chromium web content. */
watch(() => settingsStore.themeMode, (themeMode) => {
  if (!browserShown || !configReady.value) return
  void desktop?.browserConfigure({
    proxyUrl: proxyUrl.value,
    homeUrl: homeUrl.value,
    themeMode,
  })
})

onMounted(async () => {
  removeStateListener = desktop?.onBrowserState((state) => {
    browserState.value = state
    if (state.url) address.value = state.url
  })
  configFallbackTimer = window.setTimeout(() => {
    configReady.value = true
    void syncNativeView()
  }, 500)
  try {
    const config = await fetchWebSearchConfig(settingsStore.profile.userId)
    proxyUrl.value = config.browser_proxy_url || config.proxy_url || ''
    homeUrl.value = config.browser_home_url || 'https://www.google.com'
    if (!props.initialUrl) address.value = homeUrl.value
  } catch {
    // The browser remains usable with direct networking and the default home.
  } finally {
    window.clearTimeout(configFallbackTimer)
    if (disposed) return
    configReady.value = true
    if (browserShown) {
      void desktop?.browserConfigure({
        proxyUrl: proxyUrl.value,
        homeUrl: homeUrl.value,
        themeMode: settingsStore.themeMode,
      })
    } else {
      void syncNativeView()
    }
  }
})

onBeforeUnmount(() => {
  disposed = true
  window.clearTimeout(configFallbackTimer)
  removeStateListener?.()
  void desktop?.browserHide()
})
</script>

<template>
  <div class="browser-page" :class="{ 'browser-sidebar-page': sidebar }">
    <BrowserChrome
      v-model:address="address"
      :desktop-available="desktopAvailable"
      :proxy-active="Boolean(proxyUrl)"
      :state="browserState"
      :sidebar="sidebar"
      @bounds="handleBounds"
      @command="handleCommand"
      @navigate="handleNavigate"
      @open-settings="openBrowserSettings"
      @close-sidebar="workspaceStore.closeBrowserSidebar"
    />
  </div>
</template>

<style scoped>
.browser-page {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: 0;
  border-radius: var(--workspace-card-radius);
  overflow: hidden;
  background:
    radial-gradient(circle at 50% -20%, var(--color-primary-softer), transparent 44%),
    var(--color-chrome-bg-solid);
}

.browser-sidebar-page {
  border-radius: 0;
  background: var(--color-bg-app);
}
</style>
