import { describe, expect, it, vi } from 'vitest'
import { initialFormState, toRequest } from './formRules'
import {
  applySample,
  fetchSampleVessels,
  hasDivergedFields,
  sampleOverwriteConfirmMessage,
  type SampleVessel,
} from './sampleVessels'

/**
 * 샘플 선박 (#982 · `API_SPEC §2.15`).
 *
 * 화면이 샘플을 고르면 무엇이 바뀌고 무엇이 남는가를 순수 함수로 잠근다.
 */

const BULK: SampleVessel = {
  sample_id: 'bulk-50000-dwt',
  label: '샘플 벌크선 (50,000 DWT)',
  ship_type: 'BULK_CARRIER',
  gross_tonnage: 30000,
  deadweight: 50000,
  default_fuel_type: null,
  reference_speed_kn: 12,
  reference_daily_foc_ton: 23.04,
}

const RO_RO: SampleVessel = {
  sample_id: 'ro-ro-passenger-25000-gt',
  label: '샘플 로로 여객선 (25,000 GT)',
  ship_type: 'RO_RO_PASSENGER',
  gross_tonnage: 25000,
  deadweight: null,
  default_fuel_type: null,
  reference_speed_kn: 18,
  reference_daily_foc_ton: 59.52,
}

describe('applySample', () => {
  it('선종·제원을 채우고 IMO·선명은 그대로 둔다', () => {
    const typed = { ...initialFormState(), imoNumber: '9876543', name: '우리 배' }
    const next = applySample(typed, BULK)
    expect(next.imoNumber).toBe('9876543')
    expect(next.name).toBe('우리 배')
    expect(next.shipType).toBe('BULK_CARRIER')
    expect(next.deadweight).toBe('50000')
    expect(next.grossTonnage).toBe('30000')
    expect(next.referenceSpeedKn).toBe('12')
    expect(next.referenceDailyFocTon).toBe('23.04')
    expect(next.defaultFuelType).toBe('')
  })

  it('샘플을 바꿔 고르면 앞 샘플의 값이 남지 않는다 — 두 샘플이 섞인 제원이 등록되지 않게', () => {
    const next = applySample(applySample(initialFormState(), BULK), RO_RO)
    expect(next.deadweight).toBe('')
    expect(next.grossTonnage).toBe('25000')
    expect(next.shipType).toBe('RO_RO_PASSENGER')
  })
})

describe('fetchSampleVessels', () => {
  const ok = (body: unknown) =>
    ({ ok: true, status: 200, json: async () => body }) as Response

  it('GET /vessels/samples를 세션 쿠키와 함께 부른다', async () => {
    const fetchImpl = vi.fn(async () => ok({ data: [BULK] }))
    const rows = await fetchSampleVessels(fetchImpl as unknown as typeof fetch, '/api/v1')
    expect(rows).toEqual([BULK])
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vessels/samples')
    expect(init.credentials).toBe('include')
  })

  it('응답 모양이 계약과 다르면 던진다 — 빈 목록으로 삼키지 않는다', async () => {
    const fetchImpl = vi.fn(async () => ok({ data: [{ id: 'x' }] }))
    await expect(fetchSampleVessels(fetchImpl as unknown as typeof fetch, '/api/v1')).rejects.toThrow()
  })

  it('HTTP 실패도 던진다', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response)
    await expect(fetchSampleVessels(fetchImpl as unknown as typeof fetch, '/api/v1')).rejects.toThrow('500')
  })
})

/**
 * `PRD §11.4` 연료 산정 3단계(「샘플 선박 기본값」)는 **등록 시점에 실현된다** (#997).
 *
 * 샘플을 고르면 기준 일일 연료가 **등록 요청에 실린다** — 그래서 그 선박은 계산 때 2단계
 * (선박 기준값)로 계산된다. 이 연결이 끊기면 샘플로 등록한 배가 항로 비교에서 「기준 일일
 * 연료소모량이 필요합니다」로 막힌다. 두 단계(`applySample` · `toRequest`)를 **이어서** 본다.
 */
describe('샘플 → 등록 요청 (#997)', () => {
  it.each([BULK, RO_RO])('$label의 기준 연료·기준속도가 등록 요청까지 간다', (sample) => {
    const request = toRequest({
      ...applySample(initialFormState(), sample),
      imoNumber: '9000001',
      name: '새 배',
    })
    expect(request.reference_daily_foc_ton).toBe(sample.reference_daily_foc_ton)
    expect(request.reference_speed_kn).toBe(sample.reference_speed_kn)
  })
})

/**
 * 샘플 덮어쓰기 확인 (#1526).
 *
 * 「직접 남긴 값이 있는가」를 판정하는 순수 함수다. 화면(`VesselRegistration.tsx`)은
 * 이 값으로만 `confirm()`을 부른다 — 판정 자체는 여기서 잠근다.
 */
describe('hasDivergedFields', () => {
  it('빈 폼이면 false다 — 물을 것이 없다', () => {
    expect(hasDivergedFields(initialFormState(), null, BULK)).toBe(false)
  })

  it('아직 샘플을 고른 적이 없는데(lastApplied가 null) 값을 직접 넣었으면 true다', () => {
    const typed = { ...initialFormState(), deadweight: '12345' }
    expect(hasDivergedFields(typed, null, BULK)).toBe(true)
  })

  it('샘플을 적용한 뒤 손대지 않고 다른 샘플로 바로 바꾸면 false다 — 샘플→샘플 전환은 묻지 않는다', () => {
    const afterApply = applySample(initialFormState(), BULK)
    expect(hasDivergedFields(afterApply, BULK, RO_RO)).toBe(false)
  })

  it('샘플 적용 뒤 한 칸을 손으로 고치면 true다', () => {
    const afterApply = applySample(initialFormState(), BULK)
    const edited = { ...afterApply, deadweight: '60000' }
    expect(hasDivergedFields(edited, BULK, RO_RO)).toBe(true)
  })

  it('수치 문자열의 표현만 다르면(예: 50000.0 vs 50000) 같은 값으로 본다', () => {
    const afterApply = applySample(initialFormState(), BULK) // deadweight: '50000'
    const reformatted = { ...afterApply, deadweight: '50000.0' }
    expect(hasDivergedFields(reformatted, BULK, RO_RO)).toBe(false)
  })

  it('샘플이 비운 칸(RO_RO의 deadweight)에 직접 값을 넣었으면 true다', () => {
    const afterApply = applySample(initialFormState(), RO_RO) // deadweight: ''
    const typed = { ...afterApply, deadweight: '12345' }
    expect(hasDivergedFields(typed, RO_RO, BULK)).toBe(true)
  })
})

describe('hasDivergedFields — 고르려는 샘플과 같은 값은 잃지 않는다', () => {
  it('직접 적은 값이 고르려는 샘플의 값과 같으면 false다 — 바뀌는 것이 없다', () => {
    const typed = { ...initialFormState(), deadweight: '50000' } // BULK.deadweight와 같다
    expect(hasDivergedFields(typed, null, BULK)).toBe(false)
  })

  it('같은 값이 표현만 달라도(50000.0) false다', () => {
    const typed = { ...initialFormState(), deadweight: '50000.0' }
    expect(hasDivergedFields(typed, null, BULK)).toBe(false)
  })
})

describe('sampleOverwriteConfirmMessage', () => {
  it('빈 문자열이 아닌 한 문장을 반환한다', () => {
    const message = sampleOverwriteConfirmMessage()
    expect(typeof message).toBe('string')
    expect(message.length).toBeGreaterThan(0)
  })
})
