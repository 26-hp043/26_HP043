// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { VoyageCiiForm } from './VoyageCiiForm'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import type { ManagedVoyage } from '../voyage-management/types'

/**
 * 기능① 입력 폼의 **배선** 검증 (#557).
 *
 * ## 이 파일이 보는 층
 *
 * 규칙(`formRules.ts`)과 데이터 경계(`yearCatalog`·`fuelCatalog`)는 각각 순수 함수·
 * provider 테스트가 이미 잠근다. **여기서 보는 것은 그 사이의 배선**이다 — 효과가
 * 실제로 도는가, 받은 목록이 셀렉트에 들어가는가, 효과가 한 번만 도는가.
 *
 * 그 층은 종전에 **아무 테스트도 없었다.** 화면 PR이 「브라우저에서 확인하지
 * 못했습니다」를 여섯 번 연속 한계로 적은 자리가 정확히 여기다.
 *
 * ## 서버는 `fetch` 스텁으로 흉내 낸다
 *
 * 경로별로 응답을 나눈다. 실제 서버 형태는 각 provider 테스트가 잠그므로 여기서는
 * **화면이 그 값을 어떻게 쓰는지**만 본다.
 */

interface Call {
  url: string
}

function stubServer() {
  const calls: Call[] = []
  const fetchImpl = vi.fn(async (input: unknown) => {
    const url = String(input)
    calls.push({ url })
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: [{ year: 2026 }, { year: 2027 }, { year: 2030 }] })
    }
    if (url.includes('/parameters/fuel-types')) {
      return jsonResponse({
        data: [
          { code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true },
          { code: 'LNG', display_name: '액화천연가스', cf: '2.750', unit: 't', is_active: true },
        ],
      })
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return { calls, fetchImpl }
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

/** 셸이 내려주는 컨텍스트를 흉내 낸 라우트. 화면은 `useOutletContext`로 읽는다. */
function renderForm(context: Partial<ShellContext> = {}) {
  const value: ShellContext = {
    ...EMPTY_SHELL_CONTEXT,
    vesselId: '00000000-0000-4000-8000-000000000001',
    vessels: [
      { id: '00000000-0000-4000-8000-000000000001', displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
    ],
    vesselsState: 'ready',
    selectVesselId: () => {},
    ...context,
  }
  return render(
    <MemoryRouter initialEntries={['/voyage-cii']}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/voyage-cii" element={<VoyageCiiForm />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('연도 셀렉트 — 서버 목록이 화면에 들어간다', () => {
  it('규제연도 옵션이 서버가 준 값으로 채워진다', async () => {
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/규제연도/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    // 최신 연도부터 · 계획을 짜는 화면이라 미래 연도를 남긴다 (#1584)
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '2030',
      '2027',
      '2026',
    ])
  })
})

describe('연료 셀렉트 — 서버 목록이 화면에 들어간다 (#542 · #568)', () => {
  it('연료 옵션이 서버가 준 값으로 채워진다', async () => {
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/연료 종류/)
    // 첫 옵션은 「선택해 주세요」다.
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    // **서버가 주는 것은 코드 집합이고, 이름은 화면이 붙인다** (`#598`).
    // 종전에는 `display_name`을 그대로 그려 `Heavy Fuel Oil (HFO)`가 나왔다.
    expect(select.textContent).toContain('중유 (HFO)')
    expect(select.textContent).toContain('액화천연가스 (LNG)')
    // 서버 목록에 없는 연료는 나오지 않는다 — 이름을 화면이 갖는다고 8종이
    // 전부 나오면 고정표로 돌아간 것이다.
    expect(select.textContent).not.toContain('메탄올')
  })

  it('종전 고정표 8종이 아니라 서버가 준 2종만 나온다', async () => {
    // 고정표(`referenceTable.ts`)를 읽던 시절에는 서버 목록과 무관하게 늘 8종이었다.
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/연료 종류/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    expect(select.textContent).not.toContain('메탄올')
    // 서버가 준 `display_name`(여기서는 「고유황유」)은 화면에 그대로 나가지 않는다 —
    // `MEPC.364(79)` 원문 표기가 실리는 자리라 표시 문구와 별개다 (`AGENTS §4.6`).
    expect(select.textContent).not.toContain('고유황유')
  })
})

