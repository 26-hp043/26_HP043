// @vitest-environment jsdom
import '../../test/renderSetup'

import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { ScenarioComparison } from './ScenarioComparison'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import * as session from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'

/**
 * 항로 비교 화면의 **선택지 배선** (#632).
 *
 * 이 화면만 규제연도를 자유 입력으로 받았다. 다른 두 화면(`VoyageCiiForm`·
 * `AnnualSimulation`)은 서버 목록으로 셀렉트를 만드는데, 여기서는 텍스트 입력이라
 * **파라미터가 없는 해를 넣을 수 있었고 그때 서버가 `PARAMETER_ERROR`로 거부**했다.
 *
 * `#236`이 「선박·연도·연료」 세 축을 고치며 연도만 유예했고, `#534`가 두 화면을
 * 옮기며 이 화면을 빠뜨린 것이다.
 *
 * 구성은 `VoyageCiiForm.test.tsx`와 같다 — 규칙과 데이터 경계는 각각 순수 함수·
 * provider 테스트가 잠그고, **여기서는 그 사이의 배선**만 본다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function stubServer(years: number[] = [2026, 2027, 2030]) {
  // `init`을 받는 이유는 **보낸 본문을 검사하기 위해서**다 (#892). 두 번째 인자를
  // 선언하지 않으면 `mock.calls[n][1]`의 타입이 없어 본문에 닿을 수 없다.
  const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
    void init
    const url = String(input)
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: years.map((year) => ({ year })) })
    }
    if (url.includes('/parameters/fuel-types')) {
      return jsonResponse({
        data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
      })
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

/** 기존 검사는 전부 **사무직** 전제다 — 시나리오 채택(#1325)이 사무직 전용이 됐다. */
function stubRole(role: session.UserRole) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role,
    emailVerifiedAt: null,
  })
}

function renderScreen(context: Partial<ShellContext> = {}) {
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
  stubRole('OFFICE')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/**
 * 입력칸 기본값은 고른 배의 제원이다 (#1538).
 *
 * 종전에는 `initialFormState()`의 고정 데모 값(12.8 kn · 26.88 t/일)이라 어느 배를 골라도
 * 같았고, 그대로 비교하면 **다른 배의 숫자로** 계산한 결과가 그 배 이름으로 나왔다.
 */
describe('입력칸 기본값 — 고른 배의 제원 (#1538)', () => {
  const BULK = {
    id: '00000000-0000-4000-8000-000000000001',
    displayName: '샘플 벌크선 (50,000 DWT)',
    shipType: 'BULK_CARRIER',
    spec: { referenceSpeedKn: '12', referenceDailyFocTon: '23.04', defaultFuelType: null },
  }
  const CARGO = {
    id: '00000000-0000-4000-8000-000000000003',
    displayName: 'DONGJIN ENDURANCE',
    shipType: 'GENERAL_CARGO',
    spec: { referenceSpeedKn: '12.8', referenceDailyFocTon: null, defaultFuelType: null },
  }

  function tree(value: ShellContext) {
    return (
      <MemoryRouter initialEntries={['/scenarios']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/scenarios" element={<ScenarioComparison />} />
          </Route>
        </Routes>
      </MemoryRouter>
    )
  }
  function shell(vesselId: string, vessels = [BULK, CARGO]): ShellContext {
    return {
      ...EMPTY_SHELL_CONTEXT,
      vesselId,
      vessels,
      vesselsState: 'ready',
      selectVesselId: () => {},
    }
  }
  const speed = () => screen.getByLabelText(/현재 속력/) as HTMLInputElement
  const dailyFoc = () => screen.getByLabelText(/기준 일일 연료소모량/) as HTMLInputElement

  it('고른 배의 기준속도·일일 연료로 채운다 — 고정 데모 값이 아니다', async () => {
    stubServer()
    render(tree(shell(BULK.id)))

    await waitFor(() => expect(speed().value).toBe('12'))
    expect(dailyFoc().value).toBe('23.04')
    expect(screen.getByText('선박 제원 값입니다. 고치면 이 비교에만 씁니다.')).toBeTruthy()
  })

  it('제원에 일일 연료가 없으면 칸을 비우고 그 사실을 말한다', async () => {
    stubServer()
    render(tree(shell(CARGO.id)))

    await waitFor(() => expect(speed().value).toBe('12.8'))
    expect(dailyFoc().value).toBe('')
    expect(
      screen.getByText('선박 제원에 이 값이 없습니다 — 직접 입력하면 이 비교에 씁니다.'),
    ).toBeTruthy()
  })

  it('⚠️ 배를 바꾸면 새 배의 제원으로 바뀐다 — 앞 배의 값이 남지 않는다', async () => {
    stubServer()
    const { rerender } = render(tree(shell(BULK.id)))
    await waitFor(() => expect(dailyFoc().value).toBe('23.04'))

    rerender(tree(shell(CARGO.id)))

    await waitFor(() => expect(speed().value).toBe('12.8'))
    expect(dailyFoc().value).toBe('')
  })

  it('같은 배에서 고친 칸은 목록이 다시 와도 덮지 않는다', async () => {
    stubServer()
    const { rerender } = render(tree(shell(BULK.id)))
    await waitFor(() => expect(speed().value).toBe('12'))

    fireEvent.change(speed(), { target: { value: '10.5' } })
    // 셸이 목록을 다시 받아 제원 객체가 새로 만들어진 상황
    rerender(tree(shell(BULK.id, [{ ...BULK, spec: { ...BULK.spec } }, CARGO])))

    await act(async () => {})
    expect(speed().value).toBe('10.5')
  })

  it('제원을 모르는 선택지는 건드리지 않는다 — 종전 기본값 그대로', async () => {
    stubServer()
    renderScreen()

    await screen.findByLabelText(/현재 속력/)
    expect(speed().value).toBe('12.8')
    expect(dailyFoc().value).toBe('26.88')
  })
})

describe('규제연도 — 자유 입력이 아니라 서버 목록이다 (#632)', () => {
  it('셀렉트를 그리고 서버가 준 해로 채운다', async () => {
    stubServer()

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    expect(select.tagName).toBe('SELECT')
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    // 최신 연도부터 · 계획을 짜는 화면이라 미래 연도를 남긴다 (#1584)
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '2030',
      '2027',
      '2026',
    ])
  })

  it('텍스트 입력이 남아 있지 않다 — 없는 해를 넣을 수 있던 경로다', async () => {
    stubServer()

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    expect(select).not.toHaveProperty('inputMode', 'numeric')
    expect(select.tagName).not.toBe('INPUT')
  })

  it('목록에 없는 해를 고를 수 없다 — 서버가 아는 것만 옵션이다', async () => {
    stubServer([2026, 2027])

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(2))
    const values = [...select.querySelectorAll('option')].map((o) => (o as HTMLOptionElement).value)
    expect(values).not.toContain('2035')
  })

  it('⚠️ 선박을 안 골랐으면 「없습니다」가 아니라 「선박을 먼저」다 (2026-09-13 실측)', async () => {
    /*
     * `useYearOptions`는 선박이 없으면 **조회하지 않고 빈 목록**을 돌려준다. 종전에는
     * 그때도 「등록된 규제연도가 없습니다」가 떴는데 **사실이 아니다** — 연도는 등재되어
     * 있고 선박을 고르지 않았을 뿐이다.
     *
     * 화면에 처음 들어온 사용자는 그것을 **데이터가 없다**로 읽고 선박을 고를 생각을
     * 못 한다. 브라우저로 5번 돌려 전부 재현했다.
     *
     * 보고서 화면이 이미 `vesselId &&`로 같은 구분을 한다 — 그 형태에 맞췄다.
     */
    stubServer()

    renderScreen({ vesselId: null })

    expect(await screen.findByText(/선박을 먼저 선택해 주세요/)).toBeTruthy()
    expect(screen.queryByText(/등록된 규제연도가 없습니다/)).toBeNull()
  })

  it('목록이 비면 「등록된 규제연도가 없습니다」 — 빈 셀렉트를 그리지 않는다', async () => {
    stubServer([])

    renderScreen()

    expect(await screen.findByText(/등록된 규제연도가 없습니다/)).toBeTruthy()
    expect(screen.queryByLabelText(/규제연도/)).toBeNull()
  })

  it('조회가 실패하면 그 사실을 말한다 — 빈 목록과 구분한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).includes('/parameters/regulation-years')) {
          return jsonResponse({ error: { code: 'INTERNAL_ERROR', message: '…' } }, 500)
        }
        return jsonResponse({ data: [] })
      }),
    )

    renderScreen()

    expect(await screen.findByText(/규제연도 목록을 불러오지 못했습니다/)).toBeTruthy()
  })
})

