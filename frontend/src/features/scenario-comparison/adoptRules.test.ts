import { describe, expect, it } from 'vitest'
import { adoptConfirmMessage, fieldLabel, invalidatedMessage, isPlanning } from './adoptRules'

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

/**
 * 무효화 건수 문구 (`#1077` · `API_SPEC §5.2`).
 *
 * `#817`이 2026-09-11에 닫혀 이 수가 참값이 됐다. 여기서 잠그는 것은 **「없음」 세 종류가
 * 서로 다르게 보이는 것**이다 — 같은 모양으로 그리면 사용자는 가장 나쁜 해석을 고른다.
 */
describe('무효화 건수 — 없음의 종류를 구분한다', () => {
  it('서버가 수를 싣지 않으면 수를 말하지 않는다 — 「알 수 없다」를 0건으로 적지 않는다', () => {
    const message = invalidatedMessage(undefined)

    expect(message).toBe('계획이 바뀌어 이 항차의 기존 계산 결과는 다시 계산해야 합니다.')
    // 수가 없는데 수를 적으면 사용자는 없는 사실을 읽는다.
    expect(message).not.toMatch(/\d/)
  })

  it('0건은 「없다」로 단정하지 않는다 — 이미 전부 표시된 상태도 0이다', () => {
    const message = invalidatedMessage(0)

    // `API_SPEC §5.2`가 0의 두 뜻을 모두 규정한다 — 둘 다 적는다.
    expect(message).toMatch(/계산 이력이 없거나, 이미 전부 표시돼 있습니다/)
    // ⚠️ 「무효화된 계산이 없습니다」로 적으면 「옛 계산이 아직 유효하다」로 읽힌다 —
    // 이 표시가 막으려던 바로 그 오해다.
    expect(message).not.toMatch(/무효화된 계산(이|은) 없습니다/)
    // 사실은 그대로 남는다 — 계획이 바뀌었으니 다시 계산해야 한다.
    expect(message).toMatch(/다시 계산해야 합니다/)
  })

  it('n건이면 그 수를 적는다', () => {
    expect(invalidatedMessage(7)).toMatch(/계산 결과 7건에 재계산 필요 표시를 남겼습니다/)
    expect(invalidatedMessage(1)).toMatch(/계산 결과 1건에/)
  })

  it('세 경우의 문장이 서로 다르다 — 구분이 문구에서 실제로 드러난다', () => {
    const messages = [invalidatedMessage(undefined), invalidatedMessage(0), invalidatedMessage(3)]

    expect(new Set(messages).size).toBe(3)
  })
})
