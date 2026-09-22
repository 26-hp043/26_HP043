// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { AnnualSimulation } from './AnnualSimulation'
import * as session from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { ANNUAL_COPY } from './copy'
import type { FeedbackBlock, ReductionPlanBlock } from './types'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import { formatTimestamp } from '../../display/format'

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
const AS_OF = '2026-09-21T05:24:00Z'

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
    // 서버는 집계에 쓴 시각을 늘 싣는다(`API_SPEC §6.1` · `#816`) — 결과 위 고지가 쓴다 (#1578)
    meta: { duration_ms: 10, as_of: AS_OF },
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

/** 기존 검사는 전부 **사무직** 전제다 — 실행이 사무직 전용이 됐다 (#672). */
function stubRole(role: session.UserRole) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role,
    emailVerifiedAt: null,
  })
}

beforeEach(() => {
  stubRole('OFFICE')
})

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

    const ok = await screen.findByText(ANNUAL_COPY.reproduceSuccess)
    /*
     * 성공은 **실패와 같은 무게**로 보인다 (2026-09-17 확정 ⓑ · `#1053` 40번).
     *
     * 종전에는 `--text-muted` 작은 한 줄이라 실패(아이콘 달린 블록)보다 약했다.
     * 재현 확인은 **성공이 곧 결론**인 검증 행위라 그 반대가 맞다. 문구만 보면
     * 한 줄로 되돌아가도 통과하므로 **블록 안에 있는지**를 함께 잠근다.
     *
     * 색은 잠그지 않는다 — 라이트 Success가 이 면 위에서 `1.4.11`에 미달해
     * 지금은 쓰지 않으며, 값이 정해지면 입히게 된다(별건).
     */
    expect(ok.closest('.annual-sim__reproduce-ok')).toBeTruthy()
    // 낭독이 결과를 알린다 — 아이콘은 `aria-hidden`이라 문구만 읽힌다.
    expect(ok.closest('[role="status"]')).toBeTruthy()

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

    /*
     * #1580 — 같은 값 여덟 줄과 설명 두 개가 쌓이지 않는다. 표도, 표에 붙는 서버 설명
     * (`interaction_note`)도 없다 — 안내 한 줄이 이 절의 전부다.
     */
    const section = screen.getByRole('heading', { name: ANNUAL_COPY.sensitivityTitle }).closest('section')!
    expect(within(section).queryByRole('table')).toBeNull()
    expect(within(section).queryByText('개별 효과만 표시합니다.')).toBeNull()
    expect(section.querySelectorAll('p')).toHaveLength(1)
  })

  it('잔여 계획이 있으면 표와 서버 설명을 그대로 둔다 (#1580)', async () => {
    stubWith(
      withSensitivity({
        speed_minus_1kn: { projected_cii: '8.100000', rating_change: 'E→D', target_probability_change: '0.1200' },
      }),
    )
    renderScreen()
    await runOnce()

    const section = screen.getByRole('heading', { name: ANNUAL_COPY.sensitivityTitle }).closest('section')!
    expect(within(section).getByRole('table')).toBeTruthy()
    expect(within(section).getByText('개별 효과만 표시합니다.')).toBeTruthy()
    expect(within(section).queryByText(ANNUAL_COPY.sensitivityNoRemainingNote)).toBeNull()
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


/**
 * 필요 감축량 카드 (`PRD §12.3.1` · #433).
 *
 * 계산 자체는 `calc/annual_simulation.py`가 잠근다. 여기서는 **네 상태를 화면이
 * 구분해 말하는가**만 본다 — 넷을 같은 모양으로 두면 사용자가 **가장 좋은 해석**을
 * 고르고, 그 해석이 대개 틀리다.
 *
 * | 상태 | 화면이 말해야 하는 것 |
 * |---|---|
 * | 줄여야 한다 | 몇 g · 연료 몇 t |
 * | 이미 목표 안 | 줄일 것이 없다 |
 * | 잔여 계획 0건 | 줄일 **대상**이 없다 (위와 다르다) |
 * | 다 없애도 못 닿음 | **「n톤 줄이세요」가 거짓이 되는 경우** |
 */
describe('필요 감축량 — 목표 역산 (#433)', () => {
  function withPlan(plan: ReductionPlanBlock | null) {
    const payload = body('sim-1') as Record<string, any>
    if (plan === null) delete payload.data.reduction_plan
    else payload.data.reduction_plan = plan
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

  /** 타입을 붙여 **필드명 오타가 빌드에서 잡히게** 한다 — 응답 계약과 같은 모양이다. */
  const BASE = {
    target_rating: 'B',
    target_cii: '4.742300',
    allowed_planned_M_gco2: '665580000.000000',
    achievable: true,
  } satisfies Omit<ReductionPlanBlock, 'required_cut_gco2' | 'required_cut_fuel_ton'>

  it('줄여야 하는 양이 있으면 CO₂와 연료를 함께 보인다', async () => {
    stubWith(
      withPlan({ ...BASE, required_cut_gco2: '330900000.000000', required_cut_fuel_ton: '36.260000' }),
    )
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.reductionTitle)).toBeTruthy()
    expect(screen.getByText(ANNUAL_COPY.reductionCutLabel)).toBeTruthy()
    // §4.2 — CO₂는 tCO₂ · 1자리, 연료는 t · 1자리 (#1539). 종전에는 `330900000 g` · `36.26 t`였다.
    expect(screen.getByText('330.9 tCO₂')).toBeTruthy()
    expect(screen.getByText('36.3 t')).toBeTruthy()
    expect(screen.queryByText(/\d g$/)).toBeNull()
  })

  it('⚠️ 무엇을 고정했는지 말한다 — 「항차를 줄여도 되지 않나」로 읽히지 않게', async () => {
    /*
     * 부등식의 미지수가 둘이라 **무엇을 고정하느냐가 곧 산출물을 정한다**
     * (`PRD §12.3.1`). 거리를 고정했다는 사실을 적지 않으면 사용자가 다른 전제로 읽는다.
     */
    stubWith(
      withPlan({ ...BASE, required_cut_gco2: '330900000.000000', required_cut_fuel_ton: '36.260000' }),
    )
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.reductionCaption)).toBeTruthy()
  })

  it('이미 목표 안이면 0을 보이지 않고 그렇다고 말한다', async () => {
    stubWith(withPlan({ ...BASE, required_cut_gco2: '0', required_cut_fuel_ton: '0.000000' }))
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.reductionNoneNeeded)).toBeTruthy()
    expect(screen.queryByText(ANNUAL_COPY.reductionCutLabel)).toBeNull()
  })

  it('⚠️ 잔여 계획이 없는 것과 줄일 것이 없는 것을 구분한다', async () => {
    /* 둘을 같게 두면 「이미 목표 안이다」로 읽히는데, 실제로는 **계산할 대상이 없다.** */
    stubWith(withPlan({ ...BASE, required_cut_gco2: '45765000.000000', required_cut_fuel_ton: null }))
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.reductionNoPlan)).toBeTruthy()
    expect(screen.queryByText(ANNUAL_COPY.reductionNoneNeeded)).toBeNull()
  })

  it('⚠️ 다 없애도 못 닿으면 그렇게 말한다 — 「n톤 줄이세요」가 거짓이 되는 경우', async () => {
    stubWith(
      withPlan({
        ...BASE,
        allowed_planned_M_gco2: '-6739000000.000000',
        required_cut_gco2: '7735140000.000000',
        required_cut_fuel_ton: '2484.000000',
        achievable: false,
      }),
    )
    renderScreen()
    await runOnce()

    // 캡션 두 상태와 같은 무게로 두지 않는다 — Warning 좌측 스트라이프 (#1052 ⑸).
    expect(screen.getByText(ANNUAL_COPY.reductionUnreachable).className).toBe('annual-sim__unreachable')
    expect(screen.queryByText(ANNUAL_COPY.reductionCutLabel)).toBeNull()
  })

  it('블록이 없는 옛 실행에서는 카드를 그리지 않는다 — 0으로 그리면 「줄일 것 없음」이 된다', async () => {
    stubWith(withPlan(null))
    renderScreen()
    await runOnce()

    expect(screen.queryByText(ANNUAL_COPY.reductionTitle)).toBeNull()
  })
})