/*
 * 서버 경고·면책 문구·선박명이 화면에 도달한다 (#821).
 *
 * 종전에는 provider가 `warnings: []`를 넣어 배너 조건(`warnings.length > 0`)이
 * **영구 거짓**이었고, 선박명은 `''`이라 제목이 `` · 2026년 기준 · …``처럼
 * **구분점만 남은** 채 배포됐다. 면책 문구는 서버 정본이 아닌 별도 문자열이었다.
 *
 * ⚠️ **이 파일의 기존 검사는 결함을 하나도 잡지 못했다** — 폼 배선만 봤고 결과
 * 렌더는 보지 않았다. 그래서 「법적 방어선」(`PRD §0.3`·`COR-2`)이 조용히 사라진
 * 상태로 남았다.
 */

/** 서버 실측 형태(`API_SPEC §5.1`)를 줄인 것. `warnings`·`disclaimer`는 **최상위**다. */
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
      calculation_basis: {
        ship_type: 'BULK_CARRIER',
        transport_capacity_basis: 'DWT',
      },
    })),
    summary: {
      lowest_cii_scenarios: ['SLOW_STEAMING'],
      shortest_duration_scenarios: ['DIRECT'],
      lowest_fuel_scenarios: ['SLOW_STEAMING'],
    },
  },
  warnings: ['REFERENCE_ONLY', 'NON_CII_VESSEL', 'WEATHER_NONE_FALLBACK'],
  disclaimer: '참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.',
}

function stubServerWithComparison(body: unknown = COMPARE_BODY, years: number[] = [2026]) {
  // `init`을 받는 이유는 **보낸 본문을 검사하기 위해서**다 (#892). 두 번째 인자를
  // 선언하지 않으면 `mock.calls[n][1]`의 타입이 없어 본문에 닿을 수 없다.
  const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
    void init
    const url = String(input)
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: years.map((year) => ({ year })) })
    }
    if (url.includes('/parameters/fuel-types')) {
      return jsonResponse({
        data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
      })
    }
    if (url.includes('/scenarios/compare')) {
      return jsonResponse(body)
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

/**
 * 「비교하기」를 누른다 — **열릴 때까지 기다린 뒤에** 누른다 (`#1093` ⑷).
 *
 * 연도 목록이 도착해야 버튼이 열린다. 종전에는 `initialFormState()`에 보이지 않는
 * `'2026'`이 박혀 있어 목록이 오기 전에도 눌렸고, 그것이 고친 결함이다 — 사용자가
 * 고른 적 없는 해로 계산이 돌았다.
 */
async function clickCompare(distance: string | null = '1000') {
  const button = (await screen.findByRole('button', {
    name: /비교하기/,
  })) as HTMLButtonElement
  /*
   * ⚠️ **연도 셀렉트가 그려질 때까지 기다린다.** 버튼의 `disabled`만 보면 안 된다 —
   * 첫 렌더에서는 셸의 선박이 아직 폼에 동기화되지 않아 `form.vesselId`가 비어 있고,
   * 그때는 차단 조건이 걸리지 않아 버튼이 열려 있다. 셀렉트가 그려졌다는 것이 곧
   * **목록이 왔고 연도가 골라졌다**는 뜻이다.
   */
  /*
   * 대기를 기본 1초보다 넉넉히 준다. 이 파일은 부하가 걸린 기계(WSL · `/mnt/c`)에서
   * 단독 3초 → 전체 실행 10초로 늘어난다 — 기본값이면 목록이 오기 전에 대기가
   * 끊겨 **검사가 무엇을 보는지와 무관한 이유로** 빨개진다.
   */
  const WAIT = { timeout: 5000 }
  await screen.findByLabelText('규제연도', {}, WAIT)
  /*
   * ⚠️ **연료 목록도 기다린다** (#1159). 연도만 기다리면 연료 목록이 늦게 올 때
   * `isKnownFuel('HFO', [])`가 거짓이라 **로컬 검증에서 멈추고 서버를 부르지 않는다** —
   * 검사는 오지 않을 결과를 찾다 실패한다. `#1149`가 ⑶ 한 곳만 이렇게 고쳤는데 같은
   * 모양이 이 도우미를 쓰는 검사 전부에 있었다(연료 응답을 400ms 늦추면 39건 중 10건
   * 실패 — 2026-09-20 실측). 이 파일의 목은 전부 HFO를 준다.
   *
   * 옵션 이름은 서버의 `display_name`(「고유황유」)이 아니라 `fuelTypeOptionText()`가
   * 만드는 「중유 (HFO)」다 — 화면은 `FUEL_TYPE_LABELS`를 원본으로 쓰고 서버 문구를
   * 그대로 내보내지 않는다(`fuelTypes.ts` · `VoyageCiiForm.test.tsx:131`).
   */
  await screen.findByRole('option', { name: '중유 (HFO)' }, WAIT)
  await waitFor(() => expect(button.disabled).toBe(false), WAIT)
  /*
   * ⚠️ **직항 거리를 채운다** (#1750). 종전에는 `initialFormState()`가 `'1000'`을 들고
   * 있었는데, 그 기본값이 「항구를 골라도 거리를 손으로 넣는다」의 원인이라 비웠다.
   * 이 도우미를 쓰는 검사들은 거리를 조건으로 보지 않으므로 여기서 한 번 넣는다 —
   * 거리 자체를 보는 검사는 이 도우미를 쓰지 않고 직접 넣는다.
   */
  if (distance !== null) {
    fireEvent.change(screen.getByLabelText(/직항 거리/), { target: { value: distance } })
  }
  fireEvent.click(button)
  return button
}

async function compareAndWaitForResult() {
  await clickCompare()
  await screen.findByText(/시나리오 비교/)
}

describe('서버 경고가 화면에 뜬다 (#821)', () => {
  it('경고 코드마다 `API_SPEC §1.6` 문구를 보여 준다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    /*
     * 문구 맵은 `voyage-cii/resultRules.ts`가 소유하고 두 화면이 공유한다 —
     * `#630`의 `warningMessage.sync.test.ts`가 `API_SPEC §1.6`과 대조하므로,
     * 여기서는 **그 문구가 이 화면에 도달하는지**만 본다.
     */
    expect(await screen.findByText(/공식 CII 적용 대상이 아닐 수 있습니다/)).toBeTruthy()
    expect(screen.getByText(/기상 보정 없이 계산했습니다/)).toBeTruthy()
  })

  /*
   * 면책은 하단 배너 한 곳에서만 말한다 (#1416 · `DESIGN_SYSTEM §13` 🔒). `REFERENCE_ONLY`는
   * 그 배너와 같은 말이라 경고 목록에서는 거른다 — 종전에는 이 검사가 **중복을 단언**하고 있었다.
   * 배너는 이 컴포넌트가 아니라 페이지(`RouteComparisonPage`)가 그리므로, 여기서는 **컴포넌트가
   * 참고용 고지를 하나도 그리지 않는다**를 본다.
   */
  it('면책은 화면에 한 번만 나온다 — 경고 목록이 배너를 반복하지 않는다 (#1416)', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    await screen.findByText(/공식 CII 적용 대상이 아닐 수 있습니다/)
    expect(screen.queryByText(/참고용 예측값/)).toBeNull()
    // 면책과 무관한 경고는 그대로 남는다 — 목록을 통째로 지우지 않는다.
    expect(screen.getByText(/기상 보정 없이 계산했습니다/)).toBeTruthy()
  })

  it('경고 코드 원문을 그대로 노출하지 않는다 — 맵을 거친다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    expect(screen.queryByText(/NON_CII_VESSEL/)).toBeNull()
    expect(screen.queryByText(/WEATHER_NONE_FALLBACK/)).toBeNull()
  })

  it('서버가 경고를 보내지 않으면 배너 자체가 없다', async () => {
    stubServerWithComparison({ ...COMPARE_BODY, warnings: [] })
    renderScreen()
    await compareAndWaitForResult()

    expect(screen.queryByText(/공식 CII 적용 대상이 아닐 수 있습니다/)).toBeNull()
  })
})

