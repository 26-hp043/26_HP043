import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * 컴포넌트 렌더 테스트의 공통 뒷정리 (#557).
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
 */
afterEach(() => {
  cleanup()
})
