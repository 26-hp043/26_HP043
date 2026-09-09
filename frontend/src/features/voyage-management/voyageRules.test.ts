import { describe, expect, it } from 'vitest'
import {
  actualsPayload,
  canEnterActuals,
  hasErrors,
  nextStatuses,
  policyForTransition,
  toIsoInstant,
  toLocalInput,
  transitionBlocker,
  validateActuals,
  validateDraft,
} from './voyageRules'
import type { ActualsDraft, ManagedVoyage, VoyageDraft } from './types'

const voyage = (over: Partial<ManagedVoyage> = {}): ManagedVoyage => ({
  id: 'v1',
  voyageNo: 'V-2026-001',
  status: 'IN_PROGRESS',
  inclusionPolicy: 'INCLUDE_AS_PLAN',
  regulationYear: 2026,
  departurePortName: 'Busan',
  arrivalPortName: 'Rotterdam',
  plannedDistanceNm: 11000,
  plannedSpeedKn: 14,
  actualDistanceNm: null,
  actualAvgSpeedKn: null,
  plannedDepartureAt: null,
  plannedArrivalAt: null,
  actualDepartureAt: null,
  actualArrivalAt: null,
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 800, actualFuelTon: null }],
  ...over,
})

const draft = (over: Partial<VoyageDraft> = {}): VoyageDraft => ({
  voyageNo: 'V-2026-002',
  departurePortName: 'Busan',
  arrivalPortName: 'Singapore',
  plannedDistanceNm: '2800',
  plannedSpeedKn: '13.5',
  plannedDepartureAt: '',
  plannedArrivalAt: '',
  regulationYear: '2026',
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: '210' }],
  ...over,
})

const actuals = (over: Partial<ActualsDraft> = {}): ActualsDraft => ({
  actualDistanceNm: '',
  actualAvgSpeedKn: '',
  actualDepartureAt: '',
  actualArrivalAt: '',
  actualFuelTon: {},
  ...over,
})

describe('nextStatuses — services/voyage.py _TRANSITIONS와 같아야 한다', () => {
  it('데모 동선을 잇는다', () => {
    expect(nextStatuses('DRAFT')).toContain('PLANNED')
    expect(nextStatuses('PLANNED')).toContain('IN_PROGRESS')
    expect(nextStatuses('IN_PROGRESS')).toContain('COMPLETED')
  })

  it('종결 상태에서는 나갈 곳이 없다', () => {
    expect(nextStatuses('CANCELLED')).toEqual([])
    expect(nextStatuses('ARCHIVED')).toEqual([])
  })
})

describe('canEnterActuals — API_SPEC §3.6 상태별 허용', () => {
  it('뜬 항차에만 실적이 있다', () => {
    expect(canEnterActuals('IN_PROGRESS')).toBe(true)
    expect(canEnterActuals('COMPLETED')).toBe(true)
  })

  it('아직 뜨지 않았거나 확정·종결된 항차에는 폼을 열지 않는다', () => {
    for (const status of ['DRAFT', 'PLANNED', 'CONFIRMED', 'CANCELLED', 'ARCHIVED'] as const) {
      expect(canEnterActuals(status)).toBe(false)
    }
  })
})

describe('policyForTransition — 데모 마지막 한 걸음이 여기서 막혔다', () => {
  /*
   * `§3.5` — 목표 상태가 현행 policy를 허용하지 않으면 서버는 자동 보정하지 않고
   * 422로 거부한다. 계획으로 잡아 둔 항차를 완료로 옮기는 것이 정확히 그 경우다.
   */
  it('INCLUDE_AS_PLAN 항차를 COMPLETED로 보낼 때 실적 반영으로 이어 준다', () => {
    expect(policyForTransition('INCLUDE_AS_PLAN', 'COMPLETED')).toBe('INCLUDE_AS_ACTUAL')
  })

  it('목표 상태가 현행을 허용하면 생략한다 — 생략은 현행 유지다', () => {
    expect(policyForTransition('INCLUDE_AS_PLAN', 'IN_PROGRESS')).toBeNull()
    expect(policyForTransition('EXCLUDE', 'PLANNED')).toBeNull()
  })

  it('EXCLUDE only 상태로 가면 반영을 끈다', () => {
    expect(policyForTransition('INCLUDE_AS_PLAN', 'CANCELLED')).toBe('EXCLUDE')
  })
})

describe('transitionBlocker', () => {
  it('실적 연료가 없으면 완료로 가지 못한다 (ORACLE-C-4)', () => {
    expect(transitionBlocker(voyage(), 'COMPLETED')).toMatch(/실적 연료/)
  })

  it('실적 연료가 있으면 통과한다', () => {
    const ready = voyage({
      fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 800, actualFuelTon: 850 }],
    })
    expect(transitionBlocker(ready, 'COMPLETED')).toBeNull()
  })

  it('기준연도 없이 연간 반영을 켜지 못한다 (#150)', () => {
    const noYear = voyage({
      status: 'DRAFT',
      inclusionPolicy: 'EXCLUDE',
      regulationYear: null,
    })
    // DRAFT → PLANNED 자체는 열려 있지만, 반영이 켜져 있으면 기준연도를 요구한다.
    const planned = { ...noYear, inclusionPolicy: 'INCLUDE_AS_PLAN' as const, status: 'PLANNED' as const }
    expect(transitionBlocker(planned, 'IN_PROGRESS')).toMatch(/기준연도/)
  })

  it('허용표에 없는 전환은 사유를 준다', () => {
    expect(transitionBlocker(voyage({ status: 'DRAFT' }), 'COMPLETED')).toMatch(/갈 수 없는/)
  })
})