describe('면책 문구가 서버 정본과 같다 (#821)', () => {
  it('페이지로 올리는 값이 서버 문자열 그대로다 — 접두사를 붙이지 않는다', async () => {
    stubServerWithComparison()
    const seen: (string | undefined)[] = []

    render(
      <MemoryRouter initialEntries={['/scenarios']}>
        <Routes>
          <Route
            element={
              <Outlet
                context={{
                  ...EMPTY_SHELL_CONTEXT,
                  vesselId: '00000000-0000-4000-8000-000000000001',
                  vessels: [
                    {
                      id: '00000000-0000-4000-8000-000000000001',
                      displayName: '샘플 벌크선',
                      shipType: 'BULK_CARRIER',
                    },
                  ],
                  vesselsState: 'ready',
                  selectVesselId: () => {},
                } satisfies ShellContext}
              />
            }
          >
            <Route
              path="/scenarios"
              element={<ScenarioComparison onDisclaimer={(text) => seen.push(text)} />}
            />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    await compareAndWaitForResult()

    await waitFor(() =>
      expect(seen).toContain('참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.'),
    )
    expect(seen.some((text) => text?.startsWith('본 결과는'))).toBe(false)
  })
})

describe('선박명이 제목에 표시된다 (#821)', () => {
  it('셸이 가진 목록에서 고른 선박의 이름을 쓴다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    /*
     * 서버 응답에 선박명이 없으므로 **셸의 목록**에서 온다. 드롭다운이 이미 같은
     * 값을 렌더하므로 추가 조회가 필요 없다.
     */
    expect(await screen.findByText(/샘플 벌크선 · 2026년 기준/)).toBeTruthy()
  })

  it('목록에 없는 선박이면 그 배로 계산하지 않는다 — 선택을 풀고 안내한다 (#1097 ⑵)', async () => {
    stubServerWithComparison()
    /*
     * 상단바가 기억한 배가 목록에 없는 경우(삭제·권한 변경 직후). 종전 검사는 그 id로
     * 계산이 되고 제목에서 이름 칸만 빠지는 것을 확인했는데, **보이는 대상과 계산 대상이
     * 다른 것** 자체가 `#1097`이 든 결함이다. 지금은 선택을 풀고 안내한다.
     */
    const selectVesselId = vi.fn()
    renderScreen({
      vesselId: '00000000-0000-4000-8000-000000000001',
      vessels: [
        { id: '00000000-0000-4000-8000-00000000ffff', displayName: '다른 배', shipType: 'BULK_CARRIER' },
      ],
      selectVesselId,
    })
    expect(await screen.findByText(/상단바에서 고른 선박이 목록에 없습니다/)).toBeTruthy()
    expect(selectVesselId).toHaveBeenCalledWith(null)
    expect((screen.getByRole('combobox', { name: /선박/ }) as HTMLSelectElement).value).toBe('')
  })
})

/**
 * 결과 제목이 계산 시점에 고정된다 (#875).
 *
 * 종전에는 제목이 살아 있는 `form`을 읽고 숫자만 응답 스냅샷을 읽었다. 결과를 본
 * 뒤 배를 바꾸면 **A선의 계산 결과 위에 B선의 이름**이 붙었다.
 *
 * ⚠️ 위 `#821` 검사들이 이 결함을 못 잡은 이유는 **전환 이후를 보지 않아서**다.
 * 계산 직후의 제목만 확인하면 두 출처가 우연히 같은 값을 가리키는 순간만 본다.
 */

/** 셸 선택을 실제로 바꿀 수 있는 하네스. `selectVesselId`가 상태를 갱신한다. */
function renderSwitchable(
  vessels: ShellContext['vessels'],
  initialId: string | null,
) {
  function Harness() {
    const [vesselId, setVesselId] = useState<string | null>(initialId)
    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId,
      vessels,
      vesselsState: 'ready',
      selectVesselId: setVesselId,
    }
    return (
      <MemoryRouter initialEntries={['/scenarios']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/scenarios" element={<ScenarioComparison />} />
          </Route>
        </Routes>
      </MemoryRouter>
    )
  }
  return render(<Harness />)
}

const TWO_VESSELS: ShellContext['vessels'] = [
  {
    id: '00000000-0000-4000-8000-000000000001',
    displayName: '샘플 벌크선',
    shipType: 'BULK_CARRIER',
  },
  {
    id: '00000000-0000-4000-8000-000000000002',
    displayName: '두 번째 배',
    shipType: 'BULK_CARRIER',
  },
]

describe('결과 제목은 계산 시점에 고정된다 (#875)', () => {
  it('결과를 본 뒤 선박을 바꿔도 제목의 선박명이 그대로다', async () => {
    stubServerWithComparison()
    renderSwitchable(TWO_VESSELS, TWO_VESSELS[0].id)
    await compareAndWaitForResult()
    expect(await screen.findByText(/샘플 벌크선 · 2026년 기준/)).toBeTruthy()

    fireEvent.change(screen.getByLabelText('선박'), {
      target: { value: TWO_VESSELS[1].id },
    })

    // 폼은 새 배를 가리키는데 제목·숫자는 이전 계산 그대로여야 한다.
    await waitFor(() =>
      expect((screen.getByLabelText('선박') as HTMLSelectElement).value).toBe(
        TWO_VESSELS[1].id,
      ),
    )
    expect(screen.getByText(/2026년 기준/).textContent).toContain('샘플 벌크선')
    expect(screen.getByText(/2026년 기준/).textContent).not.toContain('두 번째 배')
  })

  it('결과를 본 뒤 연도를 바꿔도 제목의 연도가 그대로다', async () => {
    stubServerWithComparison(COMPARE_BODY, [2026, 2027])
    renderScreen()
    await compareAndWaitForResult()
    expect(await screen.findByText(/2026년 기준/)).toBeTruthy()

    fireEvent.change(screen.getByLabelText('규제연도'), { target: { value: '2027' } })

    await waitFor(() =>
      expect((screen.getByLabelText('규제연도') as HTMLSelectElement).value).toBe('2027'),
    )
    expect(screen.getByText(/년 기준/).textContent).toContain('2026년 기준')
    expect(screen.queryByText(/2027년 기준/)).toBeNull()
  })

  it('계산 직후에는 낡음 표시가 없다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    expect(screen.queryByText(/입력이 바뀌었습니다/)).toBeNull()
  })

  it('입력이 바뀌면 결과가 낡았음을 알린다 — 선박·연도 밖의 칸도 마찬가지다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    fireEvent.change(screen.getByLabelText(/직항 거리/), { target: { value: '1500' } })

    expect(await screen.findByText(/입력이 바뀌었습니다/)).toBeTruthy()
  })

  it('다시 비교하면 제목이 새 조건으로 갱신되고 낡음 표시가 사라진다', async () => {
    stubServerWithComparison()
    renderSwitchable(TWO_VESSELS, TWO_VESSELS[0].id)
    await compareAndWaitForResult()

    fireEvent.change(screen.getByLabelText('선박'), {
      target: { value: TWO_VESSELS[1].id },
    })
    expect(await screen.findByText(/입력이 바뀌었습니다/)).toBeTruthy()

    await clickCompare()

    await waitFor(() =>
      expect(screen.getByText(/2026년 기준/).textContent).toContain('두 번째 배'),
    )
    expect(screen.queryByText(/입력이 바뀌었습니다/)).toBeNull()
  })
})

/**
 * 선택 입력 5종의 배선 (#892).
 *
 * ## 폼이 그려지는 것만으로는 증명되지 않는다
 *
 * `#821`이 그 선례다 — 프론트 검사 59건이 전부 통과하는 동안 `warnings: []` 리터럴이
 * 배너 조건을 영구 거짓으로 만들고 있었다. 그래서 여기서는 **입력창에 친 값이
 * `fetch` 본문까지 도달하는지**를 본다. 화면 → 규칙 → provider 세 층을 한 번에 지난다.
 */
