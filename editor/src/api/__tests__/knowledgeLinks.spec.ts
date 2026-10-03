/** Verify encoded knowledge links use the current user and the object's original library. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { knowledgeLinkTarget, resolveKnowledgeLink } from '@/api/knowledgeLinks'

describe('knowledge link client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('preserves the full resource identity while ignoring assistant-supplied user scope', async () => {
    const target = knowledgeLinkTarget('/knowledge/resolve?user_id=wrong&source=literature&id=form%3A%E8%A1%8C%26%231&library_id=old%2Flibrary')
    expect(target).toEqual({ source: 'literature', id: 'form:行&#1', libraryId: 'old/library' })
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await resolveKnowledgeLink('current/user', target!)
    expect(fetchMock).toHaveBeenCalledWith(
      '/knowledge/resolve?user_id=current%2Fuser&source=literature&id=form%3A%E8%A1%8C%26%231&library_id=old%2Flibrary',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it.each([
    '/knowledge/files/raw?path=a.md',
    '/knowledge/resolve?source=files&id=a.md',
    '/knowledge/resolve?source=unknown&id=x',
    '/knowledge/resolve?source=library',
    'https://other.example/knowledge/resolve?source=library&id=x',
    'javascript:alert(1)',
  ])('leaves other links alone: %s', (href) => {
    expect(knowledgeLinkTarget(href)).toBeNull()
  })

  it.each(['http:', 'file:'])('resolves relative tool URLs in the desktop %s renderer', (protocol) => {
    vi.stubGlobal('window', {
      agentEditorDesktop: { isDesktop: true },
      location: { protocol, origin: protocol === 'file:' ? 'null' : 'http://localhost:5173', href: protocol === 'file:' ? 'file:///D:/MetaWeave/index.html' : 'http://localhost:5173/' },
    })
    expect(knowledgeLinkTarget('/knowledge/resolve?source=components&id=Panel.vue')).toEqual({ source: 'components', id: 'Panel.vue', libraryId: '' })
    expect(knowledgeLinkTarget('https://external.example/knowledge/resolve?source=components&id=Panel.vue')).toBeNull()
  })
})