describe('validateDraft — API_SPEC §3.3', () => {
  it('정상 입력은 통과한다', () => {
    expect(hasErrors(validateDraft(draft()))).toBe(false)
  })

  it('기준연도는 선택이다 — 비어 있어도 통과한다', () => {
    expect(hasErrors(validateDraft(draft({ regulationYear: '' })))).toBe(false)
  })

  it('속력 하한은 1.0 kn다', () => {
    expect(validateDraft(draft({ plannedSpeedKn: '0.5' })).plannedSpeedKn).toBeDefined()
  })

  it('숫자가 아닌 값을 잡는다', () => {
    expect(validateDraft(draft({ plannedDistanceNm: '십일천' })).plannedDistanceNm).toBeDefined()
  })
})

describe('validateDraft — 연료 다행 (#636)', () => {
  it('서로 다른 유종 여러 줄은 통과한다', () => {
    const found = validateDraft(
      draft({
        fuelUses: [
          { fuelType: 'HFO', plannedFuelTon: '800' },
          { fuelType: 'DIESEL_GAS_OIL', plannedFuelTon: '40' },
        ],
      }),
    )
    expect(hasErrors(found)).toBe(false)
  })

  it('줄마다 오류 키가 분리된다 — 어느 줄이 틀렸는지 화면이 가리켜야 한다', () => {
    const found = validateDraft(
      draft({
        fuelUses: [
          { fuelType: 'HFO', plannedFuelTon: '800' },
          { fuelType: 'DIESEL_GAS_OIL', plannedFuelTon: '0' },
        ],
      }),
    )
    expect(found['plannedFuelTon.0']).toBeUndefined()
    expect(found['plannedFuelTon.1']).toBeDefined()
  })

  it('같은 유종이 두 번이면 뒤쪽 줄을 가리킨다 — 서버는 422를 내지만 줄 번호가 없다', () => {
    const found = validateDraft(
      draft({
        fuelUses: [
          { fuelType: 'HFO', plannedFuelTon: '800' },
          { fuelType: 'HFO', plannedFuelTon: '200' },
        ],
      }),
    )
    expect(found['fuelType.0']).toBeUndefined()
    expect(found['fuelType.1']).toContain('두 번')
  })

  it('한 줄도 없으면 잡는다 — 서버가 min_length=1을 요구한다 (§3.3)', () => {
    expect(validateDraft(draft({ fuelUses: [] })).fuelUses).toBeDefined()
  })

  it('빈 유종은 중복 판정에 넣지 않는다 — 「선택해 주세요」가 먼저다', () => {
    const found = validateDraft(
      draft({
        fuelUses: [
          { fuelType: '', plannedFuelTon: '800' },
          { fuelType: '', plannedFuelTon: '200' },
        ],
      }),
    )
    expect(found['fuelType.0']).toContain('선택')
    expect(found['fuelType.1']).toContain('선택')
  })
})

describe('validateActuals — 모든 항목이 선택이다', () => {
  it('전부 비어 있어도 오류가 아니다 — 생략은 「변경 없음」이다', () => {
    expect(hasErrors(validateActuals(actuals()))).toBe(false)
  })

  it('거리만 먼저 넣는 것을 허용한다', () => {
    expect(hasErrors(validateActuals(actuals({ actualDistanceNm: '11200' })))).toBe(false)
  })

  it('들어온 값이 서버 제약을 어기면 잡는다', () => {
    expect(validateActuals(actuals({ actualFuelTon: { HFO: '0' } }))['actualFuelTon.HFO']).toBeDefined()
    expect(validateActuals(actuals({ actualAvgSpeedKn: '0.9' })).actualAvgSpeedKn).toBeDefined()
  })
})

describe('actualsPayload — 빈 칸은 키 자체를 보내지 않는다', () => {
  it('입력한 것만 담는다', () => {
    const payload = actualsPayload(
      actuals({ actualDistanceNm: '11200', actualFuelTon: { HFO: '850', MDO: '' } }),
    )
    expect(payload).toEqual({
      actual_distance_nm: 11200,
      fuel_uses: [{ fuel_type: 'HFO', actual_fuel_ton: 850, source: 'USER_INPUT' }],
    })
  })

  it('계획값을 절대 싣지 않는다 — PRD §8.4 계획값 보존', () => {
    const payload = actualsPayload(actuals({ actualDistanceNm: '11200' }))
    expect(JSON.stringify(payload)).not.toMatch(/planned/)
  })

  it('아무것도 안 넣으면 빈 본문이다', () => {
    expect(actualsPayload(actuals())).toEqual({})
  })
})

