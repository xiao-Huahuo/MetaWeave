<!--
  Inline thinking trace.

  Usage:
  Console-compatible DeepSeek-style thinking list. It hides tool start events
  and deduplicates display through the parent ChatBubble.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  traces?: Array<Record<string, unknown>>
  isStreaming?: boolean
  defaultExpanded?: boolean
}>()

const emit = defineEmits<{
  collapse: []
}>()

const isExpanded = ref(props.defaultExpanded ?? false)
const skipEvents = new Set(['tool_call_start'])
const FALLBACK_DISPLAY: Record<string, string> = {
  // 遗留工具名(兼容旧轨迹)
  get_current_utc_time: '获取UTC时间',
  echo_text: '回显文本',
  generate_uuid: '生成UUID',
  calculate: '数学计算',
  json_parse: '解析JSON',
  json_pick: '提取JSON字段',
  text_stats: '文本统计',
  list_builtin_tools: '列出工具',
  update_exploration_state: '更新探索状态',
  // 通用工具
  list_available_tools: '查看可用工具',
  get_current_time: '获取当前时间',
  run_terminal_command: '终端命令',
  download_file: '下载文件',
  // Git 工具
  git_status: 'Git 状态',
  git_diff: 'Git 差异',
  git_history: 'Git 历史',
  git_init_repository: '初始化 Git',
  git_restore_files: 'Git 回滚',
  git_commit_files: 'Git 提交',
  git_push_branch: 'Git 推送',
  git_create_branch: '创建 Git 分支',
  git_add_remote: '新增 Git 远程',
  git_switch_branch: '切换 Git 分支',
  git_pull_branch: 'Git 拉取',
  // 技能工具
  list_skills: '列出技能',
  use_skill: '使用技能',
  // 记忆工具
  get_long_term_memory: '检索记忆',
  write_long_term_memory: '写入记忆',
  write_long_term_rule: '写入长期规则',
  delete_long_term_memory: '删除记忆',
  delete_long_term_rule: '删除长期规则',
  // 知识库工具
  get_knowledge_context: '检索知识',
  rebuild_knowledge_base: '重建知识库',
  search_knowledge: '四库联合搜索',
  save_uploaded_attachment_to_knowledge: '附件存入知识库',
  get_knowledge_file_url: '获取文件URL',
  // 图书馆工具
  list_library_items: '列出图书馆',
  list_library_tags: '列出图书馆标签',
  add_library_book: '新增图书',
  add_library_collection: '新增集锦',
  update_library_item: '更新图书馆条目',
  remove_library_item: '移出图书馆',
  // 文件管理工具
  get_current_viewing_document: '获取当前文档',
  list_knowledge_files: '列出文件',
  read_file: '阅读文件',
  read_knowledge_file: '阅读文件', // 兼容旧会话轨迹。
  read_session_attachment: '阅读文件',
  write_knowledge_file: '创作文件',
  show_markdown_html: '展示Markdown-HTML',
  delete_knowledge_file: '删除文件',
  rename_knowledge_file: '重命名文件',
  create_knowledge_folder: '创建文件夹',
  // 任务列表工具
  get_task_list_status: '获取任务列表状态',
  create_task_list: '创建任务列表',
  complete_task_list_item: '完成任务项',
  finish_task_list: '完成任务列表',
  // 子 Agent 工具
  spawn_child_agent: '召唤子 Agent',
  wait_for_child_agents: '等待子 Agent',
  // 待办工具
  list_todos: '列出待办',
  add_todo: '新增待办',
  add_automation: '创建自动化任务',
  toggle_todo: '切换待办状态',
  edit_todo: '编辑待办',
  delete_todo: '删除待办',
  // 联网搜索工具
  web_search: '联网搜索',
  web_image_search: '联网搜索图片',
}

function handleToggle(event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  isExpanded.value = open
  if (!open) {
    emit('collapse')
  }
}

