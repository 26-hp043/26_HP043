// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VoyagePanel } from './VoyagePanel'
import type { VoyageManagementProvider } from './apiProvider'
import type { ActualsDraft, ManagedVoyage, VoyageDraft } from './types'

/**
 * 항차 시각 4종의 **입력 칸이 실제로 화면에 있는가** (#873).
 *
 * ## 왜 렌더 검사여야 하는가
 *
 * 이 결함은 「값이 틀렸다」가 아니라 **「칸이 없다」**였다. 규칙 함수와 provider를
 * 아무리 검사해도, 폼이 그 값을 만들어 주지 않으면 아무 일도 일어나지 않는다 —
 * `#823`(에러 경계)·`#755`(폴링 클로저)·`#872`(포매터 다리)가 각각 같은 함정을
 * 겪었고, 그 셋 모두 순수 함수 검사만으로는 드러나지 않았다.
 *
 * 종전 상태: `grep`으로 프론트 전체를 훑어 `departure_at`·`arrival_at` 참조가
 * **0건**이었다. 서버는 `§3.3`·`§3.6`에서 처음부터 받고 있었다.
 */

const IN_PROGRESS: ManagedVoyage = {
  id: 'v-1',
  voyageNo: '2026-01',
  status: 'IN_PROGRESS',
  inclusionPolicy: 'INCLUDE_AS_PLAN',
  regulationYear: 2026,
  departurePortName: 'Busan',
  arrivalPortName: 'Singapore',
  plannedDistanceNm: 2300,
  plannedSpeedKn: 14,
  actualDistanceNm: null,
  actualAvgSpeedKn: null,
  plannedDepartureAt: '2026-06-01T00:00:00+00:00',
  plannedArrivalAt: null,
  actualDepartureAt: null,
  actualArrivalAt: null,
  fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331, actualFuelTon: null }],
}

function stubProvider(over: Partial<VoyageManagementProvider> = {}): VoyageManagementProvider {
  return {
    list: vi.fn(async () => ({
      voyages: [IN_PROGRESS],
      fuelTypes: ['HFO', 'MDO'],
      nextCursor: null,
      hasMore: false,
    })),
    create: vi.fn(async () => IN_PROGRESS),
    transition: vi.fn(async () => IN_PROGRESS),
    saveActuals: vi.fn(async () => IN_PROGRESS),
    importCsv: vi.fn(async () => ({
      importedCount: 0,
      skippedCount: 0,
      errors: [],
      dryRun: true,
      missingDepartureCount: 0,
    })),
    exportData: vi.fn(async () => 'voyages.csv'),
    samplePorts: vi.fn(async () => []),
    greatCircle: vi.fn(async () => 0),
    ...over,
  }
}

/*
 * 연도 선택지는 **provider가 아니라 서버**에서 온다 (`#632`가 세 화면에 세운 규칙 —
 * `parameters/yearCatalog`). `VoyagePanel`이 쓰는 유일한 직접 fetch라, 스텁하지 않으면
 * `#890` 내보내기 구획의 연도 칸이 「불러오지 못했습니다」 갈래로 떨어진다.
 */
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = String(input)
      if (url.includes('/parameters/regulation-years')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ data: [{ year: 2026 }, { year: 2027 }] }),
        } as Response
      }
      return { ok: true, status: 200, json: async () => ({ data: {} }) } as Response
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('생성 폼에 계획 시각 두 칸이 있다 (#873)', () => {
  it('「항차 추가」를 열면 출항·도착 시각 칸이 그려진다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))

    const departure = await screen.findByLabelText('계획 출항 시각')
    const arrival = screen.getByLabelText('계획 도착 시각')
    // 달력 UI를 쓴다 — 시각은 사용자가 형식을 가장 틀리기 쉬운 칸이다.
    expect(departure.getAttribute('type')).toBe('datetime-local')
    expect(arrival.getAttribute('type')).toBe('datetime-local')
  })

  it('비워 두면 어떻게 되는지 화면이 말한다 — 규칙을 바꾸지 않고 결과를 알린다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))

    expect(await screen.findByText(/진행 중 누적에 0으로 기여합니다/)).toBeTruthy()
  })

  it('입력한 시각이 provider까지 도달한다 — 폼과 전송이 이어져 있다', async () => {
    const create = vi.fn(async (_vesselId: string, _draft: VoyageDraft) => IN_PROGRESS)
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider({ create })} />)
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))

    fireEvent.change(screen.getByLabelText('항차 번호'), { target: { value: '2026-09' } })
    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'Singapore' } })
    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '2300' } })
    fireEvent.change(screen.getByLabelText(/계획 속력/), { target: { value: '14' } })
    fireEvent.change(screen.getByLabelText(/계획 연료 1/), { target: { value: '331' } })
    fireEvent.change(screen.getByLabelText('계획 출항 시각'), {
      target: { value: '2026-06-01T09:00' },
    })

    fireEvent.click(screen.getByRole('button', { name: '항차 만들기' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    const draft = create.mock.calls[0][1]
    expect(draft.plannedDepartureAt).toBe('2026-06-01T09:00')
  })
})