/**
 * 실적 보정계수 (`PRD §12.2.1` · #363).
 *
 * 계수 계산과 재현은 백엔드 검사가 잠근다. 여기서는 ⑴ **켠 것만 요청에 실리는가**와
 * ⑵ **세 상태(곱함 · 안 곱함 · 계산 못 함)를 화면이 구분해 말하는가**를 본다.
 */
describe('실적 보정계수 (#363)', () => {
  function withFeedback(block: FeedbackBlock | null) {
    const payload = body('sim-1') as Record<string, any>
    if (block === null) delete payload.data.feedback
    else payload.data.feedback = block
    return payload
  }

  function stubWith(payload: unknown) {
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) {
        return jsonResponse({ data: [{ year: 2026 }] })
      }
      if (url.endsWith('/annual-simulations')) return jsonResponse(payload)
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  function runBody(fetchImpl: ReturnType<typeof stubWith>): Record<string, unknown> {
    const call = fetchImpl.mock.calls.find(([url]) => String(url).endsWith('/annual-simulations'))
    return JSON.parse(String(call?.[1]?.body))
  }

  const APPLIED = {
    factor: '1.064516',
    sample_size: 4,
    min_sample: 3,
    requested: true,
    applied: true,
  } satisfies FeedbackBlock

  it('끈 채로 실행하면 요청에 싣지 않는다 — 종전 요청과 같은 모양이다', async () => {
    const fetchImpl = stubWith(withFeedback(null))
    renderScreen()
    await runOnce()

    expect(runBody(fetchImpl)).not.toHaveProperty('apply_feedback_factor')
  })

  it('켜고 실행하면 apply_feedback_factor=true를 보낸다', async () => {
    const fetchImpl = stubWith(withFeedback(APPLIED))
    renderScreen()
    fireEvent.click(screen.getByLabelText(ANNUAL_COPY.feedbackToggle))
    await runOnce()

    expect(runBody(fetchImpl)).toMatchObject({ apply_feedback_factor: true })
  })

  it('곱했으면 비율과 「이번 실행에 반영했다」를 보인다', async () => {
    stubWith(withFeedback(APPLIED))
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.feedbackTitle)).toBeTruthy()
    expect(screen.getByText(/1\.0645/)).toBeTruthy()
    expect(screen.getByText(ANNUAL_COPY.feedbackApplied)).toBeTruthy()
  })

  it('켜지 않았으면 값은 보이되 반영하지 않았다고 말한다', async () => {
    stubWith(withFeedback({ ...APPLIED, requested: false, applied: false }))
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.feedbackNotApplied)).toBeTruthy()
    expect(screen.queryByText(ANNUAL_COPY.feedbackApplied)).toBeNull()
  })

  it('⚠️ 표본이 모자라면 1.0이 아니라 「계산하지 않음」이다 — 계획대로 쓰는 것처럼 읽히지 않게', async () => {
    stubWith(
      withFeedback({ factor: null, sample_size: 1, min_sample: 3, requested: true, applied: false }),
    )
    renderScreen()
    await runOnce()

    expect(screen.getByText(ANNUAL_COPY.feedbackUnavailableValue)).toBeTruthy()
    expect(screen.getByText(ANNUAL_COPY.feedbackUnavailable)).toBeTruthy()
    expect(screen.queryByText(ANNUAL_COPY.feedbackApplied)).toBeNull()
    expect(screen.queryByText(/× 1/)).toBeNull()
  })

  it('블록이 없는 옛 실행에서는 카드를 그리지 않는다', async () => {
    stubWith(withFeedback(null))
    renderScreen()
    await runOnce()

    expect(screen.queryByText(ANNUAL_COPY.feedbackTitle)).toBeNull()
  })
})

