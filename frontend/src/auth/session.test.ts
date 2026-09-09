import { describe, expect, it, vi } from 'vitest'
import {
  changePassword,
  deleteAccount,
  getCachedUser,
  logout,
  probeCurrentUser,
  readCookie,
  csrfHeaders,
  csrfToken,
  redirectToLogin,
  SESSION_EXPIRED_MESSAGE,
  updateDisplayName,
} from './session'
import { safeNext } from '../features/auth/authRules'
import { STORAGE_KEY } from '../layout/globalContext'

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

  it('서버 호출이 실패해도 이 기기의 상태는 초기화한다', async () => {
    /*
     * ⚠️ **이 검사의 전제가 `#825` ⑵에서 바뀌었다.**
     *
     * 종전 이름은 「서버 호출 실패로 로그아웃이 **막히지 않는다**」였고, 실패해도
     * 로그인 화면으로 이동하는 것을 옳다고 봤다 — 근거는 *「로그아웃 버튼에 갇히는
     * 것이 최악의 경험이다」*였다.
     *
     * 그런데 그 동작은 **서버 세션이 살아 있는데 로그아웃된 것처럼 보이게** 한다.
     * `sid`가 유효하고 `user_session.revoked_at`도 `NULL`이라, 백엔드가 돌아온 뒤
     * 다시 들어가면 **재로그인 없이 진입**된다 — 공용 PC에서 문제가 된다.
     *
     * 지금은 **이 기기의 상태는 지우되(캐시·전역 컨텍스트) 이동하지 않고 던진다.**
     * 화면(`AppShell`)이 그 문구를 띄우고 버튼은 그대로 남아 다시 누를 수 있다 —
     * 「갇힌다」가 아니다. 그 자리가 이 검사가 지키는 것이다.
     */
    await probeCurrentUser(async () => ME_OK)

    await expect(
      logout(async () => {
        throw new TypeError('Failed to fetch')
      }),
    ).rejects.toThrow(/연결하지 못했습니다/)

    // 이 기기에 남길 이유가 없는 것은 지운다.
    expect(getCachedUser()).toBeNull()
  })

  it('HTTP 실패도 잡는다 — fetch는 네트워크 실패에서만 reject한다 (#825 ⑵)', async () => {
    /*
     * 종전 구현은 `try/catch`만 있어 **403(CSRF 불일치)·500을 성공으로 취급**했다.
     * `fetch`가 reject하지 않기 때문이다 — 이것이 결함의 정확한 기전이다.
     */
    await probeCurrentUser(async () => ME_OK)

    await expect(
      logout(
        (async () =>
          jsonResponse({ error: { message: 'CSRF 토큰이 누락되었습니다.' } }, 403)) as unknown as typeof fetch,
      ),
    ).rejects.toThrow('CSRF 토큰이 누락되었습니다.')
  })

  it('성공하면 전역 컨텍스트 저장값도 지운다 (#825 ⑶)', async () => {
    /*
     * `sessionStorage`는 「탭 수명」이지 「로그인 세션 수명」이 아니고, 로그아웃은
     * **같은 탭 안에서** 이동한다. 지우지 않으면 다음 계정이 앞 계정의 선박 선택을
     * 물려받아, 쿼리로 선박을 싣는 화면에서 **없는 UUID로 404/403**이 난다.
     */
    // 이 파일은 노드 환경이라 `sessionStorage`가 없다 — 최소 구현을 끼운다.
    const store = new Map<string, string>([
      [STORAGE_KEY, JSON.stringify({ vesselId: 'a-vessel', voyageId: null })],
    ])
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    })
    await probeCurrentUser(async () => ME_OK)

    await logout((async () => jsonResponse({}, 204)) as unknown as typeof fetch)

    expect(store.has(STORAGE_KEY)).toBe(false)
    vi.unstubAllGlobals()
  })
})

describe('redirectToLogin', () => {
  it('window가 없는 환경(노드 테스트)에서는 no-op — 예외 없이 통과', () => {
    expect(() => redirectToLogin('/anywhere')).not.toThrow()
  })
})

