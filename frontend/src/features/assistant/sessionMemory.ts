/**
 * 대화 번호를 **탭 안에만** 기억한다 (`#1981` · `UIFLOW 2-7`).
 *
 * ## 왜 `sessionStorage`인가
 *
 * 2026-09-28 결정 — 새로고침하면 방금 하던 대화가 이어지고, **탭을 닫으면 새 대화로 시작한다.**
 * `localStorage`면 탭을 닫아도 남고, 화면 메모리면 새로고침에 사라진다. 전역 컨텍스트(선박
 * 선택 · `layout/globalContext.ts`)가 같은 이유로 같은 저장소를 쓴다.
 *
 * ## 읽기·쓰기 실패는 조용히 새 대화다
 *
 * 저장소가 막힌 브라우저(사생활 모드 · 시크릿 창)에서 챗봇이 죽으면 격리 실패다(`PRD §16.2`).
 * 기억은 편의이지 기능이 아니므로, 못 하면 종전처럼 새 대화로 시작한다.
 *
 * ## 탭을 복제하면 같은 대화가 이어진다
 *
 * Chrome의 「탭 복제」는 `sessionStorage`를 새 탭에 **복사**한다. 그 탭도 같은 번호를 들고
 * 서버에 가므로 두 탭이 한 대화를 잇는다 — 「새 탭은 새 대화」의 예외이며, 결정(탭마다)이
 * 막으려던 것(닫은 뒤 다시 켠 브라우저 · 따로 연 탭)은 아니다. 두 탭이 번갈아 물으면 서버 이력은
 * 하나로 쌓이고 각 탭의 화면은 자기가 보낸 것만 보인다 — 다음 새로고침이 전부를 되살린다.
 *
 * ## 번호는 비밀이 아니지만 남의 것을 열지는 못한다
 *
 * 로그아웃은 같은 탭에서 이동하므로 저장값이 남는다 — 다음 계정이 앞 계정의 번호를 들고
 * 서버에 가면 **서버가 404로 끊는다**(`API_SPEC §15.8` — 남의 대화는 없는 대화다). 그래도
 * `logout()`과 `login()`·`tourLogin()` 성공이 이 값을 지운다(`globalContext.clearStored`와 같은
 * 자리) — 서버 한 겹에만 기대지 않는다.
 */

/** `sessionStorage` 키. 다른 저장값과 섞이지 않도록 접두를 붙인다. */
export const SESSION_KEY = 'bluelog.assistant.session'

/** SSR·테스트 환경에 `sessionStorage`가 없을 수 있다. */
function safeSessionStorage(): Storage | undefined {
  try {
    return globalThis.sessionStorage
  } catch {
    return undefined
  }
}

/** 기억해 둔 대화 번호. 없거나 읽지 못하면 `undefined`. */
export function recallSession(storage: Storage | undefined = safeSessionStorage()): string | undefined {
  if (!storage) return undefined
  try {
    const value = storage.getItem(SESSION_KEY)
    return value ? value : undefined
  } catch {
    return undefined
  }
}

/** 대화 번호를 기억한다. 실패는 무시한다 — 다음 새로고침이 새 대화로 시작할 뿐이다. */
export function rememberSession(
  sessionId: string,
  storage: Storage | undefined = safeSessionStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(SESSION_KEY, sessionId)
  } catch {
    /* 저장 실패는 무시한다 — 위 머리말. */
  }
}

/** 기억을 지운다 — 대화를 지웠거나(`DELETE`), 서버가 그 번호를 모른다고 했을 때. */
export function forgetSession(storage: Storage | undefined = safeSessionStorage()): void {
  if (!storage) return
  try {
    storage.removeItem(SESSION_KEY)
  } catch {
    /* 지우기 실패도 무시한다 — 저장과 같은 이유. */
  }
}
