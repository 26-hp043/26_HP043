import { useSyncExternalStore } from 'react'

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
 * ## 가드는 항상 켜져 있다 (#542)
 *
 * 종전에는 `VITE_USE_API !== "true"`(demo provider)일 때 프로브·가드를 건너뛰었다.
 * 백엔드가 없는데 가드를 돌리면 화면이 로그인으로 막히기 때문이었다. 그 우회가
 * **데모 모드인 줄 모르고 쓰게 만든 직접 원인**이기도 하다(`#528`) — 로그인 없이
 * 화면이 열리니 실제 제품처럼 보였다.
 *
 * 데모 모드가 폐기되어 우회할 이유가 없어졌다. 개발 중 로그인을 건너뛰려면
 * `POST /api/v1/auth/dev-login`을 쓴다.
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
  /**
   * 이메일 인증 완료 시각. `null`이면 미인증.
   *
   * **미인증도 로그인은 허용한다**(`PRD §7.10`) — 인증을 강제하면 메일이 도착하지
   * 않을 때 사용자가 아무것도 하지 못한다. 대신 셸이 배너를 띄운다.
   */
  emailVerifiedAt: string | null
}

export const LOGIN_PATH = '/login'
export const LOGIN_FAILURE_PATH = '/login/failure'
export const SIGNUP_PATH = '/signup'
export const PASSWORD_RESET_PATH = '/password-reset'
export const VERIFY_EMAIL_PATH = '/verify-email'

/** 상대 경로 — 개발은 vite 프록시, 프로덕션은 같은 출처(vite.config 참조). */
const AUTH_API_BASE = '/api/v1'
const ME_URL = `${AUTH_API_BASE}/auth/me`
const LOGIN_API_URL = `${AUTH_API_BASE}/auth/login`
const LOGOUT_API_URL = `${AUTH_API_BASE}/auth/logout`
const SIGNUP_API_URL = `${AUTH_API_BASE}/auth/signup`
const VERIFY_REQUEST_URL = `${AUTH_API_BASE}/auth/verify-email/request`
const VERIFY_CONFIRM_URL = `${AUTH_API_BASE}/auth/verify-email/confirm`
const RESET_REQUEST_URL = `${AUTH_API_BASE}/auth/password-reset/request`
const RESET_CONFIRM_URL = `${AUTH_API_BASE}/auth/password-reset/confirm`
const PASSWORD_CHANGE_URL = `${AUTH_API_BASE}/auth/password-change`

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

/**
 * 세션을 프로브해 사용자를 캐시한다.
 *
 * 동시 다발 호출은 하나로 합친다(가드·로그인 화면이 동시에 마운트돼도 요청 1회).
 * 실패(네트워크·401 모두)는 비인증으로 취급한다 — **확인 안 됨을 열어 두지
 * 않는다**(fail-closed, 서버 `require_csrf`와 같은 원칙).
 *
 * 종전에는 `env`를 받아 데모 모드에서 프로브를 건너뛰었다. `#542`가 그 갈래를
 * 없애면서 인자도 사라졌다.
 */
export async function probeCurrentUser(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<CurrentUser | null> {
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
      currentUser = toCurrentUser(await response.json())
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

/** `GET /auth/me`·가입·로그인 응답을 화면 타입으로 옮긴다. */
export function toCurrentUser(body: unknown): CurrentUser | null {
  const data = (body as { data?: Record<string, unknown> } | null)?.data
  if (!data || typeof data.id !== 'string' || typeof data.email !== 'string') return null
  return {
    id: data.id,
    email: data.email,
    displayName:
      typeof data.display_name === 'string' && data.display_name ? data.display_name : null,
    emailVerifiedAt:
      typeof data.email_verified_at === 'string' ? data.email_verified_at : null,
  }
}

/**
 * 인증 요청 실패 — 화면이 사용자에게 그대로 보여 줄 문구를 담는다.
 *
 * **서버 문구를 그대로 쓴다.** 로그인 실패·재설정 요청 문구는 「계정 존재 여부를
 * 노출하지 않는다」는 규칙에 맞춰 정본이 확정한 것이라(`PRD §6.3`), 화면이 다시
 * 쓰면 그 규칙이 깨질 수 있다.
 */
export class AuthRequestError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'AuthRequestError'
    this.status = status
  }
}

async function postJson(
  url: string,
  payload: unknown,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetchImpl(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new AuthRequestError('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', 0)
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const message =
      (body as { error?: { message?: string } } | null)?.error?.message ??
      '요청을 처리하지 못했습니다.'
    throw new AuthRequestError(message, response.status)
  }
  return body
}