/**
 * 대상이 바뀌면 앞의 결과를 남기지 않는다 (`#1094` · `#874` 선례).
 *
 * 결과 카드에 **선박명이 없다.** 그래서 앞 배의 숫자가 남아 있어도 화면만 보고는
 * 알아챌 수 없다 — 「아직 안 돌렸다」와 「앞 배 결과」가 같은 모양이면 안 된다.
 */
describe('선박 전환과 늦은 응답 (#1094)', () => {
  const OTHER_ID = '00000000-0000-4000-8000-000000000002'

  /** 상단바 선택을 바꿀 수 있게 `vesselId`를 밖에서 주입한다. */
  function renderWith(vesselId: string) {
    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId,
      vessels: [
        { id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
        { id: OTHER_ID, displayName: '다른 배', shipType: 'BULK_CARRIER' },
      ],
      vesselsState: 'ready',
      selectVesselId: () => {},
    }
    return render(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('선박을 바꾸면 앞 선박의 결과가 사라진다', async () => {
    stubServer()
    const { rerender } = renderWith(VESSEL_ID)
    await runOnce()
    expect(screen.getByRole('button', { name: ANNUAL_COPY.reproduceButton })).toBeTruthy()

    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId: OTHER_ID,
      vessels: [
        { id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
        { id: OTHER_ID, displayName: '다른 배', shipType: 'BULK_CARRIER' },
      ],
      vesselsState: 'ready',
      selectVesselId: () => {},
    }
    rerender(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: ANNUAL_COPY.reproduceButton })).toBeNull()
    })
  })

  it('실행 중에 선박을 바꾸면 앞 선박의 늦은 응답이 붙지 않는다', async () => {
    /*
     * 앞 선박의 요청을 **손에 쥐고 있다가** 전환 뒤에 풀어 준다. Monte Carlo
     * 10,000회는 초 단위라 실제로 전환할 시간이 충분하다.
     */
    let release: (() => void) | null = null
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/regulation-years')) {
          return jsonResponse({ data: [{ year: 2026 }] })
        }
        if (url.endsWith('/annual-simulations')) {
          await held
          return jsonResponse(body('sim-late'))
        }
        return jsonResponse({ data: {} })
      }),
    )

    const { rerender } = renderWith(VESSEL_ID)
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId: OTHER_ID,
      vessels: [
        { id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
        { id: OTHER_ID, displayName: '다른 배', shipType: 'BULK_CARRIER' },
      ],
      vesselsState: 'ready',
      selectVesselId: () => {},
    }
    rerender(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    await act(async () => {
      release?.()
      await held
    })

    // 앞 선박의 성공 결과가 새 선박 화면에 붙지 않는다.
    expect(screen.queryByRole('button', { name: ANNUAL_COPY.reproduceButton })).toBeNull()
  })
})

