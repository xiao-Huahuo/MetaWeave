<!--
  Password vault page.

  Usage:
  Fourth knowledge-menu surface for a Bitwarden-like vault. It keeps a vault
  token in sessionStorage for the 30-minute unlock window and clears only that
  token when the user locks the vault.
-->
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  createVaultItem,
  exportVaultItems,
  getVaultItem,
  getVaultStatus,
  importVaultItems,
  listVaultItems,
  listVaultTags,
  lockVaultToken,
  purgeVaultItems,
  restoreVaultItems,
  setupVault,
  trashVaultItems,
  unlockVault,
  updateVaultItem,
  type VaultItem,
  type VaultItemType,
  type VaultTag,
} from '@/api/vault'
import VaultFilterPanel from '@/components/vault_view/VaultFilterPanel.vue'
import VaultItemEditor from '@/components/vault_view/VaultItemEditor.vue'
import VaultTable from '@/components/vault_view/VaultTable.vue'
import VaultUnlockPanel from '@/components/vault_view/VaultUnlockPanel.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'

defineOptions({ name: 'VaultView' })

withDefaults(defineProps<{ mobile?: boolean }>(), { mobile: false })

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()

const configured = ref(false)
const loading = ref(false)
const token = ref('')
const expiresAt = ref('')
const items = ref<VaultItem[]>([])
const tags = ref<VaultTag[]>([])
const query = ref('')
const selectedTag = ref('')
const selectedType = ref<VaultItemType | ''>('')
const inTrash = ref(false)
const multiSelect = ref(false)
const selectedIds = ref<Set<string>>(new Set())
const editorOpen = ref(false)
const sidebarOpen = ref(true)
const editingItem = ref<VaultItem | null>(null)
const contextItem = ref<VaultItem | null>(null)
const contextOpen = ref(false)
const contextStyle = ref({ left: '0px', top: '0px' })
const typeCounts = ref<Record<string, number>>({ login: 0, card: 0, identity: 0, secure_note: 0 })

const tokenKey = computed(() => `metaweave_vault_token_${settingsStore.profile.userId}`)
const selectedItemIds = computed(() => [...selectedIds.value])

watch([query, selectedTag, selectedType, inTrash], () => {
  if (token.value) void refresh()
})

onMounted(async () => {
  await loadStatus()
  restoreToken()
  if (token.value) await refresh()
  document.addEventListener('click', closeContext)
})

onUnmounted(() => {
  document.removeEventListener('click', closeContext)
})

async function loadStatus() {
  if (!settingsStore.profile.userId) return
  const status = await getVaultStatus(settingsStore.profile.userId)
  configured.value = status.configured
}

function restoreToken() {
  try {
    const raw = sessionStorage.getItem(tokenKey.value)
    if (!raw) return
    const payload = JSON.parse(raw) as { token: string; expires_at: string }
    if (new Date(payload.expires_at).getTime() > Date.now()) {
      token.value = payload.token
      expiresAt.value = payload.expires_at
    } else {
      sessionStorage.removeItem(tokenKey.value)
    }
  } catch {
    sessionStorage.removeItem(tokenKey.value)
  }
}

function saveToken(nextToken: string, nextExpiresAt: string) {
  token.value = nextToken
  expiresAt.value = nextExpiresAt
  sessionStorage.setItem(tokenKey.value, JSON.stringify({ token: nextToken, expires_at: nextExpiresAt }))
}

async function unlock(password: string) {
  if (!settingsStore.profile.userId) return
  loading.value = true
  try {
    const response = await unlockVault(settingsStore.profile.userId, password)
    saveToken(response.token, response.expires_at)
    await refresh()
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '解锁失败')
  } finally {
    loading.value = false
  }
}

async function setup(password: string) {
  if (!settingsStore.profile.userId) return
  loading.value = true
  try {
    const response = await setupVault(settingsStore.profile.userId, password)
    configured.value = true
    saveToken(response.token, response.expires_at)
    await refresh()
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '设置失败')
  } finally {
    loading.value = false
  }
}

async function lockVault() {
  if (token.value) {
    await lockVaultToken(token.value).catch(() => {})
  }
  token.value = ''
  expiresAt.value = ''
  items.value = []
  selectedIds.value = new Set()
  sessionStorage.removeItem(tokenKey.value)
}

