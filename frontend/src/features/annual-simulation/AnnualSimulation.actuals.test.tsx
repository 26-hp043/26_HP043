// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { AnnualSimulation } from './AnnualSimulation'
import { ANNUAL_COPY } from './copy'
import * as session from '../../auth/session'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import type { CiiYear, VesselDetail, VesselDetailProvider } from '../vessel-detail/types'
import { CiiHistoryChart } from '../vessel-detail/CiiHistoryChart'
import { VesselDetailError } from '../vessel-detail/apiProvider'
import { YTD_NOTICE_TEST_ID } from '../vessel-detail/YtdNotice'

/**
 * 연도별 실적 블록 (#2017 · `API_SPEC §2.7`).
 *
 * 디자인 담당의 정정(2026-09-29)대로 **나란히 두는 것은 시뮬레이션 결과가 아니라 확정
 * 실적**이다. 여기서 잠그는 것은 다섯 — ⑴ 두 블록이 있고 실적이 위다 ⑵ 지나간 해에 확률이
 * 없다 ⑶ `data_available=false`인 해는 사유가 보인다 ⑷ 이력 실패는 블록 안에서만 알리고 다시
 * 시도할 수 있으며 시뮬레이션은 멀쩡하다 ⑸ 선박을 바꾸면 앞 배의 늦은 응답이 붙지 않는다.
 * 그리고 ⑹ 같은 값이 선박 상세와 같게 읽힌다(`#750` · `#866`) ⑺ 진행 중인 해의 등급은 확정과
 * 다른 표기와 고지를 갖는다(`PRD COR-2` · `§3.3.7` 각주) ⑻ 결과의 해가 표의 확정 행과 같으면
 * 계산 경로가 다르다는 한 줄이 선다.
 *
 * 표시 문구는 성질로 단언한다(`AGENTS §4.6`) — 리터럴 비교는 `ANNUAL_COPY`를 거친다.
 */

const VESSEL_ID = '00000000-0000-4000-8000-000000000001'
const OTHER_ID = '00000000-0000-4000-8000-000000000002'
const AS_OF = '2026-09-21T05:24:00Z'

function year(over: Partial<CiiYear> & Pick<CiiYear, 'regulationYear'>): CiiYear {
  return {
    status: 'CONFIRMED',
    dataAvailable: true,
    reason: null,
    attainedCii: '5.412345',
    requiredCii: '5.100000',
    rating: 'D',
    voyageCount: 10,
    inProgressVoyageCount: 0,
    totalDistanceNm: '60000.0',
    totalFuelTon: '9000.0',
    fuels: [],
    ...over,
  }
}

function detail(years: CiiYear[], name = '샘플 벌크선'): VesselDetail {
  return {
    vessel: {
      id: VESSEL_ID,
      name,
      imoNumber: '9000001',
      shipType: 'BULK_CARRIER',
      deadweight: '50000',
      grossTonnage: null,
      isCiiApplicableHint: true,
      referenceSpeedKn: null,
      referenceDailyFocTon: null,
      defaultFuelType: null,
      underwayState: null,
      detailStatus: null,
      lat: null,
      lon: null,
      positionUpdatedAt: null,
    },
    capacityBasis: 'DWT',
    years,
    asOf: AS_OF,
  }
}

/** 지나간 두 해 + 올해 누적 — `§2.7` 기본 창(최근 3년)의 모양이다. */
function threeYears(): CiiYear[] {
  return [
    year({ regulationYear: 2024, attainedCii: '4.900000', requiredCii: '5.300000', rating: 'C', voyageCount: 12 }),
    year({ regulationYear: 2025, attainedCii: '5.412345', requiredCii: '5.100000', rating: 'D', voyageCount: 10 }),
    year({
      regulationYear: 2026,
      status: 'IN_PROGRESS',
      attainedCii: '5.024800',
      requiredCii: '4.950000',
      rating: 'D',
      voyageCount: 8,
      inProgressVoyageCount: 1,
    }),
  ]
}

function simulationBody() {
  return {
    data: {
      simulation_id: 'sim-1',
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
    calculation_run_id: 'run-sim-1',
    warnings: [],
    meta: { duration_ms: 10, as_of: AS_OF },
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as Response
}

/** 시뮬레이션 쪽 서버만 스텁한다 — 연도별 실적은 주입한 provider가 준다. */
function stubServer(years: number[] = [2026]) {
  const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
    void init
    const url = String(input)
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: years.map((year) => ({ year })) })
    }
    if (url.endsWith('/annual-simulations')) return jsonResponse(simulationBody())
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

