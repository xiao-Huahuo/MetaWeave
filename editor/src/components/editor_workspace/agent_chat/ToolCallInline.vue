<!--
  Inline tool call summary with per-tool expandable detail.

  Usage:
  Tool mode consumes action-node traces and merges each tool by name, matching
  the console display contract. Each completed tool shows an expand button that
  reveals its full return content, rendered per tool type.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
import ChangeDiff from '@/components/editor_workspace/agent_chat/ChangeDiff.vue'
import { toolIconName } from '@/components/editor_workspace/agent_chat/toolIcons'
import type { AgentChangeSnapshot } from '@/api/agentChanges'

const props = defineProps<{
  traces?: Array<Record<string, unknown>>
  isStreaming?: boolean
  changeSnapshot?: AgentChangeSnapshot | null
}>()

interface ToolDisplayEntry {
  key: string
  text: string
  pending: boolean
  rawContents: string[]
  toolName: string
  patch?: { path: string; before: string; after: string; complete: boolean }
}

interface ToolEntry {
  tool_name: string
  display_name: string
  args_summary: string
  terminal_command: string
  result_count?: number
  call_count: number
  filenames: string[]
  labels: string[]
  raw_contents: string[]
}

interface TerminalSegmentResult {
  index: number
  command: string
  exitCode: number
  timedOut: boolean
  stdout: string
  stderr: string
  truncated: boolean
}

interface TerminalResultDisplay {
  ok: boolean
  shell: string
  cwd: string
  truncated: boolean
  segments: TerminalSegmentResult[]
}

const expanded = ref(new Set<string>())
const copiedKey = ref('')

