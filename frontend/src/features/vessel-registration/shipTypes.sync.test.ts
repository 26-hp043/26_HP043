/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { SHIP_TYPES, capacityAxisOf } from './shipTypes'

/**
 * 선종 목록 드리프트 가드 (#441).
 *
 * `#441`이 「선종 목록은 `calc/capacity.py`의 13종을 따른다 — 화면이 따로 나열하지
 * 않는다」를 완료 기준으로 걸었다. 그런데 **선종을 내려주는 API가 아직 없다**
 * (`#444` 파라미터 조회 API). 목록을 화면에 옮겨 적는 것 말고 방법이 없다.
 *
 * 그래서 「옮겨 적지 않는다」를 **「옮겨 적은 것이 어긋나면 CI가 실패한다」**로 바꾼다.
 * 파이썬 원본을 읽어 코드 집합과 축을 대조한다 — `tokens.sync.test.ts`가 Figma
 * JSON ↔ 생성 CSS에 대해 하는 일과 같은 취지다.
 *
 * ## 왜 이 가드가 필요한가
 *
 * 선종이 늘면 화면에만 없는 선종이 생기는데, **그 상태는 화면을 봐서 드러나지 않는다.**
 * 사용자는 없는 선택지를 그리워할 수 없고, 등록도 계산도 정상으로 보인다. 이 저장소가
 * 오늘 정리한 결함들이 전부 같은 형태였다 — 규칙은 있었고 확인하는 것이 없었다.
 *
 * ## `#444` 이후
 *
 * 서버가 선종 목록을 내려주면 이 가드와 `shipTypes.ts`를 함께 지우고 provider로
 * 바꾼다. 그때까지의 임시 조치이며, **임시라는 사실이 CI에 남아 있는 편**이 낫다.
 */

const capacityPy = readFileSync(
  new URL('../../../../src/cii_platform/calc/capacity.py', import.meta.url),
  'utf8',
)

/**
 * `frozenset({...})` 리터럴에서 코드를 뽑는다.
 *
 * 정규식이 아무것도 못 잡으면 **가드가 조용히 통과**한다(빈 집합 == 빈 집합). 그래서
 * 개수를 함께 단언한다 — 파싱 실패와 「정말 비었다」를 구분한다.
 */
function frozensetCodes(name: string): string[] {
  const block = new RegExp(`${name}[^=]*=\\s*frozenset\\(\\s*\\{([^}]*)\\}`, 'm').exec(capacityPy)
  expect(block, `${name} 정의를 capacity.py에서 찾지 못했다 — 정의 형태가 바뀌었다`).not.toBeNull()
  return Array.from((block as RegExpExecArray)[1].matchAll(/"([A-Z_]+)"/g), (m) => m[1])
}

const dwtBased = frozensetCodes('DWT_BASED_SHIP_TYPES')
const gtBased = frozensetCodes('GT_BASED_SHIP_TYPES')

describe('선종 목록이 capacity.py와 어긋나지 않는다', () => {
  it('원본 파싱 자체가 실패하지 않았다', () => {
    // 이 단언이 없으면 정규식이 깨진 순간부터 아래 대조가 전부 무의미해진다.
    expect(dwtBased).toHaveLength(8)
    expect(gtBased).toHaveLength(5)
  })

  it('코드 집합이 정확히 같다 — 화면에만 없거나 화면에만 있는 선종이 없다', () => {
    const inCode = [...SHIP_TYPES].map((type) => type.code).sort()
    const inPython = [...dwtBased, ...gtBased].sort()
    expect(inCode).toEqual(inPython)
  })

  it('축이 원본의 소속 집합과 같다', () => {
    for (const code of dwtBased) {
      expect(capacityAxisOf(code), `${code}의 축`).toBe('DWT')
    }
    for (const code of gtBased) {
      expect(capacityAxisOf(code), `${code}의 축`).toBe('GT')
    }
  })

  it('중복 코드가 없다 — 셀렉트에 같은 항목이 두 번 뜨지 않는다', () => {
    const codes = SHIP_TYPES.map((type) => type.code)
    expect(new Set(codes).size).toBe(codes.length)
  })

  it('모르는 코드에는 축을 지어내지 않는다', () => {
    expect(capacityAxisOf('BULK_CARIER')).toBeNull()
    expect(capacityAxisOf('')).toBeNull()
  })
})
