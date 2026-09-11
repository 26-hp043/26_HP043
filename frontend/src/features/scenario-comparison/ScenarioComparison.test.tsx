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
    fireEvent.click(screen.getByRole('button', { name: '비교하기' }))

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
    fireEvent.click(screen.getByRole('button', { name: '비교하기' }))

    expect(await screen.findByText(/감속 속력은\(는\) 1 이상이어야 합니다\./)).toBeTruthy()
    expect(
      fetchImpl.mock.calls.some(([url]) => String(url).includes('/scenarios/compare')),
    ).toBe(false)
  })

  it('좌표를 한쪽만 넣으면 요청을 보내지 않는다 (API_SPEC:572)', async () => {
    const fetchImpl = stubServer()
    renderScreen()
    await screen.findByDisplayValue('2026')

    fireEvent.change(screen.getByLabelText(/현재 위도/), { target: { value: '35.1' } })
    fireEvent.click(screen.getByRole('button', { name: '비교하기' }))

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
                // 서버가 수를 보내도 화면은 쓰지 않는다 — `#817` 전에는 참값이 아니다.
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
    expect(screen.getByText(/기존 계산 결과는 다시 계산해야 합니다/)).toBeTruthy()
    const link = screen.getByRole('link', { name: '반영한 항차 보기' })
    expect(link.getAttribute('href')).toBe(`/vessels/${VESSEL}/voyages/v-planned`)

    const [, init] = fetchImpl.mock.calls.find(([url]) => String(url).includes('/adopt')) ?? []
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      target_voyage_id: 'v-planned',
      adopt_mode: 'UPDATE_EXISTING_PLAN',
    })
    // 서버가 보낸 재계산 건수(7)를 화면에 내지 않는다 — `#817` 전에는 참값이 아니다.
    expect(screen.queryByText(/7건/)).toBeNull()
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
})
