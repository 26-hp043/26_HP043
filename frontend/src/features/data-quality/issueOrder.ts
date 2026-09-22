import { compareFixed } from '../../display/decimal'
import { SEVERITIES, type DataQualityIssue } from './types'

/**
 * 할 일 순서 — **CII 영향 순** (`#1766`).
 *
 * ## 왜 화면이 정렬하나
 *
 * 서버는 `DESIGN_SYSTEM §2.3.1` 표 순서(심각도)로 준다. 그 순서는 **분류**이지 「무엇부터
 * 손대야 하나」가 아니다 — 누적 CII를 가장 많이 올리고 있는 항차가 세 번째 그룹에 있을 수
 * 있다(실측: `+0.208` 이상치가 화면 중간).
 *
 * `#1741`(선박 상세 항차 목록)에서는 화면 정렬을 **하지 않기로** 했다. 서버가 커서로 잘라
 * 주므로 한 페이지 안에서만 맞고 「더 보기」로 이어 받으면 어긋나기 때문이다. **이 화면은
 * 다르다** — `GET /fleet/data-quality`(`API_SPEC §2.16`)는 `issues`를 커서도 `limit`도 없이
 * 한 번에 전부 준다. 전체를 손에 쥐고 늘어놓으므로 어긋날 자리가 없다.
 *
 * ## 영향을 알 수 없는 행이 먼저다
 *
 * 값이 없는 행은 **「영향이 0」이 아니다.** 계산 불가는 그 항차가 누적에서 통째로 빠져 있고
 * (시연 데이터에서 제외 CO₂가 가장 크다), 판정 불가는 **손대야 비로소 판정이 생긴다.**
 * 0.000과 나란히 두면 「볼 것 없음」으로 읽히므로 위로 올린다. 그 안에서는 `§2.3.1` 표 순서다.
 *
 * ## 비교는 `Number`를 거치지 않는다
 *
 * `API_SPEC §1.7` `[ORACLE-C-1]`. `compareFixed`가 표시 자릿수에서 `BigInt`로 비교하므로
 * **화면에 찍힌 숫자와 순서가 어긋나지 않는다** — `+0.208`이 `+0.114`보다 위에 있는 것을
 * 눈으로 확인할 수 있다(`display/decimal.ts` · `#820`).
 */

/** CII 영향 칸의 자릿수 — `Impact`가 그리는 값과 같다. */
export const IMPACT_DIGITS = 3

const SEVERITY_RANK = new Map(SEVERITIES.map((severity, index) => [severity, index]))

/**
 * 표에 늘어놓을 순서. **원본 배열을 바꾸지 않는다** — 서버가 준 것은 그대로 둔다.
 *
 * 같은 값이면 `§2.3.1` 심각도 순으로 가르고, 그래도 같으면 서버가 준 순서를 지킨다
 * (`Array.prototype.sort`는 안정 정렬이다).
 */
export function orderedIssues(issues: readonly DataQualityIssue[]): DataQualityIssue[] {
  return [...issues].sort((a, b) => {
    const known = (issue: DataQualityIssue) => (issue.cii === null ? 0 : 1)
    if (known(a) !== known(b)) return known(a) - known(b)
    if (a.cii !== null && b.cii !== null) {
      // 누적을 많이 **올리는**(+) 것부터 — CII는 낮을수록 좋다(`§4.3`).
      const byImpact = compareFixed(b.cii.delta, a.cii.delta, IMPACT_DIGITS)
      if (byImpact !== 0) return byImpact
    }
    return (SEVERITY_RANK.get(a.severity) ?? 0) - (SEVERITY_RANK.get(b.severity) ?? 0)
  })
}