/**
 * 현장직은 폼을 읽되 실행 버튼이 잠긴다 (`API_SPEC §1.2` · #672). 결과 조회는 두 역할
 * 모두라 화면 자체는 열린다 — 잠기는 것은 「실행」 하나다.
 */
describe('역할 — 현장직은 실행 버튼이 비활성이다 (#672)', () => {
  it('현장직: 버튼 disabled + 안내, 요청은 나가지 않는다', async () => {
    stubRole('FIELD')
    const fetchImpl = stubServer()
    renderScreen()
    const button = (await screen.findByRole('button', {
      name: ANNUAL_COPY.submit,
    })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText(OFFICE_ONLY_ACTION_HINT)).toBeTruthy()
    fireEvent.click(button)
    await act(async () => {})
    expect(
      fetchImpl.mock.calls.some(([input]) => String(input).endsWith('/annual-simulations')),
    ).toBe(false)
  })

  it('사무직: 버튼이 살아 있고 안내가 없다', async () => {
    stubServer()
    renderScreen()
    const button = (await screen.findByRole('button', {
      name: ANNUAL_COPY.submit,
    })) as HTMLButtonElement
    await waitFor(() => expect(button.disabled).toBe(false))
    expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()
  })
})

/*
 * ── 입력 폼 결함 5종 (#1096) ───────────────────────────────────────────────
 */

/** `POST /annual-simulations` 요청 본문. 없으면 `null` — 요청이 나가지 않았다는 뜻이다. */
function submittedBody(fetchImpl: {
  mock: { calls: unknown[][] }
}): Record<string, unknown> | null {
  const call = fetchImpl.mock.calls.find((c) => String(c[0]).endsWith('/annual-simulations'))
  if (!call) return null
  return JSON.parse(String((call[1] as RequestInit).body))
}

describe('⑴ 반복 횟수 — step이 아니라 서버 규칙으로 검증한다 (#1096)', () => {
  it('2,500은 서버가 받는 값이다 — 그대로 보낸다', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})

    fireEvent.change(screen.getByLabelText(/반복 횟수/), { target: { value: '2500' } })
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    await screen.findByRole('button', { name: ANNUAL_COPY.reproduceButton })
    expect(submittedBody(fetchImpl)?.simulation_runs).toBe(2500)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('1,000 미만은 화면 오류 자리에 문구가 서고 요청은 나가지 않는다', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})

    const input = screen.getByLabelText(/반복 횟수/)
    fireEvent.change(input, { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe(ANNUAL_COPY.runsBelowMin)
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(submittedBody(fetchImpl)).toBeNull()

    // 값을 고치면 문구가 사라진다.
    fireEvent.change(input, { target: { value: '1000' } })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('10,000 초과도 막는다 — 잘려서 실행되는 값을 받아 주지 않는다', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})

    fireEvent.change(screen.getByLabelText(/반복 횟수/), { target: { value: '20000' } })
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    expect((await screen.findByRole('alert')).textContent).toBe(ANNUAL_COPY.runsAboveMax)
    expect(submittedBody(fetchImpl)).toBeNull()
  })
})

