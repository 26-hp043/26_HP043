// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { AnnualSimulation } from './AnnualSimulation'
import { ANNUAL_COPY } from './copy'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'

/**
 * 「이 seed로 다시 실행」의 **화면 배선** (`PRD §12.4.3` · #776).
 *
 * `#556`이 `reproduce`를 「검증 수단이지 사용자 기능이 아니다」로 판정해 화면에서
 * 도달할 수 없었다. `PRD §12.4.3`이 버튼을 요구해 판정이 뒤집혔다.
 *
 * 데이터 경계(경로·본문 없음·봉투)는 `apiProvider.test.ts`가 잠근다. 여기서는
 * **버튼이 화면에 있고, 누르면 원본 실행을 재현하며, 결과를 알리는가**만 본다 —
 * provider만 검사하면 화면이 그것을 부르지 않아도 초록이다(`#873`·`#890`과 같은 함정).
 */

const VESSEL_ID = '00000000-0000-4000-8000-000000000001'

function body(simulationId: string) {
  return {
    data: {
      simulation_id: simulationId,
      deterministic: {
        projected_attained_cii: '5.0248000000',
        projected_rating: 'C',
        completed_voyage_count: 8,
        remaining_voyage_count: 4,
        completed_M_gco2: '6290280000',
        completed_W_capacity_nm: '1260000000',
        planned_M_gco2: '3145140000',
        planned_W_capacity_nm: '630000000',
      },
      monte_carlo: {
        rng_metadata: {
          seed_entropy: '12345',
          bit_generator: 'PCG64DXSM',
          numpy_version: '2.1.0',
          python_version: '3.12.4',
          platform: 'Linux',
        },
        runs: 5000,
        rating_probabilities: { A: '0.0200', B: '0.2800', C: '0.5500', D: '0.1300', E: '0.0200' },
        target_success_probability: '0.3000',
        target_rating: 'B',
        p10: '4.7100',
        p50: '5.0400',
        p90: '5.4200',
        mean_cii: '5.0600',
      },
      risk_level: 'HIGH',
      sensitivity_analysis: { interaction_note: '개별 효과만 표시합니다.' },
      snapshot: { snapshot_id: 'snap-1', created_at: '2026-08-17T00:00:00Z', voyage_count: 12 },
    },
    calculation_run_id: `run-${simulationId}`,
    warnings: [],
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response
}

/**
 * `reproduce`에 줄 응답을 바꿔 끼울 수 있게 한다. 실행은 부를 때마다 새
 * `simulation_id`를 준다 — 실제 서버가 그렇고, 재현 상태가 **새 결과에 남지 않는가**를
 * 보려면 두 실행이 구분돼야 한다.
 */
function stubServer(reproduce: () => Response = () => jsonResponse(body('sim-1'))) {
  let runs = 0
  const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
    void init
    const url = String(input)
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: [{ year: 2026 }] })
    }
    if (url.endsWith('/reproduce')) return reproduce()
    if (url.endsWith('/annual-simulations')) {
      runs += 1
      return jsonResponse(body(`sim-${runs}`))
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

function renderScreen(entry = '/annual') {
  const value: ShellContext = {
    ...EMPTY_SHELL_CONTEXT,
    vesselId: VESSEL_ID,
    vessels: [{ id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' }],
    vesselsState: 'ready',
    selectVesselId: () => {},
  }
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/annual" element={<AnnualSimulation />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

/**
 * 기본 연도가 **선택된 뒤** 실행하고, 결과의 재현 버튼이 뜰 때까지 기다린다.
 *
 * 선택지가 그려진 것만으로는 부족하다 — 기본값은 목록이 온 다음 effect가 고르므로
 * 그 사이에 누르면 화면이 「목록을 불러오는 중」으로 실행을 거부한다. 표시값으로도
 * 기다릴 수 없다: 값이 `''`인 제어 셀렉트도 **첫 선택지를 표시**한다. 그래서 선택지가
 * 그려진 뒤 `act`로 effect를 비운다.
 */
async function runOnce(): Promise<HTMLElement> {
  await screen.findByRole('option', { name: '2026' })
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))
  return screen.findByRole('button', { name: ANNUAL_COPY.reproduceButton })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('이 seed로 다시 실행 (#776)', () => {
  it('실행 전에는 버튼이 없다 — 재현할 원본이 없다', async () => {
    stubServer()
    renderScreen()
    await screen.findByRole('option', { name: '2026' })

    expect(screen.queryByRole('button', { name: ANNUAL_COPY.reproduceButton })).toBeNull()
  })

  it('누르면 방금 본 실행을 재현하고 같은 결과였음을 알린다', async () => {
    const fetchImpl = stubServer()
    renderScreen()

    fireEvent.click(await runOnce())

    expect(await screen.findByText(ANNUAL_COPY.reproduceSuccess)).toBeTruthy()
    const urls = fetchImpl.mock.calls.map(([input]) => String(input))
    // 폼 값이 아니라 **결과의 식별자**로 부른다 — 그래야 원본 실행이 재현된다.
    expect(urls).toContain('/api/v1/annual-simulations/sim-1/reproduce')
  })

  it('재현하지 못하면 서버가 준 사유를 그대로 보인다', async () => {
    const message =
      '원본 실행 이후 규정 파라미터가 변경되어 같은 조건으로 재현할 수 없습니다. ' +
      '새로 실행하면 현재 파라미터 기준의 결과를 얻을 수 있습니다.'
    stubServer(() => jsonResponse({ error: { code: 'PARAMETER_ERROR', message } }, 409))
    renderScreen()

    fireEvent.click(await runOnce())

    const alert = await screen.findByRole('alert')
    // 제목은 `PRD §6.4` 처리 실패 패턴으로 컴포넌트가 짓는다 (2026-09-11 확정 B).
    expect(alert.textContent).toContain('재현에 실패했습니다')
    expect(alert.textContent).toContain(message)
    // 실패를 성공 문구와 함께 내지 않는다.
    expect(screen.queryByText(ANNUAL_COPY.reproduceSuccess)).toBeNull()
  })

  it('새로 실행하면 직전 결과의 재현 확인이 남지 않는다', async () => {
    // 새 결과는 아직 아무도 재현하지 않았다 — 확인 문구가 남으면 검증하지 않은 값을
    // 검증했다고 말한다.
    stubServer()
    renderScreen()
    fireEvent.click(await runOnce())
    await screen.findByText(ANNUAL_COPY.reproduceSuccess)

    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    await waitFor(() => expect(screen.getByText('run-sim-2')).toBeTruthy())
    expect(screen.queryByText(ANNUAL_COPY.reproduceSuccess)).toBeNull()
  })
})

describe('민감도 — 거리 행의 이유 (#756)', () => {
  function withSensitivity(analysis: Record<string, unknown>) {
    const payload = body('sim-1')
    payload.data.sensitivity_analysis = {
      interaction_note: '개별 효과만 표시합니다.',
      ...analysis,
    } as typeof payload.data.sensitivity_analysis
    return payload
  }

  function stubWith(payload: unknown) {
    const fetchImpl = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) {
        return jsonResponse({ data: [{ year: 2026 }] })
      }
      if (url.endsWith('/annual-simulations')) return jsonResponse(payload)
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
  }

  it('⚠️ 잔여 계획이 0건이면 표 전체가 무의미하다고 말한다 (2026-09-13 화면 실측)', async () => {
    /*
     * 지렛대는 **잔여 계획 항차를 움직여** 결과를 다시 낸다. 0건이면 무엇을 바꿔도
     * 확정 실적만 남아 **여섯 행이 전부 같은 값**이 된다. 그때 거리 행 설명만 띄우면
     * **나머지 행은 의미가 있는 것처럼 읽힌다.**
     *
     * 실제 화면에서 그 상태를 봤다 — 데모 선박 하나가 잔여 계획이 없어 여섯 행이
     * 전부 `19.789`였다. 응답에는 `NO_REMAINING_VOYAGES`가 이미 실려 있었다.
     */
    const payload = withSensitivity({
      distance_minus_5pct: { projected_cii: '19.789', rating_change: 'D→D' },
      distance_plus_5pct: { projected_cii: '19.789', rating_change: 'D→D' },
    })
    // ⚠️ `warnings`는 **`data` 밖**이다 (`API_SPEC §1.3.1` · `apiProvider.ts:142`).
    //
    // `body()`의 `warnings: []`가 `never[]`로 추론되므로 대입에 타입을 붙인다 —
    // vitest는 통과하고 `npm run build`(tsc)에서만 걸리는 자리다.
    ;(payload as { warnings: string[] }).warnings = ['NO_REMAINING_VOYAGES']
    stubWith(payload)
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.sensitivityNoRemainingNote)).toBeTruthy()
    // 거리 행 설명은 **띄우지 않는다** — 그것만 띄우면 나머지 행이 유효해 보인다.
    expect(screen.queryByText(ANNUAL_COPY.distanceNote)).toBeNull()
  })

  it('거리 행이 있으면 거의 변하지 않는 이유를 말한다 — 「효과 없음」으로 읽히지 않게', async () => {
    stubWith(
      withSensitivity({
        distance_minus_5pct: { projected_cii: '8.971337', rating_change: 'E→E' },
        distance_plus_5pct: { projected_cii: '8.970912', rating_change: 'E→E' },
      }),
    )
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.distanceNote)).toBeTruthy()
  })

  it('거리 행이 없으면 말하지 않는다', async () => {
    stubWith(
      withSensitivity({
        fuel_minus_10pct: { projected_cii: '8.1', rating_change: 'E→D' },
      }),
    )
    renderScreen()
    await runOnce()

    expect(screen.queryByText(ANNUAL_COPY.distanceNote)).toBeNull()
  })
})

