import { describe, expect, it } from 'vitest'
import {
  actualsPayload,
  canEnterActuals,
  hasErrors,
  nextStatuses,
  policyForTransition,
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
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 800, actualFuelTon: null }],
  ...over,
})

const draft = (over: Partial<VoyageDraft> = {}): VoyageDraft => ({
  voyageNo: 'V-2026-002',
  departurePortName: 'Busan',
  arrivalPortName: 'Singapore',
  plannedDistanceNm: '2800',
  plannedSpeedKn: '13.5',
  regulationYear: '2026',
  fuelType: 'HFO',
  plannedFuelTon: '210',
  ...over,
})

const actuals = (over: Partial<ActualsDraft> = {}): ActualsDraft => ({
  actualDistanceNm: '',
  actualAvgSpeedKn: '',
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