describe('⑵ 확률 스택 바 — 0% 구간에는 초점이 가지 않는다 (#1096)', () => {
  it('「0.0%」 구간은 바에 그리지 않고 범례에만 남는다', async () => {
    const payload = body('sim-z')
    payload.data.monte_carlo.rating_probabilities = {
      A: '0.0000',
      B: '0.3000',
      C: '0.5500',
      D: '0.1500',
      E: '0.0000',
    }
    const fetchImpl = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.endsWith('/annual-simulations')) return jsonResponse(payload)
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    renderScreen()
    await runOnce()

    // 바 안의 구간은 세 개뿐이다 — 초점을 받을 수 있는 보이지 않는 요소가 없다.
    const bar = screen.getByRole('group', { name: /확률/ })
    expect(bar.querySelectorAll('.annual-sim__seg').length).toBe(3)
    expect(bar.querySelectorAll('[tabindex]').length).toBe(0)
    expect(screen.queryByRole('img', { name: 'A 0.0%' })).toBeNull()
    // 값은 범례에서 읽힌다.
    expect(screen.getByText(/^A 0\.0%$/)).toBeTruthy()
    expect(screen.getByText(/^E 0\.0%$/)).toBeTruthy()
  })
})

describe('⑶ 제목 단계를 건너뛰지 않는다 (#1096)', () => {
  it('섹션 h2 아래 소제목은 h3이고 h4는 없다', async () => {
    stubServer()
    renderScreen()
    await runOnce()

    expect(screen.getByRole('heading', { level: 3, name: ANNUAL_COPY.spreadTitle })).toBeTruthy()
    expect(screen.queryAllByRole('heading', { level: 4 })).toEqual([])
  })
})