function historyStub(load: VesselDetailProvider['load']): Pick<VesselDetailProvider, 'load'> {
  return { load }
}

function shellFor(vesselId: string | null): ShellContext {
  return {
    ...EMPTY_SHELL_CONTEXT,
    vesselId,
    vessels: [
      { id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
      { id: OTHER_ID, displayName: '다른 배', shipType: 'BULK_CARRIER' },
    ],
    vesselsState: 'ready',
    selectVesselId: () => {},
  }
}

function tree(vesselId: string | null, history: Pick<VesselDetailProvider, 'load'>) {
  return (
    <MemoryRouter initialEntries={['/annual']}>
      <Routes>
        <Route element={<Outlet context={shellFor(vesselId)} />}>
          <Route path="/annual" element={<AnnualSimulation historyProvider={history} />} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

function actualsBlock(): HTMLElement {
  return screen.getByTestId('annual-sim-actuals')
}

async function runOnce(year = '2026'): Promise<void> {
  await screen.findByRole('option', { name: year })
  await act(async () => {})
  if (year !== '2026') {
    fireEvent.change(screen.getByLabelText(/기준연도/), { target: { value: year } })
  }
  fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))
  await screen.findByRole('button', { name: ANNUAL_COPY.reproduceButton })
}

beforeEach(() => {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role: 'OFFICE',
  } as ReturnType<typeof session.useAuthUser>)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('⑴ 두 블록 — 연도별 실적이 위, 올해 시뮬레이션 결과가 아래', () => {
  it('실적 블록이 결과보다 먼저 오고, 지나간 해와 올해 누적이 표에 있다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    await runOnce()

    const block = actualsBlock()
    const verdict = screen.getByRole('region', { name: ANNUAL_COPY.verdictLabel })
    // DOM 순서 — 실적이 결론 띠 **앞**이다.
    expect(block.compareDocumentPosition(verdict) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    const rows = within(block).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      '2024',
      '2025',
      '2026',
    ])
    // 진행 중인 해는 확정 행과 **다른 구분**으로 적힌다 — 연중 집계를 확정으로 읽히지 않게.
    const kindOf = (row: HTMLElement) => within(row).getAllByRole('cell')[0].textContent
    expect(kindOf(rows[2])).not.toBe(kindOf(rows[1]))
    expect(kindOf(rows[0])).toBe(kindOf(rows[1]))
  })

  it('진행 중인 해의 등급 칸은 확정 행과 다른 표기이고, 표 아래에 선박 상세와 같은 고지가 있다', async () => {
    /*
     * `PRD COR-2` — 연중 화면의 등급은 「현재 누적 기준 예상 등급」. 응답의 `IN_PROGRESS` 행에도
     * `rating`이 오지만 그것은 연중 누적 예측값이라(`§3.3.7` 각주) 확정 등급과 같은 모양이면 안 된다.
     * 문구가 아니라 **성질**을 본다 — 진행 중 행의 등급 칸에 등급 문자 말고 보이는 글자가 더 있고,
     * 확정 행에는 없다.
     */
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')
    const rows = within(block).getAllByRole('row').slice(1)
    const ratingCell = (row: HTMLElement) => within(row).getAllByRole('cell')[3]

    // 확정 행 — 등급 문자뿐이다.
    expect(ratingCell(rows[1]).textContent?.trim()).toBe('D')
    // 진행 중 행 — 같은 등급 문자인데 **보이는 글자가 더 있다**(sr 전용이 아니다).
    const ytd = ratingCell(rows[2])
    expect(ytd.textContent?.trim().startsWith('D')).toBe(true)
    expect(ytd.textContent?.trim().length).toBeGreaterThan(1)
    expect(ytd.querySelector('.sr-only')).toBeNull()

    // 고지 — 선박 상세와 같은 부품이 표 **밖**, 블록 **안**에 있다.
    const notice = within(block).getByTestId(YTD_NOTICE_TEST_ID)
    expect(notice.closest('table')).toBeNull()
    // 진행 중 행이 없으면 고지할 대상이 없다.
  })

  it('전부 확정인 이력에는 진행 중 고지가 없다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears().slice(0, 2)))))
    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')
    expect(within(block).queryByTestId(YTD_NOTICE_TEST_ID)).toBeNull()
  })

  it('표에 제목·단위를 잇는 caption이 있다 — 선박 상세 표와 같은 방식', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    const block = await screen.findByTestId('annual-sim-actuals')
    const table = await within(block).findByRole('table')
    const caption = table.querySelector('caption')
    expect(caption).not.toBeNull()
    expect(caption!.textContent).toContain(ANNUAL_COPY.actualsTitle)
    expect(caption!.textContent).toContain('DWT')
  })

  it('들어올 때 실적은 받지만 시뮬레이션은 실행하지 않는다 (#1701 유지)', async () => {
    const fetchImpl = stubServer()
    const load = vi.fn(async () => detail(threeYears()))
    render(tree(VESSEL_ID, historyStub(load)))

    await within(await screen.findByTestId('annual-sim-actuals')).findByRole('table')
    expect(load).toHaveBeenCalledWith(VESSEL_ID)
    const posted = fetchImpl.mock.calls.filter(
      ([input, init]) => String(input).endsWith('/annual-simulations') && init?.method === 'POST',
    )
    expect(posted).toHaveLength(0)
  })

  it('선박이 없으면 실적 블록을 그리지 않는다 — 「선박을 먼저」는 아래 자리표시자가 이미 말한다', () => {
    stubServer()
    const load = vi.fn(async () => detail(threeYears()))
    render(tree(null, historyStub(load)))

    expect(screen.queryByTestId('annual-sim-actuals')).toBeNull()
    expect(load).not.toHaveBeenCalled()
    expect(screen.getByText(ANNUAL_COPY.needVessel)).toBeTruthy()
  })
})

