import { describe, expect, it } from 'vitest'
import { ANNUAL_COPY, FORBIDDEN_PHRASES } from './copy'

/**
 * `#157` 완료 기준 — 「연말 예상」·「누적 기준」 등 **근거 없는 표현이 화면에 없음**.
 *
 * 문구가 JSX에 흩어져 있으면 이 검사를 할 수 없다. `copy.ts`에 모아 둔 이유다.
 */
describe('화면 문구에 근거 없는 표현이 없다', () => {
  const entries = Object.entries(ANNUAL_COPY)

  it.each(FORBIDDEN_PHRASES)('「%s」가 어느 문구에도 없다', (phrase) => {
    const hits = entries.filter(([, text]) => text.includes(phrase))
    expect(hits.map(([key]) => key)).toEqual([])
  })

  it('등급 레이블이 금지 표현을 쓰지 않는다', () => {
    // 요건은 「참고 등급」이라는 문구 자체가 아니라 **「예상 등급」을 쓰지 않는 것**이다
    // (#136). 금지 표현 전수 검사가 위에 있으므로 여기서는 레이블이 비지 않았는지만 본다.
    expect(ANNUAL_COPY.ratingLabel.length).toBeGreaterThan(0)
    expect(FORBIDDEN_PHRASES.some((phrase) => ANNUAL_COPY.ratingLabel.includes(phrase))).toBe(false)
  })

  it('예시 데이터임을 배지와 안내 문구 양쪽에서 밝힌다', () => {
    // #157 완료 기준은 「실제 계산 결과가 아님을 화면에서 구분 가능하게」다. 배지의
    // 문구가 무엇인지가 아니라 **배지가 있는지**가 요건이다.
    expect(ANNUAL_COPY.sampleBadge.length).toBeGreaterThan(0)
    expect(ANNUAL_COPY.sampleNotice).toContain('실제 계산 결과가 아니')
  })

  it('빈 상태·로딩·오류 문구가 준비돼 있다', () => {
    // 화면이 깨지지 않을 것 — #157 완료 기준
    expect(ANNUAL_COPY.loading.length).toBeGreaterThan(0)
    expect(ANNUAL_COPY.empty.length).toBeGreaterThan(0)
    expect(ANNUAL_COPY.errorTitle.length).toBeGreaterThan(0)
  })
})
