// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { VoyageCiiResult } from './VoyageCiiResult'
import type { VoyageCiiRequest, VoyageCiiResponse } from './types'
import { regulationParametersPath } from '../parameters/referenceRules'

/**
 * 기능① 결과 화면의 「계산 근거」 패널 → 설정 「규제 기준값」 절 링크 (`#1516` · `#1239` 결정 B).
 *
 * 패널은 **이 계산이 쓴** 값만 보인다. 다른 선종·연도, 대체된 옛 판본, 원문 표기(`a_raw`)는
 * 절에 있으므로 패널에서 그 절로 가는 길이 있어야 한다 — 링크의 **목적지**를 단언한다.
 */

const RESPONSE: VoyageCiiResponse = {
  data: {
    attained_cii: '4.982400',
    required_cii: '5.045066',
    ratio_to_required: '0.98758',
    estimated_rating: 'C',
    rating_boundary_cii: {
      superior_boundary: '4.338757',
      lower_boundary: '4.742362',
      upper_boundary: '5.347770',
      inferior_boundary: '5.953178',
    },
    next_worse_boundary_margin: '0.365370',
    next_worse_boundary_margin_ratio: '0.0724',
    co2_emission_ton: '249.12',
    fuel_consumption_ton: '80.00',
    distance_nm: 1000,
    risk_level: 'MEDIUM',
    transport_capacity: '50000',
    transport_capacity_basis: 'DWT',
    reference_capacity: '50000',
    reference_capacity_rule: 'DWT',
    annual_impact: null,
    calculation_basis: {
      ship_type: 'BULK_CARRIER',
      z_factor_percent: '11',
      fuel_cf_details: [{ fuel_type: 'HFO', cf: '3.114', fuel_ton: '80.0' }],
      a_decimal: '4745',
      c: '0.622',
    },
  },
  parameters_used: {
    regulation_year: { year: '2026', z_factor_percent: '11' },
    fuel_types: [{ code: 'HFO', cf: '3.114' }],
    reference_line: { ship_type: 'BULK_CARRIER', reference_capacity_rule: 'DWT', a_decimal: '4745', c: '0.622' },
    rating_boundary: { d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18' },
    parameter_source_version: '2025-q2',
  },
  calculation_run_id: '00000000-0000-4000-8000-0000000000a1',
  model_version: {
    engine: 'dual-precision-v1',
    decimal_precision: 30,
    decimal_rounding: 'ROUND_HALF_EVEN',
    rng_algorithm: 'PCG64',
    numpy_version: '2.0.0',
    python_version: '3.12',
  },
  input_hash: 'sha256:' + 'a'.repeat(64),
  parameter_hash: 'sha256:' + 'b'.repeat(64),
  warnings: ['REFERENCE_ONLY'],
  disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
  meta: { request_id: 'r', timestamp: '2026-08-08T00:00:00Z', duration_ms: 4 },
}

const REQUEST: VoyageCiiRequest = {
  vessel_id: 'v-1',
  regulation_year: 2026,
  distance_nm: 1000,
  speed_kn: 12,
  fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 80 }],
}

describe('「계산 근거」 → 규제 기준값 절 (#1516)', () => {
  it('계산 근거 패널 안에 절 앵커로 가는 링크가 있다', () => {
    render(
      <MemoryRouter>
        <VoyageCiiResult state={{ status: 'success', response: RESPONSE, request: REQUEST }} />
      </MemoryRouter>,
    )

    const panel = document.querySelector('details') as HTMLElement
    expect(panel).not.toBeNull()
    const links = within(panel).getAllByRole('link')
    expect(links.some((link) => link.getAttribute('href') === regulationParametersPath())).toBe(true)
  })

  it('패널의 기준선 계수는 여전히 서버 문자열 그대로다', () => {
    render(
      <MemoryRouter>
        <VoyageCiiResult state={{ status: 'success', response: RESPONSE, request: REQUEST }} />
      </MemoryRouter>,
    )

    expect(screen.getByText(/a 4745 · c 0\.622/)).toBeTruthy()
  })
})

