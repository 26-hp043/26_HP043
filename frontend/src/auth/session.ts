import { useSyncExternalStore } from 'react'
import { clearStored } from '../layout/globalContext'
import { SCREEN_BY_ID } from '../screens'

/**
 * 인증 세션 클라이언트 — `UIFLOW.md` §0 (#278).
 *
 * 백엔드 인증은 이메일·비밀번호 → 서버 세션 쿠키(`sid`)다(API_SPEC §1.2 · `#413`).
 * 이 모듈이 프론트엔드에서 아는 전부를 담는다:
 *
 * - **세션 확인** — `GET /auth/me` 프로브. 미들웨어가 401을 내면 비인증이다.
 * - **로그인 진입** — 세션이 없거나 만료되면 `/login?next=<원래 경로>`로 이동한다
 *   (:func:`redirectToLogin`). 로그인 뒤에는 `features/auth/authRules.ts`의 `safeNext`가
 *   같은 사이트 안의 경로인지 확인해 그리로 돌려보낸다. 종전 설명(구글 OIDC ·
 *   `redirect_to` 서버 왕복)은 `#413`에서 사라진 흐름이었다(`#758`에서 정정).
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

/*
 * 인증 화면 경로는 **`screens.ts`에서 파생시킨다** (#831 ⑺).
 *
 * 종전에는 같은 경로가 두 곳에 문자열로 박혀 있었고, `screens.test.ts`가 둘을
 * 대조해 일치를 지켰다. 그 구조에서는 **한쪽만 고치면 라우트는 옛 경로에 남고
 * `findScreenByPath()`는 새 경로를 가리킨다** — 화면이 깨지지 않고 `AppShell`의
 * 폭 정책(`DESIGN_SYSTEM §7.1`)만 조용히 어긋나 발견이 늦다.
 *
 * 파생시키면 대조할 것이 없어진다. `LOGIN_FAILURE_PATH`는 참조가 없어 지웠다 —
 * `App.tsx`가 이미 `SCREEN_BY_ID.LOGIN_FAILURE.path`를 쓴다.
 */
export const LOGIN_PATH = SCREEN_BY_ID.LOGIN.path
export const SIGNUP_PATH = SCREEN_BY_ID.SIGNUP.path
export const PASSWORD_RESET_PATH = SCREEN_BY_ID.PASSWORD_RESET.path
export const VERIFY_EMAIL_PATH = SCREEN_BY_ID.VERIFY_EMAIL.path

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
//: 세션을 한 번이라도 확인했는가 (`#825` ⑴). `isAuthResolved()` 주석 참조.
let authResolved = false

function notify(): void {
  for (const listener of listeners) listener()
}