describe('⑵ 지나간 해에는 확률이 없다 — `PRD §12.4.1`', () => {
  it('실적 블록 어디에도 백분율 · 목표 달성 확률 · 분포 요약이 없고, 결과 블록에는 있다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    await runOnce()

    const block = actualsBlock()
    expect(block.textContent).not.toMatch(/%/)
    expect(within(block).queryByText(new RegExp(ANNUAL_COPY.targetSuccessLabel))).toBeNull()
    expect(within(block).queryByText(ANNUAL_COPY.spreadTitle)).toBeNull()
    // 대조군 — 같은 화면의 결과 블록은 확률을 말한다.
    expect(screen.getByRole('region', { name: ANNUAL_COPY.verdictLabel }).textContent).toMatch(/%/)
  })

  it('실적 블록은 카드가 아니다 — 결과 카드와 같은 면 클래스를 쓰지 않는다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    await runOnce()

    const block = actualsBlock()
    expect(block.classList.contains('annual-sim__block')).toBe(false)
    // 결과 쪽 카드는 그대로 4개 이하(`DESIGN_SYSTEM §5`) — 실적을 더해도 예산이 늘지 않는다.
    expect(
      document.querySelectorAll('.annual-sim__form, .verdict-strip, .annual-sim__block').length,
    ).toBeLessThanOrEqual(4)
  })
})

describe('⑶ 「값 없음」 · 「계산 못 함」 · 「받지 못함」을 가른다', () => {
  it('`data_available=false`인 해는 칸이 비고 사유가 표 아래에 있다 — 사유마다 다른 문장', async () => {
    stubServer()
    const years = [
      year({
        regulationYear: 2024,
        dataAvailable: false,
        reason: 'NO_REGULATION_PARAMS',
        attainedCii: null,
        requiredCii: null,
        rating: null,
        voyageCount: 0,
      }),
      year({
        regulationYear: 2025,
        dataAvailable: false,
        reason: 'NO_DATA',
        attainedCii: null,
        requiredCii: null,
        rating: null,
        voyageCount: 0,
      }),
      year({ regulationYear: 2026, status: 'IN_PROGRESS' }),
    ]
    render(tree(VESSEL_ID, historyStub(async () => detail(years))))

    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')
    const rows = within(block).getAllByRole('row').slice(1)
    // 계산 못 한 해는 값 칸이 전부 빈 표시 — 0이나 빈 문자열로 지어내지 않는다.
    for (const row of rows.slice(0, 2)) {
      const cells = within(row).getAllByRole('cell').map((cell) => cell.textContent)
      expect(cells.slice(1, 4)).toEqual(['—', '—', '—'])
    }
    // 사유는 해마다 한 문장, 그리고 **서로 다르다** — 사용자가 할 일이 다르다.
    const noParams = within(block).getByText(/2024년/)
    const noData = within(block).getByText(/2025년/)
    expect(noParams.closest('table')).toBeNull()
    expect(noData.closest('table')).toBeNull()
    expect(noParams.textContent).not.toBe(noData.textContent?.replace('2025', '2024'))
    // 정상인 해에는 사유 문장이 없다.
    expect(within(block).queryByText(/2026년/)).toBeNull()
  })

  it('연도가 하나도 없으면 「값 없음」을 말한다 — 표도 오류도 아니다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(async () => detail([]))))

    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByText(ANNUAL_COPY.actualsEmpty)
    expect(within(block).queryByRole('table')).toBeNull()
    expect(within(block).queryByRole('alert')).toBeNull()
  })
})