describe('효과가 한 번만 돈다 — 무한 루프 회귀 (#484 · #557)', () => {
  /*
   * `#484`가 무한 렌더 루프를 **설계로** 막았다(값의 정체성 고정 + 참조로 최신값 읽기).
   * 그 설계가 실제로 한 번만 도는지는 확인된 적이 없다 — 이슈 본문이 그 사실을 적었다.
   *
   * 루프가 생기면 같은 GET이 끝없이 나가므로 **호출 횟수**가 그 신호다.
   */
  it('연도·연료 조회가 각각 한 번씩만 나간다', async () => {
    const { calls } = stubServer()

    renderForm()

    await screen.findByLabelText(/규제연도/)
    await screen.findByLabelText(/연료 종류/)
    // 효과가 다시 돌 시간을 준다. 루프가 있으면 이 사이에 호출이 쌓인다.
    await new Promise((resolve) => setTimeout(resolve, 120))

    const years = calls.filter((c) => c.url.includes('regulation-years'))
    const fuels = calls.filter((c) => c.url.includes('fuel-types'))
    expect(years).toHaveLength(1)
    expect(fuels).toHaveLength(1)
  })
})

describe('선박이 없으면 조회하지 않는다', () => {
  it('셸이 선박을 안 주면 연도 조회가 나가지 않는다', async () => {
    const { calls } = stubServer()

    renderForm({ vesselId: null, vessels: [], vesselsState: 'ready' })
    await new Promise((resolve) => setTimeout(resolve, 120))

    expect(calls.filter((c) => c.url.includes('regulation-years'))).toHaveLength(0)
  })
})

/**
 * 선박이 없어도 연도 로딩이 끝난다 (#824 ⑴).
 *
 * 종전 자체 구현은 `if (!state.vesselId) return`으로 조기 반환하면서 `yearsLoading`을
 * **`true`로 남겨 뒀다.** 이 화면은 목록의 첫 배를 자동 선택하므로 평시에는 드러나지
 * 않지만, **선박이 0척이거나 `GET /vessels`가 실패하면** 같은 상태가 된다.
 *
 * ⚠️ 그때 「선박」 칸은 **정확히** 안내하는데 바로 아래 「규제연도」만 영원히 로딩이라
 * **한 화면에서 두 칸이 다른 사실을 말한다.**
 */
describe('선박이 없을 때도 연도 칸이 로딩에서 벗어난다 (#824 ⑴)', () => {
  it('등록된 선박이 0척이면 「불러오는 중」이 사라진다', async () => {
    stubServer()

    renderForm({ vesselId: null, vessels: [], vesselsState: 'ready' })

    await waitFor(() =>
      expect(screen.queryByText(/규제연도 목록을 불러오는 중/)).toBeNull(),
    )
  })

  it('선박 목록 조회가 실패해도 연도 칸이 멈추지 않는다', async () => {
    stubServer()

    renderForm({ vesselId: null, vessels: [], vesselsState: 'failed' })

    await waitFor(() =>
      expect(screen.queryByText(/규제연도 목록을 불러오는 중/)).toBeNull(),
    )
  })

  it('선박이 정해지면 종전대로 목록을 채운다 — 이관이 동작을 바꾸지 않았다', async () => {
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/규제연도/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
  })
})

