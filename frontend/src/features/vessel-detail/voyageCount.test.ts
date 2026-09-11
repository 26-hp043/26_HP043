import { describe, expect, it } from 'vitest'
import { voyageCountText } from './voyageCount'

/**
 * 「완료 항차」 칸 표기 (#987 · 결정 3-④).
 *
 * 연간 실적 보고서(`services/report.py` `_voyage_count_cell`)와 **같은 표기**여야 한다 —
 * 같은 값을 화면과 문서가 다르게 적으면 두 값으로 읽힌다.
 */
describe('voyageCountText', () => {
  it('진행 중 항차가 없으면 완료 수만 적는다', () => {
    expect(voyageCountText({ voyageCount: 3, inProgressVoyageCount: 0 })).toBe('3')
  })

  it('진행 중 항차의 기여분이 들어가 있으면 함께 적는다 — 보고서와 같은 모양', () => {
    expect(voyageCountText({ voyageCount: 3, inProgressVoyageCount: 1 })).toBe('3 (+진행 중 1)')
  })

  it('완료 0건이어도 진행분이 있으면 그 사실을 적는다 — 「0」만 적으면 CII가 어디서 왔는지 모른다', () => {
    expect(voyageCountText({ voyageCount: 0, inProgressVoyageCount: 1 })).toBe('0 (+진행 중 1)')
  })
})
