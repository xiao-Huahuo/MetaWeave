/**
 * Password vault API client tests.
 *
 * Usage:
 * Ensures vault's Authorization header keeps the shared JSON content type so
 * FastAPI receives item payloads as objects rather than plain text.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createVaultItem } from '@/api/vault'

describe('Vault API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends JSON content type together with the vault authorization header', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ item: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await createVaultItem('vault-token', { item_type: 'login', fields: { name: '账号', password: '密码' }, tags: [] })

    const [, request] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(request.headers)
    expect(headers.get('Authorization')).toBe('Bearer vault-token')
    expect(headers.get('Content-Type')).toBe('application/json')
  })
})
