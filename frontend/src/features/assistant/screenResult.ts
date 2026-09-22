/**
 * 화면이 방금 낸 계산 결과 — 챗봇이 「이 결과」를 읽게 한다 (`#1533` · `API_SPEC §15.1`).
 *
 * ## 왜 모듈 하나에 두나
 *
 * 챗봇 오버레이는 셸에 있고(라우트가 바뀌어도 대화가 살아야 한다 · `UIFLOW 2-7`), 결과는
 * 각 화면 안에 있다. 둘을 잇는 상태를 셸까지 끌어올리면 화면 셋의 props가 모두 바뀐다.
 * 오버레이는 **보내는 순간에만** 이 값을 읽으므로 구독이 필요 없다 — 렌더와 무관한 값이다.
 *
 * ## 주소로 묶는다
 *
 * 결과는 **낸 화면의 주소**와 함께 기억한다. 다른 화면으로 옮긴 뒤 물으면 넘기지 않는다 —
 * 사용자는 지금 보는 화면을 두고 묻는데, 떠난 화면의 결과로 답하면 엉뚱한 설명이 된다.
 * 같은 화면에서 선박을 바꾼 경우는 서버가 막는다(상단 선박과 실행의 선박이 다르면 읽지 않는다).
 */

interface ScreenResult {
  readonly runId: string
  readonly path: string
}

let current: ScreenResult | null = null

function here(): string {
  return typeof window === 'undefined' ? '' : window.location.pathname
}

/** 화면이 계산에 성공했을 때 부른다. */
export function publishScreenResult(runId: string | undefined | null): void {
  current = runId ? { runId, path: here() } : null
}

/** 지금 화면이 낸 결과의 실행 id. 다른 화면의 것이면 `undefined`. */
export function currentScreenResult(): string | undefined {
  return current !== null && current.path === here() ? current.runId : undefined
}

/** 검사용 — 모듈 상태를 비운다. */
export function resetScreenResult(): void {
  current = null
}
