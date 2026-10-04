/** Account changes clear private renderer state and invalidate old tree/content/search callbacks. */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { setApiSessionToken } from '@/api/client'

const { listKnowledgeFiles, readKnowledgeFile, searchAllLibraries } = vi.hoisted(() => ({
  listKnowledgeFiles: vi.fn(), readKnowledgeFile: vi.fn(), searchAllLibraries: vi.fn(),
}))
vi.mock('@/api/knowledge', async (original) => ({ ...await original<typeof import('@/api/knowledge')>(), listKnowledgeFiles, readKnowledgeFile }))
vi.mock('@/api/unifiedSearch', () => ({ searchAllLibraries }))
vi.mock('@/api/agent', () => ({ updateCurrentDocumentContext: vi.fn().mockResolvedValue(undefined) }))

beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks(); vi.useFakeTimers(); setActivePinia(createPinia())
  useSettingsStore().setUserId('82631459'); setApiSessionToken('first-session')
})
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); setApiSessionToken(''); vi.unstubAllGlobals() })

describe('workspace account isolation', () => {
  it('discards old unscoped private browser histories on the first authenticated workspace mount', () => {
    localStorage.setItem('metweave_search_history', JSON.stringify(['旧账号私有问题']))
    const store = useWorkspaceStore()
    expect(store.searchHistory).toEqual([])
    expect(localStorage.getItem('metweave_search_history')).toBeNull()
  })
  it('clears documents, messages, search, visualization and event ownership immediately on logout', () => {
    const store = useWorkspaceStore()
    const close = vi.fn()
    vi.stubGlobal('EventSource', class { close = close; addEventListener() {} })
    store.startFileWatcher()
    store.tree = [{ path: 'private.md', name: 'private.md', isDir: false }]
    store.openTabs = [{ path: 'private.md', title: 'private.md', dirty: false }]
    store.selectedPath = 'private.md'
    store.chatMessages = [{ id: 'private-chat', role: 'assistant', content: '账号私有内容' }]
    store.pendingAgentPrompt = '私有问题'
    store.searchQuery = '私有搜索'
    store.showMarkdownHtmlVisualization({ url: '/visualizations/private.html', path: 'private.html', title: '私有文档', filename: 'private.html', source_path: 'private.md' })
    useSettingsStore().clearUserId()
    expect(close).toHaveBeenCalledOnce()
    expect(store.tree).toEqual([])
    expect(store.openTabs).toEqual([])
    expect(store.selectedPath).toBe('')
    expect(store.chatMessages).toEqual([])
    expect(store.pendingAgentPrompt).toBe('')
    expect(store.searchQuery).toBe('')
    expect(store.markdownHtmlVisualization).toBeNull()
  })
  it('ignores an old account tree response after switching to another account', async () => {
    let finish!: (result: unknown) => void
    listKnowledgeFiles.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const store = useWorkspaceStore()
    const pending = store.loadKnowledgeTree()
    useSettingsStore().setUserId('39578612'); setApiSessionToken('second-session')
    finish({ tree: [{ path: 'private.md', name: 'private.md', isDir: false }] })
    await pending
    expect(store.tree).toEqual([])
    expect(store.treeLoading).toBe(false)
  })
  it('ignores old text content even when the next account selects the same path', async () => {
    let finish!: (result: unknown) => void
    readKnowledgeFile.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const store = useWorkspaceStore()
    store.selectedPath = 'same.md'
    const pending = store.selectFile({ name: 'same.md', path: 'same.md', isDir: false })
    useSettingsStore().setUserId('39578612'); setApiSessionToken('second-session')
    store.selectedPath = 'same.md'
    finish({ content: '旧账号秘密', mtime: '' })
    await pending
    expect(store.activeContent).toBe('')
  })
})
