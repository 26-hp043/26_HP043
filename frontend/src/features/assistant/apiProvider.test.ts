import { describe, expect, it, vi } from 'vitest'
import { createApiAssistantProvider } from './apiProvider'

/** `GET /chat/status` 클라이언트 (`#1535` · `API_SPEC §15.7`). */

function fetchReturning(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch
}

describe('status()', () => {
  it('서버의 available 불린을 그대로 돌려준다', async () => {
    const fetchImpl = fetchReturning(200, { data: { available: false } })
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    await expect(provider.status!()).resolves.toEqual({ available: false })
    expect((fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe('/api/v1/chat/status')
  })

  it('HTTP 오류는 던진다 — 「쓸 수 없음」으로 바꾸지 않는다', async () => {
    const provider = createApiAssistantProvider(fetchReturning(500, {}), '/api/v1')
    await expect(provider.status!()).rejects.toThrow()
  })

  it('available이 불린이 아니면 던진다', async () => {
    const provider = createApiAssistantProvider(fetchReturning(200, { data: {} }), '/api/v1')
    await expect(provider.status!()).rejects.toThrow()
  })
})