describe('상단바 선박이 목록에 없을 때 (#1097 ⑵)', () => {
  it('첫 배로 바꾸고 안내한다 — 삭제된 배의 id로 계산하지 않는다', async () => {
    const selectVesselId = vi.fn()
    renderForm({
      vesselId: '00000000-0000-4000-8000-00000000dead',
      vessels: [
        { id: '00000000-0000-4000-8000-000000000001', displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
        { id: '00000000-0000-4000-8000-000000000002', displayName: 'DONGJIN', shipType: 'CONTAINER_SHIP' },
      ],
      vesselsState: 'ready',
      selectVesselId,
    })
    expect(await screen.findByText(/상단바에서 고른 선박이 목록에 없어/)).toBeTruthy()
    expect(selectVesselId).toHaveBeenCalledWith('00000000-0000-4000-8000-000000000001')
  })
})


/**
 * 「선박을 아직 안 골랐다」와 「그 선박에 연도가 없다」를 가른다 (`#1093` ⑶).
 *
 * `useYearOptions`는 선박이 비면 **조회하지 않고** 빈 목록을 돌려준다. 그래서 연도 칸이
 * 마지막 갈래로 떨어져 「등록된 규제연도가 없습니다」를 말했는데 **사실이 아니다** —
 * 연도는 등재돼 있고 선박을 고르지 않았을 뿐이다. 항로 비교 화면이 `#829`에서 이미
 * 같은 구분을 하고 있다.
 */
describe('연도 칸이 「선박 미선택」을 「연도 없음」으로 말하지 않는다 (#1093 ⑶)', () => {
  it('선박을 고르기 전에는 「등록된 규제연도가 없습니다」가 아니다', async () => {
    stubServer()

    renderForm({ vesselId: null })

    expect(await screen.findByText('선박을 먼저 선택해 주세요')).toBeTruthy()
    expect(screen.queryByText('등록된 규제연도가 없습니다')).toBeNull()
  })

  it('선박을 골랐는데 연도가 정말 없으면 그렇다고 말한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [] })
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [
              { code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true },
            ],
          })
        }
        return jsonResponse({ data: {} })
      }),
    )

    renderForm()

    expect(await screen.findByText('등록된 규제연도가 없습니다')).toBeTruthy()
    expect(screen.queryByText('선박을 먼저 선택해 주세요')).toBeNull()
  })

  /**
   * 속력 안내가 줄어도 **세 사실은 남는다** (`#1421`).
   *
   * 「속력을 바꿔도 CII는 같다」만 남기고 줄이면 **틀린 안내가 된다**(`#1263`).
   * `actionRules.ts`의 「계획 저장」이 이 값을 계획 속력으로 옮기고 **도착 예정 시각까지
   * 이 값으로 정하기** 때문이다 — 임의값을 넣어도 된다고 읽히면 그 값이 연간
   * 시뮬레이션까지 흘러간다.
   *
   * 문구가 아니라 **사실**을 본다(`AGENTS §4.6`). 안내가 입력칸의 설명으로 **닿는지**도
   * 같이 본다 — 화면에만 있고 낭독이 못 듣는 안내는 없는 것과 같다.
   */
  it('평균 속력 안내는 CII·계획 속력·도착 예정 시각 셋을 모두 말하고 입력칸 설명으로 닿는다 (#1421)', async () => {
    stubServer()

    renderForm()

    const speed = await screen.findByLabelText(/평균 속력/)
    const described = (speed.getAttribute('aria-describedby') ?? '')
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ')

    expect(described).toMatch(/CII/)
    expect(described).toMatch(/계획 속력/)
    expect(described).toMatch(/도착 예정/)
  })

  it('선박 미선택으로 제출하면 선박 오류가 사라지지 않는다', async () => {
    stubServer()

    renderForm({ vesselId: null })

    fireEvent.click(await screen.findByRole('button', { name: /계산/ }))

    /*
     * ⚠️ 종전에는 두 오류가 **같은 키(`__form__`)**를 써서 뒤에 쓴 연도 오류가
     * 선박 오류를 덮었다. 화면에는 「규제연도를 선택해 주세요」만 남는데 **고를 연도
     * 칸이 화면에 없어** 사용자가 할 수 있는 일이 없었다.
     */
    expect(await screen.findByText('선박을 선택해 주세요.')).toBeTruthy()
    expect(screen.queryByText('규제연도를 선택해 주세요.')).toBeNull()
  })
})

/**
 * 상단 항차 · 선박 기본 연료로 칸을 채운다 (#1576).
 *
 * 규칙(`prefillFromVoyage`)은 `formRules.test.ts`가 상태별로 본다. 여기서는 **폼이 셸의
 * 항차를 따라 그 규칙을 부르고, 항차마다 한 번만 채우고, 늦은 응답을 버리는가**를 본다.
 */
