/*
 * Shared knowledge editor domain types.
 *
 * Usage:
 * Keep file tree, editor, indexing, command, and chat DTOs here so Vue
 * components can stay focused on rendering and interaction.
 */

/** Index lifecycle shown in the file tree and top status bar. */
export type IndexStatus = 'clean' | 'dirty' | 'indexing' | 'indexed' | 'failed' | 'ignored'

/** Graph lifecycle shown next to index status in file browsers. */
export type GraphStatus = 'graphed' | 'dirty' | 'ignored'

/** Editor display mode controlled by the central toolbar. */
export type EditorViewMode = 'edit' | 'preview' | 'split'

/** File-modality-aware modes used by the main editor workspace. */
export type EditorWorkspaceMode = EditorViewMode | 'text' | 'forms' | 'markdown' | 'code' | 'binary'

/** Agent document visualization mode selected from the editor toolbar. */
export type MarkdownHtmlVisualizationMode = 'structure' | 'insight'

/** User-friendly design preset forwarded to the Agent visualization prompt. */
export type MarkdownHtmlVisualizationPreset = 'balanced' | 'reader' | 'dashboard' | 'magazine'

/** Presentation switches forwarded to the Agent visualization prompt. */
export interface MarkdownHtmlVisualizationOptions {
  strongMotion: boolean
  shadow: boolean
  rounded: boolean
  emoji: boolean
  visualHierarchy: boolean
  gridLayout: boolean
  callouts: boolean
  denseLayout: boolean
  typographyScale: boolean
  contrast: boolean
  accentColor: boolean
  microInteractions: boolean
  scrollReveal: boolean
}

/** Runtime HTML visualization payload emitted by the Agent tool stream. */
export interface MarkdownHtmlVisualizationPayload {
  title: string
  filename: string
  path: string
  url: string
  source_path?: string
  created_at?: string
}

/** File viewer selected by extension and backend preview metadata. */
export type FileViewerKind = 'markdown' | 'code' | 'image' | 'video' | 'pdf' | 'table' | 'document' | 'presentation' | 'text' | 'unsupported'

/** Main center workspace surface controlled by activity bar and commands. */
export type WorkspaceMainView =
  | 'home'
  | 'editor'
  | 'resources'
  | 'favorites'
  | 'privacy'
  | 'library'
  | 'component-library'
  | 'vault'
  | 'forms'
  | 'literature-reading'
  | 'ingestion'
  | 'scanner'
  | 'batch-scanner'
  | 'visualization'
  | 'graph'
  | 'dashboard'
  | 'debug'
  | 'search'
  | 'browser'
  | 'skills'
  | 'settings'
  | 'agent'
  | 'agent-queue'

/** One file or directory in the knowledge tree. */
export interface KnowledgeFileNode {
  /** Display name shown in the recursive tree. */
  name: string
  /** Path relative to the configured knowledge root. */
  path: string
  /** Whether this node is a directory. */
  isDir: boolean
  /** Optional child nodes, loaded eagerly in the mock front-end. */
  children?: KnowledgeFileNode[]
  /** File size in bytes, if known. */
  size?: number
  /** Last modified timestamp in display-ready form. */
  mtime?: string
  /** File creation timestamp in display-ready form. */
  createdAt?: string
  /** Last successful ingestion timestamp in display-ready form. */
  ingestedAt?: string
  /** Current indexing state for this file or directory. */
  indexStatus?: IndexStatus
  /** Current semantic graph state for this file or directory. */
  graphStatus?: GraphStatus
}

export interface KnowledgeTrashEntry {
  trash_id: string
  user_id: string
  library_id: string
  original_relative_path: string
  name: string
  stored_name: string
  is_dir: boolean
  size: number
  deleted_at: string
  expires_at: string
  chunks_deleted?: number
}

/** Result of restoring source content and rebuilding all managed derivatives. */
export interface KnowledgeTrashRestoreResult {
  ok: boolean
  restored_path: string
  node: KnowledgeFileNode
  artifacts_restored: boolean
  files_reingested: number
  graphs_restored: number
}

export interface LibraryAsset {
  asset_id: string
  mime_type: string
  file_name: string
  url: string
  width: number
  height: number
  size: number
  created_at: string
}

export interface LibraryTag {
  tag_id: string
  name: string
}

export interface LibraryBreadcrumb {
  item_id: string
  title: string
}

export interface LibraryItem {
  item_id: string
  user_id: string
  library_id: string
  parent_id: string
  item_type: 'book' | 'collection'
  content_type: 'knowledge_file' | 'web_url' | 'external_file' | 'collection'
  title: string
  display_title: string
  description: string
  storage_path: string
  source_path: string
  source_url: string
  source_name: string
  source_mime: string
  source_size: number
  source_mtime: string
  source_exists: boolean
  cover_mode: 'icon' | 'image' | 'description' | 'source_image' | 'title'
  cover_asset_id: string
  cover_asset: LibraryAsset | null
  sort_order: number
  index_status: IndexStatus | 'missing' | ''
  graph_status: GraphStatus | ''
  tags: string[]
  child_count: number
  created_at: string
  updated_at: string
}

export interface LibraryItemsResponse {
  items: LibraryItem[]
  parent: LibraryItem | null
  breadcrumbs: LibraryBreadcrumb[]
}

export type IngestionQueueStatus = 'waiting' | 'queued' | 'running' | 'cancelling'

export type IngestionHistoryStatus = 'finished' | 'failed' | 'skipped' | 'cancelled'

export interface IngestionQueueItem {
  id: string
  jobId?: string
  name: string
  path: string
  isDir: boolean
  size?: number
  mtime?: string
  status: IngestionQueueStatus
  progress: number
  pipeline?: string
  stage?: string
  stageLabel?: string
  stageCurrent?: number
  stageTotal?: number
  queuedAt: string
  chunksCreated?: number
  message?: string
}

