<!--
  Terminal sandbox settings section.

  Usage:
  Edits the Agent terminal sandbox policy and pages through cmd, powershell,
  and bash supported structured instruction segments.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import type { TerminalSandboxConfig, TerminalSegmentInfo, TerminalShellKey } from '@/api/settings'

const props = defineProps<{
  config: TerminalSandboxConfig
  segmentCatalog: Record<TerminalShellKey, TerminalSegmentInfo[]>
  saving: boolean
  statusMessage: string
}>()

const emit = defineEmits<{
  save: [config: TerminalSandboxConfig]
}>()

const shellPages: Array<{ key: TerminalShellKey; label: string }> = [
  { key: 'cmd', label: 'cmd' },
  { key: 'powershell', label: 'PowerShell' },
  { key: 'bash', label: 'bash' },
]

const activeShell = ref<TerminalShellKey>('cmd')
const shellSwitchRef = ref<HTMLElement | null>(null)
const shellSliderStyle = ref({ width: '0px', left: '0px' })
const draft = ref<TerminalSandboxConfig>(cloneConfig(props.config))
const allowedText = ref<Record<TerminalShellKey, string>>({
  cmd: '',
  powershell: '',
  bash: '',
})
const blockedText = ref('')

watch(
  () => props.config,
  (value) => {
    draft.value = cloneConfig(value)
    syncTextFields()
  },
  { immediate: true },
)

const activeCatalog = computed(() => props.segmentCatalog[activeShell.value] ?? [])