describe('선택 입력이 요청까지 도달한다 (#892)', () => {
  /*
   * 라벨을 **정규식으로** 찾는다. 힌트 문구가 `<label>` 안에 있어 완전 일치가
   * 실패하기 때문이다 — 기존 칸들(`기준 일일 연료소모량`)과 같은 구조다.
   */
  async function fillAndCompare(values: Array<[RegExp, string]>) {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    for (const [label, value] of values) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    await clickCompare()

    await waitFor(() => {
      expect(
        fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare')),
      ).toBe(true)
    })
    const call = fetchImpl.mock.calls.find(([url]) =>
      String(url).includes('/scenarios/compare'),
    )!
    return (call[1] as RequestInit).body as string
  }

  it('우회 거리·감속 속력·기상 모델·현재 좌표가 본문에 실린다', async () => {
    const body = await fillAndCompare([
      [/우회 거리/, '1200'],
      [/감속 속력/, '10.5'],
      [/기상 보정 모델/, 'SIMPLE_RULE'],
      [/현재 위도/, '35.1'],
      [/현재 경도/, '129.05'],
    ])

    expect(JSON.parse(body)).toMatchObject({
      detour_distance_nm: 1200,
      slow_speed_kn: 10.5,
      weather_model: 'SIMPLE_RULE',
      current_lat: 35.1,
      current_lon: 129.05,
    })
  })

  it('손대지 않으면 다섯 키가 본문에 없다 — 서버 기본이 그대로 쓰인다', async () => {
    const body = await fillAndCompare([])

    for (const key of [
      'detour_distance_nm',
      'slow_speed_kn',
      'weather_model',
      'current_lat',
      'current_lon',
    ]) {
      expect(body).not.toContain(key)
    }
  })

  it('감속 속력 0.5는 요청을 보내지 않는다 — VAL-009 하한은 1.0이다', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    fireEvent.change(screen.getByLabelText(/감속 속력/), { target: { value: '0.5' } })
    await clickCompare()

    // 조사는 받침으로 고른다 — 「속력」은 받침이 있어 「은」이다 (`#1369`).
    expect(await screen.findByText(/감속 속력은 1 이상이어야 합니다\./)).toBeTruthy()
    expect(
      fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare')),
    ).toBe(false)
  })

  it('좌표를 한쪽만 넣으면 요청을 보내지 않는다 (API_SPEC:572)', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    fireEvent.change(screen.getByLabelText(/현재 위도/), { target: { value: '35.1' } })
    await clickCompare()

    expect(await screen.findByText(/현재 경도도 함께 입력해 주세요/)).toBeTruthy()
    expect(
      fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare')),
    ).toBe(false)
  })

  it('좌표 없이 기상 모델만 고르면 누르기 전에 알린다', async () => {
    // 결과에 붙는 `WEATHER_NONE_FALLBACK` 배너로는 계산이 끝난 뒤에야 알 수 있다.
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    expect(screen.queryByText(/현재 좌표를 입력해야 기상 보정이 적용됩니다/)).toBeNull()
    fireEvent.change(screen.getByLabelText(/기상 보정 모델/), {
      target: { value: 'SIMPLE_RULE' },
    })
    expect(screen.getByText(/현재 좌표를 입력해야 기상 보정이 적용됩니다/)).toBeTruthy()

    fireEvent.change(screen.getByLabelText(/현재 위도/), { target: { value: '35.1' } })
    fireEvent.change(screen.getByLabelText(/현재 경도/), { target: { value: '129.05' } })
    expect(screen.queryByText(/현재 좌표를 입력해야 기상 보정이 적용됩니다/)).toBeNull()
  })
})

/**
 * 비교 결과를 **항차 계획에 반영**한다 (`#580`).
 *
 * 서버는 `#58`로 있었는데 화면 소비처가 0곳이었다. 흐름은 디자인 판정(2026-08-23)을
 * 따른다 — 계획 단계 항차만 · 같은 화면에 남는다 · 되돌리기 없음을 **채택 전에** 알린다.
 */
/**
 * 입력을 성격으로 셋으로 가른다 (`#1417`).
 *
 * 종전에는 13칸이 `<fieldset>` 없이 한 평면에 놓여, 비워도 되는 칸과 비우면 계산이
 * 안 되는 칸이 같은 무게였다. **비워 두면 서버 기본인 칸**을 「고급 설정」으로 접었다.
 *
 * ⚠️ jsdom은 닫힌 `<details>` 안의 칸도 찾아 준다 — 위 검사들이 고급 칸을 **펼치지 않고**
 * 채워도 통과하는 이유다. 실제 브라우저에서는 접힌 칸에 닿을 수 없으므로, 여기서는
 * **접혀 있는가 · 오류가 나면 펼치는가 · 겉에서 안쪽 상태가 보이는가**를 따로 본다.
 */
describe('입력 묶음과 고급 설정 (#1417)', () => {
  const advanced = () =>
    screen.getByText('고급 설정').closest('details') as HTMLDetailsElement

  it('필수·위치 묶음이 있고, 고급은 처음에 접혀 있다', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    expect(screen.getByRole('group', { name: '필수 입력' })).toBeTruthy()
    expect(screen.getByRole('group', { name: '위치' })).toBeTruthy()
    expect(advanced().open).toBe(false)
  })

  it('비워 두면 서버 기본이라는 것을 접힌 겉에서 말하고, 칸을 채우면 그 수를 말한다', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    const summary = advanced().querySelector('summary') as HTMLElement
    expect(summary.textContent).toContain('기본 규칙')

    fireEvent.change(screen.getByLabelText(/감속 속력/), { target: { value: '10' } })

    // 안에 값이 들어 있는데 겉에서 안 보이면 기본 규칙으로 계산했다고 믿는다 (#1418).
    expect(summary.textContent).toContain('1개')
  })

  it('고급 칸에 오류가 나면 스스로 펼친다 — 접힌 채로는 오류가 보이지 않는다', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')
    expect(advanced().open).toBe(false)

    fireEvent.change(screen.getByLabelText(/감속 속력/), { target: { value: '0.5' } })
    await clickCompare()

    expect(await screen.findByText(/감속 속력은 1 이상이어야 합니다\./)).toBeTruthy()
    expect(advanced().open).toBe(true)
  })

  it('목적항은 필수 묶음이 아니라 위치 묶음에 있다 — #1454로 선택 필드가 됐다', async () => {
    stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    const destination = screen.getByLabelText('목적항')
    expect(destination.closest('fieldset')?.querySelector('legend')?.textContent).toBe('위치')
    expect(destination.hasAttribute('required')).toBe(false)
  })

  it('결과 카드에 계약 코드가 보이지 않는다 — 한국어 이름이 바로 위에 있다', async () => {
    stubServerWithComparison()
    renderScreen()
    await compareAndWaitForResult()

    // 「감속」은 카드 이름과 표·범례에 여러 번 나온다 — 있는지만 본다.
    expect(screen.getAllByText('감속').length).toBeGreaterThan(0)
    expect(screen.queryByText('SLOW_STEAMING')).toBeNull()
    expect(screen.queryByText('DETOUR')).toBeNull()
  })
})

