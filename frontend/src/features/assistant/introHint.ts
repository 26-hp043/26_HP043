/**
 * 범이 첫 방문 안내 (#2205) — 말풍선을 띄울지 정하는 규칙.
 *
 * 컴포넌트 파일에서 함수를 내보내면 fast refresh가 깨지므로(`only-export-components`)
 * 규칙만 여기 둔다 — `fleet/panelState.ts`와 같은 자리다.
 *
 * ## 무엇을 기억하나
 *
 * | 동작 | 기억하는 곳 | 다시 뜨는가 |
 * |---|---|---|
 * | 「닫기」 | `sessionStorage` | 이 탭에서는 안 뜬다. 새 탭 · 다음 방문에는 다시 뜬다 |
 * | 「다시 보지 않기」 | `localStorage` | 이 브라우저에서는 다시 안 뜬다 |
 * | 패널을 한 번 연다 | `localStorage` | 범이를 이미 찾았으므로 안내가 할 일이 없다 |
 *
 * ⚠️ **서버에 보내지 않는다.** 계정의 설정이 아니라 **이 브라우저의 습관**이다
 * (`panelState.ts`의 판단과 같다). 저장이 막힌 환경(사생활 보호 창 등)에서도 화면이
 * 서야 하므로 읽기 · 쓰기를 모두 `try`로 감싼다 — 읽지 못하면 **띄운다**(안내는
 * 닫으면 그만이지만, 못 본 안내는 되돌릴 수 없다).
 */
export const INTRO_HINT_DISMISSED_KEY = 'bluelog.assistant.introHintDismissed'
export const INTRO_HINT_CLOSED_KEY = 'bluelog.assistant.introHintClosed'

function read(storage: () => Storage | undefined, key: string): boolean {
  try {
    return storage()?.getItem(key) === 'true'
  } catch {
    return false
  }
}

function write(storage: () => Storage | undefined, key: string): void {
  try {
    storage()?.setItem(key, 'true')
  } catch {
    // 기억하지 못해도 지금 화면에서는 닫힌다.
  }
}

const local = () => (typeof window === 'undefined' ? undefined : window.localStorage)
const session = () => (typeof window === 'undefined' ? undefined : window.sessionStorage)

/** 지금 말풍선을 띄울지. */
export function shouldShowIntroHint(): boolean {
  return !read(local, INTRO_HINT_DISMISSED_KEY) && !read(session, INTRO_HINT_CLOSED_KEY)
}

/** 「닫기」 — 이 탭에서만. */
export function closeIntroHint(): void {
  write(session, INTRO_HINT_CLOSED_KEY)
}

/** 「다시 보지 않기」 · 패널 열기 — 이 브라우저에서 계속. */
export function dismissIntroHint(): void {
  write(local, INTRO_HINT_DISMISSED_KEY)
}