/**
 * 결론이 맨 위에 선다 (#1711 · `DESIGN_SYSTEM §8.6` 🔒 · `§5` 카드 예산).
 *
 * 종전에는 등급 배지 옆에 참고 등급 · 다음 경계 · 위험도가 본문 크기로 붙고, 예상
 * CII는 타일 일곱 칸 중 첫 칸이었다. 타일이 3열에 놓여 마지막 줄에 한 칸만 남았다.
 */
describe('결론이 맨 위에 선다 (#1711)', () => {
  function renderResult(extra: Partial<VoyageCiiResponse['data']> = {}, stale = false) {
    const response = { ...RESPONSE, data: { ...RESPONSE.data, ...extra } }
    return render(
      <MemoryRouter>
        <VoyageCiiResult
          state={{ status: 'success', response, request: REQUEST }}
          stale={stale}
          actions={<section className="voyage-cii-actions">이 결과로</section>}
        />
      </MemoryRouter>,
    )
  }

  it('첫 자리는 결론 띠다 — 주: 참고 등급 + 예상 CII, 보조: 다음 경계까지', () => {
    const { container } = renderResult()
    const strip = screen.getByRole('region', { name: '결론' })
    expect(container.querySelector('.voyage-cii-result-stack')!.firstElementChild).toBe(strip)

    expect(strip.querySelector('.verdict-strip__value')!.textContent).toBe('4.982')
    expect(within(strip).getByRole('img', { name: '참고 등급 C' })).toBeTruthy()
    const sub = strip.querySelector('.verdict-strip__sub') as HTMLElement
    expect(within(sub).getByText('다음 경계까지')).toBeTruthy()
    expect(within(sub).getByText(/D 등급까지 7\.2%/)).toBeTruthy()
    expect(strip.querySelectorAll('.verdict-strip__risk')).toHaveLength(1)
  })

  it('결과 안에 회색 타일이 없고, 수치는 「라벨 · 값」 목록이다', () => {
    const { container } = renderResult()
    expect(container.querySelector('[class*="voyage-cii-result__metric"]')).toBeNull()
    const list = container.querySelector('dl.voyage-cii-result__list') as HTMLElement
    expect(within(list).getByText('기준 CII')).toBeTruthy()
    // 예상 CII는 띠로 올라갔다 — 목록에 다시 서지 않는다
    expect(within(list).queryByText('항차 조건 기준 예상 CII')).toBeNull()
  })

  it('연간 반영 시 변화가 있으면 목록의 한 줄이다 — 따로 남는 칸이 없다', () => {
    renderResult({
      annual_impact: {
        before: { attained_cii: '5.100000', rating: 'D' },
        after: { attained_cii: '5.050000', rating: 'D' },
        rating_changed: false,
      },
    } as Partial<VoyageCiiResponse['data']>)
    const row = screen.getByText('연간 반영 시 변화').closest('.voyage-cii-result__row')
    expect(row).toBeTruthy()
    expect(within(row as HTMLElement).getByText('D → D')).toBeTruthy()
  })

  it('「이 결과로」는 결과 카드 안에 있다 — 따로 떠 있는 면이 아니다 (`§5`)', () => {
    const { container } = renderResult()
    const actions = container.querySelector('.voyage-cii-actions')!
    expect(actions.closest('section.voyage-cii-result')).toBeTruthy()
    // 떠 있는 면: 결론 띠 · 결과 카드 둘 (입력 카드는 페이지 쪽)
    expect(container.querySelectorAll('.verdict-strip, section.voyage-cii-result')).toHaveLength(2)
  })

  it('입력이 바뀌면 안내가 띠 바로 아래에 선다', () => {
    const { container } = renderResult({}, true)
    const stack = container.querySelector('.voyage-cii-result-stack')!
    expect(stack.className).toContain('voyage-cii-result-stack--stale')
    const strip = screen.getByRole('region', { name: '결론' })
    expect(strip.nextElementSibling!.className).toBe('voyage-cii-result__stale')
  })
})
