// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { percentChangeFixed } from '../../display/decimal'
import { DISPLAY_DIGITS } from '../../display/format'
import { ScenarioBars } from './ScenarioBars'
import type { ScenarioResult } from './types'

function scenario(
  type: ScenarioResult['scenario_type'],
  name: string,
  values: Partial<Pick<ScenarioResult, 'attained_cii' | 'duration_hours' | 'fuel_ton' | 'co2_emission_ton'>>,
): ScenarioResult {
  return {
    scenario_id: `sc-${type}`,
    scenario_type: type,
    scenario_name: name,
    distance_nm: 1000,
    speed_kn: 12,
    duration_hours: '80.0000',
    fuel_ton: '80.00',
    co2_emission_ton: '250.00',
    attained_cii: '6.614000',
    ratio_to_required: '1.0',
    estimated_rating: 'C',
    risk_level: 'MEDIUM',
    next_worse_boundary_margin_ratio: '0.03',
    ...values,
  } as ScenarioResult
}

// 감속이 연료가 가장 적고, 우회가 가장 많다 — 정렬하지 않으면 표 순서(직항 · 우회 · 감속) 그대로다
const SCENARIOS = [
  scenario('DIRECT', '직항', { fuel_ton: '80.00' }),
  scenario('DETOUR', '우회', { fuel_ton: '100.00' }),
  scenario('SLOW_STEAMING', '감속', { fuel_ton: '50.00' }),
]

/** 타일 하나 — 제목(지표 이름)으로 찾는다. */
function tile(label: RegExp) {
  return screen.getByRole('region', { name: label })
}

function rowsOf(region: HTMLElement) {
  return within(region).getAllByRole('listitem')
}

const TILES = [/^CII/, /^소요시간/, /^연료/]

/*
 * 10/7 디자인 결정(#2315) — 드롭다운으로 항목 하나를 고르던 막대가 **지표별 타일 셋**으로
 * 바뀌었고, 표 아래 따로 있던 지표별 최소값 3줄이 타일 안으로 들어왔다. 그래서 「최소 표시를
 * 붙이지 않는다」는 더 이상 이 부품의 성질이 아니다 — 대신 `PRD §11.2` 중립(추천 없음 ·
 * 지표마다 따로 · 동률이면 전부)을 타일에서 지킨다.
 */
describe('항목별 비교 타일 (#2202 · 10/7)', () => {
  it('표와 같은 순서로 놓는다 — 어느 타일도 값으로 정렬하지 않는다 (§11 중립)', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    for (const label of TILES) {
      expect(rowsOf(tile(label)).map((row) => row.textContent?.split(/\d/)[0])).toEqual(['직항', '우회', '감속'])
    }
  })

  it('타일마다 막대 길이는 그 지표 최댓값에 대한 비율이다', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    const fuel = tile(/^연료/)
    const widths = [...fuel.querySelectorAll<HTMLElement>('.scenario-tile__fill')].map((el) => el.style.inlineSize)
    expect(widths).toEqual(['80%', '100%', '50%'])
    expect(rowsOf(fuel)[1].textContent).toContain('100.0')
  })

  it('「추천」은 없고, 최소값은 지표마다 따로 표시한다 (PRD §11.2)', () => {
    const { container } = render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    expect(container.textContent).not.toMatch(/추천 시나리오|추천합니다|최적/)
    // 연료는 감속 하나만 가장 적다 — 그 행만 표시한다
    const fuelRows = rowsOf(tile(/^연료/))
    expect(fuelRows.map((row) => row.classList.contains('scenario-tile__row--lowest'))).toEqual([false, false, true])
    const foot = tile(/^연료/).querySelector('.scenario-tile__best')!
    expect(foot.textContent).toContain('감속')
    expect(foot.textContent).not.toContain('동률')
  })

  it('동률이면 전부 표시하고 동률임을 적는다 — 하나만 지목하지 않는다 (#799)', () => {
    // CII는 세 시나리오가 같은 값이다(기본 6.614000)
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    const cii = tile(/^CII/)
    expect(rowsOf(cii).every((row) => row.classList.contains('scenario-tile__row--lowest'))).toBe(true)
    const foot = cii.querySelector('.scenario-tile__best')!.textContent ?? ''
    for (const name of ['직항', '우회', '감속']) expect(foot).toContain(name)
    expect(foot).toContain('동률')
    // 동률에는 하나를 기준으로 한 증감률을 붙이지 않는다
    expect(cii.querySelector('.scenario-tile__change')).toBeNull()
  })

  it('최소값이 직항이 아니면 직항 대비 증감률을 표시값끼리 계산해 적는다', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    const change = tile(/^연료/).querySelector('.scenario-tile__change')
    const expected = percentChangeFixed('50.00', '80.00', DISPLAY_DIGITS.fuelTon)!
    expect(change?.textContent).toContain(expected.replace(/^-/, ''))
    expect(change?.textContent).toMatch(/−/)
  })

  it('막대는 장식이고, 이름과 값은 글자로 읽힌다', () => {
    const { container } = render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    const tracks = container.querySelectorAll('.scenario-tile__track')
    expect(tracks.length).toBe(9)
    for (const track of tracks) expect(track.getAttribute('aria-hidden')).toBe('true')
    expect(rowsOf(tile(/^CII/))[0].textContent).toMatch(/직항.*6\.614/)
  })

  it('막대 색은 시나리오별이다 — 세 행이 서로 다른 시나리오 변형을 단다', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    const variants = rowsOf(tile(/^연료/)).map((row) =>
      [...row.classList].find((name) => /^scenario-tile__row--(direct|detour|slow)/.test(name)),
    )
    expect(new Set(variants).size).toBe(3)
    expect(variants.every(Boolean)).toBe(true)
  })
})