/*
 * 탈퇴 — `DELETE /auth/me` (`#754`).
 *
 * ## 왜 여기서 보는가
 *
 * `AccountPanel.test.tsx`는 이 함수를 **대역으로 바꿔** 화면 흐름만 본다. 그래서
 * 실패 처리를 되돌려도 그쪽 검사 18건이 전부 통과했다(실측). 실제 구현의 계약은
 * 여기서 잠근다.
 *
 * ## `logout`과 반대다
 *
 * `logout`은 서버 호출이 실패해도 상태를 비우고 이동한다 — **로그아웃 버튼에 갇히는
 * 것이 최악**이기 때문이다. 탈퇴는 반대다: 실패한 채 로그인 화면으로 보내면 사용자는
 * **탈퇴됐다고 믿는데 계정이 살아 있다.**
 */
describe('deleteAccount (#754)', () => {
  it('DELETE /auth/me를 CSRF 헤더와 함께 부른다', async () => {
    await probeCurrentUser(async () => ME_OK)

    const fetchImpl = vi.fn(async () => jsonResponse({}, 204))
    await deleteAccount(fetchImpl as unknown as typeof fetch)

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/auth/me')
    expect(init.method).toBe('DELETE')
    // `API_SPEC §1.2` — 상태를 바꾸는 요청은 CSRF 헤더가 필요하다.
    expect(init.credentials).toBe('include')
  })

  it('성공하면 캐시를 비운다 — 상단바에 옛 이름이 남지 않는다', async () => {
    await probeCurrentUser(async () => ME_OK)
    expect(getCachedUser()).not.toBeNull()

    await deleteAccount((async () => jsonResponse({}, 204)) as unknown as typeof fetch)

    expect(getCachedUser()).toBeNull()
  })

  it('서버가 거부하면 던지고 캐시를 비우지 않는다 — 탈퇴된 척하지 않는다', async () => {
    await probeCurrentUser(async () => ME_OK)

    /*
     * ⚠️ **종전에는 이 검사가 `401`을 예시로 썼다** (`#878`에서 정정). 검사의 의도는
     * 「탈퇴가 **거부**됐을 때」인데, `401`은 거부가 아니라 **세션이 사라진 것**이다 —
     * 그 경우에는 캐시를 비우고 로그인으로 보내는 편이 맞고, 아래 별도 검사가 그것을
     * 단언한다. 의도를 살려 **세션과 무관한 실패**로 바꿨다.
     */
    await expect(
      deleteAccount(
        (async () =>
          jsonResponse(
            { error: { message: '탈퇴 처리 중 오류가 발생했습니다.' } },
            500,
          )) as unknown as typeof fetch,
      ),
    ).rejects.toThrow('탈퇴 처리 중 오류가 발생했습니다.')

    /*
     * ⚠️ 캐시가 비워지면 화면이 「로그아웃됨」으로 읽힌다. 계정은 살아 있는데
     * 사용자는 탈퇴했다고 믿게 된다 — 그 상태가 이 검사가 막는 것이다.
     */
    expect(getCachedUser()).not.toBeNull()
  })

  it('서버가 사유를 안 주면 기본 문구를 던진다 — 빈 오류로 끝나지 않는다', async () => {
    await probeCurrentUser(async () => ME_OK)

    await expect(
      deleteAccount((async () => jsonResponse(null, 500)) as unknown as typeof fetch),
    ).rejects.toThrow('탈퇴하지 못했습니다.')
  })

  it('연결 자체가 실패해도 던진다', async () => {
    await probeCurrentUser(async () => ME_OK)

    await expect(
      deleteAccount(async () => {
        throw new TypeError('Failed to fetch')
      }),
    ).rejects.toThrow(/서버에 연결하지 못했습니다/)
    expect(getCachedUser()).not.toBeNull()
  })
})

