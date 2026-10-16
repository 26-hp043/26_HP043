import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssistantError, createApiAssistantProvider } from './apiProvider'

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

describe('ask() — 이어 가던 대화가 서버에 없을 때 (#1981 후속)', () => {
  const gone = { error: { code: 'NOT_FOUND', message: '대화를 찾을 수 없습니다.' } }

  it('대화 번호를 실어 보낸 질문의 404는 sessionGone이다', async () => {
    const provider = createApiAssistantProvider(fetchReturning(404, gone), '/api/v1')
    await expect(provider.ask({ message: 'q', sessionId: 's-1' })).rejects.toMatchObject({
      sessionGone: true,
    })
  })

  it('번호 없이 보낸 질문의 404와 다른 오류는 sessionGone이 아니다', async () => {
    const without = createApiAssistantProvider(fetchReturning(404, gone), '/api/v1')
    await expect(without.ask({ message: 'q' })).rejects.toMatchObject({ sessionGone: false })
    const other = createApiAssistantProvider(fetchReturning(422, gone), '/api/v1')
    await expect(other.ask({ message: 'q', sessionId: 's-1' })).rejects.toMatchObject({
      sessionGone: false,
    })
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

describe('message_id → messageId (#2405)', () => {
  it('ask — 저장된 답의 번호를 싣고, null이면 키를 두지 않는다', async () => {
    const saved = createApiAssistantProvider(
      fetchReturning(200, {
        data: { session_id: 's', answer: 'a', disclaimer: 'd', tool_calls: [], discarded: false, message_id: 'm-1' },
      }),
      '/api/v1',
    )
    expect((await saved.ask({ message: 'q' })).messageId).toBe('m-1')

    const unsaved = createApiAssistantProvider(
      fetchReturning(200, {
        data: { session_id: 's', answer: '버림', disclaimer: 'd', tool_calls: [], discarded: true, message_id: null },
      }),
      '/api/v1',
    )
    expect('messageId' in (await unsaved.ask({ message: 'q' }))).toBe(false)
  })

  it('history — 저장된 답에만 번호가 붙는다(사용자 턴 · 버린 답에는 없다)', async () => {
    const provider = createApiAssistantProvider(
      fetchReturning(200, {
        data: {
          session_id: 's-1',
          disclaimer: 'd',
          messages: [
            { role: 'USER', content: 'q1', discarded: false, tool_calls: [], message_id: null },
            { role: 'ASSISTANT', content: 'a1', discarded: false, tool_calls: [], message_id: 'm-1' },
            // 서버가 번호를 실어도 버린 답에는 옮기지 않는다 — 답이 아닌 것에 별을 달 수 없다.
            { role: 'ASSISTANT', content: '버림', discarded: true, tool_calls: [], message_id: 'm-2' },
          ],
        },
      }),
      '/api/v1',
    )
    const history = await provider.history!('s-1')
    expect(history!.turns.map((turn) => turn.messageId)).toEqual([undefined, 'm-1', undefined])
  })
})

describe('즐겨찾기 — favorites · favorite · unfavorite (#2405)', () => {
  const TOKEN = 'csrf-token-2405'

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const ITEM = {
    session_id: 's-1',
    message_id: 'm-1',
    question: '등급은?',
    answer: 'C입니다.',
    answered_at: '2026-10-15T01:00:00Z',
    expires_at: '2027-01-13T01:00:00Z',
    favorited_at: '2026-10-16T01:00:00Z',
  }

  it('favorites — GET /chat/favorites의 항목을 화면 키로 옮긴다', async () => {
    const fetchImpl = fetchReturning(200, { data: { favorites: [ITEM, { ...ITEM, message_id: 'm-2', question: null }] } })
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    const list = await provider.favorites!()
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/v1/chat/favorites')
    expect(init.method ?? 'GET').toBe('GET')
    expect(list).toEqual([
      {
        sessionId: 's-1',
        messageId: 'm-1',
        question: '등급은?',
        answer: 'C입니다.',
        answeredAt: '2026-10-15T01:00:00Z',
        expiresAt: '2027-01-13T01:00:00Z',
        favoritedAt: '2026-10-16T01:00:00Z',
      },
      expect.objectContaining({ messageId: 'm-2', question: null }),
    ])
  })

  it('favorites — 키가 빠진 항목이 섞이면 던진다(일부만 그리지 않는다) · HTTP 오류도 던진다', async () => {
    const { answer: _omit, ...broken } = ITEM
    const malformed = createApiAssistantProvider(fetchReturning(200, { data: { favorites: [ITEM, broken] } }), '/api/v1')
    await expect(malformed.favorites!()).rejects.toThrow()
    const failing = createApiAssistantProvider(fetchReturning(500, {}), '/api/v1')
    await expect(failing.favorites!()).rejects.toThrow()
  })

  it('favorite — PUT /chat/messages/{id}/favorite에 CSRF 헤더를 싣는다', async () => {
    vi.stubGlobal('document', { cookie: `sid=s; csrf=${TOKEN}` })
    const fetchImpl = fetchReturning(200, { data: { message_id: 'm 1', favorited_at: '2026-10-16T01:00:00Z' } })
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    await expect(provider.favorite!('m 1')).resolves.toBeUndefined()
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/v1/chat/messages/m%201/favorite')
    expect(init.method).toBe('PUT')
    expect(init.headers['X-CSRF-Token']).toBe(TOKEN)
    expect(init.credentials).toBe('include')
  })

  it('favorite — 404(남의 것·만료·없는 답)는 서버 문구로 던지고 messageGone으로 다른 오류와 가른다', async () => {
    const provider = createApiAssistantProvider(
      fetchReturning(404, { error: { code: 'NOT_FOUND', message: '답을 찾을 수 없습니다.' } }),
      '/api/v1',
    )
    const gone = await provider.favorite!('m-1').catch((error: unknown) => error)
    expect(gone).toBeInstanceOf(AssistantError)
    expect((gone as AssistantError).message).toBe('답을 찾을 수 없습니다.')
    expect((gone as AssistantError).messageGone).toBe(true)

    // 404가 아닌 실패는 messageGone이 아니다 — 화면이 목록을 다시 받을 까닭이 없다.
    const failing = createApiAssistantProvider(fetchReturning(500, {}), '/api/v1')
    const other = await failing.favorite!('m-1').catch((error: unknown) => error)
    expect(other).toBeInstanceOf(AssistantError)
    expect((other as AssistantError).messageGone).toBe(false)
  })

  it('unfavorite — DELETE에 CSRF 헤더를 싣고 204는 성공이다', async () => {
    vi.stubGlobal('document', { cookie: `sid=s; csrf=${TOKEN}` })
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch
    const provider = createApiAssistantProvider(fetchImpl, '/api/v1')
    await expect(provider.unfavorite!('m-1')).resolves.toBeUndefined()
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/v1/chat/messages/m-1/favorite')
    expect(init.method).toBe('DELETE')
    expect(init.headers['X-CSRF-Token']).toBe(TOKEN)
  })

  it('unfavorite — 404는 성공으로 보고(뗄 별이 이미 없다) 그 밖의 오류는 던진다', async () => {
    const gone = createApiAssistantProvider(fetchReturning(404, {}), '/api/v1')
    await expect(gone.unfavorite!('m-1')).resolves.toBeUndefined()
    const failing = createApiAssistantProvider(fetchReturning(500, {}), '/api/v1')
    await expect(failing.unfavorite!('m-1')).rejects.toThrow()
  })
})
