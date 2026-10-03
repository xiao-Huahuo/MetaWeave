/**
 * Four-library unified search domain types.
 *
 * Usage:
 * Shared by the API client, workspace store, unified result rows, and split
 * native-card presentation.
 */

export const SEARCH_SOURCES = ['files', 'library', 'components', 'literature'] as const

export type SearchSource = (typeof SEARCH_SOURCES)[number]
export type SearchMatchMode = 'title' | 'fulltext' | 'semantic'

export interface UnifiedSearchResult {
  /** Owning library anchors persisted links when the user's active library changes. */
  library_id?: string
  /** Stable identifier inside its source library. */
  id: string
  /** Library that owns this result. */
  source: SearchSource
  /** Display title shared by both presentation modes. */
  title: string
  /** Best lexical or semantic evidence snippet. */
  snippet: string
  /** Path, URL, or owning form location. */
  locator: string
  /** Source modification timestamp when available. */
  updated_at: string
  /** Backend relevance score after all enabled paths are merged. */
  score: number
  /** Enabled search paths that matched this same resource. */
  matched_modes: SearchMatchMode[]
  /** Original source DTO used by the split native card. */
  item: Record<string, unknown>
}

export interface UnifiedSearchResponse {
  /** Normalized query echoed by the backend. */
  query: string
  /** Sources actually searched by the backend. */
  selected_sources: SearchSource[]
  /** Whether partial full-content matching ran. */
  fulltext: boolean
  /** Whether vector retrieval and reranking ran. */
  semantic: boolean
  /** All source results in one backend-ranked sequence. */
  results: UnifiedSearchResult[]
  /** Same result objects grouped for split presentation. */
  groups: Record<SearchSource, UnifiedSearchResult[]>
  /** Real result count for every source. */
  counts: Record<SearchSource, number>
  /** Total count across selected sources. */
  total: number
}
