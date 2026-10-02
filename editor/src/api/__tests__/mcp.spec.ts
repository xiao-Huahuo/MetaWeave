/** MCP request contract: user scope, revision guards, secret preservation and one-time credential bodies. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as mcp from '@/api/mcp'

const draft: mcp.McpConnectionDraft = { name: 'Research', transport: 'http', enabled: true, command: '', args: [], cwd: '', url: 'https://example.org/mcp', env: {}, headers: { Authorization: null }, timeout_seconds: 30, disabled_tools: ['write'] }

describe('MCP management requests', () => {
  afterEach(() => vi.unstubAllGlobals())
  const cases: Array<[string, () => Promise<unknown>, string, string, Record<string, unknown> | undefined]> = [
    ['list client', () => mcp.fetchMcpClient('user/1'), '/settings/mcp/client?user_id=user%2F1', 'GET', undefined],
    ['enable client', () => mcp.saveMcpClient('user/1', true), '/settings/mcp/client?user_id=user%2F1', 'PUT', { enabled: true }],
    ['create connection', () => mcp.saveMcpConnection('user/1', draft), '/settings/mcp/client/connections?user_id=user%2F1', 'POST', draft as unknown as Record<string, unknown>],
    ['update connection', () => mcp.saveMcpConnection('user/1', draft, { connection_id: 'a/b', revision: 4 }), '/settings/mcp/client/connections/a%2Fb?user_id=user%2F1', 'PUT', { ...draft, revision: 4 }],
    ['delete connection', () => mcp.deleteMcpConnection('user/1', 'a/b'), '/settings/mcp/client/connections/a%2Fb?user_id=user%2F1', 'DELETE', undefined],
    ['reconnect', () => mcp.reconnectMcpConnection('user/1', 'a/b'), '/settings/mcp/client/connections/a%2Fb/reconnect?user_id=user%2F1', 'POST', {}],
    ['test draft', () => mcp.testMcpConnection('user/1', draft, 'a/b'), '/settings/mcp/client/test?user_id=user%2F1', 'POST', { ...draft, connection_id: 'a/b' }],
    ['export', () => mcp.exportMcpConnections('user/1'), '/settings/mcp/client/export?user_id=user%2F1', 'GET', undefined],
    ['import preview', () => mcp.previewMcpImport('user/1', '{}'), '/settings/mcp/client/import/preview?user_id=user%2F1', 'POST', { config: '{}' }],
    ['server status', () => mcp.fetchMcpServer('user/1'), '/settings/mcp/server?user_id=user%2F1', 'GET', undefined],
    ['server apply', () => mcp.saveMcpServer('user/1', { enabled: true, host: '127.0.0.1', port: 8766, tools: ['read_file'] }), '/settings/mcp/server?user_id=user%2F1', 'PUT', { enabled: true, host: '127.0.0.1', port: 8766, tools: ['read_file'] }],
    ['credential create', () => mcp.createMcpCredential('user/1', { name: 'Reader', library_id: 'lib1', tools: ['read_file'] }), '/settings/mcp/server/credentials?user_id=user%2F1', 'POST', { name: 'Reader', library_id: 'lib1', tools: ['read_file'] }],
    ['credential revoke', () => mcp.revokeMcpCredential('user/1', 'a/b'), '/settings/mcp/server/credentials/a%2Fb?user_id=user%2F1', 'DELETE', undefined],
    ['credential rotate', () => mcp.rotateMcpCredential('user/1', 'a/b'), '/settings/mcp/server/credentials/a%2Fb/rotate?user_id=user%2F1', 'POST', {}],
    ['access records', () => mcp.fetchMcpRecords('user/1'), '/settings/mcp/server/records?user_id=user%2F1', 'GET', undefined],
    ['real verification', () => mcp.verifyMcpServer('user/1', 'private-token'), '/settings/mcp/server/verify?user_id=user%2F1', 'POST', { token: 'private-token' }],
  ]
  it.each(cases)('%s preserves identity and operation contract', async (_label, action, url, method, body) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await action()
    const [path, request] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe(url)
    expect(request.method ?? 'GET').toBe(method)
    if (body) expect(JSON.parse(String(request.body))).toEqual(body)
    expect(path).not.toContain('private-token')
  })
})