describe('실적 폼에 실제 시각 두 칸이 있다 (#873)', () => {
  it('「실적 입력」을 열면 출항·도착 시각 칸이 그려진다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    fireEvent.click(await screen.findByRole('button', { name: '실적 입력' }))

    expect((await screen.findByLabelText('실제 출항 시각')).getAttribute('type')).toBe(
      'datetime-local',
    )
    expect(screen.getByLabelText('실제 도착 시각').getAttribute('type')).toBe('datetime-local')
  })

  it('입력한 시각이 provider까지 도달한다', async () => {
    const saveActuals = vi.fn(async (_id: string, _draft: ActualsDraft) => IN_PROGRESS)
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider({ saveActuals })} />)
    fireEvent.click(await screen.findByRole('button', { name: '실적 입력' }))

    fireEvent.change(await screen.findByLabelText('실제 출항 시각'), {
      target: { value: '2026-06-02T08:30' },
    })
    fireEvent.click(screen.getByRole('button', { name: '실적 저장' }))

    await waitFor(() => expect(saveActuals).toHaveBeenCalled())
    expect(saveActuals.mock.calls[0][1].actualDepartureAt).toBe('2026-06-02T08:30')
  })
})

/**
 * 운항 기록 내보내기가 **화면에서 도달 가능한가** (#890).
 *
 * `PRD §5.1`이 MUST로 규정하고 서버·검사가 완비돼 있는데 **호출부가 0건**이었다.
 *
 * ```
 * $ grep -rn "/export" frontend/src --include=*.ts --include=*.tsx | grep -v test | wc -l
 * 0
 * ```
 *
 * ⚠️ 이 결함은 「값이 틀렸다」가 아니라 **「버튼이 없다」**였다. 규칙 함수와 provider를
 * 아무리 검사해도 화면이 그것을 부르지 않으면 기능은 없는 것이다 — `#873`이 같은
 * 종류였다.
 *
 * 자리는 **가져오기 옆**이다. `PRD:636`이 `SCR-007`을 「Data Import/Export」 한 항목으로
 * 규정하므로 두 방향이 갈리면 정본이 한 화면으로 정한 것이 쪼개진다.
 */
describe('자료 내보내기가 항차 패널에 있다 (#890)', () => {
  it('가져오기와 같은 구획에 내보내기가 그려진다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)

    const exportSection = await screen.findByRole('region', { name: '자료 내보내기' })
    expect(exportSection).toBeTruthy()
    // 두 방향이 같은 패널 안에 있다 — `SCR-007`은 한 항목이다.
    expect(screen.getByRole('region', { name: 'CSV 가져오기' })).toBeTruthy()
  })

  it('종류·연도·형식을 고를 수 있다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    await screen.findByRole('region', { name: '자료 내보내기' })

    expect((screen.getByLabelText('종류') as HTMLSelectElement).value).toBe('voyages')
    expect((screen.getByLabelText('형식') as HTMLSelectElement).value).toBe('csv')
    // 연도는 「전체」가 기본이다 — `§8.1`의 `year`는 optional이다.
    expect((await screen.findByLabelText('연도')).tagName).toBe('SELECT')
  })

  it('고른 조건이 provider까지 도달한다 — 폼과 요청이 이어져 있다', async () => {
    const exportData = vi.fn(async () => 'calculations.csv')
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider({ exportData })} />)
    await screen.findByRole('region', { name: '자료 내보내기' })

    fireEvent.change(screen.getByLabelText('종류'), { target: { value: 'calculations' } })
    fireEvent.change(screen.getByLabelText('형식'), { target: { value: 'json' } })
    fireEvent.click(screen.getByRole('button', { name: '내보내기' }))

    await waitFor(() => expect(exportData).toHaveBeenCalled())
    const [vesselId, query] = exportData.mock.calls[0] as unknown as [string, string]
    expect(vesselId).toBe('ves-1')
    expect(query).toContain('type=calculations')
    expect(query).toContain('format=json')
    // 「전체」이므로 연도 키가 없다.
    expect(query).not.toContain('year')
  })

  it('저장한 파일 이름을 화면이 말한다 — 무엇을 받았는지 알 수 있어야 한다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    await screen.findByRole('region', { name: '자료 내보내기' })

    fireEvent.click(screen.getByRole('button', { name: '내보내기' }))

    expect(await screen.findByText(/voyages\.csv/)).toBeTruthy()
  })

  it('실패하면 서버 문구를 보여 준다 — 조용히 아무 일도 안 일어나지 않는다', async () => {
    const exportData = vi.fn(async () => {
      throw new Error('내보낼 자료가 없습니다.')
    })
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider({ exportData })} />)
    await screen.findByRole('region', { name: '자료 내보내기' })

    fireEvent.click(screen.getByRole('button', { name: '내보내기' }))

    expect(await screen.findByText('내보낼 자료가 없습니다.')).toBeTruthy()
  })
})