describe('⑷ 이력 실패는 블록 안에서만 — `PRD §16.2` 오류 격리', () => {
  it('실패는 블록 안 알림과 「다시 시도」로 끝나고, 시뮬레이션은 그대로 실행된다', async () => {
    stubServer()
    let calls = 0
    const load = vi.fn(async () => {
      calls += 1
      if (calls === 1) throw new Error('서버에 연결하지 못했습니다.')
      return detail(threeYears())
    })
    render(tree(VESSEL_ID, historyStub(load)))

    const block = await screen.findByTestId('annual-sim-actuals')
    const alert = await within(block).findByRole('alert')
    // 제목은 `ErrorState`가 짓는다(`PRD §6.4`) — 어느 영역이 실패했는지 주어가 있다.
    expect(alert.textContent).toContain(ANNUAL_COPY.actualsErrorSubject)
    expect(alert.textContent).toContain('서버에 연결하지 못했습니다.')
    // 화면 전체 오류가 아니다 — 알림은 블록 안 하나뿐이고, 결과 자리표시자는 그대로다.
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText(ANNUAL_COPY.empty)).toBeTruthy()

    // 실적이 실패해도 시뮬레이션은 돈다.
    await runOnce()
    expect(screen.getByRole('region', { name: ANNUAL_COPY.verdictLabel })).toBeTruthy()

    // 다시 시도 — 알림 안의 버튼 하나. 문구가 아니라 **버튼이 있다는 성질**을 본다(`AGENTS §4.6`).
    fireEvent.click(within(alert).getByRole('button'))
    await within(block).findByRole('table')
    expect(load).toHaveBeenCalledTimes(2)
    expect(within(block).queryByRole('alert')).toBeNull()
  })

  it('Error가 아닌 실패에도 블록이 문구 없이 비지 않는다', async () => {
    stubServer()
    render(tree(VESSEL_ID, historyStub(() => Promise.reject('boom'))))

    const block = await screen.findByTestId('annual-sim-actuals')
    const alert = await within(block).findByRole('alert')
    expect(alert.textContent).toContain(ANNUAL_COPY.actualsErrorFallback)
    // 다시 시도할 수 있는 실패다.
    expect(within(alert).getByRole('button')).toBeTruthy()
  })

  it('없는 선박(404)에는 「다시 시도」를 주지 않는다 — 다시 눌러도 같은 실패다', async () => {
    stubServer()
    render(
      tree(
        VESSEL_ID,
        historyStub(() =>
          Promise.reject(new VesselDetailError('선박을 찾을 수 없습니다.', { notFound: true })),
        ),
      ),
    )

    const block = await screen.findByTestId('annual-sim-actuals')
    const alert = await within(block).findByRole('alert')
    expect(within(alert).queryByRole('button')).toBeNull()
  })
})

