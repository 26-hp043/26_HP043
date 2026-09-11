import type { CiiYear } from './types'

/**
 * 「완료 항차」 칸의 표기 (#987 · 결정 3-④).
 *
 * `voyage_count`는 **완료(실적 확정) 항차 수**다(`API_SPEC §2.7`). 그런데 올해 행의 CII·거리·연료에는
 * **진행 중 항차의 기여분**이 들어 있다(`#750`). 완료 수만 적으면 같은 행의 CII가 가리키는 항차
 * 집합과 칸의 수가 어긋나 보인다 — 그래서 진행분이 있으면 함께 적는다.
 *
 * 표기는 연간 실적 보고서와 **같다**(`services/report.py` `_voyage_count_cell`: `3 (+진행 중 1)`).
 * 같은 값을 화면과 문서가 다르게 적으면 두 값으로 읽힌다.
 */
export function voyageCountText(year: Pick<CiiYear, 'voyageCount' | 'inProgressVoyageCount'>): string {
  const done = String(year.voyageCount)
  return year.inProgressVoyageCount > 0
    ? `${done} (+진행 중 ${year.inProgressVoyageCount})`
    : done
}