describe('계획에 반영 (#580)', () => {
  const VESSEL = '00000000-0000-4000-8000-000000000001'
  const VOYAGES = [
    { id: 'v-draft', voyage_no: '2026-05', status: 'DRAFT' },
    { id: 'v-planned', voyage_no: '2026-06', status: 'PLANNED' },
    { id: 'v-sailing', voyage_no: '2026-04', status: 'IN_PROGRESS' },
    { id: 'v-done', voyage_no: '2026-03', status: 'CONFIRMED' },
  ]

  function stubAdoptServer(adoptStatus = 200) {
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      if (url.includes('/scenarios/compare')) return jsonResponse(COMPARE_BODY)
      if (url.includes(`/vessels/${VESSEL}/voyages`)) return jsonResponse({ data: VOYAGES })
      if (url.includes('/adopt')) {
        return adoptStatus === 200
          ? jsonResponse({
              data: {
                voyage_id: 'v-planned',
                adopted_scenario_type: 'SLOW_STEAMING',
                updated_fields: ['planned_distance_nm', 'planned_speed_kn', 'planned_arrival_at'],
                // 화면이 이 수를 **그대로 적는다** — `#817`이 닫혀 참값이 됐다 (`#1077`).
                invalidated_calculation_runs: 7,
              },
            })
          : jsonResponse({ error: { code: 'STATE_TRANSITION_ERROR', message: '계획 단계 항차에만 반영할 수 있습니다.' } }, 409)
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  async function openPanel() {
    await compareAndWaitForResult()
    return screen.findByRole('region', { name: /계획에 반영/ })
  }

  it('계획 단계 항차만 고를 수 있다 — 출항한 항차의 계획은 바꾸지 않는다', async () => {
    stubAdoptServer()
    renderScreen()
    await openPanel()

    const select = (await screen.findByLabelText('대상 항차')) as HTMLSelectElement
    const labels = [...select.querySelectorAll('option')].map((o) => o.textContent)
    expect(labels).toEqual(['선택', '2026-05 · 작성 중', '2026-06 · 계획 확정'])
  })

  it('상단바에서 고른 항차가 반영 가능하면 그것을 기본으로 둔다', async () => {
    stubAdoptServer()
    renderScreen({ voyageId: 'v-planned' })
    await openPanel()

    const select = (await screen.findByLabelText('대상 항차')) as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe('v-planned'))
  })

  it('상단바의 항차가 출항한 항차면 기본으로 두지 않는다 — 고를 수 없는 항차다', async () => {
    stubAdoptServer()
    renderScreen({ voyageId: 'v-sailing' })
    await openPanel()

    const select = (await screen.findByLabelText('대상 항차')) as HTMLSelectElement
    expect(select.value).toBe('')
  })

  it('반영 전에 되돌릴 수 없음을 확인받는다 — 거절하면 요청을 보내지 않는다', async () => {
    const fetchImpl = stubAdoptServer()
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    renderScreen()
    await openPanel()

    fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
    fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })
    fireEvent.click(screen.getByRole('button', { name: '계획에 반영' }))

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(String(confirm.mock.calls[0])).toContain('되돌릴 수 없습니다')
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/adopt'))).toBe(false)
  })

  it('반영하면 무엇이 바뀌었는지 · 재계산이 필요하다는 것 · 그 항차로 가는 길을 낸다', async () => {
    const fetchImpl = stubAdoptServer()
    vi.stubGlobal('confirm', vi.fn(() => true))
    renderScreen()
    await openPanel()

    fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
    fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })
    fireEvent.click(screen.getByRole('button', { name: '계획에 반영' }))

    expect(await screen.findByText(/시나리오를 반영했습니다/)).toBeTruthy()
    expect(screen.getByText(/바뀐 값 — 항해거리 · 평균 속력 · 도착 예정 시각/)).toBeTruthy()
    // `#1077` — 사실만이 아니라 **건수**까지 적는다. 종전에는 이 단언이 문장 앞부분만 보아
    // 수가 빠진 것을 잡지 못했다(`#817` 유예를 정답으로 들고 있었다).
    expect(
      screen.getByText(/계산 결과 7건에 재계산 필요 표시를 남겼습니다/),
    ).toBeTruthy()
    const link = screen.getByRole('link', { name: '반영한 항차 보기' })
    expect(link.getAttribute('href')).toBe(`/vessels/${VESSEL}/voyages/v-planned`)

    const [, init] = fetchImpl.mock.calls.find(([url]) => String(url).includes('/adopt')) ?? []
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      target_voyage_id: 'v-planned',
      adopt_mode: 'UPDATE_EXISTING_PLAN',
    })
    // 서버가 보낸 재계산 건수(7)를 화면이 **그대로 낸다** — `#817`이 닫혀 참값이 됐다 (`#1077`).
    expect(screen.getByText(/7건/)).toBeTruthy()
  })

  it('거부되면 서버 사유를 그대로 보인다', async () => {
    stubAdoptServer(409)
    vi.stubGlobal('confirm', vi.fn(() => true))
    renderScreen()
    await openPanel()

    fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-direct' } })
    fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-draft' } })
    fireEvent.click(screen.getByRole('button', { name: '계획에 반영' }))

    expect(await screen.findByText('계획 단계 항차에만 반영할 수 있습니다.')).toBeTruthy()
    expect(screen.queryByText(/시나리오를 반영했습니다/)).toBeNull()
  })

  it('입력이 바뀌어 결과가 낡으면 반영하지 않는다 — 보고 있는 값과 반영될 값이 갈린다', async () => {
    stubAdoptServer()
    renderScreen()
    await openPanel()

    fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-direct' } })
    fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-draft' } })
    fireEvent.change(screen.getByLabelText(/직항 거리/), { target: { value: '1500' } })

    const button = (await screen.findByRole('button', { name: '계획에 반영' })) as HTMLButtonElement
    await waitFor(() => expect(button.disabled).toBe(true))
    expect(screen.getByText(/다시 비교한 뒤 반영할 수 있습니다/)).toBeTruthy()
  })

  // #1812 — 항차 번호가 없어 구간으로 대신할 때, 저장 코드(`BUSAN`)가 아니라 보이는
  // 이름(`부산`)이 나온다. `voyageLabel`·`voyageOptionLabel`과 같은 성질을 여기서도 본다.
  it('항차 번호가 없으면 구간을 저장 코드가 아니라 보이는 이름으로 적는다', async () => {
    const PORTS = [
      { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    ]
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/ports/samples')) return jsonResponse({ data: PORTS })
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      if (url.includes('/scenarios/compare')) return jsonResponse(COMPARE_BODY)
      if (url.includes(`/vessels/${VESSEL}/voyages`)) {
        return jsonResponse({
          data: [
            {
              id: 'v-planned-2',
              voyage_no: null,
              status: 'PLANNED',
              departure_port_name: 'BUSAN',
              arrival_port_name: 'SINGAPORE',
            },
          ],
        })
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    renderScreen()
    await openPanel()

    // 항구 목록은 비동기로 늦게 온다 — 도착하면 `voyageOptionLabel`이 그릴 때 보이는
    // 이름으로 바뀐다(항차 재조회 없이, `samplePorts` 상태 변화에 따른 리렌더만으로).
    await waitFor(() => {
      const select = screen.getByLabelText('대상 항차') as HTMLSelectElement
      const label = [...select.querySelectorAll('option')]
        .map((o) => o.textContent)
        .find((text) => text !== '선택')
      expect(label).not.toContain('BUSAN')
    })
  })

  /**
   * #1812 재작업 — 항구 목록이 항차 목록보다 늦게 도착해도, 사용자가 이미 고른 항차
   * 선택과 채택 상태가 지워지지 않는다.
   *
   * 처음에는 항차 조회 effect가 `samplePorts`에 의존해, 항구 목록이 늦게 오면 그 effect가
   * 다시 돌며 `setVoyageId('')`·`setAdopt({status:'idle'})`까지 함께 돌아 선택이 지워졌다
   * — 리뷰로 지적돼 되돌렸다.
   */
  it('항구 목록이 늦게 도착해도 이미 고른 항차 선택이 지워지지 않는다', async () => {
    let resolvePorts: ((response: Response) => void) | null = null
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/ports/samples')) {
        return new Promise<Response>((resolve) => {
          resolvePorts = resolve
        })
      }
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      if (url.includes('/scenarios/compare')) return jsonResponse(COMPARE_BODY)
      if (url.includes(`/vessels/${VESSEL}/voyages`)) return jsonResponse({ data: VOYAGES })
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    renderScreen()
    await openPanel()

    fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
    fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })

    const select = screen.getByLabelText('대상 항차') as HTMLSelectElement
    expect(select.value).toBe('v-planned')

    // 이제서야 항구 목록이 도착한다. 항차 선택은 그대로 남아야 한다.
    await act(async () => {
      resolvePorts?.(jsonResponse({ data: [] }))
    })

    expect(select.value).toBe('v-planned')
  })

  /**
   * 채택(`adopt`)은 사무직 전용이다(`API_SPEC §1.2` · `#1325`). 현장직이 폼을 다 채우고
   * 확인 대화상자까지 지나서야 서버 `403`을 받던 것을 버튼 단계에서 막는다 —
   * `VesselManagement`·`AnnualSimulation`과 같은 패턴(`isOffice` + `OFFICE_ONLY_ACTION_HINT`).
   */
  describe('역할 — 채택은 사무직 전용이다 (#1325)', () => {
    it('현장직: 반영 버튼이 잠기고 안내가 뜬다', async () => {
      stubRole('FIELD')
      stubAdoptServer()
      renderScreen()
      await openPanel()

      fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
      fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })

      const button = screen.getByRole('button', { name: '계획에 반영' }) as HTMLButtonElement
      expect(button.disabled).toBe(true)
      expect(screen.getByText(OFFICE_ONLY_ACTION_HINT)).toBeTruthy()
    })

    it('사무직: 반영 버튼이 그대로 동작한다', async () => {
      stubRole('OFFICE')
      const fetchImpl = stubAdoptServer()
      vi.stubGlobal('confirm', vi.fn(() => true))
      renderScreen()
      await openPanel()

      fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
      fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })

      const button = screen.getByRole('button', { name: '계획에 반영' }) as HTMLButtonElement
      expect(button.disabled).toBe(false)
      expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()

      fireEvent.click(button)
      expect(await screen.findByText(/시나리오를 반영했습니다/)).toBeTruthy()
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/adopt'))).toBe(true)
    })

    it('관리자: 반영 버튼이 그대로 동작한다 — ADMIN은 OFFICE의 상위집합 (#1301)', async () => {
      stubRole('ADMIN')
      const fetchImpl = stubAdoptServer()
      vi.stubGlobal('confirm', vi.fn(() => true))
      renderScreen()
      await openPanel()

      fireEvent.change(screen.getByLabelText('시나리오'), { target: { value: 'sc-slow_steaming' } })
      fireEvent.change(await screen.findByLabelText('대상 항차'), { target: { value: 'v-planned' } })

      const button = screen.getByRole('button', { name: '계획에 반영' }) as HTMLButtonElement
      expect(button.disabled).toBe(false)
      expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()

      fireEvent.click(button)
      expect(await screen.findByText(/시나리오를 반영했습니다/)).toBeTruthy()
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/adopt'))).toBe(true)
    })
  })
})