export type HistorySourceType = 'ingestion' | 'graph'

export interface IngestionHistoryItem {
  id: string
  name: string
  path: string
  isDir: boolean
  size?: number
  mtime?: string
  status: IngestionHistoryStatus
  finishedAt: string
  filesSeen?: number
  filesIngested?: number
  filesSkipped?: number
  chunksCreated?: number
  message?: string
  sourceType?: HistorySourceType
}

/** Runtime events expected from the future watchdog/SSE endpoint. */
export type KnowledgeEvent =
  | { type: 'tree_dirty'; path: string }
  | { type: 'file_changed'; path: string; isDir: boolean }
  | { type: 'file_deleted'; path: string }
  | { type: 'index_status'; path: string; status: IndexStatus }

/** Open editor tab state. */
export interface EditorTab {
  /** File path relative to the knowledge root. */
  path: string
  /** File label used in the tab strip. */
  title: string
  /** Whether local editor content differs from saved content. */
  dirty: boolean
  /** Last known mtime from disk, used to detect external changes. */
  mtime?: string
}

/** One sheet used by CSV/XLSX previews. */
export interface TablePreviewSheet {
  /** Human-readable sheet name. */
  name: string
  /** Rectangular-ish table rows loaded from the backend. */
  rows: string[][]
}

/** One lazily rendered PDF page used by the continuous Preview1 viewer. */
export interface PdfPreviewPage {
  /** Original PDF page width in points. */
  width: number
  /** Original PDF page height in points. */
  height: number
  /** Backend URL that rasterizes and caches this page only when requested. */
  url: string
}

/** Backend-generated multimodal preview payload. */
export interface FilePreviewPayload {
  /** File path relative to knowledge root. */
  path: string
  /** Viewer kind selected by backend. */
  kind: FileViewerKind
  /** Optional UTF-8 text content for generic text previews. */
  content?: string
  /** Optional Markdown used by PDF render mode, separate from ingested text. */
  render_content?: string
  /** Canonical read-only Markdown projection shared by every ingested modality. */
  semantic_markdown?: string
  /** Projection schema and fingerprint used to explain index freshness. */
  schema_version?: number
  projection_hash?: string
  /** Whether frontmatter-backed text content is ready for edit/split. */
  text_status?: 'ready' | 'empty' | 'not_ingested' | string
  /** Optional sanitized-at-render HTML for DOCX previews. */
  html?: string
  /** Optional data URL for image/PDF embeds. */
  data_url?: string
  /** Optional backend raw file URL for image, video, iframe, or object previews. */
  raw_url?: string
  /** Optional rasterized first-page image for PDF cards and compact previews. */
  thumbnail_url?: string
  /** Optional MIME type for binary embeds. */
  mime_type?: string
  /** Actual video container selected by backend header detection. */
  video_container?: 'native' | 'mpegts'
  /** Optional table sheets for CSV/XLSX previews. */
  sheets?: TablePreviewSheet[]
  /** Optional unsupported-file message. */
  message?: string
  /** Whether a PDF appears to have no extractable text layer. */
  pdf_scanned?: boolean
  /** Optional PDF page count from the backend parser. */
  page_count?: number
  /** PDF pages and lazy raster URLs used by the continuous Preview1 viewer. */
  pdf_pages?: PdfPreviewPage[]
  /** Optional count of images detected in a PDF or document. */
  image_count?: number
  /** Optional count of tables detected in a PDF or document. */
  table_count?: number
  /** Optional OCR lifecycle for image previews. */
  ocr_status?: 'disabled' | 'completed' | 'no_text' | 'pending' | string
  /** Optional count of OCR words accepted by the backend. */
  ocr_word_count?: number
  /** Optional average OCR confidence for accepted words. */
  ocr_average_confidence?: number
  /** Whether OCR engine was available when preview was generated. */
  ocr_engine_available?: boolean
  /** Last modified timestamp from disk. */
  mtime: string
  /** File size in bytes. */
  size: number
  /** File extension including dot. */
  extension: string
  /** Whether this viewer should be treated as read-only. */
  readonly: boolean
}

/** Minimal chat message used by the right-side Agent panel. */
export interface ChatMessage {
  /** Stable id for Vue list rendering. */
  id: string
  /** Message author role. */
  role: 'user' | 'assistant' | 'system'
  /** Message body. */
  content: string
  /** Optional source path associated with the message. */
  sourcePath?: string
  /** Optional reference text quoted by the user. */
  reference?: string
}

/** Command palette action model. */
export interface CommandAction {
  /** Stable command id. */
  id: string
  /** Human-readable label. */
  label: string
  /** Keyboard shortcut hint. */
  shortcut?: string
  /** Short description shown below the label. */
  description: string
}

export interface FilenameResult {
  path: string
  name: string
}

export interface FulltextResult {
  source_uri: string
  snippet: string
}

export interface SearchResults {
  filename_results: FilenameResult[]
  fulltext_results: FulltextResult[]
  semantic_results: Record<string, unknown>[]
}

export interface KnowledgeSemanticGraphNode {
  id: string
  label: string
  kind: 'document' | 'entity' | string
  entity_type?: string
  document_id?: string
  source_uri?: string
  source_range?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface KnowledgeSemanticGraphLink {
  id: string
  source: string
  target: string
  kind: string
  weight?: number
  evidence?: string
  source_document_id?: string
  source_section_id?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeSemanticGraphResponse {
  nodes: KnowledgeSemanticGraphNode[]
  links: KnowledgeSemanticGraphLink[]
  stats: Record<string, number>
}