async function refresh() {
  if (!token.value) return
  loading.value = true
  try {
    const [itemResponse, tagResponse] = await Promise.all([
      listVaultItems(token.value, {
        query: query.value,
        tag: selectedTag.value,
        itemType: selectedType.value,
        trash: inTrash.value,
      }),
      listVaultTags(token.value),
    ])
    items.value = itemResponse.items
    tags.value = tagResponse.tags
    typeCounts.value = itemResponse.type_counts
    selectedIds.value = new Set([...selectedIds.value].filter((id) => itemResponse.items.some((item) => item.item_id === id)))
  } catch (error) {
    await lockVault()
    workspaceStore.showToast(error instanceof Error ? error.message : '密码库已锁定')
  } finally {
    loading.value = false
  }
}

function openNew() {
  editingItem.value = null
  editorOpen.value = true
}

async function openEdit(item: VaultItem) {
  if (!token.value) return
  const response = await getVaultItem(token.value, item.item_id)
  editingItem.value = response.item
  editorOpen.value = true
}

async function saveItem(payload: { item_type: VaultItemType; fields: Record<string, unknown>; tags: string[]; asset_ids: string[] }) {
  if (!token.value) return
  try {
    if (editingItem.value) {
      await updateVaultItem(token.value, editingItem.value.item_id, payload)
    } else {
      await createVaultItem(token.value, payload)
    }
  } catch (error) {
    workspaceStore.showToast(error instanceof Error ? error.message : '保存密码库条目失败')
    return
  }
  editorOpen.value = false
  editingItem.value = null
  await refresh()
}

function toggleItem(item: VaultItem) {
  const next = new Set(selectedIds.value)
  if (next.has(item.item_id)) next.delete(item.item_id)
  else next.add(item.item_id)
  selectedIds.value = next
}

function openContext(event: MouseEvent, item: VaultItem) {
  contextItem.value = item
  contextOpen.value = true
  contextStyle.value = {
    left: `${Math.min(event.clientX, window.innerWidth - 220)}px`,
    top: `${Math.min(event.clientY, window.innerHeight - 220)}px`,
  }
}

function closeContext() {
  contextOpen.value = false
}

async function copyText(value: string) {
  await navigator.clipboard?.writeText(value)
  workspaceStore.showToast('已复制')
}

async function deleteSelected() {
  if (!token.value || selectedItemIds.value.length === 0) return
  if (inTrash.value) {
    await purgeVaultItems(token.value, selectedItemIds.value)
  } else {
    await trashVaultItems(token.value, selectedItemIds.value)
  }
  selectedIds.value = new Set()
  await refresh()
}

async function restoreSelected() {
  if (!token.value || selectedItemIds.value.length === 0) return
  await restoreVaultItems(token.value, selectedItemIds.value)
  selectedIds.value = new Set()
  await refresh()
}

async function exportSelected(ids: string[] = selectedItemIds.value) {
  if (!token.value) return
  if (!window.confirm('导出的 JSON 将包含密码库敏感明文。确认继续?')) return
  const payload = await exportVaultItems(token.value, ids)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `metaweave-vault-${Date.now()}.json`
  link.click()
  URL.revokeObjectURL(url)
}

function importJson() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/json,.json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file || !token.value) return
    const payload = JSON.parse(await file.text()) as { items?: Record<string, unknown>[] } | Record<string, unknown>[]
    const rawItems = Array.isArray(payload) ? payload : payload.items ?? []
    const result = await importVaultItems(token.value, rawItems)
    workspaceStore.showToast(`导入 ${result.imported} 项, 转为安全笔记 ${result.converted_to_secure_note} 项, 失败 ${result.failed} 项`)
    await refresh()
  }
  input.click()
}

async function contextCopyName() {
  if (!contextItem.value) return
  await copyText(contextItem.value.name)
}

async function contextCopySecret() {
  const item = contextItem.value
  if (!item || !token.value) return
  const detail = (await getVaultItem(token.value, item.item_id)).item
  const value = detail.item_type === 'card' ? detail.fields.security_code : detail.fields.password
  await copyText(String(value ?? ''))
}

async function contextDelete() {
  const item = contextItem.value
  closeContext()
  if (!item || !token.value) return
  if (inTrash.value) await purgeVaultItems(token.value, [item.item_id])
  else await trashVaultItems(token.value, [item.item_id])
  await refresh()
}
</script>

