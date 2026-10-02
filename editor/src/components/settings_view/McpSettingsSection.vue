<!-- MCP coordinator keeps drafts mounted while refreshing actual backend state. -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import SettingsPageSwitch from './SettingsPageSwitch.vue'
import McpClientSettings from './McpClientSettings.vue'
import McpServerSettings from './McpServerSettings.vue'
import { fetchMcpClient, fetchMcpServer } from '@/api/mcp'
import type { McpClientState, McpServerState } from '@/api/mcp'
import './mcp-settings.css'
const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })
const settings = useSettingsStore(), workspace = useWorkspaceStore()
const userId = computed(() => settings.profile.userId)
const page = ref('client'), client = ref<McpClientState | null>(null), server = ref<McpServerState | null>(null)
const error = ref(''), loading = ref(false), clientDirty = ref(false), serverDirty = ref(false)
const clientBusy = ref(false), serverBusy = ref(false)
const dirty = computed(() => clientDirty.value || serverDirty.value)
let interval: ReturnType<typeof setInterval> | undefined
let disposed = false, generation = 0
/** Ignore stale identity responses and preserve child form drafts during polling. */
async function refresh() {
  if (!userId.value || loading.value || clientBusy.value || serverBusy.value) return
  const owner = userId.value, requestGeneration = generation
  loading.value = true
  try {
    const nextClient = await fetchMcpClient(owner)
    const nextServer = await fetchMcpServer(owner)
    if (disposed || owner !== userId.value || generation !== requestGeneration) return
    client.value = nextClient; server.value = nextServer; error.value = ''
  } catch (reason) { if (!disposed && generation === requestGeneration) error.value = reason instanceof Error ? reason.message : '加载 MCP 设置失败' }
  finally { loading.value = false; if (!disposed && generation !== requestGeneration && props.active) void refresh() }
}
/** Protect unsaved forms and new one-time credentials from accidental navigation. */
function canLeave() { return !dirty.value || window.confirm('MCP 有未保存的配置或尚未关闭的新令牌，确认离开？') }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(canLeave)
watch(() => workspace.mainView, (next, previous) => {
  if (previous === 'settings' && next !== 'settings' && props.active && !canLeave()) workspace.setMainView('settings')
}, { flush: 'sync' })
watch([clientBusy, serverBusy], ([a, b]) => { if (!a && !b && props.active) void refresh() })
watch(userId, () => { generation++; client.value = null; server.value = null; clientDirty.value = false; serverDirty.value = false; if (props.active) void refresh() })
watch(() => props.active, active => { if (active) void refresh() })
onMounted(() => {
  if (props.active) void refresh()
  interval = setInterval(() => { if (props.active && !error.value) void refresh() }, 4000)
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => { disposed = true; generation++; clearInterval(interval); window.removeEventListener('beforeunload', beforeUnload) })
defineExpose({ canLeave, dirty })
</script>
<template>
  <section class="mcp-settings-section" aria-label="MCP 设置">
    <SettingsPageSwitch v-model="page" :pages="[{ key: 'client', label: '客户端' }, { key: 'server', label: '服务器' }]" label="MCP 类型" />
    <p v-if="!userId" class="mcp-empty">请先在基础设置中设置用户 ID。</p>
    <LoadingState v-else-if="loading && !client" label="加载 MCP 设置" />
    <div v-if="error" class="mcp-inline-error" role="alert">{{ error }} <button class="mcp-outline-button" type="button" @click="refresh">重试</button></div>
    <FormHeightTransition :watch-key="page">
      <McpClientSettings v-if="client" v-show="page === 'client'" :key="'client-' + userId" :user-id="userId" :state="client" @refresh="refresh" @dirty="clientDirty = $event" @busy="clientBusy = $event" />
      <McpServerSettings v-if="server" v-show="page === 'server'" :key="'server-' + userId" :user-id="userId" :state="server" :libraries="settings.profile.knowledgeLibraries" @refresh="refresh" @dirty="serverDirty = $event" @busy="serverBusy = $event" />
    </FormHeightTransition>
  </section>
</template>