/**
 * 세션 만료 상태의 설정 화면 동작 (#878).
 *
 * `redirectToLogin()`의 소비처는 `features/<기능>/apiProvider.ts` 열세 곳뿐이고
 * **`auth/session.ts` 자신의 요청은 0곳**이었다. 그래서 세션이 만료된 채 설정 화면에서
 * 이름 변경·비밀번호 변경·탈퇴를 하면 서버 문구가 폼 아래 붙을 뿐 **화면이 설정에
 * 갇혔다** — 그 상태에서는 어떤 동작도 401이라 빠져나갈 길이 없다.
 *
 * `changePassword.md` 주석의 「다음 요청이 401을 받아 `redirectToLogin`으로 간다」는
 * **이 모듈 안의 요청에는 성립하지 않았다.**
 *
 * ⚠️ 이 파일은 노드 환경이라 `window`가 없어 `redirectToLogin()`이 no-op다. 화면 이동
 * 자체는 단언할 수 없으므로 **관측 가능한 두 결과**를 본다: 세션 만료 문구를 던지는가,
 * 캐시를 비우는가(비우지 않으면 상단바에 옛 사용자가 남는다).
 */
describe('세션 만료(401)를 설정 화면 동작이 스스로 처리한다 (#878)', () => {
  it('표시 이름 변경 — 401이면 만료 문구를 던지고 캐시를 비운다', async () => {
    await probeCurrentUser(async () => ME_OK)
    expect(getCachedUser()).not.toBeNull()

    await expect(
      updateDisplayName(
        '새 이름',
        (async () =>
          jsonResponse({ error: { message: '인증이 필요합니다.' } }, 401)) as unknown as typeof fetch,
      ),
    ).rejects.toThrow(SESSION_EXPIRED_MESSAGE)

    expect(getCachedUser()).toBeNull()
  })

  it('탈퇴 — 401이면 만료 문구를 던지고 캐시를 비운다', async () => {
    await probeCurrentUser(async () => ME_OK)

    await expect(
      deleteAccount(
        (async () =>
          jsonResponse({ error: { message: '인증이 필요합니다.' } }, 401)) as unknown as typeof fetch,
      ),
    ).rejects.toThrow(SESSION_EXPIRED_MESSAGE)

    expect(getCachedUser()).toBeNull()
  })

  it('표시 이름 변경 — 401이 아닌 실패는 종전대로 서버 문구를 던지고 캐시를 남긴다', async () => {
    await probeCurrentUser(async () => ME_OK)

    await expect(
      updateDisplayName(
        '가'.repeat(200),
        (async () =>
          jsonResponse({ error: { message: '표시 이름이 너무 깁니다.' } }, 422)) as unknown as typeof fetch,
      ),
    ).rejects.toThrow('표시 이름이 너무 깁니다.')

    expect(getCachedUser()).not.toBeNull()
  })
})

/**
 * 비밀번호 변경의 401은 두 사유가 섞여 있다 (#878).
 *
 * 실측 — **`code`가 같다.**
 *
 * ```
 * 세션 만료   {"code":"UNAUTHORIZED","message":"인증이 필요합니다."}
 * 비번 오입력 {"code":"UNAUTHORIZED","message":"현재 비밀번호가 올바르지 않습니다."}
 * ```
 *
 * 그래서 문구가 아니라 **세션이 실제로 살아 있는지**로 가른다.
 */