/**
 * 항차 시각 4종 (#873).
 *
 * **화면이 이 네 값을 어디에서도 수집하지 않았다** — 프론트 전체 참조 0건(grep 실측).
 * 서버는 `§3.3`·`§3.6`에서 처음부터 받고 있었으므로 계약이 아니라 화면이 빠져 있었다.
 *
 * 결과: 화면으로 만든 항차는 출항 시각이 영원히 `null`이고, 진행 중으로 옮기면
 * 시뮬레이션 시계가 `departure_at is None`에서 거리·연료 **0**을 돌려준다
 * (`services/simulation_clock.py:177`). 경고 체계는 `distance_nm > 0`을 전제하므로
 * 그 0도 잡지 못한다 — **조용히 0으로 기여한다.**
 *
 * ⚠️ 로컬 스택 실측으로 확정했다(`#616` 선례). 화면의 `create` 본문 그대로 보내
 * 201을 받았고 `planned_departure_at`이 `None`이었으며, `IN_PROGRESS` 전환 뒤
 * `/cii/current`의 `warnings`가 `null`이었다.
 */
describe('항차 시각 다리 — 화면 값 ↔ 서버 값 (#873)', () => {
  it('빈 칸은 null이다 — 「보내지 않는다」의 표현이다', () => {
    expect(toIsoInstant('')).toBeNull()
    expect(toIsoInstant('   ')).toBeNull()
  })

  it('읽을 수 없는 값도 null이다 — 지어내지 않는다', () => {
    expect(toIsoInstant('내일 아침')).toBeNull()
  })

  it('지역 시각으로 읽어 UTC 문자열로 낸다 — 왕복하면 같은 값이다', () => {
    const local = '2026-06-01T09:00'
    const iso = toIsoInstant(local)
    expect(iso).not.toBeNull()
    /*
     * 고정 오프셋을 단언하지 않는다 — 이 검사는 실행 환경의 표준시각에 따라 값이
     * 달라지는 것이 **정상**이다(사용자가 적은 9시는 자기 지역의 9시다). 대신
     * **왕복이 보존되는지**를 본다.
     */
    expect(toLocalInput(iso)).toBe(local)
  })

  it('서버 값이 없으면 빈 폼으로 시작한다 — 틀린 시각을 보여 주지 않는다', () => {
    expect(toLocalInput(null)).toBe('')
    expect(toLocalInput('')).toBe('')
    expect(toLocalInput('not-a-date')).toBe('')
  })

  it('초를 남기지 않는다 — 항차마다 칸 모양이 달라지지 않게', () => {
    expect(toLocalInput('2026-06-01T00:00:37Z')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  })
})

describe('시각 검증 — 비어 있는 것은 오류가 아니다 (#873)', () => {
  it('생성 폼: 두 칸이 비어도 통과한다 — §3.3이 optional이다', () => {
    expect(hasErrors(validateDraft(draft()))).toBe(false)
  })

  it('생성 폼: 도착이 출항보다 빠르면 막는다', () => {
    const found = validateDraft(
      draft({ plannedDepartureAt: '2026-06-08T09:00', plannedArrivalAt: '2026-06-01T09:00' }),
    )
    expect(found.plannedArrivalAt).toBeDefined()
  })

  it('생성 폼: 같은 시각도 막는다 — 항해 시간이 0이면 누적도 0이다', () => {
    const found = validateDraft(
      draft({ plannedDepartureAt: '2026-06-01T09:00', plannedArrivalAt: '2026-06-01T09:00' }),
    )
    expect(found.plannedArrivalAt).toBeDefined()
  })

  it('생성 폼: 출항만 넣어도 통과한다 — 도착은 나중에 온다', () => {
    expect(hasErrors(validateDraft(draft({ plannedDepartureAt: '2026-06-01T09:00' })))).toBe(false)
  })

  it('실적 폼: 도착이 출항보다 빠르면 막는다', () => {
    const found = validateActuals(
      actuals({ actualDepartureAt: '2026-06-08T09:00', actualArrivalAt: '2026-06-01T09:00' }),
    )
    expect(found.actualArrivalAt).toBeDefined()
  })
})

describe('actualsPayload — 시각 두 칸 (#873)', () => {
  it('입력한 시각을 UTC 문자열로 싣는다', () => {
    const payload = actualsPayload(actuals({ actualDepartureAt: '2026-06-01T09:00' }))
    expect(typeof payload.actual_departure_at).toBe('string')
    expect(payload.actual_departure_at).toBe(toIsoInstant('2026-06-01T09:00'))
  })

  it('빈 칸은 키 자체를 넣지 않는다 — null을 보내면 이미 넣은 시각이 지워진다', () => {
    const payload = actualsPayload(actuals({ actualDistanceNm: '11200' }))
    expect(payload).not.toHaveProperty('actual_departure_at')
    expect(payload).not.toHaveProperty('actual_arrival_at')
  })
})
