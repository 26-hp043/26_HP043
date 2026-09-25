import { describe, expect, it } from 'vitest'
import { orderedIssues } from './issueOrder'
import type { DataQualityIssue, Severity } from './types'

/**
 * 할 일 순서 (`#1766`) — 서버가 주는 심각도 순을 **CII 영향 순**으로 다시 늘어놓는다.
 */
function issue(
  severity: Severity,
  voyageNo: string | null,
  delta: string | null,
): DataQualityIssue {
  return {
    severity,
    vesselId: 'v',
    vesselName: '배',
    voyageId: voyageNo === null ? null : `id-${voyageNo}`,
    voyageNo,
    codes: ['DISTANCE'],
    cii:
      delta === null
        ? null
        : {
            attainedCii: '8.214',
            attainedCiiWithout: '8.100',
            delta,
            rating: 'E',
            ratingWithout: 'E',
          },
    ciiReason: delta === null ? 'NO_SPEC' : null,
    publicRecord: null,
  }
}

const order = (issues: DataQualityIssue[]) =>
  orderedIssues(issues).map((i) => i.voyageNo ?? `vessel:${i.severity}`)

describe('할 일 순서 — CII 영향 순 (#1766)', () => {
  it('누적을 많이 올리는 항차가 먼저다 — CII는 낮을수록 좋다', () => {
    const rows = [
      issue('SUBSTITUTED', 'a', '+0.114'),
      issue('ANOMALY', 'b', '+0.208'),
      issue('SUBSTITUTED', 'c', '-0.031'),
    ]
    expect(order(rows)).toEqual(['b', 'a', 'c'])
  })

  it('영향을 알 수 없는 행이 맨 위다 — 0.000과 나란히 두지 않는다', () => {
    const rows = [
      issue('ANOMALY', 'a', '+0.208'),
      issue('UNAVAILABLE', null, null),
      issue('ANOMALY', 'b', '0.000'),
      issue('ANOMALY', 'c', null),
    ]
    /* 알 수 없는 둘이 먼저, 그 안에서는 §2.3.1 표 순서(UNAVAILABLE < ANOMALY). */
    expect(order(rows)).toEqual(['vessel:UNAVAILABLE', 'c', 'a', 'b'])
  })

  it('⚠️ 화면에 같은 숫자로 보이는 둘은 숨은 자리로 가르지 않는다', () => {
    /*
     * 표시 자릿수(3)에서 비교한다 — 둘 다 `0.124`로 찍히는데 순서만 다르면, 화면만 보는
     * 사람에게는 이유 없이 뒤바뀐 것으로 보인다(`display/decimal.ts` · `#820`과 같은 판단).
     * 서버가 준 순서를 그대로 둔다.
     */
    const rows = [issue('ANOMALY', 'a', '0.1235'), issue('ANOMALY', 'b', '0.1244')]
    expect(order(rows)).toEqual(['a', 'b'])
  })

  it('세 자리 안에서 갈리면 순서가 선다', () => {
    const rows = [issue('ANOMALY', 'a', '0.1240'), issue('ANOMALY', 'b', '0.1250')]
    expect(order(rows)).toEqual(['b', 'a'])
  })

  it('같은 영향이면 심각도 표 순서로 가른다 (§2.3.1)', () => {
    const rows = [
      issue('ANOMALY', 'a', '+0.100'),
      issue('SUBSTITUTED', 'b', '+0.100'),
    ]
    expect(order(rows)).toEqual(['b', 'a'])
  })

  it('다섯째 심각도 PUBLIC_RECORD는 표 순서에서 맨 뒤다 (#1197)', () => {
    const rows = [
      issue('PUBLIC_RECORD', 'a', '+0.100'),
      issue('UNCONFIRMED', 'b', '+0.100'),
    ]
    expect(order(rows)).toEqual(['b', 'a'])
  })

  it('원본 배열을 바꾸지 않는다 — 서버가 준 것은 그대로 둔다', () => {
    const rows = [issue('SUBSTITUTED', 'a', '+0.1'), issue('ANOMALY', 'b', '+0.2')]
    const before = rows.map((r) => r.voyageNo)
    orderedIssues(rows)
    expect(rows.map((r) => r.voyageNo)).toEqual(before)
  })
})