<template>
  <VaultUnlockPanel
    v-if="!token"
    :configured="configured"
    :loading="loading"
    @unlock="unlock"
    @setup="setup"
  />
  <section v-else class="vault-view" :class="{ mobile, 'sidebar-collapsed': !sidebarOpen }">
    <VaultFilterPanel
      class="vault-filter-sidebar"
      :title="inTrash ? '回收站' : '密码库'"
      :title-icon="inTrash ? 'trash' : 'shield'"
      :mobile="mobile"
      v-model:query="query"
      v-model:tag="selectedTag"
      v-model:item-type="selectedType"
      :tags="tags"
      :counts="typeCounts"
      @collapse="sidebarOpen = false"
    />
    <div class="vault-workspace">
    <header class="vault-topbar">
      <Transition name="vault-sidebar-toggle">
        <button
          v-if="mobile && !sidebarOpen"
          class="vault-sidebar-toggle"
          type="button"
          title="展开密码库侧边栏"
          aria-label="展开密码库侧边栏"
          @click="sidebarOpen = true"
        >
          <IcIcon name="arrow-right" :size="18" />
        </button>
      </Transition>
      <div class="vault-switch" :class="{ trash: inTrash }">
        <span class="switch-indicator"></span>
        <button :class="{ active: !inTrash }" type="button" @click="inTrash = false"><IcIcon name="shield" :size="17" /><span>密码库</span></button>
        <button :class="{ active: inTrash }" type="button" @click="inTrash = true"><IcIcon name="trash" :size="17" /><span>回收站</span></button>
      </div>
      <div class="top-actions">
        <button class="tool-button v1-icon-button" type="button" title="导出" aria-label="导出" @click="exportSelected([])"><IcIcon name="upload" :size="17" /></button>
        <button class="tool-button v1-icon-button" type="button" title="导入" aria-label="导入" @click="importJson"><IcIcon name="download" :size="17" /></button>
        <button class="tool-button v1-icon-button" :class="{ active: multiSelect }" type="button" :title="multiSelect ? '退出多选' : '多选'" :aria-label="multiSelect ? '退出多选' : '多选'" @click="multiSelect = !multiSelect"><IcIcon name="multi-select" :size="17" /></button>
        <template v-if="multiSelect">
          <button class="selection-action danger" type="button" :disabled="selectedIds.size === 0" @click="deleteSelected"><IcIcon name="trash" :size="17" /><span>{{ inTrash ? '永久删除' : '删除' }}</span></button>
          <button v-if="inTrash" class="selection-action" type="button" :disabled="selectedIds.size === 0" @click="restoreSelected"><IcIcon name="replay" :size="17" /><span>恢复</span></button>
          <button class="selection-action" type="button" :disabled="selectedIds.size === 0" @click="exportSelected()"><IcIcon name="upload" :size="17" /><span>导出 JSON</span></button>
        </template>
        <button class="new-btn" type="button" @click="openNew"><IcIcon name="add" :size="17" /><span>新建</span></button>
        <button class="lock-btn" type="button" @click="lockVault"><IcIcon name="shield" :size="17" /><span>锁定</span></button>
      </div>
    </header>
    <div class="vault-main">
      <main class="table-area">
        <VaultTable
          :token="token"
          :items="items"
          :item-type="selectedType"
          :selected-ids="selectedIds"
          :multi-select="multiSelect"
          @open="openEdit"
          @toggle="toggleItem"
          @context="openContext"
        />
      </main>
    </div>
    </div>
    <ul v-if="contextOpen && contextItem" class="context-menu ui-floating-menu-surface" :style="contextStyle" @click.stop>
      <li @click="contextCopyName">复制项目名称</li>
      <li v-if="contextItem.item_type === 'login' || contextItem.item_type === 'card'" @click="contextCopySecret">复制密码</li>
      <li @click="openEdit(contextItem); closeContext()">编辑</li>
      <li @click="exportSelected([contextItem.item_id]); closeContext()">导出</li>
      <li class="danger" @click="contextDelete">删除</li>
    </ul>
    <VaultItemEditor :open="editorOpen" :item="editingItem" :token="token" :available-tags="tags" @close="editorOpen = false" @save="saveItem" />
  </section>
</template>

<style scoped>
.vault-view {
  position: relative;
  display: grid;
  grid-template-columns: 222px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  width: 100%;
  height: 100%;
  background: var(--color-canvas);
  font-family: var(--font-ui);
  font-size: calc(14px * var(--font-scale));
}

