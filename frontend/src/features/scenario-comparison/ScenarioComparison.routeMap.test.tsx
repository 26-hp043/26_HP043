// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import type { RouteLine } from '../fleet/FleetMap'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import * as session from '../../auth/session'

/**
 * 항로 비교 지도의 **선 이름** (#1836 ⑹).
 *
 * 목적항 datalist는 `<option value={port.name}>`이라 「부산 · KR」을 고르면 입력칸에 저장
 * 코드(`SINGAPORE`)가 들어간다 — 항차 입력 폼(`VoyagePanel`·`VoyageCiiActions`)과 같은
 * 패턴이고 `ScenarioComparison.test.tsx`(#1005)가 그 값을 단언한다. 지도 선 이름은 **표시
 * 자리**라 저장 코드가 아니라 보이는 이름이어야 한다(`#1742` `portDisplayName`).
 *
 * `ScenarioComparison.test.tsx`는 지도 대역을 두지 않아(자산 없음 → 지도 생략) 별도 파일로
 * 둔다 — `FleetMap` 대역은 `VoyageRouteMap.test.tsx`와 같다.
 */
vi.mock('../fleet/basemap', () => ({ hasBasemap: async () => true }))
vi.mock('../fleet/FleetMap', () => ({
  FleetMap: (props: { routes: RouteLine[]; caption: unknown; ariaLabel: string }) => (
    <div data-testid="map" data-routes={JSON.stringify(props.routes)} aria-label={props.ariaLabel}>
      {props.caption as never}
    </div>
  ),
}))

const { ScenarioComparison } = await import('./ScenarioComparison')

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const PORTS = [
  { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
  { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
]

const COMPARE_BODY = {
  data: {
    scenarios: ['DIRECT', 'DETOUR', 'SLOW_STEAMING'].map((type, index) => ({
      scenario_id: `sc-${type.toLowerCase()}`,
      scenario_type: type,
      scenario_name: ['직항', '우회', '감속'][index],
      distance_nm: 1000,
      speed_kn: 12.8,
      duration_hours: '78.1250',
      fuel_ton: '87.50',
      co2_emission_ton: '272.48',
      attained_cii: '42.535870',
      required_cii: '17.374582',
      ratio_to_required: '2.44817',
      estimated_rating: 'E',
      risk_level: 'CRITICAL',
      next_worse_boundary_margin_ratio: null,
      calculation_basis: { ship_type: 'BULK_CARRIER', transport_capacity_basis: 'DWT' },
    })),
    summary: {
      lowest_cii_scenarios: ['SLOW_STEAMING'],
      shortest_duration_scenarios: ['DIRECT'],
      lowest_fuel_scenarios: ['SLOW_STEAMING'],
    },
  },
  warnings: [],
  disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
}

function stubServer() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/ports/samples')) return jsonResponse({ data: PORTS })
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      if (url.includes('/scenarios/compare')) return jsonResponse(COMPARE_BODY)
      return jsonResponse({ data: {} })
    }),
  )
}

function renderScreen() {
  const value: ShellContext = {
    ...EMPTY_SHELL_CONTEXT,
    vesselId: '00000000-0000-4000-8000-000000000001',
    vessels: [
      { id: '00000000-0000-4000-8000-000000000001', displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
    ],
    vesselsState: 'ready',
    selectVesselId: () => {},
  }
  return render(
    <MemoryRouter initialEntries={['/scenarios']}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/scenarios" element={<ScenarioComparison />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role: 'OFFICE',
    emailVerifiedAt: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('항로 비교 지도의 선 이름 (#1836 ⑹)', () => {
  it('샘플 항만을 골라 비교하면 입력칸은 저장 코드, 지도 선 이름은 보이는 이름이다', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')
    await waitFor(() => expect(document.querySelectorAll('#sc-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText(/현재 위치/), { target: { value: PORTS[0].name_ko } })
    fireEvent.change(screen.getByLabelText('목적항'), { target: { value: PORTS[1].name_ko } })
    // 입력칸은 항차 입력 폼과 같은 패턴 — 저장 코드가 들어간다. 이 동작은 바꾸지 않는다.
    expect((screen.getByLabelText('목적항') as HTMLInputElement).value).toBe(PORTS[1].name)

    fireEvent.click(await screen.findByRole('button', { name: /비교하기/ }))

    const map = await screen.findByTestId('map', undefined, { timeout: 10_000 })
    const routes = JSON.parse(map.getAttribute('data-routes') ?? '[]') as RouteLine[]
    expect(routes).toHaveLength(1)
    // 지도 선 이름은 표시 자리다 — 저장 코드가 아니라 픽스처의 보이는 이름이다.
    expect(routes[0].name).not.toContain(PORTS[1].name)
    expect(routes[0].name).toContain(PORTS[1].name_ko)
  })

  it('다시 비교하면 지도가 새로 마운트된다 — 못 받은 항로선을 처음부터 다시 묻는다 (#1856)', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')
    await waitFor(() => expect(document.querySelectorAll('#sc-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText(/현재 위치/), { target: { value: PORTS[0].name_ko } })
    fireEvent.change(screen.getByLabelText('목적항'), { target: { value: PORTS[1].name_ko } })

    fireEvent.click(await screen.findByRole('button', { name: /비교하기/ }))
    const first = await screen.findByTestId('map', undefined, { timeout: 10_000 })

    // 계산 중 분기가 결과 트리를 내리므로 지도는 새 노드다 — 훅 상태(실패 기록)도 새것이다.
    fireEvent.click(screen.getByRole('button', { name: /비교하기/ }))
    await waitFor(() => expect(screen.getByTestId('map')).not.toBe(first), { timeout: 10_000 })
    expect(first.isConnected).toBe(false)
  })
})
