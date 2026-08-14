import { useSyncExternalStore } from 'react'

/**
 * `VITE_USE_API` 해석 — `providerSelection`과 같은 키·같은 규칙(문자열 `"true"`만 참).
 *
 * `providerSelection.shouldUseApi`를 import하지 않는 이유: `apiProvider`가 이 모듈의
 * `csrfHeaders`·`redirectToLogin`을 import하는데, 그러면
 * session → providerSelection → apiProvider → session 순환이 생긴다. 해석 한 줄을
 * 여기 두는 것으로 순환을 끊는다 — 키가 바뀌면 두 곳을 함께 고친다.
 */
const USE_API_ENV_KEY = 'VITE_USE_API'

/**
 * 인증 세션 클라이언트 — `UIFLOW.md` §0 (#278).
 *
 * 백엔드 인증은 구글 OIDC → 서버 세션 쿠키(`sid`)다(API_SPEC §1.2). 이 모듈이
 * 프론트엔드에서 아는 전부를 담는다:
 *
 * - **세션 확인** — `GET /auth/me` 프로브. 미들웨어가 401을 내면 비인증이다.
 * - **로그인 진입** — `GET /auth/login?redirect_to=…` 로 **전체 페이지 이동**.
 *   구글 인증 화면을 거치는 흐름이라 SPA 라우팅 밖으로 나갔다가 돌아온다.
 *   복귀 경로는 `redirect_to`로 서버가 왕복 보존한다(#274).
 * - **CSRF** — 상태 변경 요청에 `csrf` 쿠키 값을 `X-CSRF-Token` 헤더로 옮긴다.
 *   쿠키는 자동 전송되므로 검증은 헤더로만 한다(API_SPEC §1.2).
 *
 * ## demo 모드에서는 가드가 꺼진다
 *
 * `VITE_USE_API !== "true"`(demo provider)면 백엔드가 없다 — 이때 프로브·가드를
 * 돌리면 화면이 로그인으로 막혀 버린다. `providerSelection`의 스위치를 그대로
 * 공유해 demo 모드에서는 인증을 우회한다(#138과 같은 판단).
 *
 * ## 상태 전파
 *
 * 사용자 상태는 모듈 캐시 하나로 유지하고 `useSyncExternalStore`로 구독한다 —
 * 상태 라이브러리 없이(#133 제약) React 19 표준 수단만 쓴다.
 */

/** 인증된 사용자 — `GET /auth/me` 응답의 `data` 블록. */
export interface CurrentUser {
  id: string
  email: string
  displayName: string | null
}

export const LOGIN_PATH = '/login'
export const LOGIN_FAILURE_PATH = '/login/failure'

/** 상대 경로 — 개발은 vite 프록시, 프로덕션은 같은 출처(vite.config 참조). */
const AUTH_API_BASE = '/api/v1'
const ME_URL = `${AUTH_API_BASE}/auth/me`
const LOGIN_API_URL = `${AUTH_API_BASE}/auth/login`
const LOGOUT_API_URL = `${AUTH_API_BASE}/auth/logout`

/** dev-login이 내려주는 CSRF 쿠키 이름(auth_dev.py와 계약). */
const CSRF_COOKIE_NAME = 'csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'

type Listener = () => void

const listeners = new Set<Listener>()
let currentUser: CurrentUser | null = null
let probing: Promise<CurrentUser | null> | null = null

function notify(): void {
  for (const listener of listeners) listener()
}