describe('상단 항차와 기본 연료로 채우기 (#1576)', () => {
  const VESSEL = '00000000-0000-4000-8000-000000000001'
  const planned = (over: Partial<ManagedVoyage> = {}): ManagedVoyage => ({
    id: 'voy-1',
    voyageNo: '2026-03',
    status: 'PLANNED',
    inclusionPolicy: 'INCLUDE_AS_PLAN',
    regulationYear: 2026,
    departurePortName: 'Busan',
    arrivalPortName: 'Singapore',
    plannedDistanceNm: 2300,
    plannedDistanceSource: null,
    plannedSpeedKn: 14,
    actualDistanceNm: null,
    actualAvgSpeedKn: null,
    plannedDepartureAt: null,
    plannedArrivalAt: null,
    actualDepartureAt: null,
    actualArrivalAt: null,
    fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331, actualFuelTon: null }],
    ...over,
  })

  function renderWith(
    context: Partial<ShellContext>,
    loadVoyage: (id: string) => Promise<ManagedVoyage>,
  ) {
    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId: VESSEL,
      vessels: [
        {
          id: VESSEL,
          displayName: '샘플 벌크선',
          shipType: 'BULK_CARRIER',
          spec: { referenceSpeedKn: '12', referenceDailyFocTon: '23.04', defaultFuelType: 'LNG' },
        },
      ],
      vesselsState: 'ready',
      selectVesselId: () => {},
      ...context,
    }
    const element = <VoyageCiiForm loadVoyage={loadVoyage} />
    const tree = (ctx: ShellContext) => (
      <MemoryRouter initialEntries={['/voyage-cii']}>
        <Routes>
          <Route element={<Outlet context={ctx} />}>
            <Route path="/voyage-cii" element={element} />
          </Route>
        </Routes>
      </MemoryRouter>
    )
    const result = render(tree(value))
    return {
      rerenderWith: (over: Partial<ShellContext>) => result.rerender(tree({ ...value, ...over })),
    }
  }

  const input = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement

  it('계획 항차를 고르고 들어오면 거리 · 속력 · 연료 · 연료량이 채워진다', async () => {
    stubServer()
    renderWith({ voyageId: 'voy-1' }, vi.fn(async () => planned()))
    await waitFor(() => expect(input(/항해거리/).value).toBe('2300'))
    expect(input(/평균 속력/).value).toBe('14')
    expect(input(/연료 사용량/).value).toBe('331')
    await waitFor(() => expect((screen.getByLabelText(/연료 종류/) as HTMLSelectElement).value).toBe('HFO'))
  })

  it('연료가 여러 종이면 연료 칸은 비우고 그 까닭을 말한다 — 기본 연료로도 채우지 않는다', async () => {
    stubServer()
    renderWith(
      { voyageId: 'voy-1' },
      vi.fn(async () =>
        planned({
          fuelUses: [
            { fuelType: 'HFO', plannedFuelTon: 300, actualFuelTon: null },
            { fuelType: 'MDO', plannedFuelTon: 31, actualFuelTon: null },
          ],
        }),
      ),
    )
    expect(await screen.findByText(/연료가 2종이라 여기서는 한 종만/)).toBeTruthy()
    expect(input(/항해거리/).value).toBe('2300')
    expect(input(/연료 사용량/).value).toBe('')
    expect((screen.getByLabelText(/연료 종류/) as HTMLSelectElement).value).toBe('')
  })

  it('항해 중 항차는 채우지 않고 그렇다고 말한다', async () => {
    stubServer()
    renderWith({ voyageId: 'voy-1' }, vi.fn(async () => planned({ status: 'IN_PROGRESS' })))
    expect(await screen.findByText(/「항해 중」 상태라 계획값으로 채우지 않았습니다/)).toBeTruthy()
    expect(input(/항해거리/).value).toBe('')
  })

  it('항차가 없으면 선박 기본 연료로 연료 종류만 채운다', async () => {
    stubServer()
    const load = vi.fn(async () => planned())
    renderWith({ voyageId: null }, load)
    await waitFor(() => expect((screen.getByLabelText(/연료 종류/) as HTMLSelectElement).value).toBe('LNG'))
    expect(input(/항해거리/).value).toBe('')
    expect(load).not.toHaveBeenCalled()
  })

  it('같은 항차에서 고친 칸은 다시 덮지 않고, 항차를 바꾸면 새 값이 들어온다', async () => {
    stubServer()
    const load = vi.fn(async (id: string) =>
      id === 'voy-1' ? planned() : planned({ id: 'voy-2', plannedDistanceNm: 4100 }),
    )
    const { rerenderWith } = renderWith({ voyageId: 'voy-1' }, load)
    await waitFor(() => expect(input(/항해거리/).value).toBe('2300'))
    fireEvent.change(input(/항해거리/), { target: { value: '2500' } })

    rerenderWith({ voyageId: 'voy-1' })
    await Promise.resolve()
    expect(input(/항해거리/).value).toBe('2500')
    expect(load).toHaveBeenCalledTimes(1)

    rerenderWith({ voyageId: 'voy-2' })
    await waitFor(() => expect(input(/항해거리/).value).toBe('4100'))
  })

  it('늦게 온 앞 항차의 응답은 버린다', async () => {
    stubServer()
    let releaseFirst: (v: ManagedVoyage) => void = () => {}
    const load = vi.fn((id: string) =>
      id === 'voy-1'
        ? new Promise<ManagedVoyage>((resolve) => {
            releaseFirst = resolve
          })
        : Promise.resolve(planned({ id: 'voy-2', plannedDistanceNm: 4100 })),
    )
    const { rerenderWith } = renderWith({ voyageId: 'voy-1' }, load)
    rerenderWith({ voyageId: 'voy-2' })
    await waitFor(() => expect(input(/항해거리/).value).toBe('4100'))
    await act(async () => {
      releaseFirst(planned())
    })
    expect(input(/항해거리/).value).toBe('4100')
  })

  it('제원이 늦게 와도 항차가 비운 연료 칸을 기본 연료로 덮지 않는다 — 항차가 우선이다', async () => {
    stubServer()
    const multi = planned({
      fuelUses: [
        { fuelType: 'HFO', plannedFuelTon: 300, actualFuelTon: null },
        { fuelType: 'MDO', plannedFuelTon: 31, actualFuelTon: null },
      ],
    })
    const noSpec = [{ id: VESSEL, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' }]
    const { rerenderWith } = renderWith({ voyageId: 'voy-1', vessels: noSpec }, vi.fn(async () => multi))
    await screen.findByText(/연료가 2종이라/)
    rerenderWith({
      voyageId: 'voy-1',
      vessels: [
        {
          id: VESSEL,
          displayName: '샘플 벌크선',
          shipType: 'BULK_CARRIER',
          spec: { referenceSpeedKn: '12', referenceDailyFocTon: '23.04', defaultFuelType: 'LNG' },
        },
      ],
    })
    await act(async () => {})
    expect((screen.getByLabelText(/연료 종류/) as HTMLSelectElement).value).toBe('')
  })

  it('항차를 못 불러오면 칸은 비운 채 한 줄로 말한다', async () => {
    stubServer()
    renderWith(
      { voyageId: 'voy-1' },
      vi.fn(async () => {
        throw new Error('x')
      }),
    )
    expect(await screen.findByText(/상단의 항차를 불러오지 못해/)).toBeTruthy()
    expect(input(/항해거리/).value).toBe('')
  })
})

