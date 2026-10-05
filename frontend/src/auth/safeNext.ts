import { matchPath } from 'react-router'
import { SCREEN_BY_ID } from '../screens'

/** 검사를 통과하지 못한 값이 가는 곳 — 앱 루트가 기본 화면으로 보낸다. */
const FALLBACK = '/'

/**
 * 창이 없는 환경(테스트·SSR)에서 상대 경로를 해석할 기준. 실제 원점이 아니므로
 * 절대 주소는 여기서도 전부 「다른 원점」으로 판정된다.
 */
const PLACEHOLDER_ORIGIN = 'http://same-origin.invalid'

/** 역슬래시와 제어문자(탭·개행 포함). 하나라도 있으면 거부한다. */
// eslint-disable-next-line no-control-regex -- 제어문자를 찾는 것이 이 식의 목적이다.
const FORBIDDEN_CHARS = /[\\\u0000-\u001f\u007f]/

/**
 * 라우터가 이 경로를 로그인 화면에 닿게 하는가.
 *
 * **라우터와 같은 판정**을 쓴다. 문자열 일치로 보면 `/login/`·`/LOGIN`이 빠져나가는데,
 * 라우터는 대소문자와 끝 슬래시를 가리지 않아 둘 다 로그인 화면에 닿는다. 라우터는
 * 맞추기 전에 경로를 풀어 읽으므로(`/%6Cogin`도 로그인 화면이다) 여기서도 풀어서 본다.
 */
function isLoginPath(pathname: string): boolean {
  let decoded = pathname
  try {
    decoded = decodeURI(pathname)
  } catch {
    // 풀 수 없는 경로는 라우터도 원문으로 맞춘다.
  }
  return matchPath({ path: SCREEN_BY_ID.LOGIN.path, end: true }, decoded) !== null
}

/**
 * `?next=` 복귀 경로 — **앱 내부 경로만** 허용한다 (`#2127`).
 *
 * 외부 URL을 그대로 쓰면 open redirect가 된다. 로그인 직후 이동하는 자리라
 * 공격자가 이 값을 심으면 사용자가 로그인한 상태로 외부 사이트에 도착한다.
 *
 * ## 접두어가 아니라 해석 결과로 판정한다
 *
 * 종전 검사는 `/`로 시작하고 `//`로 시작하지 않는지만 봤다. 그런데 **브라우저의 URL
 * 해석은 그 문자열 규칙과 다르다** — 역슬래시를 `/`로 읽고(`/\evil.example`은
 * `//evil.example`과 같은 뜻이 된다), 탭·개행을 지우고(`/<탭>/evil.example`), 점
 * 구간을 접는다(`/.//evil.example`의 경로는 `//evil.example`이다). 셋 다 종전 검사를
 * 통과했다.
 *
 * 그래서 브라우저와 **같은 해석기**(`URL`)에 넣어 원점이 그대로인지 보고, 넘기는 값도
 * 원문이 아니라 **해석 결과**(`pathname + search + hash`)를 쓴다. 역슬래시·제어문자는
 * 정상 경로에 나올 일이 없어 해석 전에 거부한다.
 *
 * 로그인 화면 자신도 거부한다 — 로그인한 사람을 로그인 화면으로 되돌리는 값이다.
 *
 * 이 함수는 `auth/session.ts`의 `redirectToLogin`과 로그인 화면이 **함께** 쓴다.
 * 종전에는 같은 검사가 두 곳에 사본으로 있었다.
 */
export function safeNext(raw: string | null | undefined): string {
  // 타입으로는 막혀 있지만, 문자열이 아닌 값이 흘러들어도 던지지 않는다.
  if (typeof raw !== 'string') return FALLBACK
  if (!raw || FORBIDDEN_CHARS.test(raw)) return FALLBACK
  if (!raw.startsWith('/') || raw.startsWith('//')) return FALLBACK

  const origin = typeof window === 'undefined' ? PLACEHOLDER_ORIGIN : window.location.origin
  let url: URL
  try {
    url = new URL(raw, origin)
    if (url.origin !== new URL(origin).origin) return FALLBACK
  } catch {
    return FALLBACK
  }
  // 점 구간이 접히면 경로가 `//…`가 될 수 있다 — 그 값은 다시 다른 원점으로 읽힌다.
  if (url.pathname.startsWith('//')) return FALLBACK
  if (isLoginPath(url.pathname)) return FALLBACK
  return `${url.pathname}${url.search}${url.hash}`
}