/** `useSyncExternalStore` 구독 해제 함수를 반환한다. */
export function subscribeAuth(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 현재 캐시된 사용자. 없으면 `null` — 아직 확인 전과 비인증을 구분하지 않는다. */
export function getCachedUser(): CurrentUser | null {
  return currentUser
}

/** demo 모드에서는 라우트 가드·프로브 전체가 필요 없다. */
export function authGuardEnabled(env: ImportMetaEnv = import.meta.env): boolean {
  return env[USE_API_ENV_KEY] === 'true'
}

/**
 * 세션을 프로브해 사용자를 캐시한다.
 *
 * 동시 다발 호출은 하나로 합친다(가드·로그인 화면이 동시에 마운트돼도 요청 1회).
 * 실패(네트워크·401 모두)는 비인증으로 취급한다 — **확인 안 됨을 열어 두지
 * 않는다**(fail-closed, 서버 `require_csrf`와 같은 원칙). `env`는 테스트 주입용.
 */
export async function probeCurrentUser(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  env: ImportMetaEnv = import.meta.env,
): Promise<CurrentUser | null> {
  if (!authGuardEnabled(env)) return null
  if (probing) return probing

  probing = (async () => {
    try {
      const response = await fetchImpl(ME_URL, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) {
        currentUser = null
        notify()
        return null
      }
      const body = (await response.json()) as {
        data?: { id?: unknown; email?: unknown; display_name?: unknown }
      }
      const data = body?.data
      currentUser =
        data && typeof data.id === 'string' && typeof data.email === 'string'
          ? {
              id: data.id,
              email: data.email,
              displayName:
                typeof data.display_name === 'string' && data.display_name
                  ? data.display_name
                  : null,
            }
          : null
      notify()
      return currentUser
    } catch {
      currentUser = null
      notify()
      return null
    } finally {
      probing = null
    }
  })()
  return probing
}

/** `document.cookie` 원문에서 쿠키 하나를 꺼낸다 — 순수 함수(테스트 대상). */
export function readCookie(
  raw: string | null | undefined,
  name: string,
): string | null {
  if (!raw) return null
  for (const part of raw.split(';')) {
    const eq = part.indexOf('=')
    if (eq < 0) continue
    if (part.slice(0, eq).trim() === name) {
      const value = part.slice(eq + 1).trim()
      return value || null
    }
  }
  return null
}

/** CSRF 토큰 원문 — 노드 환경(테스트)에서는 쿠키가 없어 `null`. */
export function csrfToken(): string | null {
  if (typeof document === 'undefined') return null
  return readCookie(document.cookie, CSRF_COOKIE_NAME)
}

/** 상태 변경 요청에 붙일 CSRF 헤더. 토큰이 없으면 빈 객체(헤더 미첨부). */
export function csrfHeaders(): Record<string, string> {
  const token = csrfToken()
  return token ? { [CSRF_HEADER_NAME]: token } : {}
}

/**
 * 백엔드 로그인 진입 URL — `next`는 앱 내부 경로만 허용한다.
 *
 * 외부 URL을 그대로 넘기면 open redirect가 되므로 서버(#274)와 같은 규칙으로
 * 여기서도 걸러낸다.
 */
export function loginUrl(next?: string): string {
  const safeNext = next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
  return `${LOGIN_API_URL}?redirect_to=${encodeURIComponent(safeNext)}`
}

/** 로그인으로 전체 페이지 이동한다. `next` 생략 시 현재 경로를 보존한다. */
export function redirectToLogin(next?: string): void {
  if (typeof window === 'undefined') return
  const target = next ?? `${window.location.pathname}${window.location.search}`
  window.location.assign(loginUrl(target))
}

/**
 * 로그아웃 — 서버 세션 무효화 후 로그인 화면으로 이동한다.
 *
 * 서버 호출이 실패해도 클라이언트 상태는 초기화하고 이동한다 — 로그아웃 버튼에
 * 갇히는 것이 최악의 경험이다. 세션은 서버 만료·브라우저 재시작으로 자연 정리된다.
 */
export async function logout(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<void> {
  try {
    await fetchImpl(LOGOUT_API_URL, {
      method: 'POST',
      credentials: 'include',
      headers: { ...csrfHeaders() },
    })
  } catch {
    // 의도된 무시 — 위 주석 참조.
  }
  currentUser = null
  notify()
  if (typeof window !== 'undefined') {
    window.location.assign(LOGIN_PATH)
  }
}

/** 현재 사용자를 구독한다 — 가드·상단바가 함께 쓴다. */
export function useAuthUser(): CurrentUser | null {
  return useSyncExternalStore(subscribeAuth, getCachedUser, getCachedUser)
}
