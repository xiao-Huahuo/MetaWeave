/** MCP management requests and DTOs. All business state is persisted by the backend. */
import { apiDelete, apiGet, apiPost, apiPut, buildApiUrl } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

export interface McpTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
  annotations?: { readOnlyHint?: boolean; destructiveHint?: boolean }
  title?: string
  domain?: string
  write?: boolean
}
export interface McpConnectionDraft {
  name: string
  transport: 'stdio' | 'http'
  enabled: boolean
  command: string
  args: string[]
  cwd: string
  url: string
  env: Record<string, string | null>
  headers: Record<string, string | null>
  timeout_seconds: number
  disabled_tools: string[]
}
export interface McpConnection extends McpConnectionDraft {
  connection_id: string
  revision: number
  inherited?: boolean
  state: string
  error: string
  tools: McpTool[]
}
export interface McpClientState {
  config: { enabled: boolean }
  override: { enabled?: boolean }
  connections: McpConnection[]
}
export interface McpServerConfig { enabled: boolean; host: string; port: number; tools: string[] }
export interface McpCredential {
  credential_id: string
  name: string
  token_prefix: string
  revoked: boolean
  created_at: string
  grants: { tools: string[]; library_id: string }
}
export interface McpServerState {
  config: McpServerConfig
  override: Partial<McpServerConfig>
  state: string
  error: string
  url: string
  active_config: McpServerConfig | null
  catalog: McpTool[]
  credentials: McpCredential[]
}
export interface McpAccessRecord {
  record_id: string; credential_id: string; tool_name: string
  status: string; duration_ms: number; message: string; created_at: string
}
export interface McpImportEntry { index: number; draft?: McpConnectionDraft; conflict?: boolean; error: string }
export interface McpTestResult { state: string; error: string; tools: McpTool[] }
export interface McpSecret { credential_id: string; token: string }

/** Scope all management writes to the same user as reads. */
const scoped = (path: string, userId: string) => buildApiUrl(path, { user_id: userId })
export const fetchMcpClient = (userId: string) => apiGet<McpClientState>(API_ROUTES.MCP_CLIENT, { user_id: userId })
export const saveMcpClient = (userId: string, enabled: boolean | null) => apiPut<McpClientState>(scoped(API_ROUTES.MCP_CLIENT, userId), { enabled }, { timeoutMs: 600_000 })
export const saveMcpConnection = (userId: string, draft: McpConnectionDraft, existing?: { connection_id: string; revision: number }) => existing
  ? apiPut<McpConnection>(scoped(API_ROUTES.MCP_CONNECTION(existing.connection_id), userId), { ...draft, revision: existing.revision }, { timeoutMs: (draft.timeout_seconds + 20) * 1000 })
  : apiPost<McpConnection>(scoped(API_ROUTES.MCP_CONNECTIONS, userId), draft, { timeoutMs: (draft.timeout_seconds + 20) * 1000 })
export const deleteMcpConnection = (userId: string, id: string) => apiDelete(scoped(API_ROUTES.MCP_CONNECTION(id), userId))
export const reconnectMcpConnection = (userId: string, id: string) => apiPost<McpTestResult>(scoped(API_ROUTES.MCP_RECONNECT(id), userId), {}, { timeoutMs: 620_000 })
export const testMcpConnection = (userId: string, draft: McpConnectionDraft, connectionId = '') => apiPost<McpTestResult>(
  scoped(API_ROUTES.MCP_TEST, userId), { ...draft, connection_id: connectionId }, { timeoutMs: (draft.timeout_seconds + 20) * 1000 })
export const exportMcpConnections = (userId: string) => apiGet<{ connections: McpConnectionDraft[] }>(API_ROUTES.MCP_EXPORT, { user_id: userId })
export const previewMcpImport = (userId: string, config: string) => apiPost<{ entries: McpImportEntry[] }>(scoped(API_ROUTES.MCP_IMPORT_PREVIEW, userId), { config })
export const fetchMcpServer = (userId: string) => apiGet<McpServerState>(API_ROUTES.MCP_SERVER, { user_id: userId })
export const saveMcpServer = (userId: string, config: McpServerConfig) => apiPut<McpServerState>(scoped(API_ROUTES.MCP_SERVER, userId), config, { timeoutMs: 60_000 })
export const createMcpCredential = (userId: string, payload: { name: string; tools: string[]; library_id: string }) => apiPost<McpSecret>(scoped(API_ROUTES.MCP_CREDENTIALS, userId), payload)
export const revokeMcpCredential = (userId: string, id: string) => apiDelete(scoped(API_ROUTES.MCP_CREDENTIAL(id), userId))
export const rotateMcpCredential = (userId: string, id: string) => apiPost<McpSecret>(scoped(API_ROUTES.MCP_ROTATE(id), userId))
export const fetchMcpRecords = (userId: string) => apiGet<{ records: McpAccessRecord[] }>(API_ROUTES.MCP_RECORDS, { user_id: userId })
export const verifyMcpServer = (userId: string, token: string) => apiPost<{ initialized: boolean; tool_count: number; call_verified: boolean; message: string }>(
  scoped(API_ROUTES.MCP_VERIFY, userId), { token }, { timeoutMs: 60_000 })
