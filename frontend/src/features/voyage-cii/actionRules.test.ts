import { describe, expect, it } from 'vitest'
import {
  annualSimulatorPath,
  csvExportQuery,
  initialPlanSaveForm,
  planDraftFrom,
  planPolicy,
  plannedArrivalFrom,
  validatePlanSave,
} from './actionRules'
import type { VoyageCiiRequest, VoyageCiiResponse } from './types'

/**
 * 기능① 결과 액션 3종의 규칙 (#891 · `PRD §10.5`).
 */

const REQUEST: VoyageCiiRequest = {
  vessel_id: '00000000-0000-4000-8000-000000000001',
  regulation_year: 2026,
  distance_nm: 2300,
  speed_kn: 14,
  fuel_uses: [
    { fuel_type: 'HFO', fuel_ton: 150 },
    { fuel_type: 'MDO', fuel_ton: 34 },
  ],
}

describe('validatePlanSave', () => {
  it('출발항·도착항·출항 예정 시각이 필수다 — 계산은 어디서 언제 떠나는지 모른다', () => {
    const errors = validatePlanSave(initialPlanSaveForm())
    expect(Object.keys(errors).sort()).toEqual(
      ['arrivalPortName', 'departurePortName', 'plannedDepartureAt'].sort(),
    )
  })

  it('항차 번호는 선택이다', () => {
    const form = {
      ...initialPlanSaveForm(),
      departurePortName: 'Busan',
      arrivalPortName: 'Singapore',
      plannedDepartureAt: '2026-10-01T09:00',
    }
    expect(validatePlanSave(form)).toEqual({})
  })
})

describe('plannedArrivalFrom', () => {
  it('출항 + 거리 ÷ 속력 — 기능② 채택과 같은 식', () => {
    // 2300 nm ÷ 14 kn = 164.2857 h = 6일 20시간 17분
    expect(plannedArrivalFrom('2026-10-01T09:00', 2300, 14)).toBe('2026-10-08T05:17')
  })

  it('출항 시각을 읽을 수 없거나 속력이 0이면 비운다 — 틀린 도착 시각을 만들지 않는다', () => {
    expect(plannedArrivalFrom('', 2300, 14)).toBe('')
    expect(plannedArrivalFrom('2026-10-01T09:00', 2300, 0)).toBe('')
  })
})

describe('planDraftFrom', () => {
  it('계산 요청의 거리·속력·연료·연도로 초안을 만든다 — 연료는 행마다', () => {
    const draft = planDraftFrom(REQUEST, {
      ...initialPlanSaveForm(),
      departurePortName: ' Busan ',
      arrivalPortName: 'Singapore',
      plannedDepartureAt: '2026-10-01T09:00',
    })
    expect(draft.departurePortName).toBe('Busan')
    expect(draft.plannedDistanceNm).toBe('2300')
    expect(draft.plannedSpeedKn).toBe('14')
    // `INCLUDE_AS_PLAN` 전환에는 기준연도가 필수다(`API_SPEC §3.5` [#150]).
    expect(draft.regulationYear).toBe('2026')
    expect(draft.plannedArrivalAt).toBe('2026-10-08T05:17')
    expect(draft.fuelUses).toEqual([
      { fuelType: 'HFO', plannedFuelTon: '150' },
      { fuelType: 'MDO', plannedFuelTon: '34' },
    ])
  })
})

describe('planPolicy', () => {
  it('기본은 연간 반영(INCLUDE_AS_PLAN)이고 끄면 EXCLUDE — 계획 저장과 연간 반영은 별개다', () => {
    expect(initialPlanSaveForm().includeInAnnual).toBe(true)
    expect(planPolicy(initialPlanSaveForm())).toBe('INCLUDE_AS_PLAN')
    expect(planPolicy({ ...initialPlanSaveForm(), includeInAnnual: false })).toBe('EXCLUDE')
  })
})

describe('이동·내보내기 경로', () => {
  it('연간 시뮬레이터로 연도를 싣는다 — 선박은 셸이 들고 있다', () => {
    expect(annualSimulatorPath(REQUEST)).toBe('/annual-grade?year=2026')
  })

  it('CSV는 이 계산 한 건을 서버가 만든다', () => {
    const response = { calculation_run_id: 'run 1/2' } as VoyageCiiResponse
    expect(csvExportQuery(response)).toBe(
      'type=calculations&calculation_run_id=run%201%2F2&format=csv',
    )
  })
})