/**
 * 연료 입력 방식 전환 (#1718).
 *
 * 셈과 검증은 `formRules.test.ts`가 잠근다. 여기서는 **화면이 그 셈을 쓰는가** —
 * 고른 방식의 칸이 서고, 환산값이 보이고, 그 값이 그대로 요청에 실리는가를 본다.
 */
describe('연료 입력 방식 (#1718)', () => {
  const VESSEL_ID = '00000000-0000-4000-8000-000000000001'

  function renderWithSpec(referenceDailyFocTon: string | null) {
    return renderForm({
      vessels: [
        {
          id: VESSEL_ID,
          displayName: '샘플 벌크선',
          shipType: 'BULK_CARRIER',
          spec: { referenceSpeedKn: '12', referenceDailyFocTon, defaultFuelType: 'HFO' },
        },
      ],
    })
  }

  async function ready() {
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})
    fireEvent.change(screen.getByLabelText(/항해거리/), { target: { value: '1000' } })
    fireEvent.change(screen.getByLabelText(/평균 속력/), { target: { value: '12' } })
  }

  function submittedBody(fetchImpl: ReturnType<typeof stubServer>['fetchImpl']) {
    /*
     * `stubServer`의 스텁은 첫 인자만 선언해 두었다 — 본문을 보는 검사는 여기뿐이라
     * 스텁의 서명을 넓히는 대신 이 자리에서 호출 기록을 읽는다.
     */
    const calls = fetchImpl.mock.calls as unknown as Array<[unknown, RequestInit | undefined]>
    const call = calls.find(([url]) => String(url).includes('/calculations/voyage-cii'))
    return JSON.parse(String(call?.[1]?.body))
  }

  it('하루 × 항해일을 고르면 하루 칸이 서고 환산 총량이 보인다', async () => {
    stubServer()
    renderWithSpec('23.04')
    await ready()

    fireEvent.click(screen.getByLabelText('하루 × 항해일'))
    // 총량 칸은 사라지고 하루 칸이 선다 (라벨이 서로 겹치므로 id로 본다)
    expect(document.querySelector('#fuel-ton')).toBeNull()
    fireEvent.change(screen.getByLabelText(/하루 연료 사용량/), { target: { value: '23.04' } })

    // 1000nm ÷ 12kn = 83.3h → 80.0t (`§4.2` — 시간 1자리 · 연료 1자리)
    expect(screen.getByText(/항해시간 83\.3 h/)).toBeTruthy()
    expect(screen.getByText(/80\.0 t/)).toBeTruthy()
  })

  it('화면이 보인 환산값이 그대로 요청에 실린다 — 계약은 `fuel_ton` 하나다', async () => {
    const { fetchImpl } = stubServer()
    renderWithSpec('23.04')
    await ready()

    fireEvent.click(screen.getByLabelText('하루 × 항해일'))
    fireEvent.change(screen.getByLabelText(/하루 연료 사용량/), { target: { value: '23.04' } })
    fireEvent.click(screen.getByRole('button', { name: '계산하기' }))

    await waitFor(() => expect(submittedBody(fetchImpl)).toBeTruthy())
    const body = submittedBody(fetchImpl) as { fuel_uses: Array<Record<string, unknown>> }
    expect(body.fuel_uses).toHaveLength(1)
    expect(body.fuel_uses[0].fuel_ton as number).toBeCloseTo(80, 3)
  })

  it('선박 제원에서 — 입력칸 대신 제원 값을 보이고 같은 값을 보낸다', async () => {
    const { fetchImpl } = stubServer()
    renderWithSpec('23.04')
    await ready()

    fireEvent.click(screen.getByLabelText('선박 제원에서'))
    expect(screen.getByText(/23\.0 t\/일 · 선박 제원/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '계산하기' }))

    await waitFor(() => expect(submittedBody(fetchImpl)).toBeTruthy())
    const body = submittedBody(fetchImpl) as { fuel_uses: Array<Record<string, unknown>> }
    expect(body.fuel_uses[0].fuel_ton as number).toBeCloseTo(80, 3)
  })

  it('⚠️ 제원이 없는 선박이면 사유를 값 자리에 적고, 누르면 오류로 막는다', async () => {
    const { fetchImpl } = stubServer()
    renderWithSpec(null)
    await ready()

    fireEvent.click(screen.getByLabelText('선박 제원에서'))
    expect(screen.getByText(/기준 일일 연료소모량이 없습니다/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '계산하기' }))

    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/calculations/voyage-cii'))).toBe(
      false,
    )
  })

  it('방식을 바꿨다 돌아와도 처음 총량이 그대로다', async () => {
    stubServer()
    renderWithSpec('23.04')
    await ready()

    fireEvent.change(document.querySelector('#fuel-ton') as HTMLInputElement, {
      target: { value: '80' },
    })
    fireEvent.click(screen.getByLabelText('하루 × 항해일'))
    fireEvent.click(screen.getByLabelText('총량'))

    expect((document.querySelector('#fuel-ton') as HTMLInputElement).value).toBe('80')
  })
})