function toggleExpand(key: string) {
  const next = new Set(expanded.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expanded.value = next
}

function copyContent(key: string, text: string) {
  navigator.clipboard.writeText(text).then(() => {
    copiedKey.value = key
    setTimeout(() => { copiedKey.value = '' }, 1500)
  })
}

function getCopyText(rawContents: string[]) {
  return rawContents.join('\n---\n')
}

const FALLBACK_DISPLAY: Record<string, string> = {
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
  read_knowledge_file: '阅读文件',
  write_knowledge_file: '创作文件',
  patch_knowledge_file: '局部修改文件',
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

function asString(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function asNumber(value: unknown) {
  return typeof value === 'number' ? value : undefined
}

function truncateLabel(value: string, maxLength = 42) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength)}…`
}

function extractArgsValue(argsSummary: string, key: string) {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(`(?:^|,\\s*)${escapedKey}=([^,]+)`)
  return (argsSummary.match(pattern)?.[1] ?? '').trim()
}

function uniquePush(values: string[], value: string | null | undefined) {
  const normalized = truncateLabel(value ?? '')
  if (normalized && !values.includes(normalized)) {
    values.push(normalized)
  }
}

function formatLabels(values: string[], singlePrefix: string, multiPrefix: string) {
  if (values.length === 0) return singlePrefix
  if (values.length <= 2) return `${singlePrefix}：${values.join('、')}`
  return `${multiPrefix} ${values.length} 项`
}

function formatIsoTime(rawContent: string) {
  const trimmed = rawContent.trim()
  const date = new Date(trimmed)
  if (Number.isNaN(date.getTime())) return trimmed || '未知'
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function parseJsonObject(rawContent: string): Record<string, unknown> | null {
  try {
    return asRecord(JSON.parse(rawContent))
  } catch {
    return null
  }
}

function currentDocumentLabel(rawContent: string) {
  const parsed = parseJsonObject(rawContent)
  if (parsed) {
    return asString(parsed.name) || asString(parsed.path) || '无活动文件'
  }
  if (rawContent.includes('没有') || rawContent.includes('暂无')) return '无活动文件'
  return truncateLabel(rawContent)
}

function taskListStatusLabel(rawContent: string) {
  if (rawContent.includes('No task list')) return '无任务列表'
  const status = rawContent.match(/^Status:\s*(.+)$/m)?.[1]?.trim()
  if (status) return status
  return rawContent.includes('finished') || rawContent.includes('completed') ? '已完成' : '进行中'
}

function countTodoLines(rawContent: string) {
  if (rawContent.includes('当前没有待办事项')) return 0
  return rawContent.split('\n').filter((line) => /^\d+\.\s+\[todo_[^\]]+\]/.test(line.trim())).length
}

function fileTreeCounts(rawContent: string) {
  const summary = rawContent.match(/共\s*(\d+)\s*个文件,\s*(\d+)\s*个文件夹/)
  if (summary) {
    return {
      files: Number(summary[1] ?? 0),
      dirs: Number(summary[2] ?? 0),
    }
  }
  return {
    files: rawContent.split('\n').filter((line) => line.trim().startsWith('[FILE]')).length,
    dirs: rawContent.split('\n').filter((line) => line.trim().startsWith('[DIR]')).length,
  }
}

function firstPathFromArgs(argsSummary: string) {
  return extractArgsValue(argsSummary, 'path')
    || extractArgsValue(argsSummary, 'source_path')
    || extractArgsValue(argsSummary, 'target_path')
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

function extractToolLabel(trace: Record<string, unknown>, toolName: string) {
  const argsSummary = asString(trace.tool_args_summary)
  const rawContent = asString(trace.raw_content)
  if (toolName === 'web_search' || toolName === 'web_image_search' || toolName === 'search_knowledge') {
    return extractArgsValue(argsSummary, 'query')
  }
  if (toolName === 'use_skill') return extractArgsValue(argsSummary, 'skill_ref')
  if (toolName === 'create_task_list') return extractArgsValue(argsSummary, 'title')
  if (toolName === 'add_todo') {
    return extractArgsValue(argsSummary, 'text') || rawContent.match(/已创建待办\s*\[[^\]]+\]:\s*(.+?)(?:,\s*截止日期|$)/)?.[1] || ''
  }
  if (toolName === 'edit_todo') return extractArgsValue(argsSummary, 'text') || rawContent.match(/已更新待办:\s*(.+?)(?:\s*\||$)/)?.[1] || ''
  if (toolName === 'write_long_term_rule') return extractArgsValue(argsSummary, 'content')
  if (toolName === 'get_knowledge_file_url') return extractArgsValue(argsSummary, 'path') || rawContent
  return extractFilename(trace, toolName) || firstPathFromArgs(argsSummary)
}

function extractQuotedListItems(value: string) {
  return Array.from(value.matchAll(/['"]([^'"]+)['"]/g)).map((match) => match[1] ?? '').filter(Boolean)
}

function terminalCommandSummary(argsSummary: string, terminalCommand = '', fallbackShell = '') {
  const shell = (argsSummary.match(/(?:^|,\s*)shell=([^,]+)/)?.[1] ?? fallbackShell).trim()
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

function toolSummary(entry: ToolEntry) {
  if (entry.tool_name === 'run_terminal_command') {
    const summary = terminalCommandSummary(entry.args_summary, entry.terminal_command)
    return entry.call_count > 1 ? `${summary} × ${entry.call_count}` : summary
  }

  const displayName = entry.display_name || entry.tool_name
  if (!displayName) return null

  const latest = entry.raw_contents.length > 0 ? entry.raw_contents[entry.raw_contents.length - 1] ?? '' : ''
  const count = entry.result_count ?? entry.call_count

  if (entry.tool_name === 'web_search') {
    const suffix = entry.labels.length > 0 ? ` 条结果 | ${entry.labels.join(' | ')}` : ' 条结果'
    return `联网搜索：${entry.result_count ?? entry.call_count}${suffix}`
  }
  if (entry.tool_name === 'web_image_search') {
    const suffix = entry.labels.length > 0 ? ` 张图片 | ${entry.labels.join(' | ')}` : ' 张图片'
    return `联网搜图：${entry.result_count ?? entry.call_count}${suffix}`
  }
  if (entry.tool_name === 'get_knowledge_context') {
    return `检索到 ${entry.result_count ?? entry.call_count} 条知识`
  }
  if (entry.tool_name === 'search_knowledge') {
    const suffix = entry.labels.length > 0 ? ` 条结果 | ${entry.labels.join(' | ')}` : ' 条结果'
    return `四库联合搜索：${entry.result_count ?? entry.call_count}${suffix}`
  }
  if (entry.tool_name === 'get_long_term_memory') {
    return `检索到 ${entry.result_count ?? entry.call_count} 条记忆`
  }
  if (entry.tool_name === 'write_long_term_memory') {
    return `写入 ${count} 条记忆`
  }
  if (entry.tool_name === 'delete_long_term_memory') {
    return `删除 ${count} 条记忆`
  }
  if (entry.tool_name === 'delete_long_term_rule') {
    return `删除 ${count} 条长期规则`
  }
  if (entry.tool_name === 'complete_task_list_item') {
    return `完成 ${count} 个任务项`
  }
  if (entry.tool_name === 'toggle_todo') {
    return `更新 ${count} 条待办`
  }
  if (entry.tool_name === 'delete_todo') {
    return `删除 ${count} 条待办`
  }
  if (entry.tool_name === 'list_knowledge_files') {
    const totals = entry.raw_contents.reduce((sum, rawContent) => {
      const parsed = fileTreeCounts(rawContent)
      return { files: sum.files + parsed.files, dirs: sum.dirs + parsed.dirs }
    }, { files: 0, dirs: 0 })
    return totals.dirs > 0 ? `列出 ${totals.files} 个文件 / ${totals.dirs} 个文件夹` : `列出 ${totals.files} 个文件`
  }

  const fileCountLabels: Record<string, [string, string, string]> = {
    read_knowledge_file: ['阅读文件', '阅读 ', ' 个文件'],
    write_knowledge_file: ['创作文件', '创作 ', ' 个文件'],
    delete_knowledge_file: ['删除文件', '删除 ', ' 个文件'],
    rename_knowledge_file: ['重命名文件', '重命名 ', ' 个文件'],
    create_knowledge_folder: ['创建文件夹', '创建 ', ' 个文件夹'],
    save_uploaded_attachment_to_knowledge: ['附件存入知识库', '保存 ', ' 个附件到知识库'],
    download_file: ['下载文件', '下载 ', ' 个文件'],
  }
  const fileCountConfig = fileCountLabels[entry.tool_name]
  if (fileCountConfig) {
    if (entry.call_count === 1 && entry.labels.length > 0) {
      return `${fileCountConfig[0]}：${entry.labels[0]}`
    }
    return `${fileCountConfig[1]}${entry.call_count}${fileCountConfig[2]}`
  }

  const contentSummary: Record<string, [string, string]> = {
    use_skill: ['使用技能', '使用'],
    create_task_list: ['创建任务列表', '创建'],
    add_todo: ['新增待办', '新增'],
    edit_todo: ['编辑待办', '编辑'],
    write_long_term_rule: ['写入长期规则', '写入'],
  }
  const contentConfig = contentSummary[entry.tool_name]
  if (contentConfig) {
    return formatLabels(entry.labels, contentConfig[0], `${contentConfig[1]} ${entry.call_count}`)
  }

  const statusSummary: Record<string, string> = {
    get_current_time: `获取当前时间：${formatIsoTime(latest)}`,
    get_current_viewing_document: `获取当前文档：${currentDocumentLabel(latest)}`,
    get_task_list_status: `获取任务列表状态：${taskListStatusLabel(latest)}`,
    list_todos: `列出待办：${countTodoLines(latest) > 0 ? `${countTodoLines(latest)} 条` : '无'}`,
    get_knowledge_file_url: `获取文件链接：${entry.labels[0] || '完成'}`,
    rebuild_knowledge_base: `重建知识库：${latest.includes('失败') ? '失败' : '完成'}`,
    finish_task_list: '完成任务列表：完成',
    list_skills: '列出技能',
  }
  if (statusSummary[entry.tool_name]) {
    return statusSummary[entry.tool_name]
  }

  if (entry.call_count > 1) {
    if (entry.filenames.length === 1) {
      return `${displayName}：${entry.filenames[0]}`
    }
    if (entry.filenames.length > 1) {
      return `${displayName} × ${entry.call_count}：${entry.filenames.join(', ')}`
    }
    return `${displayName} × ${entry.call_count}`
  }

  if (entry.filenames.length === 1) {
    return `${displayName}：${entry.filenames[0]}`
  }
  return displayName
}

function parseSearchResults(content: string) {
  const lines = content.split('\n').filter((l) => l.trim())
  const items: { index: number; source: string; content: string }[] = []
  let current: { index: number; source: string; content: string[] } | null = null
  for (const line of lines) {
    const m = line.match(/^(\d+)\.\s*\[([^\]]+)\]\s*来源:\s*(.+)/)
    if (m) {
      if (current) {
        items.push({ index: current.index, source: current.source, content: current.content.join('\n').trim() })
      }
      current = { index: parseInt(m[1] ?? '0', 10), source: (m[2] ?? '').trim(), content: [] }
      const afterSource = (m[3] ?? '').trim()
      if (afterSource) current.content.push(afterSource)
    } else if (current) {
      current.content.push(line)
    }
  }
  if (current) {
    items.push({ index: current.index, source: current.source, content: current.content.join('\n').trim() })
  }
  if (items.length === 0) {
    // fallback: just treat whole content as text
    return null
  }
  return items
}

function parseFileList(content: string) {
  const lines = content.split('\n').filter((l) => l.trim())
  const result: { type: 'dir' | 'file'; name: string; indent: number }[] = []
  for (const line of lines) {
    if (line.startsWith('[DIR] ')) {
      result.push({ type: 'dir', name: line.slice(6), indent: 0 })
    } else if (line.startsWith('[FILE] ')) {
      result.push({ type: 'file', name: line.slice(7), indent: 0 })
    }
  }
  return result.length > 0 ? result : null
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function parseTerminalResult(content: string): TerminalResultDisplay | null {
  try {
    const parsed = asRecord(JSON.parse(content))
    if (!parsed || !Array.isArray(parsed.results)) {
      return null
    }
    const segments = parsed.results
      .map((item) => {
        const result = asRecord(item)
        if (!result) return null
        const rawArgs = Array.isArray(result.args) ? result.args.map((arg) => String(arg)) : []
        const program = asString(result.program)
        return {
          index: asNumber(result.index) ?? 0,
          command: [program, ...rawArgs].filter(Boolean).join(' '),
          exitCode: asNumber(result.exit_code) ?? -1,
          timedOut: result.timed_out === true,
          stdout: asString(result.stdout),
          stderr: asString(result.stderr),
          truncated: result.truncated === true,
        }
      })
      .filter((item): item is TerminalSegmentResult => item !== null)
    return {
      ok: parsed.ok === true,
      shell: asString(parsed.shell) || '终端',
      cwd: asString(parsed.cwd) || '-',
      truncated: parsed.truncated === true,
      segments,
    }
  } catch {
    return null
  }
}

const toolEntries = computed(() => {
  /** The call id is the lifecycle identity: a result updates its preview in place. */
  const calls = new Map<string, ToolDisplayEntry>()
  ;(props.traces ?? []).forEach((trace, index) => {
    const event = asString(trace.event)
    const toolName = asString(trace.tool_name)
    if (!toolName || (event !== 'tool_call_start' && event !== 'tool_call_end')) return
    const key = asString(trace.tool_call_id) || `${toolName}-${index}`
    const displayName = asString(trace.display_name) || FALLBACK_DISPLAY[toolName] || toolName
    if (event === 'tool_call_start') {
      calls.set(key, {
        key,
        text: `正在${displayName}`,
        pending: true,
        rawContents: [],
        toolName,
        patch: asPatch(trace.patch),
      })
      return
    }
    const rawContent = asString(trace.raw_content)
    const entry: ToolEntry = {
      tool_name: toolName,
      display_name: displayName,
      args_summary: asString(trace.tool_args_summary),
      terminal_command: asString(trace.terminal_command),
      result_count: asNumber(trace.result_count),
      call_count: 1,
      filenames: [],
      labels: [],
      raw_contents: rawContent ? [rawContent] : [],
    }
    const filename = extractFilename(trace, toolName)
    const label = extractToolLabel(trace, toolName)
    if (filename) entry.filenames.push(filename)
    uniquePush(entry.labels, label)
    calls.set(key, {
      key,
      text: toolSummary(entry) || displayName,
      pending: false,
      rawContents: entry.raw_contents,
      toolName,
      patch: asPatch(trace.patch) ?? existingPatch(calls.get(key)),
    })
  })
  return Array.from(calls.values())
})

function asPatch(value: unknown): { path: string; before: string; after: string; complete: boolean } | undefined {
  const patch = asRecord(value)
  if (!patch) return undefined
  const before = asString(patch.before)
  const after = asString(patch.after)
  return before || after ? { path: asString(patch.path), before, after, complete: patch.complete === true } : undefined
}

function existingPatch(entry: ToolDisplayEntry | undefined) {
  return entry?.patch
}

/** Uses the finalized snapshot rather than transient tool arguments when available. */
function finalizedPatch(entry: ToolDisplayEntry) {
  const path = entry.patch?.path
  const file = props.changeSnapshot?.files.find((item) => item.path === path)
  const edit = file?.edits[file.edits.length - 1]
  return edit ? { path: edit.path, before: edit.before ?? '', after: edit.after, complete: true } : entry.patch
}
</script>

<template>
  <div class="tool-call-list">
    <div
      v-for="entry in toolEntries"
      :key="entry.key"
      class="action-row tool-call-box"
      :class="{ expandable: !entry.pending && entry.rawContents.length > 0 }"
    >
    <div class="tool-call-header">
      <button
        v-if="!entry.pending && entry.rawContents.length > 0"
        class="tool-leading-icon tool-expand-btn"
        type="button"
        :class="{ expanded: expanded.has(entry.key) }"
        :aria-label="expanded.has(entry.key) ? '收起结果' : '展开结果'"
        :aria-expanded="expanded.has(entry.key)"
        @click="toggleExpand(entry.key)"
      >
        <IcIcon class="tool-category-icon" :name="toolIconName(entry.toolName)" :data-tool-icon="toolIconName(entry.toolName)" :size="15" />
        <IcIcon class="tool-expand-chevron" name="chevron-down" :size="15" />
      </button>
      <span v-else class="tool-leading-icon tool-static-icon" aria-hidden="true">
        <IcIcon class="tool-category-icon" :name="toolIconName(entry.toolName)" :data-tool-icon="toolIconName(entry.toolName)" :size="15" />
      </span>
      <span
        class="tool-text"
        :class="{ pending: entry.pending, 'thinking-shimmer-text': entry.pending }"
      >{{ entry.text }}</span>
    </div>
    <div
      v-if="!entry.pending && entry.rawContents.length > 0"
      class="tool-result-collapse"
      :class="{ open: expanded.has(entry.key) }"
      :aria-hidden="!expanded.has(entry.key)"
      :inert="!expanded.has(entry.key)"
    >
      <div class="tool-result-collapse-inner">
      <div v-if="expanded.has(entry.key)" class="tool-result-content is-expandable">
        <div v-if="finalizedPatch(entry)" class="patch-preview" aria-label="局部代码修改">
          <span v-if="finalizedPatch(entry)?.path" class="patch-path">{{ finalizedPatch(entry)?.path }}</span>
          <ChangeDiff :before="finalizedPatch(entry)!.before" :after="finalizedPatch(entry)!.after" :show-line-numbers="finalizedPatch(entry)!.complete" />
        </div>
        <button
          v-if="copiedKey === entry.key"
          class="tool-copy-btn copied"
          type="button"
        >已复制</button>
        <button
          v-else
          class="tool-copy-btn"
          type="button"
          title="复制内容"
          @click="copyContent(entry.key, getCopyText(entry.rawContents))"
        >
          <IcIcon name="copy" :size="14" />
        </button>
        <template v-for="(rawContent, idx) in entry.rawContents" :key="idx">
          <!-- Search results: numbered items with source -->
          <div v-if="(entry.toolName === 'search_knowledge' || entry.toolName === 'get_knowledge_context') && parseSearchResults(rawContent)" class="search-results">
            <div v-for="item in parseSearchResults(rawContent)!" :key="item.index" class="search-result-item">
              <span class="search-result-citation">[{{ item.source }}]</span>
              <span class="search-result-source">{{ item.index }}.</span>
              <pre class="search-result-body">{{ item.content }}</pre>
            </div>
          </div>
          <!-- File list -->
          <div v-else-if="entry.toolName === 'list_knowledge_files' && parseFileList(rawContent)" class="file-tree">
            <div v-for="(item, fi) in parseFileList(rawContent)!" :key="fi" class="file-tree-row" :class="item.type">
              <span v-if="item.type === 'dir'" class="tree-icon tree-dir">▸</span>
              <span v-else class="tree-icon tree-file">·</span>
              <span class="tree-name">{{ item.name }}</span>
            </div>
          </div>
          <!-- File read: code block -->
          <div v-else-if="entry.toolName === 'read_knowledge_file'">
            <pre class="tool-result-code">{{ rawContent }}</pre>
          </div>
          <!-- Time and status tools: simple result -->
          <div v-else-if="entry.toolName === 'get_current_time' || entry.toolName === 'get_current_viewing_document' || entry.toolName === 'get_task_list_status'">
            <pre class="tool-result-text">{{ rawContent }}</pre>
          </div>
          <!-- File operations: write/delete/rename/create folder -->
          <div v-else-if="entry.toolName === 'write_knowledge_file' || entry.toolName === 'delete_knowledge_file' || entry.toolName === 'rename_knowledge_file' || entry.toolName === 'create_knowledge_folder'">
            <pre class="tool-result-text">{{ rawContent }}</pre>
          </div>
          <!-- Long-term memory -->
          <div v-else-if="entry.toolName === 'get_long_term_memory'">
            <pre class="tool-result-text">{{ rawContent }}</pre>
          </div>
          <!-- Terminal command result -->
          <div v-else-if="entry.toolName === 'run_terminal_command' && parseTerminalResult(rawContent)" class="terminal-result">
            <div class="terminal-summary">
              <span class="terminal-status" :class="{ ok: parseTerminalResult(rawContent)!.ok, failed: !parseTerminalResult(rawContent)!.ok }">
                {{ parseTerminalResult(rawContent)!.ok ? '执行成功' : '执行失败' }}
              </span>
              <span>终端: {{ parseTerminalResult(rawContent)!.shell }}</span>
              <span>工作目录: {{ parseTerminalResult(rawContent)!.cwd }}</span>
              <span v-if="parseTerminalResult(rawContent)!.truncated">输出已截断</span>
            </div>
            <div
              v-for="segment in parseTerminalResult(rawContent)!.segments"
              :key="segment.index"
              class="terminal-segment"
            >
              <div class="terminal-segment-head">
                <span>第 {{ segment.index }} 段</span>
                <code>{{ segment.command || '内部指令' }}</code>
                <span :class="{ 'exit-ok': segment.exitCode === 0, 'exit-failed': segment.exitCode !== 0 }">
                  退出码 {{ segment.exitCode }}
                </span>
                <span v-if="segment.timedOut">已超时</span>
                <span v-if="segment.truncated">本段输出已截断</span>
              </div>
              <div v-if="segment.stdout" class="terminal-stream">
                <div class="terminal-stream-label">标准输出</div>
                <pre>{{ segment.stdout }}</pre>
              </div>
              <div v-if="segment.stderr" class="terminal-stream error">
                <div class="terminal-stream-label">错误输出</div>
                <pre>{{ segment.stderr }}</pre>
              </div>
              <div v-if="!segment.stdout && !segment.stderr" class="terminal-empty">没有输出</div>
            </div>
          </div>
          <!-- Default: raw text -->
          <div v-else>
            <pre class="tool-result-text">{{ rawContent }}</pre>
          </div>
        </template>
      </div>
      </div>
    </div>
    </div>
  </div>
</template>

<style scoped>
.tool-call-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.tool-call-box {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
  margin-bottom: var(--space-4);
  border-radius: 8px;
  animation: tool-slide-in 220ms ease-out;
}

.action-row {
  align-self: stretch;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: none;
}

.tool-call-box.expandable {
  padding: 0;
}

.tool-call-header {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 32px;
}

.tool-leading-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

.tool-text {
  min-width: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  line-height: var(--line-height-normal);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-expand-btn {
  position: relative;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.tool-expand-btn:hover {
  color: var(--color-text-secondary);
  background: rgba(148, 163, 184, 0.12);
}

.tool-category-icon,
.tool-expand-chevron {
  transition:
    opacity 150ms ease,
    transform 180ms ease;
}

.tool-category-icon[data-tool-icon='build'] { color: var(--color-primary); }
.tool-category-icon[data-tool-icon='git'] { color: var(--color-git-modified); }
.tool-category-icon[data-tool-icon='auto-awesome'] { color: var(--color-accent); }
.tool-category-icon[data-tool-icon='psychology'] { color: color-mix(in srgb, var(--color-accent) 52%, var(--color-warning)); }
.tool-category-icon[data-tool-icon='manage-search'] { color: var(--color-sky); }
.tool-category-icon[data-tool-icon='document'] { color: var(--color-warning); }
.tool-category-icon[data-tool-icon='book'] { color: color-mix(in srgb, var(--color-warning) 58%, var(--color-danger)); }
.tool-category-icon[data-tool-icon='checklist'] { color: var(--color-success); }
.tool-category-icon[data-tool-icon='todo'] { color: var(--color-danger); }
.tool-category-icon[data-tool-icon='group'] { color: color-mix(in srgb, var(--color-primary) 54%, var(--color-accent)); }
.tool-category-icon[data-tool-icon='language'] { color: color-mix(in srgb, var(--color-success) 52%, var(--color-sky)); }

.tool-expand-chevron {
  position: absolute;
  opacity: 0;
  transform: rotate(-90deg);
}

.tool-expand-btn:hover .tool-category-icon,
.tool-expand-btn:focus-visible .tool-category-icon,
.tool-expand-btn.expanded .tool-category-icon {
  opacity: 0;
}

.tool-expand-btn:hover .tool-expand-chevron,
.tool-expand-btn:focus-visible .tool-expand-chevron,
.tool-expand-btn.expanded .tool-expand-chevron {
  opacity: 1;
}

.tool-expand-btn.expanded .tool-expand-chevron {
  transform: rotate(0deg);
}

.tool-result-collapse {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 200ms cubic-bezier(0.23, 1, 0.32, 1);
}

.tool-result-collapse.open {
  grid-template-rows: 1fr;
}

.tool-result-collapse-inner {
  min-height: 0;
  overflow: hidden;
}

.tool-result-content {
  margin-top: var(--space-4);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 8px;
  background: transparent;
  opacity: 0;
  transform: translateY(-6px);
  transition:
    opacity 200ms cubic-bezier(0.23, 1, 0.32, 1),
    transform 200ms cubic-bezier(0.23, 1, 0.32, 1);
}

.tool-result-collapse.open .tool-result-content {
  opacity: 1;
  transform: translateY(0);
}

.tool-result-text {
  margin: 0;
  padding: var(--space-8) var(--space-12);
  color: var(--color-text-muted);
  font-family: var(--font-text);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 600px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.tool-result-text + .tool-result-text {
  border-top: 1px dashed rgba(148, 163, 184, 0.08);
}

.patch-preview { padding: var(--space-8) var(--space-12); border-bottom: 1px solid rgba(148, 163, 184, 0.1); }
.patch-path { display: block; margin-bottom: var(--space-6); color: var(--color-text-muted); font-family: var(--font-code); font-size: calc(10px * var(--font-scale)); }

/* Code block for file content */
.tool-result-code {
  margin: 0;
  padding: var(--space-10) var(--space-12);
  background: rgba(0, 0, 0, 0.12);
  color: var(--color-text-secondary);
  font-family: var(--font-text);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
  max-height: 600px;
  scrollbar-width: thin;
}

/* Search results list */
.search-results {
  display: flex;
  flex-direction: column;
  padding: var(--space-6) 0;
}

.search-result-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-4) var(--space-8);
  padding: var(--space-6) var(--space-12);
  border-bottom: 1px solid rgba(148, 163, 184, 0.06);
}

.search-result-item:last-child {
  border-bottom: 0;
}

.search-result-citation {
  grid-column: 1;
  grid-row: 1;
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 var(--space-4);
  border-radius: 3px;
  background: rgba(66, 36, 235, 0.12);
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(9px * var(--font-scale));
  font-weight: 600;
}

.search-result-source {
  grid-column: 2;
  grid-row: 1;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
  align-self: center;
}

.search-result-body {
  grid-column: 2;
  grid-row: 2;
  margin: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-text);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* File tree */
.file-tree {
  display: flex;
  flex-direction: column;
  padding: var(--space-6) 0;
}

.file-tree-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-3) var(--space-12);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.5;
}

.tree-icon {
  flex-shrink: 0;
  width: 10px;
  text-align: center;
}

.tree-dir {
  color: var(--color-primary);
}

.tree-file {
  color: var(--color-text-muted);
}

.tree-name {
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-tree-row.dir .tree-name {
  color: var(--color-primary);
  font-weight: 600;
}

.terminal-result {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  padding: var(--space-10) var(--space-12);
}

.terminal-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.5;
}

.terminal-status,
.terminal-segment-head span {
  color: var(--color-text-secondary);
}

.terminal-status.ok,
.exit-ok {
  color: var(--color-success);
}

.terminal-status.failed,
.exit-failed {
  color: var(--color-error);
}

.terminal-segment {
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 4px;
  overflow: hidden;
}

.terminal-segment-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-8);
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  background: rgba(148, 163, 184, 0.05);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
}

.terminal-segment-head code {
  max-width: 100%;
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
  font-size: calc(11px * var(--font-scale));
  white-space: pre-wrap;
  word-break: break-word;
}

.terminal-stream {
  padding: var(--space-8);
}

.terminal-stream + .terminal-stream {
  border-top: 1px dashed rgba(148, 163, 184, 0.08);
}

.terminal-stream-label {
  margin-bottom: var(--space-4);
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
}

.terminal-stream pre {
  margin: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-text);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow: auto;
  scrollbar-width: thin;
}

.terminal-stream.error pre {
  color: var(--color-error);
}

.terminal-empty {
  padding: var(--space-8);
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
}


.tool-copy-btn {
  position: absolute;
  top: var(--space-4);
  right: var(--space-4);
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  opacity: 0;
  transition:
    opacity var(--transition-fast),
    color var(--transition-fast);
}

.tool-result-content.is-expandable {
  position: relative;
}

.tool-result-content.is-expandable:hover .tool-copy-btn {
  opacity: 1;
}

.tool-copy-btn:hover {
  color: var(--color-text-secondary);
}

.tool-copy-btn.copied {
  width: auto;
  padding: 0 var(--space-8);
  opacity: 1;
  color: var(--color-success);
  border: none;
  background: transparent;
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  cursor: default;
}

@keyframes tool-slide-in {
  0% {
    opacity: 0;
    transform: translateY(-10px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tool-result-content {
    transform: none;
    transition: opacity 200ms cubic-bezier(0.23, 1, 0.32, 1);
  }
}

</style>
