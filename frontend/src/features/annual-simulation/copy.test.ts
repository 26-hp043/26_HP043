import { describe, expect, it } from 'vitest'
import { ANNUAL_COPY, FORBIDDEN_PHRASES } from './copy'
import { WARNING_MESSAGE } from '../voyage-cii/resultRules'

/**
 * 기능③ 화면이 그리는 문구에 금지 표현이 없다 (`#157` · **범위는 `#749`에서 넓혔다**).
 *
 * 종전에는 `ANNUAL_COPY`만 봤는데 테스트 이름은 「어느 문구에도 없다」였다. 이 화면은
 * 경고를 `voyage-cii/resultRules.ts`의 `WARNING_MESSAGE`로 그리므로(`warningMessage`)
 * **그쪽 문구가 검사 밖**이었고, 실제로 금지 낱말이 든 경고가 데모 선박 두 척에서 떴다.
 *
 * 범위를 이름에 적는다 — 이 화면이 문구를 가져오는 두 곳이다. 문구를 가져오는 곳이
 * 늘면 여기에 더한다.
 */
describe('기능③이 그리는 문구에 금지 표현이 없다', () => {
  const entries: Array<[string, string]> = [
    ...Object.entries(ANNUAL_COPY).map(([key, text]): [string, string] => [`ANNUAL_COPY.${key}`, text]),
    ...Object.entries(WARNING_MESSAGE).map(([key, text]): [string, string] => [
      `WARNING_MESSAGE.${key}`,
      text,
    ]),
  ]

  it('검사 대상에 경고 문구가 들어 있다', () => {
    // 범위가 다시 `ANNUAL_COPY`로 좁아지면 아래 검사는 통과하지만 경고 문구를 못 본다.
    expect(entries.some(([key]) => key === 'WARNING_MESSAGE.NO_REMAINING_VOYAGES')).toBe(true)
  })

  it.each(FORBIDDEN_PHRASES)('「%s」가 화면 문구·경고 문구 어디에도 없다', (phrase) => {
    const hits = entries.filter(([, text]) => text.includes(phrase))
    expect(hits.map(([key]) => key)).toEqual([])
  })

  it('등급 레이블이 금지 표현을 쓰지 않는다', () => {
    // `#136`의 「예상 등급」 금지는 `#749`에서 풀렸다(근거 소멸 · `PRD COR-2` — `copy.ts`
    // 표). 금지 표현 전수 검사가 위에 있으므로 여기서는 레이블이 비지 않았는지만 본다.
    expect(ANNUAL_COPY.projectedRatingLabel.length).toBeGreaterThan(0)
    expect(
      FORBIDDEN_PHRASES.some((phrase) => ANNUAL_COPY.projectedRatingLabel.includes(phrase)),
    ).toBe(false)
  })

  it('예시 데이터임을 배지와 안내 문구 양쪽에서 밝힌다', () => {
    // #157 완료 기준은 「실제 계산 결과가 아님을 화면에서 구분 가능하게」다. 배지의
    // 문구가 무엇인지가 아니라 **배지가 있는지**가 요건이다.
    expect(ANNUAL_COPY.sampleBadge.length).toBeGreaterThan(0)
    // 어미까지 단언하지 않는다 — 「아니며」·「아닙니다」는 같은 뜻인데 부분 문자열이
    // 달라 문구를 다듬을 때마다 깨진다 (`AGENTS §4.6`).
    expect(ANNUAL_COPY.sampleNotice).toContain('실제 계산 결과')
  })

  it('빈 상태·로딩·오류 문구가 준비돼 있다', () => {
    // 화면이 깨지지 않을 것 — #157 완료 기준
    expect(ANNUAL_COPY.loading.length).toBeGreaterThan(0)
    expect(ANNUAL_COPY.empty.length).toBeGreaterThan(0)
    expect(ANNUAL_COPY.errorTitle.length).toBeGreaterThan(0)
  })
})