/**
 * 저장 실패에 입력이 사라지지 않는다 (#824 ⑸).
 *
 * 종전에는 `await run(...)` 뒤에 **무조건** 폼을 닫았다. `run()`이 오류를 잡아
 * 표시하고 끝이라 호출부가 성공·실패를 가릴 수 없었고, `ActualsForm`이 `useState`로
 * 초안을 들고 있어 **언마운트와 함께 실제 거리·평균 속력·연료별 실적이 전부
 * 소실**됐다.
 *
 * ⚠️ **바로 옆 `VoyageForm`(항차 생성)은 정반대로 처리한다** — 자체 `try/catch`로
 * 폼을 열어 둔다. **두 폼의 규율이 갈려 있었다.**
 */
describe('실적 저장이 실패해도 폼이 닫히지 않는다 (#824 ⑸)', () => {
  it('실패하면 폼이 남고 입력값도 남는다', async () => {
    const saveActuals = vi.fn(async () => {
      throw new Error('실적을 저장하지 못했습니다.')
    })
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider({ saveActuals })} />)
    fireEvent.click(await screen.findByRole('button', { name: '실적 입력' }))

    const distance = await screen.findByLabelText(/실제 거리/)
    fireEvent.change(distance, { target: { value: '4321' } })
    fireEvent.click(screen.getByRole('button', { name: '실적 저장' }))

    await waitFor(() => expect(saveActuals).toHaveBeenCalled())

    // 폼이 살아 있고
    expect(await screen.findByLabelText(/실제 거리/)).toBeTruthy()
    // 넣은 값도 그대로다 — 이것이 사라지던 것이 결함이다.
    expect((screen.getByLabelText(/실제 거리/) as HTMLInputElement).value).toBe('4321')
    // 사유도 보인다.
    expect(await screen.findByText('실적을 저장하지 못했습니다.')).toBeTruthy()
  })

  it('성공하면 종전대로 닫힌다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    fireEvent.click(await screen.findByRole('button', { name: '실적 입력' }))
    fireEvent.change(await screen.findByLabelText(/실제 거리/), { target: { value: '4321' } })
    fireEvent.click(screen.getByRole('button', { name: '실적 저장' }))

    await waitFor(() => expect(screen.queryByLabelText(/실제 거리/)).toBeNull())
  })
})

/**
 * 연료가 선택돼 보이면 그 값으로 저장된다 (#824 ⑹).
 *
 * `draft.fuelUses`는 `useState` 초기화 때 `fuelTypes[0] ?? ''`로 굳는데 `fuelTypes`는
 * 비동기로 채워진다. 목록이 오기 전에 「항차 추가」를 누르면 `fuelType: ''`로 **굳고
 * 이후에도 재동기되지 않는다.** `<option value="">`가 없으므로 브라우저는
 * `selectedIndex=0`, 즉 **첫 연료가 선택된 것처럼 그린다** — 사용자는 고른 것으로 보고
 * 저장을 누르는데 「연료 종류를 선택해 주세요.」가 뜬다.
 */
describe('연료가 선택돼 보이면 그대로 저장된다 (#824 ⑹)', () => {
  it('연료 목록이 늦게 와도 화면이 그리는 값으로 저장된다', async () => {
    /*
     * **폼이 열린 뒤에 목록이 도착해야** 결함이 재현된다.
     *
     * `VoyageForm`의 `useState` 초기화가 `fuelTypes[0] ?? ''`를 읽는데, 그 시점에
     * 목록이 비어 있으면 `''`로 **굳고 이후 도착해도 재동기되지 않는다.** 스텁이
     * 즉시 응답하면 이 조건이 만들어지지 않아, 첫 검사 판본은 돌연변이 검사에서
     * 통과해 버렸다.
     */
    let release: ((rows: { voyages: ManagedVoyage[]; fuelTypes: string[]; nextCursor: null; hasMore: false }) => void) | null =
      null
    const create = vi.fn(async (_vesselId: string, _draft: VoyageDraft) => IN_PROGRESS)
    const provider = stubProvider({
      create,
      list: vi.fn(
        async () =>
          new Promise<{
            voyages: ManagedVoyage[]
            fuelTypes: string[]
            nextCursor: null
            hasMore: false
          }>((resolve) => {
            release = resolve
          }),
      ),
    })
    render(<VoyagePanel vesselId="ves-1" provider={provider} />)

    // 목록이 오기 전에 연다 — 이때 초안의 연료가 빈 문자열로 굳는다.
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))

    await act(async () => {
      release?.({ voyages: [IN_PROGRESS], fuelTypes: ['HFO', 'MDO'], nextCursor: null, hasMore: false })
    })

    // 셀렉트가 그리고 있는 값 = 첫 연료. 상태는 비어 있어도 화면은 이렇게 보인다.
    const fuel = (await screen.findByLabelText(/연료 종류 1/)) as HTMLSelectElement
    expect(fuel.value).toBe('HFO')

    fireEvent.change(screen.getByLabelText('항차 번호'), { target: { value: '2026-09' } })
    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'Singapore' } })
    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '2300' } })
    fireEvent.change(screen.getByLabelText(/계획 속력/), { target: { value: '14' } })
    fireEvent.change(screen.getByLabelText(/계획 연료 1/), { target: { value: '331' } })

    fireEvent.click(screen.getByRole('button', { name: '항차 만들기' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    // 화면이 보인 값과 보낸 값이 같다 — 갈리면 「선택해 주세요」로 거부된다.
    expect(create.mock.calls[0][1].fuelUses[0].fuelType).toBe('HFO')
  })
})