/**
 * 샘플 항만으로 현재 위치·목적항을 고르고, 직항 거리를 비우면 좌표로 계산한다 (#1005).
 *
 * `PRD §11.2` 「직항 거리 = 사용자 입력 **또는 좌표 기반 대권거리**」의 뒤엣것을 화면에서
 * 쓸 수 없었다 — 목적항 칸이 없었다. `PRD §15.2`대로 결과가 「좌표 기반 추정 거리」라고 말하는지도 본다.
 */
describe('샘플 항만 — 현재 위치·목적항 (#1005)', () => {
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  function stubServerWithPorts() {
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
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
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  it('고른 두 항의 좌표로 계산하고, 결과가 좌표 기반 추정 거리라고 말한다', async () => {
    const fetchImpl = stubServerWithPorts()
    renderScreen()
    await screen.findByDisplayValue('2026')
    await waitFor(() => expect(document.querySelectorAll('#sc-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText(/현재 위치/), { target: { value: '부산' } })
    // 현재 위치는 입력 보조다 — 고르면 위도·경도 칸을 채운다.
    expect((screen.getByLabelText(/현재 위도/) as HTMLInputElement).value).toBe('35.1')
    expect((screen.getByLabelText(/현재 경도/) as HTMLInputElement).value).toBe('129.0333')
    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'singapore' } })
    expect((screen.getByLabelText(/목적항/) as HTMLInputElement).value).toBe('SINGAPORE')
    fireEvent.change(screen.getByLabelText(/직항 거리/), { target: { value: '' } })
    expect(screen.getByText(/비워 두면 현재 위치와 목적항 좌표로 계산합니다/)).toBeTruthy()

    // 거리를 비운 채로 보낸다 — 이 검사가 보는 것이 그 경로다 (#1005).
    await clickCompare(null)

    await waitFor(() =>
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare'))).toBe(true),
    )
    const call = fetchImpl.mock.calls.find(([url]) => String(url).includes('/scenarios/compare'))!
    const body = JSON.parse((call[1] as RequestInit).body as string)
    expect(body).not.toHaveProperty('direct_distance_nm')
    expect(body).toMatchObject({
      current_lat: 35.1,
      current_lon: 129.0333,
      destination_port_name: 'SINGAPORE',
      destination_lat: 1.2833,
      destination_lon: 103.85,
    })
    expect(await screen.findByText(/직항 거리는 좌표 기반 추정 거리입니다/)).toBeTruthy()
  })

  it('목록에 없는 목적항은 이름만 싣는다 — 좌표를 추측하지 않는다', async () => {
    const fetchImpl = stubServerWithPorts()
    renderScreen()
    await screen.findByDisplayValue('2026')
    await waitFor(() => expect(document.querySelectorAll('#sc-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'Busan New Port' } })
    await clickCompare()

    await waitFor(() =>
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare'))).toBe(true),
    )
    const call = fetchImpl.mock.calls.find(([url]) => String(url).includes('/scenarios/compare'))!
    const body = JSON.parse((call[1] as RequestInit).body as string)
    expect(body.destination_port_name).toBe('Busan New Port')
    expect(body).not.toHaveProperty('destination_lat')
    // 직항 거리를 그대로 두었으므로 결과는 좌표 추정이라고 말하지 않는다.
    expect(screen.queryByText(/직항 거리는 좌표 기반 추정 거리입니다/)).toBeNull()
  })
})

describe('보이는 대상 = 계산 대상 (#1097)', () => {
  it('⑴ 좌표를 찾는 동안 목적항 이름이 바뀌면 늦게 온 좌표를 버린다', async () => {
    let release: ((r: Response) => void) | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/ports/lookup')) {
          return new Promise<Response>((resolve) => {
            release = resolve
          })
        }
        if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        return jsonResponse({ data: [] })
      }),
    )
    renderScreen()
    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'Rotterdam' } })
    fireEvent.click(await screen.findByRole('button', { name: /좌표 찾기/ }))
    await waitFor(() => expect(release).not.toBeNull())
    // 응답이 오기 전에 이름을 바꾼다
    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'Busan' } })
    await act(async () => {
      release!(jsonResponse({ data: { lat: 51.9, lon: 4.5, source: 'ONLINE' } }))
    })
    expect((screen.getByLabelText(/목적지 위도|도착 위도|위도/) as HTMLInputElement).value).toBe('')
  })

  it('⑶ 서버가 칸을 짚은 422는 그 입력칸에 붙는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/scenarios/compare')) {
          return jsonResponse(
            {
              error: {
                code: 'VALIDATION_ERROR',
                message: '직항 거리가 너무 큽니다.',
                details: [{ field: 'direct_distance_nm', field_label: '직항 거리', message: '직항 거리가 너무 큽니다.' }],
              },
            },
            422,
          )
        }
        if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        return jsonResponse({ data: [] })
      }),
    )
    renderScreen()
    // 연료 목록이 로드되기 전에 클릭하면 isKnownFuel('HFO', [])=false → 로컬 검증 실패 → API 미호출.
    // 연료 목록 대기는 `clickCompare()`가 한다 — 이 검사가 처음 드러낸 경합이다(#1149 · #1159).
    await clickCompare()
    const alerts = await screen.findAllByText('직항 거리가 너무 큽니다.')
    // 폼 위 오류와 **입력칸 아래** 오류 — 둘 다 있다
    expect(alerts.length).toBeGreaterThanOrEqual(2)
  })
})


/**
 * 선박 목록 조회 **실패**를 「등록된 선박이 없다」로 말하지 않는다 (`#1093` ⑵·⑷).
 *
 * 셸은 조회가 실패하면 `vessels`를 `[]`로 두고 `vesselsState`만 `'failed'`로 세운다.
 * 종전 `noVessel`은 배열 길이만 봐서 실패에서도 참이었고, 「불러오지 못했습니다」와
 * 「등록된 선박이 없어 비교할 대상이 없습니다. 선박을 먼저 등록해 주세요」가 **동시에**
 * 떴다 — 뒤쪽이 행동을 지시하므로 사용자는 등록할 필요가 없는데 등록 화면으로 갔다.
 */