describe('⑷ 주소의 연도는 목록과 대조된 뒤에만 쓴다 (#1096)', () => {
  it('목록이 오지 않으면 주소의 해로 실행하지 않는다 — 안내가 서고 요청은 없다', async () => {
    const fetchImpl = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) {
        return jsonResponse({ error: { code: 'INTERNAL_ERROR', message: 'x' } }, 500)
      }
      if (url.endsWith('/annual-simulations')) return jsonResponse(body('sim-x'))
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    renderScreen('/annual?year=2099')

    await screen.findByText('규제연도 목록을 불러오지 못했습니다')
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    expect((await screen.findByRole('status')).textContent).toBe(ANNUAL_COPY.yearsUnavailable)
    expect(submittedBody(fetchImpl)).toBeNull()
    // 실패가 아니라 안내다.
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('숫자가 아닌 주소 값은 기본값으로 떨어진다 — NaN을 보내지 않는다', async () => {
    const fetchImpl = stubServer()
    renderScreen('/annual?year=abc')
    await runOnce()

    expect(submittedBody(fetchImpl)?.regulation_year).toBe(2026)
  })
})

describe('⑸ 선박 미선택은 실패가 아니라 안내다 (#1096)', () => {
  function renderWithoutVessel() {
    const value: ShellContext = { ...EMPTY_SHELL_CONTEXT, vesselsState: 'ready' }
    return render(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('실행을 누르면 「실패했습니다」 없이 선박을 고르라는 안내만 선다', async () => {
    const fetchImpl = stubServer()
    renderWithoutVessel()

    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    const status = await screen.findByRole('status')
    expect(status.textContent).toBe(ANNUAL_COPY.needVessel)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(/실패했습니다/)).toBeNull()
    expect(submittedBody(fetchImpl)).toBeNull()
  })

  it('누르기 전에도 빈 자리가 선박부터 고르라고 말한다', () => {
    stubServer()
    renderWithoutVessel()
    expect(screen.getByText(ANNUAL_COPY.needVessel)).toBeTruthy()
  })
})

/**
 * 재현 응답의 경고가 화면에 남는다 (`#1095` ⑶ · `#833`).
 *
 * 서버는 원본과 **다른 `model_version`**에서 돌아 결과가 같았을 때
 * `MODEL_VERSION_DIFFERS`를 붙인다. 화면이 응답을 통째로 버리고 있어
 * 「같은 환경에서 같은 결과」와 「다른 환경에서 같은 결과」가 한 문장으로 뭉개졌다 —
 * `#833`이 만든 구분이 화면에서 사라진 상태였다.
 */
describe('재현 경고가 결과와 함께 보인다 (#1095 ⑶)', () => {
  it('MODEL_VERSION_DIFFERS가 재현 성공 문구 옆에 뜬다', async () => {
    const reproduced = { ...body('sim-1'), warnings: ['MODEL_VERSION_DIFFERS'] }
    stubServer(() => jsonResponse(reproduced))
    renderScreen()
    // `runOnce()`가 실행을 마치고 **재현 버튼**을 돌려준다.
    fireEvent.click(await runOnce())

    expect(await screen.findByText(ANNUAL_COPY.reproduceSuccess)).toBeTruthy()
    // 문구는 `API_SPEC §1.6`이 소유한다 — 화면이 다시 적지 않는다.
    expect(screen.getByText(/원본 실행과 다른 환경/)).toBeTruthy()
  })

  it('경고가 없으면 성공 문구만 뜬다 — 없는 경고를 지어내지 않는다', async () => {
    stubServer(() => jsonResponse({ ...body('sim-1'), warnings: [] }))
    renderScreen()
    fireEvent.click(await runOnce())

    expect(await screen.findByText(ANNUAL_COPY.reproduceSuccess)).toBeTruthy()
    expect(screen.queryByText(/원본 실행과 다른 환경/)).toBeNull()
  })
})

/**
 * 값이 없으면 단위를 붙이지 않는다 (`#1095` ⑷).
 *
 * `number()`가 값이 없을 때 `'—'`를 돌려주는데 그 뒤에 단위를 그대로 이어 붙여
 * **`LNG —t`**가 나갔다. 「모른다」에 단위를 붙이면 0에 가까운 어떤 수로 읽힌다.
 */
describe('스냅샷 항차의 연료량이 없으면 「—」다 (#1095 ⑷)', () => {
  it('연료량이 null이면 「LNG —t」가 아니라 「LNG —」다', async () => {
    const fetchImpl = stubServer()
    fetchImpl.mockImplementation(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.endsWith('/snapshot-voyages')) {
        return jsonResponse({
          data: [
            {
              snapshot_voyage_id: 'sv-2',
              original_voyage_id: 'v-2',
              voyage_no: 'V-2026-002',
              status_at_snapshot: 'PLANNED',
              distance_nm: 900,
              speed_kn: 12,
              fuel_uses: [{ fuel_type: 'LNG', fuel_ton: null, cf_used: 2.75 }],
              annual_inclusion_policy: 'INCLUDE_AS_PLAN',
            },
          ],
        })
      }
      if (url.endsWith('/annual-simulations')) return jsonResponse(body('sim-1'))
      return jsonResponse({ data: {} })
    })
    renderScreen()
    await runOnce()

    const summary = screen.getByText(/이 실행에 쓴 항차 보기/)
    const details = summary.closest('details') as HTMLDetailsElement
    details.open = true
    fireEvent(details, new Event('toggle'))

    expect(await screen.findByText('V-2026-002')).toBeTruthy()
    expect(screen.getByText('LNG —')).toBeTruthy()
    expect(screen.queryByText('LNG —t')).toBeNull()
  })
})

/**
 * 첫 화면은 기준연도 · 목표 등급 · 실행이다 (#1418).
 *
 * 반복 횟수·seed·실적 보정·대체 연료는 모두 기본값이 있어 비워도 실행된다. 접되 **보이지 않는
 * 칸이 결과를 바꾸고 있으면 접은 쪽이 말한다** — 요약이 「기본값으로 실행 / n개 바꿈」을 적는다.
 * 검사는 문구가 아니라 **접힘 상태와 칸의 소속**을 본다(`AGENTS §4.6`).
 */
