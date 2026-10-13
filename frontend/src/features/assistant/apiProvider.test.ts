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

describe('ask()', () => {
  it('화면의 결과 id를 calculation_run_id로 싣는다 (#1533) · 없으면 키를 싣지 않는다', async () => {
    const body = {
      data: { session_id: 's', answer: 'a', disclaimer: 'd', tool_calls: [], discarded: false },
    }
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify(body), { status: 200 }),
    ) as unknown as typeof fetch
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    await provider.ask({ message: 'q', calculationRunId: 'run-1' })
    await provider.ask({ message: 'q' })
    const calls = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls
    expect(JSON.parse(calls[0][1].body).calculation_run_id).toBe('run-1')
    expect('calculation_run_id' in JSON.parse(calls[1][1].body)).toBe(false)
  })
})

describe('history() — `GET /chat/sessions/{id}/messages` (`#1981` · `API_SPEC §15.8`)', () => {
  const body = {
    data: {
      session_id: 's-1',
      disclaimer: 'd',
      messages: [
        { role: 'USER', content: 'q1', discarded: false, tool_calls: [] },
        { role: 'ASSISTANT', content: 'a1', discarded: false, tool_calls: ['calc_voyage_cii'] },
        { role: 'USER', content: 'q2', discarded: false, tool_calls: [] },
        { role: 'ASSISTANT', content: '답을 보내지 않았습니다.', discarded: true, tool_calls: [] },
      ],
    },
  }

  it('저장 역할(USER · ASSISTANT)을 말풍선 역할로 옮기고 버린 답·도구를 그대로 싣는다', async () => {
    const fetchImpl = fetchReturning(200, body)
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    const history = await provider.history!('s-1')
    expect((fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      '/api/v1/chat/sessions/s-1/messages',
    )
    expect(history).toEqual({
      sessionId: 's-1',
      disclaimer: 'd',
      turns: [
        { role: 'user', text: 'q1' },
        { role: 'assistant', text: 'a1', discarded: false, toolCalls: ['calc_voyage_cii'] },
        { role: 'user', text: 'q2' },
        { role: 'assistant', text: '답을 보내지 않았습니다.', discarded: true, toolCalls: undefined },
      ],
    })
  })

  it('404는 null이다 — 남의 것·만료된 것·없는 것을 화면이 가르지 않는다', async () => {
    const provider = createApiAssistantProvider(fetchReturning(404, { error: { code: 'NOT_FOUND' } }), '/api/v1')
    await expect(provider.history!('x')).resolves.toBeNull()
  })

  it('면책이 없으면 던진다 — 되살린 답에서 면책만 조용히 빠지지 않게', async () => {
    const provider = createApiAssistantProvider(
      fetchReturning(200, { data: { session_id: 's', messages: [] } }),
      '/api/v1',
    )
    await expect(provider.history!('s')).rejects.toThrow()
  })

  it('모르는 역할이 섞이면 던진다', async () => {
    const provider = createApiAssistantProvider(
      fetchReturning(200, {
        data: { session_id: 's', disclaimer: 'd', messages: [{ role: 'SYSTEM', content: 'x' }] },
      }),
      '/api/v1',
    )
    await expect(provider.history!('s')).rejects.toThrow()
  })
})

describe('forget() — `DELETE /chat/sessions/{id}` (`#1981` · `API_SPEC §15.6`)', () => {
  it('204는 성공이고 DELETE로 간다', async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    await expect(provider.forget!('s-1')).resolves.toBeUndefined()
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/v1/chat/sessions/s-1')
    expect(init.method).toBe('DELETE')
  })

  it('404도 성공으로 본다 — 지우려던 것이 이미 없다', async () => {
    const provider = createApiAssistantProvider(fetchReturning(404, {}), '/api/v1')
    await expect(provider.forget!('s-1')).resolves.toBeUndefined()
  })

  it('그 밖의 오류는 서버 문구로 던진다', async () => {
    const provider = createApiAssistantProvider(
      fetchReturning(500, { error: { message: '잠시 뒤 다시 시도해 주세요.' } }),
      '/api/v1',
    )
    await expect(provider.forget!('s-1')).rejects.toThrow('잠시 뒤 다시 시도해 주세요.')
  })
})