describe('선박 목록 실패를 「선박 없음」으로 말하지 않는다 (#1093 ⑵)', () => {
  it('실패했을 때 「등록된 선박이 없어…」가 나오지 않는다', async () => {
    stubServer()

    renderScreen({ vesselId: null, vessels: [], vesselsState: 'failed' })

    /*
     * ⚠️ 이 문구는 **두 곳**에 나온다 — 폼 상단 안내와 셀렉트의 빈 선택지.
     * `findByText`는 둘을 다 잡아 실패하므로 개수로 받는다.
     */
    expect(await screen.findAllByText(/선박 목록을 불러오지 못했습니다/)).toHaveLength(2)
    expect(screen.queryByText(/등록된 선박이 없어/)).toBeNull()
  })

  it('실패했을 때 선박 셀렉트가 「선택」이라 말하지 않고 비활성이다', async () => {
    stubServer()

    renderScreen({ vesselId: null, vessels: [], vesselsState: 'failed' })

    /*
     * 라벨 배선으로 찾는다 — `#936`의 공용 `Field`가 `<label for>` + 컨트롤을
     * **형제로** 그리므로 `.closest('label')`로는 닿지 않는다.
     */
    const select = (await screen.findByLabelText('선박')) as HTMLSelectElement
    expect(select.textContent).toContain('선박 목록을 불러오지 못했습니다')
    expect(select.textContent).not.toContain('선택')
    expect(select.disabled).toBe(true)
  })

  it('진짜로 0척이면 종전대로 「등록된 선박이 없어…」다', async () => {
    stubServer()

    renderScreen({ vesselId: null, vessels: [], vesselsState: 'ready' })

    expect(await screen.findByText(/등록된 선박이 없어/)).toBeTruthy()
    expect(screen.queryByText(/선박 목록을 불러오지 못했습니다/)).toBeNull()
  })
})

/**
 * 연도를 고를 수 없으면 비교하지 않는다 (`#1093` ⑷).
 *
 * 연도 목록이 실패·빈 목록이면 화면은 셀렉트 대신 주석 한 줄을 그린다 — 사용자가
 * 연도를 고를 수 없다. 그런데 `initialFormState()`가 `'2026'`을 들고 있어 검증을
 * 통과했고, **고른 적 없는 2026년 기준 결과**가 나왔다.
 */
describe('연도 목록이 없으면 비교를 차단한다 (#1093 ⑷)', () => {
  function submitButton(): HTMLButtonElement {
    return screen.getByRole('button', { name: '비교하기' }) as HTMLButtonElement
  }

  it('연도 목록이 비면 비교하기가 눌리지 않는다', async () => {
    stubServer([])

    renderScreen()

    await screen.findByText('등록된 규제연도가 없습니다')
    expect(submitButton().disabled).toBe(true)
  })

  it('연도 조회가 실패하면 비교하기가 눌리지 않는다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/regulation-years')) {
          return jsonResponse({ error: { message: '서버 오류' } }, 500)
        }
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

    renderScreen()

    await screen.findByText('규제연도 목록을 불러오지 못했습니다')
    expect(submitButton().disabled).toBe(true)
  })

  it('연도 목록이 오면 비교하기가 열린다', async () => {
    stubServer()

    renderScreen()

    await waitFor(() => expect(submitButton().disabled).toBe(false))
  })
})

/*
 * 비교 표 (#1745).
 *
 * 종전에는 시나리오마다 카드 한 장이었고 카드마다 같은 여덟 줄이 반복됐다 —
 * **비교하는 화면에서 비교가 가장 어려웠다.** 여기서 보는 것은 셋이다: 같은 지표의
 * 세 값이 한 줄에 서는가, 증감이 직항 기준인가, 화면이 어느 쪽을 추천하지 않는가.
 */
describe('비교 표 — 행은 지표, 열은 시나리오 (#1745)', () => {
  /** `COMPARE_BODY`는 세 시나리오가 값이 같다 — 증감을 보려면 갈라 놓아야 한다. */
  const VARIED: Record<string, Partial<{ distance_nm: number; attained_cii: string; fuel_ton: string }>> = {
    DIRECT: { distance_nm: 1000, attained_cii: '42.535870', fuel_ton: '87.50' },
    DETOUR: { distance_nm: 1050, attained_cii: '42.535870', fuel_ton: '91.88' },
    SLOW_STEAMING: { distance_nm: 1000, attained_cii: '38.100000', fuel_ton: '78.40' },
  }

  const variedBody = {
    ...COMPARE_BODY,
    data: {
      ...COMPARE_BODY.data,
      scenarios: COMPARE_BODY.data.scenarios.map((scenario) => ({
        ...scenario,
        ...VARIED[scenario.scenario_type],
      })),
    },
  }

  async function renderTable(body: unknown = variedBody) {
    stubServerWithComparison(body)
    renderScreen()
    await compareAndWaitForResult()
    return screen.getByRole('table')
  }

  it('열 머리가 시나리오 셋이고, 기준인 직항이 그 사실을 말한다', async () => {
    const table = await renderTable()
    const heads = within(table).getAllByRole('columnheader')

    expect(heads.map((head) => head.textContent)).toEqual([
      '지표',
      '직항기준',
      '우회',
      '감속',
    ])
  })

  it('같은 지표의 세 값이 한 줄에 선다 — 카드 사이로 눈을 옮기지 않는다', async () => {
    const table = await renderTable()
    const row = within(table).getByRole('row', { name: /항해거리/ })

    expect(
      within(row)
        .getAllByRole('cell')
        .map((cell) => cell.textContent),
    ).toEqual(['1,000', '1,050+50', '1,000동일'])
  })

  it('단위는 지표 이름 옆에 한 번만 — 칸마다 반복하지 않는다', async () => {
    const table = await renderTable()
    const row = within(table).getByRole('row', { name: /항해거리/ })

    expect(within(row).getByRole('rowheader').textContent).toBe('항해거리 (nm)')
    for (const cell of within(row).getAllByRole('cell')) {
      expect(cell.textContent).not.toMatch(/nm/)
    }
  })

  it('증감은 직항 기준이다 — 직항 칸에는 증감이 없다', async () => {
    const table = await renderTable()
    const cells = within(within(table).getByRole('row', { name: /예상 연료/ })).getAllByRole('cell')

    expect(cells[0].textContent).toBe('87.5')
    expect(cells[1].textContent).toBe('91.9+4.4')
    expect(cells[2].textContent).toBe('78.4−9.1')
  })

  it('증감에 색을 주지 않는다 — 어느 쪽이 나은지는 화면이 판정하지 않는다 (PRD §11.2)', async () => {
    const table = await renderTable()
    const cells = within(within(table).getByRole('row', { name: /예상 연료/ })).getAllByRole('cell')

    for (const cell of cells.slice(1)) {
      const delta = cell.querySelector('.scenario-table__delta')
      expect(delta?.className).toBe('scenario-table__delta')
    }
  })

  it('결론 띠를 두지 않는다 — §8.6 표의 「항로 비교」 행이 그렇게 정했다', async () => {
    await renderTable()

    expect(document.querySelector('.verdict-strip')).toBeNull()
    expect(screen.queryByText(/추천/)).toBeNull()
  })

  it('CII가 직항과 같으면 그 이유를 표 아래에 적는다 (#739)', async () => {
    await renderTable()

    /* 우회는 거리가 길고 CII가 같다 — 「거리당 값」 설명이 붙는다. */
    expect(screen.getByText(/우회의 CII는 직항과 같습니다/)).toBeTruthy()
    expect(screen.getByText(/거리가 늘어도 연료가 같은 비율로 늘어/)).toBeTruthy()
    /* 감속은 CII가 다르다 — 설명할 일이 없다. */
    expect(screen.queryByText(/감속의 CII는 직항과 같습니다/)).toBeNull()
  })

  it('지표별 최소값은 그대로 남는다 — 추천이 아니라 중립 표기다 (PRD §11.2)', async () => {
    await renderTable()

    expect(screen.getByText('CII가 가장 낮은 시나리오')).toBeTruthy()
  })

  it('결과는 면 하나다 — 표와 최소값이 같은 면에 있고 카드가 남아 있지 않다 (§5)', async () => {
    const table = await renderTable()

    expect(document.querySelectorAll('.scenario-card')).toHaveLength(0)
    const result = document.querySelector('.scenario-result')
    expect(result?.contains(table)).toBe(true)
    expect(result?.querySelector('.scenario-comparison__lowest')).toBeTruthy()
  })
})

/*
 * 항구를 고르면 직항 거리를 손으로 넣지 않는다 (#1750).
 *
 * `#1005`가 「비우면 좌표로 계산한다」를 열어 두었지만 `initialFormState()`의 `'1000'`이
 * 그 경로를 덮고 있었고, 비우고 눌러도 **거리는 결과에서야** 보였다. 여기서 보는 것은:
 * 추정 거리가 칸에 들어오는가, 항을 바꾸면 사라지는가, 손으로 넣은 값은 남는가.
 */
