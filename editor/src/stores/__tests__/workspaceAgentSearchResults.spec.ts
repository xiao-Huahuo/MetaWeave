/** Agent-mounted search-result navigation tests. */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { updateSettingsKnowledgeDir } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import type { SearchSource, UnifiedSearchResult } from '@/types/unifiedSearch'

vi.mock('@/api/settings', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/settings')>(),
  updateSettingsKnowledgeDir: vi.fn(),
}))
vi.mock('@/api/knowledge', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/knowledge')>(),
  listKnowledgeFiles: vi.fn().mockResolvedValue({ tree: [] }),
}))

function result(source: SearchSource, item: Record<string, unknown> = {}): UnifiedSearchResult {
  return {
    id: `${source}-1`, source, title: source, snippet: '', locator: `${source}/1`, updated_at: '',
    score: 1, matched_modes: ['title'], item,
  }
}

describe('workspace Agent search-result navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(updateSettingsKnowledgeDir).mockReset()
  })

  it('opens blocks from the Agent page in the shared search-result sidebar', async () => {
    const store = useWorkspaceStore()
    const target = result('library')

    await store.openAgentSearchResult(target, false)

    expect(store.editorSidebarOpen).toBe(true)
    expect(store.searchSidebarResult).toEqual(target)
  })

  it('routes sidebar-Agent blocks into each owning main library and exact item', async () => {
    const store = useWorkspaceStore()
    const library = result('library', { item_id: 'book-1', parent_id: 'collection-1' })
    await store.openAgentSearchResult(library, true)
    expect(store.mainView).toBe('library')
    expect(store.pendingMainSearchResult).toEqual(library)

    const component = result('components', { component_id: 'cards/a.vue' })
    await store.openAgentSearchResult(component, true)
    expect(store.mainView).toBe('component-library')
    expect(store.pendingMainSearchResult).toEqual(component)

    await store.openAgentSearchResult(result('literature', { form_id: 'form-1', row_id: 'row-1' }), true)
    expect(store.mainView).toBe('literature-reading')
    expect(store.pendingLiteratureEntry).toEqual({ formId: 'form-1', rowId: 'row-1' })

    await store.openAgentSearchResult(result('files', { name: 'a.md', path: 'docs/a.md', isDir: false }), true)
    expect(store.mainView).toBe('editor')
    expect(store.selectedPath).toBe('docs/a.md')
  })

  it.each([false, true])('activates the owned original library before opening a historical block: compact=%s', async (compact) => {
    const settings = useSettingsStore()
    settings.updateProfile({ userId: 'u1', activeLibraryId: 'current', knowledgeDir: 'D:/current', knowledgeWatchEnabled: false, knowledgeLibraries: [
      { libraryId: 'origin', name: '原库', knowledgeDir: 'D:/original', libraryStorageDir: '.mw/library', isActive: false },
    ] })
    vi.mocked(updateSettingsKnowledgeDir).mockResolvedValue({
      user_id: 'u1', knowledge_dir: 'D:/original', active_library_id: 'origin', created_at: '', updated_at: '',
    })
    const store = useWorkspaceStore()
    store.openTabs = [{ path: 'shared.md', title: '旧库文件', dirty: false }]
    store.selectedPath = 'shared.md'
    store.updateActiveContent('当前库缓存')
    store.openTabs[0]!.dirty = false
    expect(store.activeContent).toBe('当前库缓存')
    const target = { ...result('components', { component_id: 'cards/shared.vue' }), library_id: 'origin' }
    await store.openAgentSearchResult(target, compact)
    expect(updateSettingsKnowledgeDir).toHaveBeenCalledWith('u1', 'D:/original')
    expect(settings.profile.activeLibraryId).toBe('origin')
    expect(store.openTabs).toEqual([])
    store.selectedPath = 'shared.md'
    expect(store.activeContent).toBe('')
    expect(compact ? store.pendingMainSearchResult : store.searchSidebarResult).toEqual(target)
  })

  it('does not open a deleted or foreign original library in the current library', async () => {
    const settings = useSettingsStore()
    settings.updateProfile({ userId: 'u1', activeLibraryId: 'current', knowledgeLibraries: [] })
    const store = useWorkspaceStore()
    await store.openAgentSearchResult({ ...result('components'), library_id: 'foreign' }, true)
    expect(updateSettingsKnowledgeDir).not.toHaveBeenCalled()
    expect(store.pendingMainSearchResult).toBeNull()
    expect(store.toastMessage).toContain('知识库')
  })

  it('uses the same library scope when a historical K citation opens the sidebar', async () => {
    const settings = useSettingsStore()
    settings.updateProfile({ userId: 'u1', activeLibraryId: 'current', knowledgeLibraries: [
      { libraryId: 'origin', name: '原库', knowledgeDir: 'D:/original', libraryStorageDir: '.mw/library', isActive: false },
    ] })
    vi.mocked(updateSettingsKnowledgeDir).mockRejectedValue(new Error('切库连接失败'))
    const store = useWorkspaceStore()
    await store.openSearchResultSidebar({ ...result('library'), library_id: 'origin' })
    expect(store.searchSidebarResult).toBeNull()
    expect(store.toastMessage).toBe('切库连接失败')
    await store.openAgentSearchResult(result('components'), true)
    expect(store.pendingMainSearchResult?.source).toBe('components')
  })

  it('retains unsaved current-library tabs when a historical block requests another library', async () => {
    const settings = useSettingsStore()
    settings.updateProfile({ userId: 'u1', activeLibraryId: 'current', knowledgeLibraries: [
      { libraryId: 'origin', name: '原库', knowledgeDir: 'D:/original', libraryStorageDir: '.mw/library', isActive: false },
    ] })
    const store = useWorkspaceStore()
    store.openTabs = [{ path: 'shared.md', title: '未保存', dirty: true }]
    await store.openAgentSearchResult({ ...result('components'), library_id: 'origin' }, true)
    expect(updateSettingsKnowledgeDir).not.toHaveBeenCalled()
    expect(store.openTabs[0]?.dirty).toBe(true)
    expect(store.pendingMainSearchResult).toBeNull()
    expect(store.toastMessage).toContain('保存')
  })

  it('rejects concurrent navigation until the owned-library switch finishes and then releases the guard', async () => {
    const settings = useSettingsStore()
    settings.updateProfile({ userId: 'u1', activeLibraryId: 'current', knowledgeWatchEnabled: false, knowledgeLibraries: [
      { libraryId: 'origin', name: '原库', knowledgeDir: 'D:/original', libraryStorageDir: '.mw/library', isActive: false },
    ] })
    let finish!: (profile: Awaited<ReturnType<typeof updateSettingsKnowledgeDir>>) => void
    vi.mocked(updateSettingsKnowledgeDir).mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const store = useWorkspaceStore()
    const original = { ...result('components'), library_id: 'origin' }
    const opening = store.openAgentSearchResult(original, true)
    // Even a click into the currently active library cannot overtake the pending profile write.
    await store.openAgentSearchResult({ ...result('library'), library_id: 'current' }, true)
    await store.openSearchResultSidebar(original)
    expect(updateSettingsKnowledgeDir).toHaveBeenCalledTimes(1)
    expect(store.pendingMainSearchResult).toBeNull()
    expect(store.searchSidebarResult).toBeNull()
    finish({ user_id: 'u1', knowledge_dir: 'D:/original', active_library_id: 'origin', created_at: '', updated_at: '' })
    await opening
    expect(store.pendingMainSearchResult).toEqual(original)
    await store.openSearchResultSidebar(original)
    expect(store.searchSidebarResult).toEqual(original)
    expect(updateSettingsKnowledgeDir).toHaveBeenCalledTimes(1)
  })
})