describe('고급 설정을 접는다 (#1418)', () => {
  function openScreen() {
    stubServer()
    renderScreen()
  }

  function advanced(): HTMLDetailsElement {
    const summary = screen.getByText(ANNUAL_COPY.advancedTitle)
    return summary.closest('details') as HTMLDetailsElement
  }

  it('네 칸이 접힌 「고급 설정」 안에 있고, 목표 등급은 밖에 있다', async () => {
    openScreen()
    await screen.findByLabelText(ANNUAL_COPY.targetRatingLabel)

    const details = advanced()
    expect(details.open).toBe(false)
    expect(details.contains(screen.getByLabelText(/반복 횟수/))).toBe(true)
    expect(details.contains(screen.getByLabelText(/seed/))).toBe(true)
    expect(details.contains(screen.getByLabelText(ANNUAL_COPY.feedbackToggle))).toBe(true)
    expect(details.contains(screen.getByLabelText(ANNUAL_COPY.targetRatingLabel))).toBe(false)
  })

  /*
   * seed 안내는 칸 안에(placeholder) 두고 화면에서는 감춘다 (#1418 화면 확인). 낭독에는
   * 남아야 한다 — placeholder는 값이 들어오면 사라지고 낭독이 건너뛰기도 한다.
   */
  it('seed 안내가 칸 안에 있고 낭독에도 남는다', async () => {
    openScreen()
    const seedInput = (await screen.findByLabelText(/seed/)) as HTMLInputElement

    expect(seedInput.placeholder).toBe(ANNUAL_COPY.seedHint)
    const hintId = seedInput.getAttribute('aria-describedby')
    const hint = document.getElementById(hintId ?? '')
    expect(hint?.textContent).toBe(ANNUAL_COPY.seedHint)
    // 같은 문장을 칸 아래에 한 번 더 그리지 않는다.
    expect(hint?.className).toBe('sr-only')
  })

  it('기본값 그대로면 「기본값으로 실행」, 바꾸면 그 수를 적는다', async () => {
    openScreen()
    await screen.findByLabelText(ANNUAL_COPY.targetRatingLabel)
    expect(screen.getByText(new RegExp(ANNUAL_COPY.advancedDefault))).toBeTruthy()

    fireEvent.change(screen.getByLabelText(/seed/), { target: { value: '42' } })
    fireEvent.click(screen.getByLabelText(ANNUAL_COPY.feedbackToggle))

    expect(screen.getByText(new RegExp(`2${ANNUAL_COPY.advancedChangedSuffix}`))).toBeTruthy()
  })

  it('반복 횟수가 규칙을 어기면 펼쳐서 사유를 보인다 — 접힌 칸의 오류는 보이지 않는다', async () => {
    openScreen()
    // 연도 목록이 온 뒤에 눌러야 반복 횟수 판정까지 간다 — 그 전에는 「목록을 불러오는 중」이다.
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})
    fireEvent.change(screen.getByLabelText(/반복 횟수/), { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))

    expect((await screen.findByRole('alert')).textContent).toBe(ANNUAL_COPY.runsBelowMin)
    expect(advanced().open).toBe(true)
  })
})

/**
 * 재현 정보에서 seed 줄은 밖, 식별자와 항차 사본은 「계산 근거 보기」 안 (#1418).
 *
 * `PRD §12.4.3`이 「자동 seed … 결과에 표시한다」와 「이 seed로 다시 실행」 버튼을 요구한다 —
 * 둘은 접지 않는다. 접는 것은 스냅샷·계산 이력 UUID와 이 실행에 쓴 항차다.
 */
describe('재현 정보의 식별자를 접는다 (#1418)', () => {
  it('seed와 재현 버튼은 접히지 않고, 스냅샷·계산 이력은 접힌다', async () => {
    stubServer()
    renderScreen()
    const card = await runOnce()

    const seedRow = screen.getByText(/seed 12345/)
    expect(seedRow.closest('details')).toBeNull()
    expect(
      screen.getByRole('button', { name: ANNUAL_COPY.reproduceButton }).closest('details'),
    ).toBeNull()

    const details = screen
      .getByText(ANNUAL_COPY.reproDetailsToggle)
      .closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.contains(screen.getByText(ANNUAL_COPY.snapshotLabel))).toBe(true)
    expect(details.contains(screen.getByText(ANNUAL_COPY.runIdLabel))).toBe(true)
    expect(card).toBeTruthy()
  })
})