describe('추정 거리 넣기 (#1750)', () => {
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  function stubWithGreatCircle(distanceNm: unknown = 2504.62) {
    const fetchImpl = vi.fn(async (input: unknown, init?: RequestInit) => {
      void init
      const url = String(input)
      if (url.includes('/ports/great-circle')) {
        return jsonResponse({ data: { distance_nm: distanceNm } })
      }
      if (url.includes('/ports/samples')) return jsonResponse({ data: PORTS })
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    return fetchImpl
  }

  async function pickBothPorts() {
    await screen.findByDisplayValue('2026')
    await waitFor(() => expect(document.querySelectorAll('#sc-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText(/현재 위치/), { target: { value: '부산' } })
    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'SINGAPORE' } })
  }

  const distanceInput = () => screen.getByLabelText(/직항 거리/) as HTMLInputElement
  const estimateButton = () =>
    screen.getByRole('button', { name: /추정 거리 넣기|추정하는 중/ }) as HTMLButtonElement

  it('직항 거리는 처음에 비어 있다 — 고른 적 없는 1000nm으로 계산하지 않는다', async () => {
    stubWithGreatCircle()
    renderScreen()
    await screen.findByDisplayValue('2026')

    expect(distanceInput().value).toBe('')
  })

  it('좌표가 없으면 버튼이 잠기고 그 사유를 적는다 (§14)', async () => {
    stubWithGreatCircle()
    renderScreen()
    await screen.findByDisplayValue('2026')

    expect(estimateButton().disabled).toBe(true)
    expect(screen.getByText(/좌표가 모두 있어야 추정할 수 있습니다/)).toBeTruthy()
  })

  it('두 항을 고르고 누르면 거리가 칸에 들어오고, 추정이라는 것과 왜 짧을 수 있는지를 적는다', async () => {
    const fetchImpl = stubWithGreatCircle()
    renderScreen()
    await pickBothPorts()

    await waitFor(() => expect(estimateButton().disabled).toBe(false))
    fireEvent.click(estimateButton())

    await waitFor(() => expect(distanceInput().value).toBe('2504.62'))
    expect(screen.getByText(/좌표 기반 추정 거리/)).toBeTruthy()
    expect(screen.getByText(/실제 항로보다 짧을 수 있습니다/)).toBeTruthy()

    // 화면에서 계산하지 않는다 — 서버가 쓰는 값과 갈리면 안 된다.
    const call = fetchImpl.mock.calls.find(([url]) => String(url).includes('/ports/great-circle'))!
    expect(String(call[0])).toContain('from_lat=35.1')
    expect(String(call[0])).toContain('to_lon=103.85')
  })

  it('항을 바꾸면 추정으로 채운 거리가 남지 않는다 (#1256)', async () => {
    stubWithGreatCircle()
    renderScreen()
    await pickBothPorts()
    await waitFor(() => expect(estimateButton().disabled).toBe(false))
    fireEvent.click(estimateButton())
    await waitFor(() => expect(distanceInput().value).toBe('2504.62'))

    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'TOKYO' } })

    expect(distanceInput().value).toBe('')
    expect(screen.queryByText(/좌표 기반 추정 거리 —/)).toBeNull()
  })

  it('손으로 넣은 거리는 항을 바꿔도 남는다 — 사용자가 넣은 값이다', async () => {
    stubWithGreatCircle()
    renderScreen()
    await pickBothPorts()
    fireEvent.change(distanceInput(), { target: { value: '2600' } })

    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'TOKYO' } })

    expect(distanceInput().value).toBe('2600')
  })

  it('추정한 값을 손으로 고치면 추정 표시가 사라진다', async () => {
    stubWithGreatCircle()
    renderScreen()
    await pickBothPorts()
    await waitFor(() => expect(estimateButton().disabled).toBe(false))
    fireEvent.click(estimateButton())
    await waitFor(() => expect(distanceInput().value).toBe('2504.62'))

    fireEvent.change(distanceInput(), { target: { value: '3100' } })

    expect(screen.queryByText(/좌표 기반 추정 거리 —/)).toBeNull()
  })

  it.each([
    ['현재 위도', /현재 위도/, '40.0'],
    ['현재 경도', /현재 경도/, '130.5'],
  ])(
    '%s를 손으로 고치면 추정으로 채운 거리와 그 고지가 남지 않는다 (#1777)',
    async (_name, label, value) => {
      stubWithGreatCircle()
      renderScreen()
      await pickBothPorts()
      await waitFor(() => expect(estimateButton().disabled).toBe(false))
      fireEvent.click(estimateButton())
      await waitFor(() => expect(distanceInput().value).toBe('2504.62'))

      fireEvent.change(screen.getByLabelText(label), { target: { value } })

      expect(distanceInput().value).toBe('')
      expect(screen.queryByText(/좌표 기반 추정 거리 —/)).toBeNull()
    },
  )

  it('손으로 넣은 거리는 좌표를 고쳐도 남는다 (#1777 · #1750의 종전 동작)', async () => {
    stubWithGreatCircle()
    renderScreen()
    await pickBothPorts()
    fireEvent.change(distanceInput(), { target: { value: '2600' } })

    fireEvent.change(screen.getByLabelText(/현재 위도/), { target: { value: '40.0' } })

    expect(distanceInput().value).toBe('2600')
  })

  it('요청 중에 항을 바꾸면 늦게 온 추정 거리를 버린다 (#1778 → #1777)', async () => {
    // 응답을 손으로 풀 수 있게 붙잡아 둔다 — 「누름 → 항 변경 → 응답 도착」 순서를 만든다.
    let release: (nm: number) => void = () => {}
    const fetchImpl = stubWithGreatCircle()
    const base = fetchImpl.getMockImplementation()!
    fetchImpl.mockImplementation(async (input: unknown, init?: RequestInit) => {
      if (String(input).includes('/ports/great-circle')) {
        const nm = await new Promise<number>((resolve) => {
          release = resolve
        })
        return jsonResponse({ data: { distance_nm: nm } })
      }
      return base(input, init)
    })
    renderScreen()
    await pickBothPorts()
    await waitFor(() => expect(estimateButton().disabled).toBe(false))
    fireEvent.click(estimateButton())
    await waitFor(() =>
      expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/ports/great-circle'))).toBe(
        true,
      ),
    )

    fireEvent.change(screen.getByLabelText(/목적항/), { target: { value: 'TOKYO' } })
    release(2504.62)

    // 버튼이 풀릴 때까지 기다린다 — 응답 처리가 끝났다는 뜻이다.
    await waitFor(() => expect(screen.queryByRole('button', { name: /추정하는 중/ })).toBeNull())
    expect(distanceInput().value).toBe('')
    expect(screen.queryByText(/좌표 기반 추정 거리 —/)).toBeNull()
  })

  it('응답이 계약과 다르면 거리를 넣지 않고 그 사실을 말한다', async () => {
    stubWithGreatCircle('2504.62')
    renderScreen()
    await pickBothPorts()
    await waitFor(() => expect(estimateButton().disabled).toBe(false))
    fireEvent.click(estimateButton())

    expect(await screen.findByText(/추정 거리 응답이 계약과 다릅니다/)).toBeTruthy()
    expect(distanceInput().value).toBe('')
  })

  it('현재 위치도 목록 밖이면 좌표를 찾을 수 있다 — 종전에는 목적항에만 있었다 (#768)', async () => {
    const fetchImpl = vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/ports/lookup')) {
        return jsonResponse({ data: { name: 'ULSAN', lat: 35.5, lon: 129.4, source: 'LOOKUP' } })
      }
      if (url.includes('/ports/samples')) return jsonResponse({ data: PORTS })
      if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      return jsonResponse({ data: {} })
    })
    vi.stubGlobal('fetch', fetchImpl)
    renderScreen()
    await screen.findByDisplayValue('2026')

    fireEvent.change(screen.getByLabelText(/현재 위치/), { target: { value: '울산항' } })
    const buttons = screen.getAllByRole('button', { name: '좌표 찾기' })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])

    await waitFor(() =>
      expect((screen.getByLabelText(/현재 위도/) as HTMLInputElement).value).toBe('35.5'),
    )
    expect(screen.getByText(/지도 서비스\(OpenStreetMap\)에서 찾은 좌표입니다/)).toBeTruthy()
  })
})
