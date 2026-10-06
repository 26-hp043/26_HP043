// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
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

function rows() {
  return within(screen.getByRole('list')).getAllByRole('listitem')
}

describe('항목별 미니 막대 (#2202)', () => {
  it('표와 같은 순서로 놓는다 — 값으로 정렬하지 않는다 (§11 중립)', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    fireEvent.change(screen.getByLabelText('막대로 볼 항목'), { target: { value: 'fuel_ton' } })
    expect(rows().map((row) => row.textContent?.split(/\d/)[0])).toEqual(['직항', '우회', '감속'])
  })

  it('항목을 바꾸면 값과 길이가 바뀐다 — 길이는 최댓값에 대한 비율이다', () => {
    const { container } = render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    fireEvent.change(screen.getByLabelText('막대로 볼 항목'), { target: { value: 'fuel_ton' } })
    const widths = [...container.querySelectorAll<HTMLElement>('.scenario-bars__fill')].map(
      (el) => el.style.inlineSize,
    )
    expect(widths).toEqual(['80%', '100%', '50%'])
    expect(rows()[1].textContent).toContain('100.0')
  })

  it('「최소」 · 「추천」 같은 표시를 붙이지 않는다', () => {
    render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    fireEvent.change(screen.getByLabelText('막대로 볼 항목'), { target: { value: 'fuel_ton' } })
    expect(screen.getByRole('list').textContent).not.toMatch(/최소|최저|추천|최적|가장/)
  })

  it('막대는 장식이고, 이름과 값은 글자로 읽힌다', () => {
    const { container } = render(<ScenarioBars scenarios={SCENARIOS} ciiUnit="gCO₂/(DWT·nm)" />)
    for (const track of container.querySelectorAll('.scenario-bars__track')) {
      expect(track.getAttribute('aria-hidden')).toBe('true')
    }
    expect(rows()[0].textContent).toMatch(/직항.*6\.614/)
  })
})
