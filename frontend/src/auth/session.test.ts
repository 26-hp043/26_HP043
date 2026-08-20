import { describe, expect, it, vi } from 'vitest'
import {
  getCachedUser,
  logout,
  probeCurrentUser,
  readCookie,
  csrfHeaders,
  csrfToken,
  redirectToLogin,
} from './session'
import { safeNext } from '../features/auth/authRules'

/**
 * 인증 세션 클라이언트 검증 (#278).
 *
 * `fetch`·`env`를 주입해 서버 없이 돈다 — 확인하는 것은 「서버가 이렇게 응답하면
 * 클라이언트가 무엇으로 판단하는가」다. 서버 응답 형태는 백엔드 테스트
 * (`tests/test_auth_*.py`)가 잠근다.
 *
 * 각 테스트는 프로브로 시작해 모듈 캐시를 스스로 초기화한다 — 캐시 상태가
 * 테스트 순서에 의존하지 않게 하기 위해서다.
 */


function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

const ME_OK = jsonResponse({
  data: {
    id: '00000000-0000-4000-8000-0000000000aa',
    email: 'captain@example.com',
    display_name: '김선장',
  },
})

describe('readCookie', () => {
  it('여러 쿠키에서 이름으로 값을 찾는다', () => {
    expect(readCookie('sid=abc; csrf=tok%201; theme=dark', 'csrf')).toBe('tok%201')
  })

  it('앞뒤 공백을 무시한다', () => {
    expect(readCookie(' sid = abc ', 'sid')).toBe('abc')
  })

  it('값이 없는 쿠키는 null', () => {
    expect(readCookie('sid=', 'sid')).toBeNull()
  })

  it.each([
    ['대상 없음', 'a=1; b=2'],
    ['빈 문자열', ''],
    ['null', null],
    ['undefined', undefined],
  ])('%s → null', (_label, raw) => {
    expect(readCookie(raw as string | null, 'sid')).toBeNull()
  })
})

describe('safeNext — open redirect 방어', () => {
  /*
   * #415에서 `loginUrl`(백엔드 OIDC 진입점)이 사라졌다. 자체 인증에서는 로그인이
   * 앱 안의 화면이므로 복귀 경로 검증이 `safeNext`로 옮겨졌다. **막아야 하는 값은
   * 그대로다** — 외부 URL이 통과하면 로그인 직후 사용자가 외부 사이트에 도착한다.
   */
  it('내부 경로는 그대로 쓴다', () => {
    expect(safeNext('/voyage-cii')).toBe('/voyage-cii')
  })

  it('미지정 시 루트로 보낸다', () => {
    expect(safeNext(null)).toBe('/')
  })

  it.each([
    ['절대 URL', 'https://evil.example.com'],
    ['프로토콜 상대 URL', '//evil.example.com'],
    ['상대 경로', 'voyage-cii'],
  ])('%s는 거부되고 루트로 대체된다', (_label, raw) => {
    expect(safeNext(raw)).toBe('/')
  })

  it('쿼리스트링이 포함된 경로는 그대로 보존된다', () => {
    expect(safeNext('/annual-grade?vessel=1')).toBe('/annual-grade?vessel=1')
  })
})

describe('probeCurrentUser', () => {
  it('200이면 사용자를 캐시한다 — display_name이 없으면 null', async () => {
    const noName = jsonResponse({
      data: { id: 'u1', email: 'a@b.c', display_name: null },
    })
    const user = await probeCurrentUser(async () => noName)
    expect(user).toEqual({
      id: 'u1',
      email: 'a@b.c',
      displayName: null,
      emailVerifiedAt: null,
    })
    expect(getCachedUser()?.id).toBe('u1')
  })

  it('401이면 비인증 — 캐시도 비운다(fail-closed)', async () => {
    await probeCurrentUser(async () => ME_OK)
    const user = await probeCurrentUser(async () => jsonResponse({ error: { code: 'UNAUTHORIZED' } }, 401))
    expect(user).toBeNull()
    expect(getCachedUser()).toBeNull()
  })

  it('네트워크 실패도 비인증으로 취급한다 — 확인 안 됨을 열어 두지 않는다', async () => {
    const user = await probeCurrentUser(
      async () => {
        throw new TypeError('Failed to fetch')
      },
    )
    expect(user).toBeNull()
  })

  it('동시 호출은 하나로 합쳐진다 — fetch 1회', async () => {
    let calls = 0
    const slow: typeof fetch = async () => {
      calls += 1
      await new Promise((resolve) => setTimeout(resolve, 10))
      return ME_OK
    }
    const [a, b] = await Promise.all([
      probeCurrentUser(slow),
      probeCurrentUser(slow),
    ])
    expect(calls).toBe(1)
    expect(a?.id).toBe(b?.id)
  })

  it('응답 형태가 계약(data.id·data.email 문자열)을 어기면 비인증으로 취급한다', async () => {
    const malformed = jsonResponse({ data: { id: 123, email: 'a@b.c' } })
    const user = await probeCurrentUser(async () => malformed)
    expect(user).toBeNull()
  })
})

describe('csrf', () => {
  it('노드 환경(쿠키 없음)에서는 토큰도 헤더도 없다', () => {
    expect(csrfToken()).toBeNull()
    expect(csrfHeaders()).toEqual({})
  })
})

describe('logout', () => {
  it('POST /auth/logout을 부르고 캐시를 비운다', async () => {
    await probeCurrentUser(async () => ME_OK)
    expect(getCachedUser()).not.toBeNull()

    const fetchImpl = vi.fn(async () => jsonResponse({}, 204))
    await logout(fetchImpl as unknown as typeof fetch)

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/auth/logout')
    expect(init.method).toBe('POST')
    expect(getCachedUser()).toBeNull()
  })

  it('서버 호출 실패로 로그아웃이 막히지 않는다 — 상태는 초기화', async () => {
    await probeCurrentUser(async () => ME_OK)
    await logout(
      async () => {
        throw new TypeError('Failed to fetch')
      },
    )
    expect(getCachedUser()).toBeNull()
  })
})

describe('redirectToLogin', () => {
  it('window가 없는 환경(노드 테스트)에서는 no-op — 예외 없이 통과', () => {
    expect(() => redirectToLogin('/anywhere')).not.toThrow()
  })
})