function asString(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function asNumber(value: unknown) {
  return typeof value === 'number' ? value : null
}

function resolveDisplayName(trace: Record<string, unknown>) {
  return asString(trace.display_name) || FALLBACK_DISPLAY[asString(trace.tool_name)] || asString(trace.tool_name) || '工具'
}

function toolSummary(trace: Record<string, unknown>) {
  if (asString(trace.tool_name) === 'run_terminal_command') {
    return terminalCommandSummary(asString(trace.tool_args_summary), asString(trace.terminal_command))
  }
  const displayName = resolveDisplayName(trace)
  const resultCount = asNumber(trace.result_count)
  if (resultCount !== null) {
    return `${displayName}：${resultCount} 条结果`
  }
  return displayName
}

function extractQuotedListItems(value: string) {
  return Array.from(value.matchAll(/['"]([^'"]+)['"]/g)).map((match) => match[1] ?? '').filter(Boolean)
}

function terminalCommandSummary(argsSummary: string, terminalCommand = '') {
  const shell = (argsSummary.match(/(?:^|,\s*)shell=([^,]+)/)?.[1] ?? '').trim()
  if (terminalCommand) {
    return `运行了${shell || '终端'}命令: ${terminalCommand}`
  }
  const program = (argsSummary.match(/['"]?program['"]?\s*:\s*['"]([^'"]+)['"]/)?.[1] ?? '').trim()
  const rawArgs = argsSummary.match(/['"]?args['"]?\s*:\s*\[([^\]]*)\]/)?.[1] ?? ''
  const args = extractQuotedListItems(rawArgs)
  const command = [program, ...args].filter(Boolean).join(' ').trim()
  if (!shell && !command) {
    return '运行了终端命令'
  }
  if (!command) {
    return `运行了${shell || '终端'}命令`
  }
  return `运行了${shell || '终端'}命令: ${command}`
}

function aggregatedToolSummary(displayName: string, count: number, filenames: string[], argsSummary = '', terminalCommand = '') {
  if (displayName === '终端命令') {
    const summary = terminalCommandSummary(argsSummary, terminalCommand)
    return count > 1 ? `${summary} × ${count}` : summary
  }
  if (filenames.length === 1) {
    return `${displayName}：${filenames[0]}`
  }
  if (filenames.length > 1) {
    return `${displayName} × ${count}：${filenames.join(', ')}`
  }
  return `${displayName} × ${count}`
}

function extractFilename(trace: Record<string, unknown>, toolName: string) {
  const rawContent = asString(trace.raw_content)
  if (toolName === 'write_knowledge_file') {
    const m = rawContent.match(/已保存文件:\s*(.+?)\s*\(/)
    return m ? m[1] : null
  }
  if (toolName === 'delete_knowledge_file') {
    const m = rawContent.match(/已删除:\s*(.+)/)
    return m ? m[1] : null
  }
  if (toolName === 'rename_knowledge_file') {
    const m = rawContent.match(/已重命名:\s*(.+)/)
    return m ? m[1] : null
  }
  if (toolName === 'create_knowledge_folder') {
    const m = rawContent.match(/已创建文件夹:\s*(.+)/)
    return m ? m[1] : null
  }
  return null
}

function entryText(trace: Record<string, unknown>) {
  if (trace.event === 'tool_call_end') {
    return toolSummary(trace)
  }
  return asString(trace.human_readable) || asString(trace.event)
}

const entries = computed(() => {
  const raw = (props.traces ?? [])
    .filter((trace) => {
      const event = asString(trace.event)
      const isChatVisible = trace.chat_visible === true || event === 'tool_call_end'
      return isChatVisible && !skipEvents.has(event) && asString(trace.human_readable)
    })

  // First pass: collect all tool_call_end events into groups by tool_name,
  // recording the position of the first occurrence.
  const toolGroupOrder: string[] = []
  const toolGroups = new Map<string, { displayName: string; count: number; filenames: string[]; firstIdx: number; argsSummary: string; terminalCommand: string }>()
  const nonToolEntries: Array<{ idx: number; key: string; text: string; isTool: boolean }> = []

  raw.forEach((trace, idx) => {
    const event = asString(trace.event)
    if (event !== 'tool_call_end') {
      nonToolEntries.push({
        idx,
        key: `${asString(trace.node)}-${event}-${asString(trace.tool_name)}-${idx}`,
        text: entryText(trace),
        isTool: false,
      })
      return
    }

    const toolName = asString(trace.tool_name)
    const displayName = resolveDisplayName(trace)
    if (!asString(trace.display_name) && !FALLBACK_DISPLAY[toolName]) {
      nonToolEntries.push({
        idx,
        key: `${asString(trace.node)}-${event}-${toolName}-${idx}`,
        text: entryText(trace),
        isTool: true,
      })
      return
    }

    let group = toolGroups.get(toolName)
    if (!group) {
      group = {
        displayName,
        count: 0,
        filenames: [],
        firstIdx: idx,
        argsSummary: asString(trace.tool_args_summary),
        terminalCommand: asString(trace.terminal_command),
      }
      toolGroups.set(toolName, group)
      toolGroupOrder.push(toolName)
    }
    group.count++
    const fn = extractFilename(trace, toolName)
    if (fn && !group.filenames.includes(fn)) {
      group.filenames.push(fn)
    }
  })

  // Merge: interleave non-tool entries with tool group summaries at firstIdx positions.
  const result: Array<{ key: string; text: string; isTool: boolean }> = []

  const toolPositions = toolGroupOrder.map((name) => {
    const g = toolGroups.get(name)!
    return { name: g.displayName, ...g }
  })

  // Build combined sorted list
  const ordered: Array<
    { type: 'tool'; name: string; count: number; filenames: string[]; idx: number; argsSummary: string; terminalCommand: string }
    | { type: 'entry'; idx: number; key: string; text: string; isTool: boolean }
  > = [
    ...nonToolEntries.map((e) => ({ type: 'entry' as const, idx: e.idx, key: e.key, text: e.text, isTool: e.isTool })),
    ...toolPositions.map((g) => ({
      type: 'tool' as const,
      idx: g.firstIdx,
      name: g.name,
      count: g.count,
      filenames: g.filenames,
      argsSummary: g.argsSummary,
      terminalCommand: g.terminalCommand,
    })),
  ]
  ordered.sort((a, b) => a.idx - b.idx)

  for (const item of ordered) {
    if (item.type === 'entry') {
      result.push({ key: item.key, text: item.text, isTool: item.isTool })
    } else {
      result.push({
        key: `agg-tool-${item.name}-${item.count}`,
        text: aggregatedToolSummary(item.name, item.count, item.filenames, item.argsSummary, item.terminalCommand),
        isTool: true,
      })
    }
  }

  return result
})
</script>

<template>
  <details v-if="entries.length > 0" class="thinking-inline" :open="isExpanded" @toggle="handleToggle">
    <summary class="toggle-bar">
      <span class="bar-chevron" :class="{ expanded: isExpanded }">></span>
      <span v-if="!isExpanded && isStreaming" class="bar-label">思考中...</span>
      <span v-else-if="!isExpanded && !isStreaming" class="bar-label">思考完成</span>
      <span v-else class="bar-label">思考过程</span>
    </summary>

    <Transition name="inline-list">
      <div v-if="isExpanded" class="entry-list">
        <p
          v-for="(entry, index) in entries"
          :key="entry.key"
          class="entry-line"
          :class="{ 'is-tool': entry.isTool, 'is-new': index === entries.length - 1 && entries.length > 1 && isStreaming }"
        >
          <span class="entry-bullet">-</span>
          <span class="entry-text">{{ entry.text }}</span>
        </p>
      </div>
    </Transition>
  </details>
</template>

<style scoped>
.thinking-inline {
  margin-bottom: var(--space-8);
}

.thinking-inline > summary {
  list-style: none;
}

.thinking-inline > summary::-webkit-details-marker {
  display: none;
}

.toggle-bar {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  width: fit-content;
  min-height: 24px;
  color: #8a93a3;
  cursor: pointer;
}

.bar-chevron {
  display: inline-block;
  flex-shrink: 0;
  color: currentColor;
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  transition: transform 0.25s ease;
}

.bar-chevron.expanded {
  transform: rotate(90deg);
}

.bar-label {
  color: currentColor;
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  opacity: 0.9;
  transition: opacity var(--transition-fast);
}

.toggle-bar:hover .bar-label {
  opacity: 1;
}

.inline-list-enter-active {
  overflow: hidden;
  transition:
    max-height 0.35s ease,
    opacity 0.3s ease;
}

.inline-list-leave-active {
  overflow: hidden;
  transition:
    max-height 0.25s ease,
    opacity 0.2s ease;
}

.inline-list-enter-from,
.inline-list-leave-to {
  max-height: 0;
  opacity: 0;
}

.inline-list-enter-to,
.inline-list-leave-from {
  max-height: 2000px;
  opacity: 1;
}

.entry-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding-left: var(--space-12);
}

.entry-line {
  display: flex;
  gap: var(--space-6);
  margin: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-text);
  font-size: var(--font-size-xs);
  line-height: var(--line-height-relaxed);
}

.entry-bullet {
  flex-shrink: 0;
  color: var(--color-text-secondary);
  opacity: 0.6;
}

.entry-text {
  color: var(--color-text-secondary);
  opacity: 0.85;
}

.entry-line.is-tool .entry-text {
  color: var(--color-blue);
  opacity: 0.7;
}

.is-new {
  animation: entry-slide-in 0.4s ease-out;
}

@keyframes entry-slide-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