describe('비밀번호 변경의 401을 사유별로 가른다 (#878)', () => {
  /** `POST /auth/password-change`는 401, `GET /auth/me`는 주어진 응답을 낸다. */
  function passwordChangeThen(meResponse: Response) {
    return vi.fn(async (url: unknown) =>
      String(url).includes('/auth/me')
        ? meResponse
        : jsonResponse({ error: { code: 'UNAUTHORIZED', message: '…' } }, 401),
    ) as unknown as typeof fetch
  }

  it('세션이 죽었으면 만료로 처리한다 — 캐시를 비운다', async () => {
    await probeCurrentUser(async () => ME_OK)

    await expect(
      changePassword('현재비밀번호1!', '새비밀번호2@', passwordChangeThen(jsonResponse(null, 401))),
    ).rejects.toThrow(SESSION_EXPIRED_MESSAGE)

    expect(getCachedUser()).toBeNull()
  })

  it('세션이 살아 있으면 비밀번호 오입력이다 — 서버 문구를 폼에 남긴다', async () => {
    await probeCurrentUser(async () => ME_OK)

    const fetchImpl = vi.fn(async (url: unknown) =>
      String(url).includes('/auth/me')
        ? ME_OK
        : jsonResponse(
            { error: { code: 'UNAUTHORIZED', message: '현재 비밀번호가 올바르지 않습니다.' } },
            401,
          ),
    ) as unknown as typeof fetch

    await expect(
      changePassword('틀린비밀번호1!', '새비밀번호2@', fetchImpl),
    ).rejects.toThrow('현재 비밀번호가 올바르지 않습니다.')

    /*
     * ⚠️ 여기서 캐시가 비워지면 **비밀번호를 잘못 친 것만으로 로그아웃**된다.
     * 종전 결함의 정반대 방향 판본이라 함께 못 박는다.
     */
    expect(getCachedUser()).not.toBeNull()
  })

  it('세션 확인은 실패 경로에서만 한다 — 성공하면 추가 요청이 없다', async () => {
    await probeCurrentUser(async () => ME_OK)

    const fetchImpl = vi.fn(async () =>
      jsonResponse({ data: { message: '비밀번호를 변경했습니다. 3개 기기에서 로그아웃됩니다.' } }),
    )
    const message = await changePassword(
      '현재비밀번호1!',
      '새비밀번호2@',
      fetchImpl as unknown as typeof fetch,
    )

    expect(message).toContain('비밀번호를 변경했습니다')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})


describe('비밀번호 변경 후 캐시를 비운다 (#825 ⑷)', () => {
  it('성공하면 `getCachedUser()`가 null이다', async () => {
    /*
     * 종전에는 캐시를 남겼다. 근거는 *「라우트 가드가 즉시 밀어내면 안내를 볼 틈이
     * 없다」*였는데, 그 결과 **화면이 주는 「로그인 화면으로」 버튼이 로그인 화면에
     * 도달하지 못했다.**
     *
     * ```
     * /login → 살아 있는 캐시 → LoginPage가 <Navigate to={next}> → /dashboard
     *        → 가드 통과 → GET /fleet/summary 401 → redirectToLogin()
     *        → 전체 페이지 재로드 → 그제서야 로그인 폼
     * ```
     *
     * `confirmPasswordReset`이 이미 같은 처리를 한다 — **대칭이 깨져 있었다.**
     */
    await probeCurrentUser(async () => ME_OK)
    expect(getCachedUser()).not.toBeNull()

    const message = await changePassword(
      '현재비밀번호1!',
      '새비밀번호2@',
      (async () =>
        jsonResponse({ data: { message: '비밀번호를 변경했습니다.' } })) as unknown as typeof fetch,
    )

    expect(message).toContain('비밀번호를 변경했습니다')
    expect(getCachedUser()).toBeNull()
  })

  it('실패하면 캐시를 건드리지 않는다 — 비밀번호를 잘못 친 것만으로 로그아웃되지 않는다', async () => {
    await probeCurrentUser(async () => ME_OK)

    const fetchImpl = vi.fn(async (url: unknown) =>
      String(url).includes('/auth/me')
        ? ME_OK
        : jsonResponse(
            { error: { code: 'UNAUTHORIZED', message: '현재 비밀번호가 올바르지 않습니다.' } },
            401,
          ),
    ) as unknown as typeof fetch

    await expect(
      changePassword('틀린비밀번호1!', '새비밀번호2@', fetchImpl),
    ).rejects.toThrow('현재 비밀번호가 올바르지 않습니다.')

    expect(getCachedUser()).not.toBeNull()
  })
})
