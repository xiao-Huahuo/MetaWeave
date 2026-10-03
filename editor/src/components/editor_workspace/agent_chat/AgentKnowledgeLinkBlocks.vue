<!--
  Mount only explicitly linked non-file knowledge at its Markdown position.
  Usage: MarkdownContent supplies its sanitized final DOM. Native search cards
  are teleported into those links; file blocks keep their original renderer.
-->
<script setup lang="ts">
import { nextTick, shallowRef, watch } from 'vue'
import { knowledgeLinkTarget, resolveKnowledgeLink } from '@/api/knowledgeLinks'
import SearchNativeResultCard from '@/components/search_page/SearchNativeResultCard.vue'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { UnifiedSearchResult } from '@/types/unifiedSearch'

const props = defineProps<{
  /** Sanitized Markdown DOM that owns the explicit link anchors. */
  root: HTMLElement | null
  /** Re-scan when the final answer changes, and discard obsolete asynchronous results. */
  content: string
}>()
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const blocks = shallowRef<Array<{ target: HTMLElement; result: UnifiedSearchResult }>>([])

/** Follow the same page/sidebar navigation as existing Agent file blocks. */
function openResult(result: UnifiedSearchResult): void {
  void workspaceStore.openAgentSearchResult(result, workspaceStore.mainView !== 'agent')
}

watch(() => [props.root, props.content, settingsStore.profile.userId] as const, async ([root, , userId], _, onCleanup) => {
  let cancelled = false
  const replacements: Array<{ target: HTMLElement; original: HTMLElement }> = []
  onCleanup(() => {
    cancelled = true
    for (const { target, original } of replacements) {
      if (root?.contains(target)) target.replaceWith(original)
    }
  })
  blocks.value = []
  await nextTick()
  if (cancelled || !root || !userId) return
  // Resolve duplicates once per answer; every explicit link retains its own position.
  const requests = new Map<string, Promise<UnifiedSearchResult>>()
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>('a[href]')) {
    const href = anchor.getAttribute('href') ?? ''
    const link = knowledgeLinkTarget(href)
    if (!link) continue
    anchor.setAttribute('aria-busy', 'true')
    let request = requests.get(href)
    if (!request) {
      request = resolveKnowledgeLink(userId, link)
      requests.set(href, request)
    }
    void request.then((result) => {
      if (cancelled || !root.contains(anchor)) return
      const target = document.createElement('div')
      target.className = 'agent-knowledge-block'
      target.dataset.source = result.source
      const paragraph = anchor.parentElement
      const standalone = paragraph?.tagName === 'P' && paragraph.querySelectorAll('a').length === 1
        && (paragraph.textContent?.replace(anchor.textContent ?? '', '').trim() ?? '') === ''
      const original = standalone ? paragraph : anchor
      replacements.push({ target, original })
      original.replaceWith(target)
      blocks.value = [...blocks.value, { target, result }]
    }).catch(() => {
      if (cancelled || !root.contains(anchor)) return
      anchor.removeAttribute('aria-busy')
      anchor.title = '知识已删除或无法访问'
      anchor.dataset.knowledgeError = 'true'
    })
  }
}, { immediate: true, flush: 'post' })
</script>

<template>
  <Teleport v-for="(block, index) in blocks" :key="index" :to="block.target">
    <SearchNativeResultCard :result="block.result" @activate="openResult" @open="openResult" />
  </Teleport>
</template>

<style>
/* Use native card styles and contain their existing widths in narrow Agent panels. */
.agent-knowledge-block {
  width: min(100%, 360px);
  max-width: 100%;
  min-width: 0;
  margin-bottom: var(--space-12);
  font-family: var(--font-ui);
  line-height: normal;
  word-break: normal;
}
.agent-knowledge-block[data-source="library"] { width: min(100%, 220px); }
.agent-knowledge-block > * { max-width: 100%; }
</style>
