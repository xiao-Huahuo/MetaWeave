<!-- Complete client management: persisted connections, draft tests, tool policy, import/export and live diagnostics. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import SettingsDisclosure from '@/components/common/SettingsDisclosure.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import McpKeyValueEditor from './McpKeyValueEditor.vue'
import McpToolList from './McpToolList.vue'
import { deleteMcpConnection, exportMcpConnections, previewMcpImport, reconnectMcpConnection, saveMcpClient, saveMcpConnection, testMcpConnection } from '@/api/mcp'
import type { McpClientState, McpConnection, McpConnectionDraft, McpImportEntry, McpTestResult } from '@/api/mcp'

const props = defineProps<{ userId: string; state: McpClientState }>()
const emit = defineEmits<{ refresh: []; dirty: [value: boolean]; busy: [value: boolean] }>()
const busy = ref(false)
const feedback = ref('')
const error = ref('')
const draft = ref<McpConnectionDraft | null>(null)
const existing = ref<McpConnection | undefined>()
const baseline = ref('')
const testResult = ref<McpTestResult | null>(null)
const testedDraft = ref('')
const importText = ref('')
const importOpen = ref(false)
const preview = ref<McpImportEntry[]>([])
const importStrategy = ref<'skip' | 'replace' | 'rename'>('skip')
const importSource = ref('')
const dirty = computed(() => Boolean(draft.value && JSON.stringify(draft.value) !== baseline.value) || Boolean(importOpen.value && importText.value))
const testStale = computed(() => testedDraft.value !== JSON.stringify(draft.value))
const availableTools = computed(() => testResult.value?.tools ?? existing.value?.tools ?? [])
const allowedTools = computed({
  get: () => availableTools.value.filter(t => !draft.value?.disabled_tools.includes(t.name)).map(t => t.name),
  set: value => { if (draft.value) draft.value.disabled_tools = availableTools.value.filter(t => !value.includes(t.name)).map(t => t.name) },
})
watch(dirty, value => emit('dirty', value), { immediate: true })
watch(busy, value => emit('busy', value))
const stateNames: Record<string, string> = { connected: '可用', connecting: '连接中', failed: '连接失败', stopped: '未连接' }

/** Keep errors local and retain all drafts on failure. */
async function perform(action: () => Promise<void>) {
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action() } catch (reason) { error.value = reason instanceof Error ? reason.message : '操作失败' }
  finally { busy.value = false }
}
/** Extract only editable DTO fields from a live connection. */
function editable(row?: McpConnection): McpConnectionDraft {
  return row ? {
    name: row.name, transport: row.transport, enabled: row.enabled, command: row.command,
    args: [...row.args], cwd: row.cwd, url: row.url, env: { ...row.env }, headers: { ...row.headers },
    timeout_seconds: row.timeout_seconds, disabled_tools: [...row.disabled_tools],
  } : { name: '', transport: 'stdio', enabled: true, command: '', args: [], cwd: '', url: '', env: {}, headers: {}, timeout_seconds: 30, disabled_tools: [] }
}
function edit(row?: McpConnection) {
  if (dirty.value && !window.confirm('放弃当前未保存的配置？')) return
  existing.value = row; draft.value = editable(row); baseline.value = JSON.stringify(draft.value)
  testResult.value = null; testedDraft.value = ''; error.value = ''; feedback.value = ''
}
function cancel() {
  if (dirty.value && !window.confirm('放弃当前未保存的配置？')) return
  draft.value = null; importText.value = ''; importOpen.value = false; preview.value = []
}
async function test() {
  if (!draft.value) return
  const submitted = JSON.stringify(draft.value)
  await perform(async () => {
    testResult.value = await testMcpConnection(props.userId, draft.value!, existing.value?.connection_id)
    testedDraft.value = submitted
    if (testResult.value.state !== 'connected') error.value = testResult.value.error
    else feedback.value = `连接通过，发现 ${testResult.value.tools.length} 个工具`
  })
}
async function save() {
  if (!draft.value) return
  await perform(async () => {
    const saved = await saveMcpConnection(props.userId, draft.value!, existing.value)
    existing.value = saved; draft.value = editable(saved); baseline.value = JSON.stringify(draft.value)
    feedback.value = saved.state === 'connected' ? '已保存并生效；下一轮 Agent 使用新配置' : '已保存；' + (saved.error || '启用客户端和此服务后连接')
    emit('refresh')
  })
}
async function toggleClient(enabled: boolean) {
  await perform(async () => { await saveMcpClient(props.userId, enabled); emit('refresh'); feedback.value = enabled ? '客户端已启用' : '客户端已停用，连接已释放' })
}
async function toggleConnection(row: McpConnection, enabled: boolean) {
  await perform(async () => { await saveMcpConnection(props.userId, { ...editable(row), enabled }, row); emit('refresh') })
}
async function remove(row: McpConnection) {
  if (!window.confirm(`删除 ${row.name} 的连接配置？`)) return
  await perform(async () => { await deleteMcpConnection(props.userId, row.connection_id); if (existing.value?.connection_id === row.connection_id) draft.value = null; emit('refresh') })
}
async function reconnect(row: McpConnection) {
  await perform(async () => { const result = await reconnectMcpConnection(props.userId, row.connection_id); if (result.error) error.value = result.error; emit('refresh') })
}
async function exportConfig() {
  await perform(async () => {
    const config = await exportMcpConnections(props.userId)
    const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'mcp-connections.json'; link.click(); URL.revokeObjectURL(url)
    feedback.value = '已导出配置，环境变量和认证请求头已排除'
  })
}
async function previewImport() {
  await perform(async () => { preview.value = (await previewMcpImport(props.userId, importText.value)).entries; importSource.value = importText.value })
}
/** Apply exactly the reviewed file and conflict strategy; retain actionable failures. */
async function importConfig() {
  await perform(async () => {
    const reservedNames = new Set([...props.state.connections.map(row => row.name), ...preview.value.flatMap(entry => entry.draft ? [entry.draft.name] : [])])
    for (const entry of preview.value) {
      if (!entry.draft || entry.error) throw new Error('先修正导入配置中的错误')
      const config: McpConnectionDraft = JSON.parse(JSON.stringify(entry.draft))
      const match = props.state.connections.find(row => row.name === config.name)
      if (match && importStrategy.value === 'skip') continue
      if (match && importStrategy.value === 'rename') {
        let count = 2
        while (reservedNames.has(`${config.name} ${count}`)) count++
        config.name = `${config.name} ${count}`
        reservedNames.add(config.name)
      }
      await saveMcpConnection(props.userId, config, match && importStrategy.value === 'replace' ? match : undefined)
    }
    preview.value = []; importText.value = ''; importOpen.value = false; feedback.value = '导入完成'; emit('refresh')
  })
}
defineExpose({ dirty })
</script>