/**
 * 기능①의 「연간 시뮬레이터에서 보기」가 싣는 연도 (#891 · `PRD §10.5` 「해당 선박·연도로」).
 *
 * 주소의 `?year=`가 선택지에 있으면 그 해로 실행하고, 없으면 화면 기본값(`pickDefaultYear`)으로
 * 떨어진다 — 주소 값을 검증 없이 쓰지 않는다.
 */
describe('주소의 연도로 시작한다 (#891)', () => {
  function stubYears(years: number[]) {
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) {
        return jsonResponse({ data: years.map((year) => ({ year })) })
      }
      if (url.endsWith('/annual-simulations')) {
        void init
        return jsonResponse(body('sim-y'))
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  async function submittedYear(fetchImpl: ReturnType<typeof stubYears>): Promise<number> {
    await runOnce()
    const call = fetchImpl.mock.calls.find(([url]) => String(url).endsWith('/annual-simulations'))
    return JSON.parse(String((call as unknown as [string, RequestInit])[1].body)).regulation_year
  }

  it('선택지에 있는 해면 그 해로 실행한다', async () => {
    const fetchImpl = stubYears([2025, 2026, 2027])
    renderScreen('/annual?year=2025')
    expect(await submittedYear(fetchImpl)).toBe(2025)
  })

  it('선택지에 없는 해면 기본값으로 떨어진다 — 주소 값을 그대로 쓰지 않는다', async () => {
    const fetchImpl = stubYears([2026])
    renderScreen('/annual?year=1999')
    expect(await submittedYear(fetchImpl)).toBe(2026)
  })
})

/**
 * 「이 실행에 쓴 항차」 (#992 · `API_SPEC §6.3`) — 서버에 있는데 화면에서 닿을 수 없던 조회다.
 *
 * **펼칠 때만** 부른다 — 결과마다 미리 받으면 쓰지 않을 조회가 실행마다 는다.
 */
describe('이 실행에 쓴 항차 (#992)', () => {
  const SNAPSHOT = {
    data: [
      {
        snapshot_voyage_id: 'sv-1',
        original_voyage_id: 'v-1',
        voyage_no: 'V-2026-001',
        status_at_snapshot: 'COMPLETED',
        distance_nm: 11200,
        speed_kn: 13.5,
        fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 850, cf_used: 3.114 }],
        annual_inclusion_policy: 'INCLUDE_AS_ACTUAL',
      },
    ],
  }

  it('펼치기 전에는 부르지 않고, 펼치면 그 실행의 스냅샷 항차를 그린다', async () => {
    const fetchImpl = stubServer()
    fetchImpl.mockImplementation(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.endsWith('/snapshot-voyages')) return jsonResponse(SNAPSHOT)
      if (url.endsWith('/annual-simulations')) return jsonResponse(body('sim-1'))
      return jsonResponse({ data: {} })
    })
    renderScreen()
    await runOnce()

    const calls = () => fetchImpl.mock.calls.map(([u]) => String(u))
    expect(calls().some((u) => u.endsWith('/snapshot-voyages'))).toBe(false)

    const summary = screen.getByText(/이 실행에 쓴 항차 보기/)
    const details = summary.closest('details') as HTMLDetailsElement
    details.open = true
    fireEvent(details, new Event('toggle'))

    expect(await screen.findByText('V-2026-001')).toBeTruthy()
    expect(calls()).toContain('/api/v1/annual-simulations/sim-1/snapshot-voyages')
    expect(screen.getByText('연간 반영 — 실적')).toBeTruthy()
    expect(screen.getByText('HFO 850.0t')).toBeTruthy()
  })
})