.vault-sidebar-toggle {
  display: none;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.vault-sidebar-toggle:hover {
  background: var(--color-selection-blue-soft);
  color: var(--color-selection-blue);
}

.vault-workspace {
  display: grid;
  grid-template-rows: 44px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.vault-topbar {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
  border-bottom: 0;
  background: var(--color-panel-bg);
  font-size: calc(12px * var(--font-scale));
}

.top-actions,
.vault-switch {
  display: inline-flex;
  align-items: center;
}

.top-actions {
  margin-left: auto;
  gap: var(--space-4);
  justify-content: flex-end;
}

.tool-button:disabled {
  opacity: 0.45;
  cursor: default;
}

.new-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 28px;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary);
  color: #fff;
  padding: 0 var(--space-10);
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  transition: background 180ms ease, border-color 180ms ease;
}

.new-btn:hover {
  background: color-mix(in srgb, var(--color-primary) 84%, white);
}

.lock-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 28px;
  border: 1px solid var(--color-danger);
  border-radius: 999px;
  background: transparent;
  color: var(--color-danger);
  padding: 0 var(--space-10);
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  transition: background 180ms ease, border-color 180ms ease, color 180ms ease;
}

.lock-btn:hover {
  border-color: var(--color-danger);
  background: var(--color-danger);
  color: #fff;
}

.vault-switch {
  position: relative;
  height: 32px;
  gap: var(--space-2);
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
}

.vault-switch button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 28px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0 var(--space-8);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.switch-indicator {
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 2px;
  width: calc(50% - 2px);
  border-radius: 999px;
  background: var(--color-primary-softer);
  transition: transform 250ms ease;
}

.vault-switch.trash .switch-indicator { transform: translateX(100%); }
.vault-switch button.active { color: var(--color-primary); }

.tool-button {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0;
  cursor: pointer;
}

.tool-button:hover,
.tool-button.active {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.selection-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 28px;
  border: 0;
  border-radius: 999px;
  background: var(--color-primary-softer);
  color: var(--color-primary);
  padding: 0 var(--space-8);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.selection-action.danger { background: color-mix(in srgb, var(--color-danger) 12%, transparent); color: var(--color-danger); }
.selection-action:disabled { cursor: default; opacity: 0.45; }

.vault-main {
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.table-area {
  flex: 1 1 auto;
  min-width: 0;
  overflow: auto;
  padding: 14px;
}

.table-tools {
  justify-content: flex-end;
  margin-bottom: 10px;
}

.context-menu {
  position: fixed;
  z-index: 120;
  display: grid;
  min-width: 190px;
  padding: 6px;
  list-style: none;
  margin: 0;
}

.context-menu li {
  min-height: 30px;
  border-radius: 5px;
  color: var(--color-text-secondary);
  padding: 7px 10px;
  cursor: pointer;
}

.context-menu li:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.context-menu li.danger:hover {
  background: color-mix(in srgb, var(--color-danger) 12%, transparent);
  color: var(--color-danger);
}

@media (max-width: 860px) {
  .vault-view {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }

  .vault-main {
    min-height: 0;
  }

  .vault-topbar,
  .top-actions {
    align-items: flex-start;
    flex-wrap: wrap;
  }

}

.vault-view.mobile {
  grid-template-columns: minmax(0, 1fr);
  overflow: hidden;
}

.vault-view.mobile .vault-filter-sidebar {
  position: absolute;
  inset: var(--space-8) auto var(--space-8) var(--space-8);
  z-index: 20;
  width: min(280px, calc(100% - var(--space-16)));
  margin: 0;
  padding: var(--space-12);
  border-radius: 18px;
  box-shadow: 12px 0 32px rgba(12, 18, 38, 0.22);
  opacity: 1;
  transform: translateX(0);
  transition: opacity 160ms ease, transform 180ms ease;
}

.vault-view.mobile.sidebar-collapsed .vault-filter-sidebar {
  pointer-events: none;
  opacity: 0;
  transform: translateX(calc(-100% - var(--space-16)));
}

.vault-view.mobile .vault-sidebar-toggle {
  display: inline-flex;
}

.vault-sidebar-toggle-enter-active,
.vault-sidebar-toggle-leave-active {
  transition: opacity 160ms ease, transform 180ms ease;
}

.vault-sidebar-toggle-enter-from,
.vault-sidebar-toggle-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}
</style>
