/**
 * 어느 항만에 장면이 있는가 (`#1933`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 화면 회귀 테스트)
 *
 * 이 판정이 두 곳에서 쓰인다 — 핀을 **누를 수 있게** 만들지(`adapters.ts`), 그리고 선택
 * 이벤트로 **장면을 열지**(`HarborTransitionShell`). 한쪽만 알면 「항만이 있는데 들어갈
 * 길이 없는」 상태가 된다.
 */

import { describe, expect, it } from 'vitest'

import { harborSceneFor } from './harborScenes'

describe('harborSceneFor', () => {
  it('핀 id와 선택 이벤트 id 양쪽에서 찾는다', () => {
    expect(harborSceneFor('fleet:KRPUS:35.1000,129.0333')).toBe('busan')
    expect(harborSceneFor('port:fleet:KRPUS:35.1000,129.0333')).toBe('busan')
  })

  it('싱가포르는 두 코드로 온다', () => {
    // 항만표가 쓰는 값은 `SGKEP`다 — `SGSIN`만 보던 종전 판정이 도착 핀을 그림으로 남겼다.
    expect(harborSceneFor('fleet:SGKEP:1.2833,103.8500')).toBe('singapore')
    expect(harborSceneFor('port:SGSIN')).toBe('singapore')
  })

  it('대소문자를 가리지 않는다', () => {
    expect(harborSceneFor('fleet:krpus:35.1,129.0')).toBe('busan')
  })

  it('장면이 없는 항만은 `null`이다', () => {
    // 눌러도 아무 일이 없는 버튼은 고장으로 읽힌다 — 없는 것은 없다고 답해야 한다.
    expect(harborSceneFor('fleet:CNSHA:31.2,121.5')).toBeNull()
    expect(harborSceneFor('fleet:35.1000,129.0333')).toBeNull()
    expect(harborSceneFor(null)).toBeNull()
    expect(harborSceneFor('')).toBeNull()
  })
})
