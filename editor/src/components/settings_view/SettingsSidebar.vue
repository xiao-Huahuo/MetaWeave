<!--
  Settings sidebar component.

  Usage:
  Receives the tab metadata and active key from SettingsView, then emits the
  selected key when the user switches sections.
-->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
import AccountIdentity from '@/components/settings_view/AccountIdentity.vue'
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()

export type SettingsTabKey = 'basic' | 'appearance' | 'llm' | 'vlm' | 'tools' | 'terminal' | 'web' | 'memory' | 'graph' | 'safety' | 'storage' | 'floating' | 'skills' | 'mcp'

/** Feature icons and protocol marks use downloaded local SVGs through IcIcon. */
const TAB_ICONS: Record<SettingsTabKey, string> = {
  basic: 'settings',
  appearance: 'appearance',
  llm: 'llm',
  vlm: 'ocr',
  tools: 'build',
  terminal: 'terminal',
  web: 'language',
  memory: 'memory',
  graph: 'hub',
  safety: 'shield',
  storage: 'ingest',
  floating: 'floating-window',
  skills: 'skills',
  mcp: 'mcp',
}

const props = defineProps<{
  tabs: Array<{ key: SettingsTabKey; label: string }>
  activeTab: SettingsTabKey
}>()
const sidebar = ref<HTMLElement | null>(null)

/** Keep the selected tab fully visible in the mobile horizontal rail. */
function revealActiveTab(): void {
  nextTick(() => sidebar.value?.querySelector('.sidebar-tab.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }))
}

watch(() => props.activeTab, revealActiveTab)
onMounted(() => {
  revealActiveTab()
  window.addEventListener('resize', revealActiveTab)
})
onBeforeUnmount(() => window.removeEventListener('resize', revealActiveTab))

defineEmits<{
  select: [key: SettingsTabKey]
}>()
</script>

<template>
  <aside ref="sidebar" class="settings-sidebar">
    <nav class="settings-tabs" aria-label="设置分类">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      class="sidebar-tab"
      :class="{ active: activeTab === tab.key }"
      type="button"
      @click="$emit('select', tab.key)"
    >
      <IcIcon class="sidebar-tab-icon" :name="TAB_ICONS[tab.key]" :size="16" />
      <span>{{ tab.label }}</span>
    </button>
    </nav>
    <AccountIdentity v-if="auth.session" :username="auth.session.username" :user-id="auth.session.user_id" />
  </aside>
</template>
<style scoped>
.settings-sidebar { overflow: hidden; }
.settings-tabs { display: flex; flex-direction: column; gap: 2px; flex: 1; min-height: 0; overflow-y: auto; }
@media (max-width: 600px) {
  .settings-sidebar { flex-direction: column; }
  .settings-tabs { flex-direction: row; flex: 0 0 auto; width: 100%; overflow-x: auto; overflow-y: hidden; }
}
</style>
