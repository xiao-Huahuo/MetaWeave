/**
 * Resolve explicitly linked knowledge objects to their native four-library DTO.
 * The signed-in profile supplies user scope; the link preserves its owning library.
 */
import { apiGet, buildApiUrl } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'
import { SEARCH_SOURCES } from '@/types/unifiedSearch'
import type { SearchSource, UnifiedSearchResult } from '@/types/unifiedSearch'

export interface KnowledgeLinkTarget {
  /** Source shape chosen by get_knowledge_url. File links keep their existing renderer. */
  source: Exclude<SearchSource, 'files'>
  /** Stable resource ID, including the form:row ID for literature. */
  id: string
  /** Owning library remains stable when the active library changes. */
  libraryId: string
}

/** Recognize only this application's non-file knowledge links, never external lookalikes. */
export function knowledgeLinkTarget(href: string): KnowledgeLinkTarget | null {
  try {
    const endpoint = new URL(buildApiUrl(API_ROUTES.KNOWLEDGE_RESOLVE), window.location.href)
    const url = new URL(href, endpoint)
    const source = url.searchParams.get('source')
    const id = url.searchParams.get('id') ?? ''
    if (url.origin !== endpoint.origin || url.pathname !== endpoint.pathname
      || !source || source === 'files' || !SEARCH_SOURCES.some((item) => item === source) || !id) return null
    return { source: source as KnowledgeLinkTarget['source'], id, libraryId: url.searchParams.get('library_id') ?? '' }
  } catch {
    return null
  }
}

/** Fetch the formal native DTO without trusting user_id or card data in assistant text. */
export function resolveKnowledgeLink(userId: string, target: KnowledgeLinkTarget): Promise<UnifiedSearchResult> {
  return apiGet<UnifiedSearchResult>(API_ROUTES.KNOWLEDGE_RESOLVE, {
    user_id: userId,
    source: target.source,
    id: target.id,
    library_id: target.libraryId || undefined,
  })
}