<template>
  <section aria-label="MCP 客户端" class="setting-section">
    <div class="setting-row toggle-row"><label for="mcp-client-enabled">启用客户端</label><input id="mcp-client-enabled" type="checkbox" :checked="state.config.enabled" :disabled="busy" @change="toggleClient(($event.target as HTMLInputElement).checked)" /></div>
    <div class="mcp-toolbar"><h3>外部服务</h3><div class="mcp-actions"><button class="mcp-text-button" type="button" :disabled="busy" @click="exportConfig"><IcIcon name="download" :size="16" /><span>导出</span></button><button class="mcp-text-button" type="button" :disabled="busy" @click="importOpen = !importOpen"><IcIcon name="upload" :size="16" /><span>导入配置</span></button><button class="mcp-text-button" type="button" :disabled="busy" @click="edit()"><IcIcon name="add" :size="16" /><span>添加服务</span></button></div></div>
    <p v-if="!state.connections.length" class="mcp-empty">尚未添加服务。添加服务或导入现有 MCP 配置。</p>
    <div v-else class="mcp-connection-list">
      <div v-for="row in state.connections" :key="row.connection_id" class="mcp-connection-row" :class="{ selected: existing?.connection_id === row.connection_id && draft }">
        <div class="mcp-connection-name"><strong>{{ row.name }}</strong><span>{{ row.transport === 'stdio' ? '本地进程' : 'HTTP' }}</span><span v-if="row.inherited">服务默认</span></div>
        <span class="mcp-status" :class="row.state"><i aria-hidden="true"></i>{{ row.enabled ? stateNames[row.state] || row.state : '已禁用' }}</span>
        <div class="mcp-actions"><button class="mcp-text-button" type="button" :disabled="busy" @click="edit(row)"><IcIcon name="settings" :size="16" /><span>配置</span></button><button class="mcp-icon-button" type="button" :disabled="busy || !state.config.enabled || !row.enabled" :aria-label="`重连 ${row.name}`" @click="reconnect(row)"><IcIcon name="refresh" :size="16" /></button><button class="mcp-icon-button danger" type="button" :disabled="busy" :aria-label="`删除 ${row.name}`" @click="remove(row)"><IcIcon name="trash" :size="16" /></button><label class="toggle-row"><input type="checkbox" :checked="row.enabled" :disabled="busy" :aria-label="`启用 ${row.name}`" @change="toggleConnection(row, ($event.target as HTMLInputElement).checked)" /></label></div>
        <p v-if="row.error" class="mcp-inline-error">{{ row.error }}</p>
      </div>
    </div>

    <FormHeightTransition :watch-key="`${Boolean(draft)}-${draft?.transport}-${importOpen}`">
      <form v-if="draft" class="mcp-editor settings-model-form" @submit.prevent="save">
        <div class="mcp-toolbar"><h3>{{ existing ? '编辑服务' : '添加服务' }}</h3><span v-if="dirty" class="mcp-status">未保存</span></div>
        <fieldset :disabled="busy">
          <div class="setting-row"><label for="mcp-name">名称</label><input id="mcp-name" v-model="draft.name" required maxlength="128" /></div>
          <div class="setting-row"><label for="mcp-transport">连接方式</label><select id="mcp-transport" v-model="draft.transport"><option value="stdio">本地进程（stdio）</option><option value="http">远程 HTTP</option></select></div>
          <template v-if="draft.transport === 'stdio'">
            <div class="setting-row"><label for="mcp-command">程序</label><input id="mcp-command" v-model="draft.command" required spellcheck="false" placeholder="程序名称或完整路径" /></div>
            <div class="mcp-toolbar"><h4>参数</h4><button class="mcp-text-button" type="button" @click="draft.args.push('')"><IcIcon name="add" :size="16" /><span>添加参数</span></button></div>
            <div v-for="(_, index) in draft.args" :key="index" class="mcp-argument-row"><input v-model="draft.args[index]" :aria-label="`参数 ${index + 1}`" spellcheck="false" /><button class="mcp-icon-button" type="button" :aria-label="`删除参数 ${index + 1}`" @click="draft.args.splice(index, 1)"><IcIcon name="trash" :size="16" /></button></div>
            <McpKeyValueEditor v-model="draft.env" label="环境变量" />
          </template>
          <template v-else><div class="setting-row"><label for="mcp-url">服务地址</label><input id="mcp-url" v-model="draft.url" type="url" required spellcheck="false" placeholder="https://…/mcp" /></div><McpKeyValueEditor v-model="draft.headers" label="请求头" /><p class="mcp-note">Bearer 认证：添加 Authorization 请求头，值为 Bearer 加访问令牌。</p></template>
          <SettingsDisclosure class="mcp-advanced" label="高级设置"><div v-if="draft.transport === 'stdio'" class="setting-row"><label for="mcp-cwd">工作目录</label><input id="mcp-cwd" v-model="draft.cwd" spellcheck="false" /></div><div class="setting-row"><label for="mcp-timeout">超时（秒）</label><input id="mcp-timeout" v-model.number="draft.timeout_seconds" type="number" min="1" max="600" required /></div></SettingsDisclosure>
          <div class="mcp-actions mcp-bottom-actions"><button class="mcp-outline-button" type="button" @click="test">测试连接</button><button class="mcp-outline-button" type="submit">保存并应用</button><button class="mcp-outline-button mcp-cancel-button" type="button" @click="cancel">取消</button></div>
        </fieldset>
        <p v-if="testResult && testStale" class="mcp-note">配置已改变，之前的测试结果不再适用。</p>
        <div v-if="availableTools.length" class="mcp-discovery"><h4>允许 Agent 使用的工具</h4><McpToolList v-model="allowedTools" :tools="availableTools" label="客户端工具权限" :disabled="busy" /><p class="mcp-note">未声明只读的外部工具，仅在 Agent 完全访问模式下提供。</p></div>
      </form>
      <div v-if="importOpen" class="mcp-editor"><h3>导入配置</h3><label for="mcp-import-json">配置 JSON</label><textarea id="mcp-import-json" v-model="importText" class="mcp-code" rows="7" spellcheck="false"></textarea><div class="mcp-actions mcp-bottom-actions"><button class="mcp-outline-button" type="button" :disabled="busy || !importText.trim()" @click="previewImport">检查配置</button><button class="mcp-outline-button mcp-cancel-button" type="button" :disabled="busy" @click="cancel">取消</button></div>
        <template v-if="preview.length"><div v-for="entry in preview" :key="entry.index" class="mcp-import-row"><strong>{{ entry.draft?.name || `配置 ${entry.index + 1}` }}</strong><span :class="{ 'mcp-inline-error': entry.error }">{{ entry.error || (entry.conflict ? '名称已存在' : '可导入') }}</span></div><div class="setting-row"><label for="mcp-import-strategy">同名处理</label><select id="mcp-import-strategy" v-model="importStrategy"><option value="skip">跳过</option><option value="replace">替换</option><option value="rename">自动改名</option></select></div><button class="mcp-outline-button" type="button" :disabled="busy || preview.some(e => e.error) || importText !== importSource" @click="importConfig">确认导入</button></template>
      </div>
    </FormHeightTransition>
    <p v-if="busy" class="feedback" role="status">正在处理…</p><p v-if="feedback" class="feedback" role="status">{{ feedback }}</p><p v-if="error" class="feedback error" role="alert">{{ error }}</p>
  </section>
</template>
