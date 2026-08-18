import { describe, expect, it } from 'vitest'
import { createDemoScenarioProvider } from './demoProvider'
import { ScenarioComparisonError } from './provider'
import { DEMO_VESSELS } from '../voyage-cii/referenceTable'
import { createDemoProvider } from '../voyage-cii/demoProvider'
import type { ScenarioComparisonRequest } from './types'

const BASE: ScenarioComparisonRequest = {
  vessel_id: DEMO_VESSELS[0].id,
  regulation_year: 2026,
  base_distance_nm: 1000,
  base_speed_kn: 14,
  base_daily_foc_ton: 26.88,
  fuel_type: 'HFO',
}

const provider = createDemoScenarioProvider()

describe('시나리오 생성 — PRD §11.2', () => {
  it('DIRECT · DETOUR · SLOW_STEAMING 세 건을 표 순서대로 낸다', async () => {
    const result = await provider.compare(BASE)
    expect(result.scenarios.map((s) => s.scenario_type)).toEqual([
      'DIRECT',
      'DETOUR',
      'SLOW_STEAMING',
    ])
  })

  it('DIRECT는 입력 그대로다', async () => {
    const [direct] = (await provider.compare(BASE)).scenarios
    expect(direct.distance_nm).toBe(1000)
    expect(direct.speed_kn).toBe(14)
  })

  it('DETOUR는 거리 +5% — PRD §11.2 기본값', async () => {
    const [, detour] = (await provider.compare(BASE)).scenarios
    expect(detour.distance_nm).toBe(1050)
    expect(detour.speed_kn).toBe(14)
  })

  it('SLOW_STEAMING은 속력 −1 kn, 거리는 그대로', async () => {
    const [, , slow] = (await provider.compare(BASE)).scenarios
    expect(slow.speed_kn).toBe(13)
    expect(slow.distance_nm).toBe(1000)
  })

  it('속력 하한 1.0 kn를 지킨다 — floor가 없으면 소요 시간이 무한이 된다', async () => {
    const [, , slow] = (
      await provider.compare({ ...BASE, base_speed_kn: 1.0 })
    ).scenarios
    expect(slow.speed_kn).toBe(1.0)
    expect(Number.isFinite(Number(slow.duration_hours))).toBe(true)
  })
})

describe('계산 — 기능① 엔진을 그대로 통과시킨다', () => {
  it('DIRECT 결과가 기능① 단독 호출과 완전히 같다', async () => {
    // 두 화면이 서로 다른 값을 내면 시연 중에야 드러난다.
    const [direct] = (await provider.compare(BASE)).scenarios
    const single = await createDemoProvider().estimate({
      vessel_id: BASE.vessel_id,
      regulation_year: BASE.regulation_year,
      distance_nm: 1000,
      speed_kn: 14,
      fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 80 }],
    })

    expect(direct.attained_cii).toBe(single.data.attained_cii)
    expect(direct.co2_emission_ton).toBe(single.data.co2_emission_ton)
    expect(direct.estimated_rating).toBe(single.data.estimated_rating)
    expect(direct.risk_level).toBe(single.data.risk_level)
    expect(direct.ratio_to_required).toBe(single.data.ratio_to_required)
  })

  it('DIRECT는 #132 계약 fixture와 같다', async () => {
    const [direct] = (await provider.compare(BASE)).scenarios
    expect(direct.attained_cii).toBe('4.982400')
    expect(direct.estimated_rating).toBe('C')
    expect(direct.risk_level).toBe('MEDIUM')
  })

  it('소요 시간은 거리 ÷ 속력이다', async () => {
    const { scenarios } = await provider.compare(BASE)
    for (const s of scenarios) {
      expect(Number(s.duration_hours)).toBeCloseTo(s.distance_nm / s.speed_kn, 3)
    }
  })

  it('소요 시간을 표시 자릿수로 미리 자르지 않는다', async () => {
    // DESIGN_SYSTEM §4.2 반올림 🔒 — 내부에는 원본 값을 보관한다.
    const [direct] = (await provider.compare(BASE)).scenarios
    expect(direct.duration_hours.split('.')[1].length).toBeGreaterThan(1)
  })

  it('세 시나리오가 같은 required_cii를 공유한다', async () => {
    const result = await provider.compare(BASE)
    expect(result.required_cii).toBe('5.045066')
  })
})

