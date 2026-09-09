// @vitest-environment jsdom
import '../../test/renderSetup'

import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { ScenarioComparison } from './ScenarioComparison'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'

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
  const fetchImpl = vi.fn(async (input: unknown) => {
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

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('규제연도 — 자유 입력이 아니라 서버 목록이다 (#632)', () => {
  it('셀렉트를 그리고 서버가 준 해로 채운다', async () => {
    stubServer()

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    expect(select.tagName).toBe('SELECT')
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '2026',
      '2027',
      '2030',
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
  const fetchImpl = vi.fn(async (input: unknown) => {
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

async function compareAndWaitForResult() {
  const button = await screen.findByRole('button', { name: /비교하기/ })
  fireEvent.click(button)
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
    expect(screen.getByText(/참고용 예측값입니다\. 규제 제출용이 아닙니다/)).toBeTruthy()
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

  it('목록에 없는 선박이면 구분점만 남기지 않는다', async () => {
    stubServerWithComparison()
    /*
     * 선박이 선택돼 있는데 **그 배가 목록에 없는** 경우(삭제·권한 변경 직후).
     * 종전에는 이름이 빈 문자열이라 제목이 `` · 2026년 기준``으로 시작해
     * **레이아웃이 깨진 것처럼 보였다.** 지금은 이름 칸을 통째로 뺀다.
     *
     * 목록을 비우지 않고 **다른 배 하나**를 넣는다 — 목록이 완전히 비면 화면이
     * 「등록된 선박이 없습니다」 갈래로 가 폼 제출 자체가 막힌다.
     */
    renderScreen({
      vesselId: '00000000-0000-4000-8000-000000000001',
      vessels: [
        {
          id: '00000000-0000-4000-8000-00000000ffff',
          displayName: '다른 배',
          shipType: 'BULK_CARRIER',
        },
      ],
    })
    await compareAndWaitForResult()

    const context = await screen.findByText(/2026년 기준/)
    expect(context.textContent?.trimStart().startsWith('·')).toBe(false)
    expect(context.textContent).not.toContain('다른 배')
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

    fireEvent.click(screen.getByRole('button', { name: /비교하기/ }))

    await waitFor(() =>
      expect(screen.getByText(/2026년 기준/).textContent).toContain('두 번째 배'),
    )
    expect(screen.queryByText(/입력이 바뀌었습니다/)).toBeNull()
  })
})