/** `useSyncExternalStore` 구독 해제 함수를 반환한다. */
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
function subscribeAuth(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 현재 캐시된 사용자. 없으면 `null`. */
export function getCachedUser(): CurrentUser | null {
  return currentUser
}

/**
 * 세션을 **한 번이라도 확인했는가** (`#825` ⑴).
 *
 * ## 왜 필요한가
 *
 * `currentUser`가 `null`인 데는 두 이유가 있다 — **아직 안 물어봤다**와 **비인증이다**.
 * 종전에는 둘을 구분하지 않아 `RequireAuth`가 **첫 렌더에서 무조건 로그인으로**
 * 보냈다. 프로브는 `useEffect`라 커밋 **이후**에 돌기 때문이다.
 *
 * 그래서 로그인 상태로 새로고침할 때마다 주소가 `/login?next=…`로 바뀌며 **로그인
 * 카드가 그려졌다가 되돌아왔다.** `RequireAuth`의 주석은 *「확인 중에는 자식을
 * 렌더하지 않되 레이아웃을 유지한다 — 깜빡임으로 로그인 화면을 잠깐 보여주는 것보다
 * 낫다」*를 이미 규정하고 있었다 — **문서화된 동작이 구현되지 않은 상태**였다.
 *
 * 실패(401·네트워크 모두)도 「확인됨」이다. fail-closed는 그대로다 — 확인 결과가
 * 「비인증」일 뿐이고, 그 판정을 **내렸다는 사실**이 여기 기록된다.
 */
// 이 파일 안에서만 쓴다 — 화면은 `useAuthResolved()`를 쓴다 (#594).
function isAuthResolved(): boolean {
  return authResolved
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
      // 성공·실패 모두 **확인은 끝났다** (`#825` ⑴). `notify()`보다 먼저 세워야
      // 구독자가 깨어난 시점에 이미 확정된 값을 본다.
      authResolved = true
      probing = null
      notify()
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
// 이 파일 안에서만 쓴다 — `export`를 붙이면 모듈 경계가 실제보다 넓어 보인다 (#594).
function toCurrentUser(body: unknown): CurrentUser | null {
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

/**
 * 세션 만료 문구 (`#878`).
 *
 * 이 파일이 정본 자리다 — 종전에는 **같은 상태를 두 문구로** 말하고 있었다:
 * `features/<기능>/apiProvider.ts` 네 곳이 이 문구를, 나머지 열 곳이 「세션이
 * 만료되었습니다.」를 각자 리터럴로 들고 있다. 이번 작업은 **새 사본을 만들지 않는
 * 것**까지만 하고, 열네 곳의 통합은 `#901`로 갈랐다 — 13파일을 건드리는 것은 이
 * 이슈의 범위가 아니다(`AGENTS §7` 1 PR = 1 이슈).
 */
export const SESSION_EXPIRED_MESSAGE = '로그인이 만료되었습니다. 다시 로그인해 주세요.'

/**
 * 세션이 만료된 요청을 끝낸다 — **캐시를 비우고 로그인 화면으로 보낸 뒤 던진다**
 * (`#878`).
 *
 * ## 왜 `postJson`에 넣지 않는가
 *
 * `postJson`을 쓰는 것은 로그인·가입·메일 인증·비밀번호 재설정이다. **그쪽의 401은
 * 세션 만료가 아니라 「자격 증명이 틀렸다」**이고, 거기서 로그인 화면으로 튕기면
 * 로그인 실패가 화면 이동으로 나타난다 — 사용자는 무엇이 틀렸는지 보지 못한다.
 *
 * 세션이 있어야만 부를 수 있는 요청(`PATCH`·`DELETE /auth/me`,
 * `POST /auth/password-change`)에서만 부른다.
 *
 * `redirectToLogin()`은 현재 경로를 `next`로 보존하므로, 다시 로그인하면 하던
 * 화면으로 돌아온다 — `logout`·탈퇴 성공이 쓰는 `LOGIN_PATH` 직행과 다른 점이고,
 * 그 차이가 「끝났다」와 「다시 하라」를 가른다.
 */
function failExpiredSession(): never {
  currentUser = null
  notify()
  redirectToLogin()
  throw new AuthRequestError(SESSION_EXPIRED_MESSAGE, 401)
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

/**
 * 회원가입 — 성공 시 **즉시 로그인 상태**가 된다(`API_SPEC §1.2`).
 *
 * `inviteCode`는 회사 메일이 아닌 사람이 가입할 때만 쓴다(#808 가입 게이트). 비었으면
 * 필드를 보내지 않는다 — 허용 도메인으로 가입하는 평상시 요청을 바꾸지 않기 위해서다.
 */
export async function signup(
  email: string,
  password: string,
  displayName: string | null,
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  inviteCode: string | null = null,
): Promise<CurrentUser | null> {
  const code = inviteCode?.trim()
  const body = await postJson(
    SIGNUP_API_URL,
    {
      email,
      password,
      display_name: displayName || null,
      ...(code ? { invite_code: code } : {}),
    },
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
  /*
   * **HTTP 상태를 본다** (`#825` ⑵).
   *
   * `fetch`는 **네트워크 실패에서만 reject**한다. 종전에는 `try/catch`만 있어
   * **403(CSRF 불일치)·500에도 로그아웃한 척**했다 — 화면은 로그인으로 가는데
   * `sid`는 살아 있고 `user_session.revoked_at`도 `NULL`이라, 백엔드가 돌아온 뒤
   * `/dashboard`로 들어가면 **재로그인 없이 진입**된다. 공용 PC에서 문제가 된다.
   *
   * **같은 파일이 정답을 갖고 있었다** — `postJson`이 `if (!response.ok) throw`를 한다.
   */
  let failure: string | null = null
  try {
    const response = await fetchImpl(LOGOUT_API_URL, {
      method: 'POST',
      credentials: 'include',
      headers: { ...csrfHeaders() },
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        error?: { message?: string }
      } | null
      failure = body?.error?.message ?? `로그아웃하지 못했습니다 (HTTP ${response.status}).`
    }
  } catch {
    failure = '서버에 연결하지 못했습니다.'
  }

  /*
   * ⑶ 전역 컨텍스트를 지운다.
   *
   * `sessionStorage`는 「탭 수명」이지 「로그인 세션 수명」이 아니고, 아래 이동은
   * **같은 탭 안에서** 일어난다. 지우지 않으면 다음 계정이 **앞 계정의 선박 선택**을
   * 물려받는다(`globalContext.clearStored` 주석 참조).
   *
   * **실패했더라도 지운다** — 이 기기의 화면 상태를 남길 이유는 없다.
   */
  clearStored()
  currentUser = null
  authResolved = true
  notify()

  /*
   * 실패했으면 **알리고 멈춘다.** 종전처럼 이동하면 사용자는 로그아웃됐다고 믿는데
   * 서버 세션이 살아 있다 — 그것이 이 결함의 핵심이다.
   *
   * 던지는 이유는 `AuthRequestError`가 이미 「화면이 그대로 보여 줄 문구」를 담는
   * 계약이기 때문이다. 호출부가 그것을 띄운다.
   */
  if (failure !== null) {
    throw new AuthRequestError(failure, 0)
  }

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

  // `PATCH /auth/me`의 401은 세션 문제뿐이다 — 이 라우트에 다른 401 원인이 없다.
  if (response.status === 401) failExpiredSession()

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
 * ⚠️ **그 「다음 요청」이 이 모듈 안에는 없었다** (`#878`). `redirectToLogin()`의
 * 소비처는 `features/<기능>/apiProvider.ts` 열세 곳뿐이고, 설정 화면에 머무는 동안에는
 * 그중 아무것도 불리지 않는다 — 이름 변경·비밀번호 변경·탈퇴가 전부 이 파일의
 * 요청이기 때문이다. 이제 이 파일의 세 요청도 401에서 `failExpiredSession()`을 지난다.
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
    error?: { code?: string; message?: string }
  } | null

  /*
   * 401의 두 사유를 `code`로 가른다 (#902).
   *
   * ```
   * 세션 만료   {"code":"UNAUTHORIZED",          "message":"인증이 필요합니다."}
   * 비번 오입력 {"code":"INVALID_CREDENTIALS",   "message":"현재 비밀번호가 올바르지 않습니다."}
   * ```
   *
   * 종전(#878)에는 두 `code`가 같아 `GET /auth/me`로 세션 생존을 직접 확인했다 —
   * 실패 경로마다 요청이 한 번 더 나갔다. 서버가 코드를 갈라 주므로(#902) 그 요청은
   * 필요 없다. `INVALID_CREDENTIALS`는 아래 `!response.ok`로 흘러 서버 문구를 그대로
   * 폼에 보여 주고, 그 외 401(`UNAUTHORIZED`·code 없음)은 세션 만료로 끝낸다.
   * code가 없는 쪽으로 기우는 이유 — 이 라우트의 401은 두 종류뿐이고, 봉투가
   * 깨진 응답을 「자격 증명 오류」로 잘못 읽으면 사용자가 폼에 갇힌다.
   */
  const error = body?.error ?? null
  if (response.status === 401 && error?.code !== 'INVALID_CREDENTIALS') {
    failExpiredSession()
  }

  if (!response.ok) {
    /*
     * 현재 비밀번호가 틀렸다는 것도 서버 문구를 그대로 쓴다. 화면이 다시 쓰면
     * 「계정 존재 여부를 숨기는」 규칙(`API_SPEC §1.2`)과 문구가 갈라진다.
     */
    throw new AuthRequestError(body?.error?.message ?? '비밀번호를 바꾸지 못했습니다.', response.status)
  }

  /*
   * ⑷ 캐시를 비운다 (`#825`).
   *
   * ## 종전 주석의 판단은 옳았지만 결과가 반대였다
   *
   * 위 「캐시를 비우지 않는다」는 *「라우트 가드가 즉시 로그인 화면으로 밀어내면
   * 안내를 볼 틈이 없다」*를 근거로 삼았다. 그 걱정 자체는 맞다 — 그런데 **화면이
   * 그 뒤에 주는 「로그인 화면으로」 버튼이 실제로는 로그인 화면에 가지 못했다.**
   *
   * ```
   * /login → useAuthUser()가 살아 있는 캐시 반환 → LoginPage가 <Navigate to={next}>
   *        → /dashboard → RequireAuth 통과 → GET /fleet/summary 401
   *        → redirectToLogin() → 전체 페이지 재로드 → 그제서야 로그인 폼
   * ```
   *
   * **버튼이 가리키는 곳에 갈 수 없고**, 없애려던 「왜 튕겼지」가 그대로 재현된다.
   *
   * ## 그러면 안내는 어떻게 보이나
   *
   * `AccountPanel`은 성공 문구를 **자기 상태에 담아** 그린다. 라우트 가드가 무엇을
   * 하든 그 문구는 이미 화면에 있고, 사용자가 「로그인 화면으로」를 누르면 이번에는
   * **정말로** 로그인 폼이 나온다.
   *
   * `confirmPasswordReset`이 이미 같은 처리를 한다 — **대칭이 깨져 있던 것**을 맞춘다.
   */
  currentUser = null
  authResolved = true
  notify()

  return body?.data?.message ?? '비밀번호를 변경했습니다.'
}

/**
 * 탈퇴 — `DELETE /auth/me` (`API_SPEC §1.2`, `#754`).
 *
 * ## 서버가 하는 일
 *
 * `app_user.is_deleted`를 세우는 **soft delete**이고 행을 지우지 않는다. 그 사용자가
 * 남긴 `calculation_run`(immutable)·`audit_log`(보존 대상)는 **그대로 남는다** —
 * 규제 대응의 근거가 되는 기록이기 때문이다. 세션은 전량 무효화되고 쿠키 2종이
 * 지워지며 응답은 **204**(돌려줄 사용자 정보가 없다)다.
 *
 * ## 실패해도 이동하지 않는다 — `logout`과 다르다
 *
 * `logout`은 서버 호출이 실패해도 클라이언트 상태를 비우고 이동한다. **로그아웃
 * 버튼에 갇히는 것이 최악**이기 때문이다.
 *
 * 탈퇴는 반대다. 실패한 채 로그인 화면으로 보내면 사용자는 **탈퇴됐다고 믿는데
 * 계정이 살아 있다.** 그래서 실패를 그대로 던지고 화면이 사유를 보여 준다.
 *
 * ## 성공하면 캐시를 비우고 로그인 화면으로
 *
 * 서버가 세션을 무효화했으므로 어느 화면에 남아 있어도 다음 요청이 401이다.
 * 화면이 아니라 여기서 이동시키는 것은 `logout`과 같은 이유 — 상태 초기화와 이동이
 * 갈리면 「로그아웃된 화면에 옛 사용자 이름이 남는」 상태가 생긴다.
 */
export async function deleteAccount(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
): Promise<void> {
  let response: Response
  try {
    response = await fetchImpl(ME_URL, {
      method: 'DELETE',
      credentials: 'include',
      headers: { Accept: 'application/json', ...csrfHeaders() },
    })
  } catch {
    throw new AuthRequestError('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', 0)
  }

  /*
   * 401은 **탈퇴 실패가 아니라 세션 만료**다 — 이 라우트에 다른 401 원인이 없다
   * (`#878`). 종전에는 「탈퇴하지 못했습니다」류의 서버 문구가 폼 아래 붙을 뿐
   * 화면이 설정에 갇혔고, 그 상태에서는 **어떤 동작도 401이라 빠져나갈 길이 없었다.**
   *
   * 위 「실패해도 이동하지 않는다」와 어긋나지 않는다: 그 규칙은 **탈퇴가 거부된**
   * 경우(사용자가 계정이 지워졌다고 오해하면 안 된다)를 말하고, 여기는 요청이 아예
   * 접수되지 않은 경우다. `next`가 붙은 로그인 이동이라 다시 로그인하면 설정 화면으로
   * 돌아와 탈퇴를 다시 시도할 수 있다 — 성공 경로의 `LOGIN_PATH` 직행과 다르다.
   */
  if (response.status === 401) failExpiredSession()

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string }
    } | null
    throw new AuthRequestError(body?.error?.message ?? '탈퇴하지 못했습니다.', response.status)
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

/**
 * 세션 확인이 끝났는지 구독한다 (`#825` ⑴).
 *
 * `useAuthUser`와 **같은 구독**을 쓴다 — 확인이 끝나는 순간 `notify()`가 돌므로
 * 두 훅이 같은 프레임에서 함께 갱신된다. 별도 구독을 두면 둘이 한 프레임 어긋나
 * 「확인은 끝났는데 사용자는 아직 `null`」인 순간이 생긴다.
 */
export function useAuthResolved(): boolean {
  return useSyncExternalStore(subscribeAuth, isAuthResolved, isAuthResolved)
}