describe('⑸ 선박을 바꾸면 앞 배의 늦은 응답이 붙지 않는다', () => {
  it('앞 배의 응답을 쥐고 있다가 전환 뒤에 풀어도 새 배의 표가 남는다', async () => {
    stubServer()
    let releaseFirst: ((value: VesselDetail) => void) | null = null
    const first = new Promise<VesselDetail>((resolve) => {
      releaseFirst = resolve
    })
    const load = vi.fn((vesselId: string) =>
      vesselId === VESSEL_ID
        ? first
        : Promise.resolve(
            detail([year({ regulationYear: 2025, attainedCii: '3.000000', rating: 'A' })], '다른 배'),
          ),
    )
    const history = historyStub(load)
    const { rerender } = render(tree(VESSEL_ID, history))
    await screen.findByTestId('annual-sim-actuals')
    expect(within(actualsBlock()).queryByRole('table')).toBeNull()

    rerender(tree(OTHER_ID, history))
    await within(actualsBlock()).findByRole('table')
    expect(within(actualsBlock()).getByText('3.000')).toBeTruthy()

    // 이제 앞 배의 응답이 돌아온다 — 새 배 화면에 붙으면 안 된다.
    await act(async () => {
      releaseFirst!(detail(threeYears()))
      await first
    })
    expect(within(actualsBlock()).getByText('3.000')).toBeTruthy()
    expect(within(actualsBlock()).queryByText('4.900')).toBeNull()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('선박을 바꾸는 동안 앞 배의 표를 새 배 이름 아래 남기지 않는다', async () => {
    stubServer()
    let releaseSecond: ((value: VesselDetail) => void) | null = null
    const second = new Promise<VesselDetail>((resolve) => {
      releaseSecond = resolve
    })
    const load = vi.fn((vesselId: string) =>
      vesselId === VESSEL_ID ? Promise.resolve(detail(threeYears())) : second,
    )
    const history = historyStub(load)
    const { rerender } = render(tree(VESSEL_ID, history))
    await within(await screen.findByTestId('annual-sim-actuals')).findByRole('table')

    rerender(tree(OTHER_ID, history))
    // 새 배는 아직 받는 중 — 앞 배의 표가 보이면 안 된다.
    await waitFor(() => expect(within(actualsBlock()).queryByRole('table')).toBeNull())
    expect(within(actualsBlock()).getByRole('status')).toBeTruthy()

    await act(async () => {
      releaseSecond!(detail([year({ regulationYear: 2025, attainedCii: '3.000000' })]))
      await second
    })
    expect(within(actualsBlock()).getByText('3.000')).toBeTruthy()
  })
})

describe('⑹ 선박 상세와 같게 읽힌다 — `#750` · `#866`', () => {
  it('같은 연도의 실적 · 기준 · 등급 · 완료 항차가 선박 상세 표와 같은 문자열이다', async () => {
    stubServer()
    const years = threeYears()
    render(tree(VESSEL_ID, historyStub(async () => detail(years))))
    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')

    const ours = within(block)
      .getAllByRole('row')
      .slice(1)
      .map((row) => {
        const cells = within(row).getAllByRole('cell').map((cell) => cell.textContent?.trim())
        // 구분 칸(0)은 이 화면의 표시 문구다 — 값 칸(실적 · 기준 · 등급 · 완료 항차)만 견준다.
        return [within(row).getByRole('rowheader').textContent, ...cells.slice(1)]
      })

    const { container } = render(<CiiHistoryChart years={years} basis="DWT" />)
    const theirs = [...container.querySelectorAll('table')][0]
    const rows = [...theirs.querySelectorAll('tbody tr')].map((row) => {
      const cells = [...row.querySelectorAll('td')].map((cell) => cell.textContent?.trim())
      // 선박 상세 표는 [상태, 실적, 기준, 등급, 완료 항차] — 상태 칸을 뺀다.
      return [row.querySelector('th')!.textContent, ...cells.slice(1)]
    })

    // 확정 행은 네 칸이 문자열까지 같다.
    expect(ours.slice(0, 2)).toEqual(rows.slice(0, 2))
    // 진행 중 행은 등급 칸에 예상 표기가 붙으므로(`COR-2`) 등급 문자로 **시작**하는지만 보고,
    // 나머지 세 칸(실적 · 기준 · 완료 항차)은 같다.
    const [year3, attained, required, rating, count] = ours[2]
    const [, tAttained, tRequired, tRating, tCount] = rows[2]
    expect([year3, attained, required, count]).toEqual([rows[2][0], tAttained, tRequired, tCount])
    expect(rating?.startsWith(tRating!)).toBe(true)
  })
})

describe('⑻ 결과의 해가 표의 확정 행과 같으면 계산 경로가 다르다는 한 줄', () => {
  it('2025년으로 실행하면 표 아래에 2025년을 가리키는 안내가 서고, 2026년(진행 중)에는 없다', async () => {
    stubServer([2025, 2026])
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')
    expect(within(block).queryByTestId('annual-sim-actuals-same-year')).toBeNull()

    await runOnce('2025')
    const note = within(block).getByTestId('annual-sim-actuals-same-year')
    expect(note.textContent).toContain('2025')
    expect(note.closest('table')).toBeNull()
    // 결과 쪽에도 같은 해가 있다 — 두 값이 같은 화면에 있는 상태가 이 안내의 전제다.
    expect(screen.getByText(new RegExp(ANNUAL_COPY.resultConditionsLabel)).parentElement!.textContent).toContain('2025')
  })

  it('진행 중인 해(2026)로 실행하면 안내가 없다 — 그 해는 표에 확정 행이 아니다', async () => {
    stubServer([2025, 2026])
    render(tree(VESSEL_ID, historyStub(async () => detail(threeYears()))))
    const block = await screen.findByTestId('annual-sim-actuals')
    await within(block).findByRole('table')
    await runOnce('2026')
    expect(within(block).queryByTestId('annual-sim-actuals-same-year')).toBeNull()
  })
})