/**
 * 목표 등급은 C로 시작한다 (`#1453` · `PRD §12.2`).
 *
 * 종전에는 B였다. 첫 값을 바꾸지 않고 실행하는 사용자에게는 기본값이 곧 목표다 —
 * 요청 본문까지 C가 가는지를 본다. 셀렉트만 보면 화면과 전송이 갈릴 때 잡지 못한다.
 */
describe('목표 등급 기본값 (#1453)', () => {
  it('처음 고른 목표가 C이고, 바꾸지 않고 실행하면 C가 전송된다', async () => {
    stubRole('OFFICE')
    const fetchImpl = stubServer()
    renderScreen()

    const select = (await screen.findByLabelText(/목표 등급/)) as HTMLSelectElement
    expect(select.value).toBe('C')

    await runOnce()

    const call = fetchImpl.mock.calls.find(([url]) => String(url).endsWith('/annual-simulations'))
    expect(call).toBeTruthy()
    expect(JSON.parse((call![1] as RequestInit).body as string).target_rating).toBe('C')
  })
})

/**
 * 어느 배 · 어느 조건으로 계산했는지 화면에 있다 (#1553).
 *
 * 선박은 상단바 전역 선택을 따르는데 이름이 입력에도 결과에도 없었다. 결과 줄은 **실행
 * 시점의 값**이어야 한다 — 목표 등급은 실행 뒤에 바꿔도 결과가 지워지지 않는다.
 */
describe('대상 선박과 결과의 조건 (#1553)', () => {
  function renderShell(value: ShellContext) {
    return render(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  const targetLine = () =>
    screen.getByText(ANNUAL_COPY.targetVesselLabel).closest('.annual-sim__target') as HTMLElement

  it('실행 조건 머리에 대상 선박 이름과 바꾸는 곳이 있다', async () => {
    stubServer()
    renderScreen()
    await screen.findByRole('option', { name: '2026' })
    expect(within(targetLine()).getByText('샘플 벌크선')).toBeTruthy()
    expect(within(targetLine()).getByText(ANNUAL_COPY.targetVesselHint)).toBeTruthy()
  })

  it('고르지 않았으면 「선택되지 않음」, 목록이 오는 중이면 「불러오는 중」', () => {
    stubServer()
    const { unmount } = renderShell({ ...EMPTY_SHELL_CONTEXT, vesselsState: 'ready' })
    expect(within(targetLine()).getByText(ANNUAL_COPY.targetVesselNone)).toBeTruthy()
    unmount()

    renderShell({ ...EMPTY_SHELL_CONTEXT, vesselId: VESSEL_ID, vesselsState: 'loading' })
    expect(within(targetLine()).getByText(ANNUAL_COPY.targetVesselLoading)).toBeTruthy()
  })

  it('결과 머리에 이 결과의 조건이 있다 — 결과만 캡처해도 어느 배인지 읽힌다', async () => {
    stubServer()
    renderScreen()
    await runOnce()
    const line = screen.getByText(ANNUAL_COPY.resultConditionsLabel).closest('p') as HTMLElement
    expect(line.textContent).toContain('샘플 벌크선 · 2026년 · 목표 등급 C')
    // 결과 영역의 맨 위다 — 추정 고지보다 먼저.
    expect(line.previousElementSibling).toBeNull()
  })

  it('⚠️ 실행 뒤 목표를 바꿔도 결과 줄은 실행 때의 목표다', async () => {
    stubServer()
    renderScreen()
    await runOnce()
    fireEvent.change(screen.getByLabelText(ANNUAL_COPY.targetRatingLabel), { target: { value: 'A' } })

    const line = screen.getByText(ANNUAL_COPY.resultConditionsLabel).closest('p') as HTMLElement
    expect(line.textContent).toContain('목표 등급 C')
    expect(line.textContent).not.toContain('목표 등급 A')
  })
})

describe('결과 위 추정 고지 (#1578 · `DESIGN_SYSTEM §11`)', () => {
  it('응답의 기준 시각을 담고, 하단 면책의 「예측값」을 되풀이하지 않는다', async () => {
    stubServer()
    renderScreen()
    await runOnce()

    const notice = await screen.findByText(/잔여 계획을 전제로 한 추정값/)
    expect(notice.textContent).toContain(`기준 시각은 ${formatTimestamp(AS_OF)}입니다.`)
    expect(notice.textContent).not.toMatch(/예측값/)
  })
})
