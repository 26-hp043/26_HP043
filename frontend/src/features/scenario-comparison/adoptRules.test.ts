import { describe, expect, it } from 'vitest'
import { adoptConfirmMessage, fieldLabel, isPlanning } from './adoptRules'

/** 시나리오 채택의 순수 규칙 (`#580`). */
describe('채택 대상 — 계획 단계 항차만', () => {
  it('작성 중·계획 확정만 받는다 — 서버 PLANNING_STATUSES와 같다', () => {
    expect(['DRAFT', 'PLANNED'].every(isPlanning)).toBe(true)
    // 출항 뒤 계획을 갈아 끼우면 계획 대비 실적 비교의 기준선이 사라진다.
    for (const status of ['IN_PROGRESS', 'COMPLETED', 'CONFIRMED', 'CANCELLED', 'ARCHIVED']) {
      expect(isPlanning(status), status).toBe(false)
    }
  })
})

describe('확인 문구 — 되돌릴 수 없음을 채택 전에 알린다', () => {
  const text = adoptConfirmMessage('2026-03', '감속')

  it('무엇을 덮어쓰는지와 되돌릴 수 없다는 것을 말한다', () => {
    expect(text).toContain('「2026-03」')
    expect(text).toContain('「감속」')
    expect(text).toContain('덮어씁니다')
    expect(text).toContain('되돌릴 수 없습니다')
  })

  it('「취소는 안 되지만 다른 안으로 바꿀 수는 있다」를 함께 말한다', () => {
    // 서버 `_clear_previous_adoption()`이 이전 채택을 내리고 새 값으로 덮는다.
    expect(text).toContain('다른 시나리오를 다시 반영하면')
  })
})

describe('바뀐 필드의 이름', () => {
  it('서버 필드를 화면 이름으로 옮긴다', () => {
    expect(['planned_distance_nm', 'planned_speed_kn', 'planned_arrival_at'].map(fieldLabel)).toEqual([
      '항해거리',
      '평균 속력',
      '도착 예정 시각',
    ])
  })

  it('모르는 필드는 원문을 보인다 — 서버가 필드를 늘려도 조용히 감추지 않는다', () => {
    expect(fieldLabel('planned_fuel_ton')).toBe('planned_fuel_ton')
  })
})