/**
 * 출발·도착항 — 샘플 항만에서 고르면 좌표가 따라오고, 추정 거리로 채울 수 있다 (#760).
 *
 * `PRD §15.1` 「샘플 항만 테이블」 MUST. 종전에는 항만명이 자유 텍스트뿐이라 좌표를 사람이
 * 직접 찾아 넣어야 했다.
 */
describe('샘플 항만 선택 (#760)', () => {
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  async function openForm(over: Partial<VoyageManagementProvider> = {}) {
    const create = vi.fn(async (_vesselId: string, _draft: VoyageDraft) => IN_PROGRESS)
    const greatCircle = vi.fn(async () => 2470.2)
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({ create, greatCircle, samplePorts: vi.fn(async () => PORTS), ...over })}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))
    return { create, greatCircle }
  }

  it('고른 두 항의 좌표로 추정 거리를 채우고, 그 값이 추정값임을 표시한다', async () => {
    const { create, greatCircle } = await openForm()
    // 목록이 오기 전에는 좌표를 붙일 수 없다 — 선택지가 그려진 뒤에 고른다.
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: '부산' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'singapore' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))

    await waitFor(() =>
      expect((screen.getByLabelText(/계획 거리/) as HTMLInputElement).value).toBe('2470.20'),
    )
    expect(greatCircle).toHaveBeenCalledWith({ lat: 35.1, lon: 129.0333 }, { lat: 1.2833, lon: 103.85 })
    expect(screen.getByText(/좌표 기반 추정 거리 — /)).toBeTruthy()
    // 고른 항은 저장 이름(대문자 영문)으로 바뀐다 — 데모 시드와 같은 표기로 쌓인다.
    expect((screen.getByLabelText('출발항') as HTMLInputElement).value).toBe('BUSAN')

    fireEvent.change(screen.getByLabelText('항차 번호'), { target: { value: '2026-10' } })
    fireEvent.change(screen.getByLabelText(/계획 속력/), { target: { value: '14' } })
    fireEvent.change(screen.getByLabelText(/계획 연료 1/), { target: { value: '331' } })
    fireEvent.click(screen.getByRole('button', { name: '항차 만들기' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    const draft = create.mock.calls[0][1]
    expect(draft.departureCoord).toEqual({ lat: 35.1, lon: 129.0333 })
    expect(draft.arrivalCoord).toEqual({ lat: 1.2833, lon: 103.85 })
  })

  it('거리를 고치면 추정값 표시를 내린다 — 사용자가 넣은 값은 추정이 아니다', async () => {
    await openForm()
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'BUSAN' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'SINGAPORE' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))
    await screen.findByText(/좌표 기반 추정 거리 — /)

    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '2600' } })

    expect(screen.queryByText(/좌표 기반 추정 거리 — /)).toBeNull()
  })

  it('목록에 없는 항은 자유 입력이다 — 좌표가 없고 추정 버튼도 없다', async () => {
    await openForm()
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan New Port' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'SINGAPORE' } })

    expect((screen.getByLabelText('출발항') as HTMLInputElement).value).toBe('Busan New Port')
    expect(screen.queryByRole('button', { name: '좌표 기반 추정 거리로 채우기' })).toBeNull()
  })

  it('목록을 못 받아도 폼은 그대로 쓴다 — 목록은 편의다', async () => {
    await openForm({ samplePorts: vi.fn(async () => Promise.reject(new Error('down'))) })

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan' } })

    expect((screen.getByLabelText('출발항') as HTMLInputElement).value).toBe('Busan')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