function updateShellSlider() {
  void nextTick(() => {
    const container = shellSwitchRef.value
    const active = container?.querySelector<HTMLElement>('.settings-resource-page-button.active')
    if (!active) return
    shellSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

onMounted(updateShellSlider)
watch(activeShell, updateShellSlider)

function cloneConfig(config: TerminalSandboxConfig): TerminalSandboxConfig {
  return {
    ...config,
    enabled_shells: [...config.enabled_shells],
    allowed_programs: {
      cmd: [...(config.allowed_programs.cmd ?? [])],
      powershell: [...(config.allowed_programs.powershell ?? [])],
      bash: [...(config.allowed_programs.bash ?? [])],
    },
    blocked_programs: [...config.blocked_programs],
  }
}

function syncTextFields() {
  allowedText.value = {
    cmd: (draft.value.allowed_programs.cmd ?? []).join(', '),
    powershell: (draft.value.allowed_programs.powershell ?? []).join(', '),
    bash: (draft.value.allowed_programs.bash ?? []).join(', '),
  }
  blockedText.value = draft.value.blocked_programs.join(', ')
}

function parseList(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

function setShellEnabled(shell: TerminalShellKey, enabled: boolean) {
  const enabledShells = new Set(draft.value.enabled_shells)
  if (enabled) enabledShells.add(shell)
  else enabledShells.delete(shell)
  draft.value.enabled_shells = shellPages.map((item) => item.key).filter((key) => enabledShells.has(key))
  save()
}

function save() {
  const next = cloneConfig(draft.value)
  next.allowed_programs = {
    cmd: parseList(allowedText.value.cmd),
    powershell: parseList(allowedText.value.powershell),
    bash: parseList(allowedText.value.bash),
  }
  next.blocked_programs = parseList(blockedText.value)
  next.default_timeout_seconds = Number(next.default_timeout_seconds) || 30
  next.max_timeout_seconds = Number(next.max_timeout_seconds) || 120
  next.max_output_chars = Number(next.max_output_chars) || 20000
  next.max_segments_per_call = Number(next.max_segments_per_call) || 3
  emit('save', next)
}
</script>

<template>
  <div class="setting-section terminal-sandbox-section">
    <h3>终端沙盒</h3>
    <div class="setting-row toggle-row">
      <label>启用</label>
      <input v-model="draft.enabled" type="checkbox" @change="save" />
      <span class="hint-text">关闭时 Agent 无法调用终端工具</span>
    </div>
    <div class="setting-row">
      <label>工作区</label>
      <input v-model="draft.workspace_root" spellcheck="false" @blur="save" />
    </div>
    <p class="setting-hint">cwd 与参数中的路径会解析为绝对路径,真实路径必须留在此工作区内。</p>

    <div class="terminal-grid">
      <div class="setting-row compact-row">
        <label>默认超时</label>
        <input v-model.number="draft.default_timeout_seconds" min="1" type="number" @blur="save" />
      </div>
      <div class="setting-row compact-row">
        <label>最大超时</label>
        <input v-model.number="draft.max_timeout_seconds" min="1" type="number" @blur="save" />
      </div>
      <div class="setting-row compact-row">
        <label>输出上限</label>
        <input v-model.number="draft.max_output_chars" min="1000" type="number" @blur="save" />
      </div>
      <div class="setting-row compact-row">
        <label>段数上限</label>
        <input v-model.number="draft.max_segments_per_call" min="1" type="number" @blur="save" />
      </div>
    </div>

    <div class="setting-row ignore-row">
      <label>禁止程序</label>
      <textarea v-model="blockedText" spellcheck="false" @blur="save"></textarea>
    </div>

    <div ref="shellSwitchRef" class="settings-resource-page-switch terminal-shell-switch" role="tablist" aria-label="终端类型">
      <span class="settings-resource-page-slider" :style="shellSliderStyle" aria-hidden="true"></span>
      <button
        v-for="page in shellPages"
        :key="page.key"
        class="settings-resource-page-button"
        :class="{ active: activeShell === page.key }"
        type="button"
        role="tab"
        :aria-selected="activeShell === page.key"
        @click="activeShell = page.key"
      >
        {{ page.label }}
      </button>
    </div>

    <div class="terminal-page-body library-form-surface terminal-page-card">
      <div class="setting-row toggle-row">
        <label>启用终端</label>
        <input
          :checked="draft.enabled_shells.includes(activeShell)"
          type="checkbox"
          @change="setShellEnabled(activeShell, ($event.target as HTMLInputElement).checked)"
        />
      </div>
      <div class="setting-row ignore-row">
        <label>允许程序</label>
        <textarea v-model="allowedText[activeShell]" spellcheck="false" @blur="save"></textarea>
      </div>
      <div class="segment-list">
        <div class="segment-table-header" aria-hidden="true">
          <span>类型</span>
          <span>程序</span>
          <span>用途</span>
        </div>
        <div v-for="segment in activeCatalog" :key="`${segment.type}:${segment.program}`" class="segment-row">
          <code>{{ segment.type }}</code>
          <strong>{{ segment.program }}</strong>
          <span>{{ segment.usage }}</span>
        </div>
        <p v-if="!activeCatalog.length" class="empty-hint">当前终端没有可用指令段</p>
      </div>
    </div>

    <div class="model-actions">
      <span v-if="saving" class="feedback">保存中...</span>
      <span v-if="statusMessage" class="feedback">{{ statusMessage }}</span>
    </div>
  </div>
</template>

<style scoped>
.hint-text,
.setting-hint,
.empty-hint {
  display: none;
}

.segment-row code {
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
}

.segment-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.segment-list {
  display: grid;
  gap: 0;
  margin: var(--space-8) 0 var(--space-12);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
}

.segment-table-header,
.segment-row {
  display: grid;
  grid-template-columns: minmax(130px, 0.8fr) minmax(180px, 1fr) minmax(0, 2fr);
  align-items: center;
  column-gap: var(--space-10);
  min-width: 0;
  padding: 0 var(--space-12);
}

.segment-table-header {
  min-height: 44px;
  background: var(--color-surface-raised);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  font-weight: 600;
}

.segment-row {
  min-height: 38px;
  background: transparent;
}

.segment-row:hover {
  background: var(--color-primary-softer);
}

.segment-row code {
  overflow: hidden;
  color: var(--color-text-secondary);
  font-family: var(--font-code);
  font-size: calc(12px * var(--font-scale));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-shell-switch {
  margin: var(--space-12) 0 var(--space-8);
}

.terminal-page-card {
  padding: var(--space-12);
  border-radius: 28px;
}
</style>
