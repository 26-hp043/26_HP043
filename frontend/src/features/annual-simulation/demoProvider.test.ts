import { describe, expect, it } from 'vitest'
import { createDemoAnnualProvider } from './demoProvider'
import { FUEL_CF } from '../voyage-cii/referenceTable'
import type { AnnualSimulationRequest } from './types'

const provider = createDemoAnnualProvider()

const REQUEST: AnnualSimulationRequest = {
  vessel_id: '00000000-0000-4000-8000-000000000001',
  regulation_year: 2026,
  target_rating: 'B',
  simulation_runs: 5000,
}

describe('예시 데이터임이 응답에 드러난다', () => {
  it('is_sample_data가 true다', async () => {
    // 화면이 배지를 상수로 박으면 실 API 연결 후에도 남는다. 응답에서 판단한다.
    expect((await provider.run(REQUEST)).is_sample_data).toBe(true)
  })

  it('REFERENCE_ONLY 경고를 낸다', async () => {
    expect((await provider.run(REQUEST)).warnings).toContain('REFERENCE_ONLY')
  })

  it('seed가 실 API 형태와 구분된다', async () => {
    // 실 API는 128-bit hex를 낸다. demo 값이 그것과 같은 모양이면 화면에서
    // 「이게 실제 실행인가」를 구분할 수 없다.
    const mc = (await provider.run(REQUEST)).monte_carlo
    expect(mc.rng_metadata.seed_entropy).not.toMatch(/^0x[0-9a-f]+$/i)
  })
})

describe('서버 계약과 같은 블록을 낸다', () => {
  it('결정론·확률·민감도·스냅샷이 모두 있다', async () => {
    // demo가 서버와 다른 모양을 내면 화면이 두 형태를 다뤄야 하고, 그 분기가 버그 자리다.
    const r = await provider.run(REQUEST)
    expect(r.deterministic.projected_rating).toMatch(/^[A-E]$/)
    expect(Object.keys(r.monte_carlo.rating_probabilities).sort()).toEqual([
      'A',
      'B',
      'C',
      'D',
      'E',
    ])
    expect(r.sensitivity_analysis.interaction_note.length).toBeGreaterThan(0)
    expect(r.snapshot.voyage_count).toBeGreaterThan(0)
  })

  it('요청의 반복 횟수를 그대로 반영한다', async () => {
    const r = await provider.run({ ...REQUEST, simulation_runs: 3000 })
    expect(r.monte_carlo.runs).toBe(3000)
  })
})

describe('목업이 스스로 모순되지 않는다', () => {
  it('등급별 확률의 합이 1이다', async () => {
    const p = (await provider.run(REQUEST)).monte_carlo.rating_probabilities
    const sum = Object.values(p).reduce((acc, v) => acc + Number(v), 0)
    expect(sum).toBeCloseTo(1, 4)
  })

  it('예측 CII가 (누적+잔여 분자) ÷ (누적+잔여 분모)와 같다', async () => {
    // `PRD §12.3`. 목업이 스스로 모순되면 시연에서 그것이 먼저 눈에 띈다.
    const det = (await provider.run(REQUEST)).deterministic
    const expected =
      (Number(det.completed_M_gco2) + Number(det.planned_M_gco2)) /
      (Number(det.completed_W_capacity_nm) + Number(det.planned_W_capacity_nm))
    expect(Number(det.projected_attained_cii)).toBeCloseTo(expected, 6)
  })

  it('분자가 연료 × CF × 10⁶다', async () => {
    const det = (await provider.run(REQUEST)).deterministic
    const cf = Number(FUEL_CF.HFO.cf)
    // 누적 연료 2020t (demoProvider 상수)
    expect(Number(det.completed_M_gco2)).toBeCloseTo(2020 * cf * 1_000_000, 0)
  })

  it('목표 등급이 낮아지면 달성 확률이 올라간다', async () => {
    // 목표를 고르는 입력이 화면에서 아무 일도 하지 않으면 안 된다.
    const a = await provider.run({ ...REQUEST, target_rating: 'A' })
    const d = await provider.run({ ...REQUEST, target_rating: 'D' })
    expect(Number(d.monte_carlo.target_success_probability)).toBeGreaterThan(
      Number(a.monte_carlo.target_success_probability),
    )
  })
})