/** 이메일·비밀번호로 로그인하고 사용자 상태를 갱신한다. */
export async function login(
  email: string,
  password: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<CurrentUser | null> {
  const body = await postJson(LOGIN_API_URL, { email, password }, fetchImpl)
  currentUser = toCurrentUser(body)
  notify()
  return currentUser
}

/** 회원가입 — 성공 시 **즉시 로그인 상태**가 된다(`API_SPEC §1.2`). */
export async function signup(
  email: string,
  password: string,
  displayName: string | null,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<CurrentUser | null> {
  const body = await postJson(
    SIGNUP_API_URL,
    { email, password, display_name: displayName || null },
    fetchImpl,
  )
  currentUser = toCurrentUser(body)
  notify()
  return currentUser
}

/** 인증 메일 재발송. 성공 문구는 서버가 준다. */
export async function requestEmailVerification(
  email: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<string> {
  const body = await postJson(VERIFY_REQUEST_URL, { email }, fetchImpl)
  return messageOf(body)
}

/** 메일 링크의 토큰으로 이메일 인증을 완료한다. */
export async function confirmEmailVerification(
  token: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<string> {
  const body = await postJson(VERIFY_CONFIRM_URL, { token }, fetchImpl)
  return messageOf(body)
}

/** 비밀번호 재설정 메일 요청. **가입 여부와 무관하게 같은 응답이 온다.** */
export async function requestPasswordReset(
  email: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<string> {
  const body = await postJson(RESET_REQUEST_URL, { email }, fetchImpl)
  return messageOf(body)
}

/**
 * 새 비밀번호로 교체한다.
 *
 * 성공하면 **기존 세션이 전부 끊긴다**(`API_SPEC §1.2`). 화면은 로그인으로 보낸다.
 */
export async function confirmPasswordReset(
  token: string,
  password: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<string> {
  const body = await postJson(RESET_CONFIRM_URL, { token, password }, fetchImpl)
  currentUser = null
  notify()
  return messageOf(body)
}

function messageOf(body: unknown): string {
  const message = (body as { data?: { message?: unknown } } | null)?.data?.message
  return typeof message === 'string' ? message : '요청이 처리되었습니다.'
}

/** 로그인 화면으로 이동한다. `next` 생략 시 현재 경로를 보존한다.
 *
 * 종전에는 백엔드 OIDC 진입점으로 **전체 페이지 이동**했으나, 자체 인증에서는
 * 로그인이 앱 안의 화면이므로 SPA 경로로 간다(#415).
 */
export function redirectToLogin(next?: string): void {
  if (typeof window === 'undefined') return
  const target = next ?? `${window.location.pathname}${window.location.search}`
  const safeNext = target.startsWith('/') && !target.startsWith('//') ? target : '/'
  window.location.assign(`${LOGIN_PATH}?next=${encodeURIComponent(safeNext)}`)
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

/**
 * 표시 이름을 바꾼다 — `PATCH /auth/me` (`#506`).
 *
 * **`email`을 보내지 않는다.** 서버가 `extra="forbid"`로 422를 낸다(`API_SPEC §1.2`).
 * 이메일은 로그인 ID이자 `idx_app_user_email`의 키라, 잘못 바꾸면 계정에 접근할 수
 * 없다 — 재설정 메일도 그 주소로 간다.
 *
 * 성공하면 캐시를 갱신한다. 상단바가 같은 사용자를 보고 있으므로 여기서 갱신하지
 * 않으면 화면마다 다른 이름이 보인다.
 */
export async function updateDisplayName(
  displayName: string | null,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<CurrentUser | null> {
  let response: Response
  try {
    response = await fetchImpl(ME_URL, {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...csrfHeaders(),
      },
      body: JSON.stringify({ display_name: displayName }),
    })
  } catch {
    throw new AuthRequestError('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', 0)
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new AuthRequestError(
      (body as { error?: { message?: string } } | null)?.error?.message ??
        '표시 이름을 바꾸지 못했습니다.',
      response.status,
    )
  }

  currentUser = toCurrentUser(body)
  notify()
  return currentUser
}

/**
 * 비밀번호를 바꾼다 — `POST /auth/password-change` (`#506`).
 *
 * ## 캐시를 비우지 않는다
 *
 * 서버가 **기존 세션을 전량 무효화**하므로 이 기기의 쿠키도 이미 죽어 있다
 * (`API_SPEC §1.2`). 여기서 `currentUser`를 비우면 라우트 가드가 **즉시** 로그인
 * 화면으로 밀어내고, 그러면 「모든 기기에서 로그아웃됐다」는 안내를 볼 틈이 없다.
 *
 * 캐시를 그대로 두면 다음 요청이 401을 받아 `redirectToLogin()`으로 간다. 그 사이에
 * 화면이 사유를 설명한다 — 사용자가 「왜 튕겼지」로 받지 않게 하는 것이 목적이다.
 *
 * @returns 서버가 준 안내 문구. 무효화된 기기 수를 담고 있다.
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<string> {
  let response: Response
  try {
    response = await fetchImpl(PASSWORD_CHANGE_URL, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...csrfHeaders(),
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    })
  } catch {
    throw new AuthRequestError('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', 0)
  }

  const body = (await response.json().catch(() => null)) as {
    data?: { message?: string }
    error?: { message?: string }
  } | null

  if (!response.ok) {
    /*
     * 현재 비밀번호가 틀렸다는 것도 서버 문구를 그대로 쓴다. 화면이 다시 쓰면
     * 「계정 존재 여부를 숨기는」 규칙(`API_SPEC §1.2`)과 문구가 갈라진다.
     */
    throw new AuthRequestError(body?.error?.message ?? '비밀번호를 바꾸지 못했습니다.', response.status)
  }

  return body?.data?.message ?? '비밀번호를 변경했습니다.'
}

/** 현재 사용자를 구독한다 — 가드·상단바가 함께 쓴다. */
export function useAuthUser(): CurrentUser | null {
  return useSyncExternalStore(subscribeAuth, getCachedUser, getCachedUser)
}