describe('결정성', () => {
  it('같은 입력에 같은 결과가 나온다', async () => {
    const a = await provider.compare(BASE)
    const b = await provider.compare(BASE)
    expect(a).toEqual(b)
  })
})

describe('연료가 시나리오별 고정 배수다 — #75 대기하지 않는다', () => {
  it('DETOUR 연료 증가율이 거리 증가율보다 크다', async () => {
    // 우회 이유가 기상이고 그 조건에서 소모가 늘기 때문이다. 실제 산정은 #75 소관.
    const { scenarios } = await provider.compare(BASE)
    const [direct, detour] = scenarios
    const fuelRatio = Number(detour.fuel_ton) / Number(direct.fuel_ton)
    const distanceRatio = detour.distance_nm / direct.distance_nm
    expect(fuelRatio).toBeGreaterThan(distanceRatio)
  })

  it('SLOW_STEAMING이 연료를 가장 적게 쓴다', async () => {
    const { scenarios } = await provider.compare(BASE)
    const fuels = scenarios.map((s) => Number(s.fuel_ton))
    expect(Math.min(...fuels)).toBe(fuels[2])
  })

  it('감속이 등급을 개선한다 — 비교 화면의 목적이 드러나는 조합이다', async () => {
    const { scenarios } = await provider.compare(BASE)
    expect(scenarios[0].estimated_rating).toBe('C')
    expect(scenarios[2].estimated_rating).toBe('A')
  })
})

describe('검증', () => {
  it.each([
    [{ base_distance_nm: 0 }, 'base_distance_nm'],
    [{ base_speed_kn: 0.9 }, 'base_speed_kn'],
    [{ base_daily_foc_ton: 0 }, 'base_daily_foc_ton'],
  ])('%o → %s 오류', async (patch, field) => {
    await expect(provider.compare({ ...BASE, ...patch })).rejects.toMatchObject({
      name: 'ScenarioComparisonError',
      code: 'VALIDATION_ERROR',
      field,
    })
  })

  it('고정표에 없는 선박은 UNSUPPORTED_VESSEL', async () => {
    await expect(
      provider.compare({ ...BASE, vessel_id: '00000000-0000-4000-8000-00000000ffff' }),
    ).rejects.toBeInstanceOf(ScenarioComparisonError)
  })

  it('실패 문구가 어느 선박인지·왜 안 되는지 적는다 (#511)', async () => {
    // 종전 문구는 「지원하지 않는 선박입니다.」 한 줄이라, 서버가 거부한 것으로
    // 읽혔다 — 실제로는 서버에 요청이 나가지도 않았다.
    const error = await provider
      .compare({ ...BASE, vessel_id: '00000000-0000-4000-8000-000000000003' })
      .then(() => null, (e: unknown) => e as ScenarioComparisonError)
    expect(error?.message).toContain('00000000-0000-4000-8000-000000000003')
    expect(error?.message).toContain('데모')
    expect(error?.message).not.toBe('지원하지 않는 선박입니다.')
  })

  it('기능① 오류를 기능② 오류 타입으로 옮긴다 — 화면이 두 타입을 알지 않는다', async () => {
    const error = await provider
      .compare({ ...BASE, fuel_type: 'ETHANE' })
      .then(() => null, (e: unknown) => e)
    expect(error).toBeInstanceOf(ScenarioComparisonError)
    expect((error as ScenarioComparisonError).code).toBe('UNKNOWN_FUEL_TYPE')
  })

  it('지원하지 않는 연도는 오류를 낸다', async () => {
    await expect(
      provider.compare({ ...BASE, regulation_year: 2030 }),
    ).rejects.toBeInstanceOf(ScenarioComparisonError)
  })
})

describe('응답 메타', () => {
  it('단위 파생용 축과 선종을 함께 낸다', async () => {
    const result = await provider.compare(BASE)
    expect(result.transport_capacity_basis).toBe('DWT')
    expect(result.ship_type).toBe('BULK_CARRIER')
    expect(result.vessel_display_name).toContain('벌크선')
  })

  it('경고와 면책 문구를 그대로 전달한다', async () => {
    const result = await provider.compare(BASE)
    expect(result.warnings).toContain('REFERENCE_ONLY')
    expect(result.disclaimer.length).toBeGreaterThan(0)
  })
})
