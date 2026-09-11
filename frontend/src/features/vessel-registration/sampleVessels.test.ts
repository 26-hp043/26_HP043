import { describe, expect, it, vi } from 'vitest'
import { initialFormState } from './formRules'
import { applySample, fetchSampleVessels, type SampleVessel } from './sampleVessels'

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
