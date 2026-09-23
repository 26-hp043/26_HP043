import { format } from 'node:util'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * 컴포넌트 렌더 테스트의 공통 뒷정리 (#557) · 콘솔 오류 감시 (#1616).
 *
 * ## 왜 필요한가
 *
 * `@testing-library/react`는 `render()`가 만든 DOM을 **자동으로 지우지 않는다**
 * (전역 `afterEach`가 있는 프레임워크에서만 자동 정리가 붙는다). 남겨 두면 다음
 * 테스트의 `screen.getBy*`가 **이전 테스트의 노드를 먼저 찾아** 통과해 버린다.
 *
 * 그 실패는 조용하다 — 테스트가 깨지는 것이 아니라 **잘못된 것을 보고 통과**한다.
 * 그래서 개별 파일에 맡기지 않고 한 곳에 둔다.
 *
 * ## 쓰는 법
 *
 * 컴포넌트 테스트 파일 머리에 두 줄을 적는다.
 *
 * ```ts
 * // @vitest-environment jsdom
 * import '../../test/renderSetup'
 * ```
 *
 * **전역 environment를 바꾸지 않는 이유**는 `vite.config.ts`의 `test` 주석에 있다.
 *
 * ## `console.error`가 찍히면 그 테스트는 실패다 (#1616)
 *
 * React는 중복 key · `act(...)` 누락 · controlled/uncontrolled 전환 같은 경고를 전부
 * `console.error`로 낸다. 테스트는 통과하고 경고만 콘솔에 쌓이는데, **비-TTY 리포터는
 * 그 콘솔을 접어 버려** CI 로그에서는 보이지도 않는다 — 실제로 `#1738`이 fixture 하나를
 * 고친 뒤에도 같은 모양의 중복 key 경고 7건이 두 파일에서 계속 나고 있었다.
 *
 * 경고 문구를 열거해 고르지 않는다. React 19는 `Warning:` 접두어를 뗐고 문구는 판마다
 * 바뀌므로, 목록에 없는 새 경고는 **잡는 것이 없는데 초록**이 된다. 대신 **잠재우지 않은
 * `console.error` 자체**를 실패로 본다 — 지금 스위트에서 그런 호출은 0건이다.
 *
 * `console.error`가 나야 맞는 테스트(오류 경계가 예외를 남기는 경우 등)는 종전처럼
 * `vi.spyOn(console, 'error').mockImplementation(...)`으로 **테스트 안에서** 받는다.
 * 스파이가 감시기 위에 얹히므로 감시기에는 닿지 않는다. `ErrorBoundary.test.tsx` ·
 * `AppShell.test.tsx` · `VoyagePanel.test.tsx`가 그 형태다.
 *
 * 매 테스트 앞에서 감시기를 **원본 위에 새로** 얹고 끝나면 원본으로 되돌린다. 테스트가
 * 스파이를 되돌리지 않고 끝나도 다음 테스트는 원본에서 다시 시작한다.
 */

/** 모듈이 처음 실행될 때의 `console.error` — 감시기가 얹히기 전 원본이다. */
const ORIGINAL_ERROR = console.error

/** 현재 테스트에서 감시기에 닿은 `console.error` 호출 — 인자를 `%s`까지 풀어 둔 문장이다. */
let unexpectedErrors: string[] = []

function watchedError(...args: unknown[]) {
  unexpectedErrors.push(format(...args))
  ORIGINAL_ERROR(...args)
}

beforeEach(() => {
  unexpectedErrors = []
  console.error = watchedError
})

afterEach(() => {
  cleanup()
  console.error = ORIGINAL_ERROR
  if (unexpectedErrors.length > 0) {
    throw new Error(
      `잠재우지 않은 console.error ${unexpectedErrors.length}건 — React 경고면 원인을 고치고, ` +
        `나야 맞는 오류면 테스트 안에서 vi.spyOn(console, 'error')로 받는다 (#1616).\n` +
        unexpectedErrors.map((text, i) => `[${i + 1}] ${text}`).join('\n'),
    )
  }
})
