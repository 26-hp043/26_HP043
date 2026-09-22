// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { VoyagePanel } from './VoyagePanel'
import type { VoyageManagementProvider } from './apiProvider'
import type { ActualsDraft, DistanceSource, ManagedVoyage, VoyageDraft } from './types'
import { ESTIMATED_DISTANCE_HINT } from '../ports/samplePorts'

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
  plannedDistanceSource: null,
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

  it('추정을 기다리는 동안 항을 바꾸면 늦게 온 거리를 쓰지 않는다 (#1657)', async () => {
    let release: (value: number) => void = () => {}
    const greatCircle = vi.fn(
      () =>
        new Promise<number>((resolve) => {
          release = resolve
        }),
    )
    await openForm({ greatCircle })
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: '부산' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'singapore' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))

    // 응답이 오기 전에 도착항을 바꾼다 — 이 순간부터 앞 요청의 거리는 이 항로의 값이 아니다.
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: '부산' } })
    release(2470.2)

    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: /좌표 기반 추정 거리로 채우기/ }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )
    expect((screen.getByLabelText(/계획 거리/) as HTMLInputElement).value).toBe('')
    expect(screen.queryByText(/좌표 기반 추정 거리 — /)).toBeNull()
  })

  it('추정을 기다리는 동안 직접 입력한 거리를 덮어쓰지 않는다 (#1657)', async () => {
    let release: (value: number) => void = () => {}
    const greatCircle = vi.fn(
      () =>
        new Promise<number>((resolve) => {
          release = resolve
        }),
    )
    await openForm({ greatCircle })
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: '부산' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'singapore' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))

    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '999' } })
    release(2470.2)

    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: /좌표 기반 추정 거리로 채우기/ }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )
    // 직접 입력이 자동 추정보다 앞선다 — 값도 출처 표시도 그대로다.
    expect((screen.getByLabelText(/계획 거리/) as HTMLInputElement).value).toBe('999')
    expect(screen.queryByText(/좌표 기반 추정 거리 — /)).toBeNull()
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

  it('추정 뒤 항을 바꾸면 추정 거리를 비운다 — 옛 항로의 거리가 추정값으로 저장되지 않게 (#1256)', async () => {
    await openForm()
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'BUSAN' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'SINGAPORE' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))
    await screen.findByText(/좌표 기반 추정 거리 — /)

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan New Port' } })

    expect((screen.getByLabelText(/계획 거리/) as HTMLInputElement).value).toBe('')
    expect(screen.queryByText(/좌표 기반 추정 거리 — /)).toBeNull()
  })

  it('추정하지 않은 거리는 항을 바꿔도 그대로다 — 사용자가 넣은 값이다', async () => {
    await openForm()
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '2600' } })

    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'BUSAN' } })

    expect((screen.getByLabelText(/계획 거리/) as HTMLInputElement).value).toBe('2600')
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


/**
 * 계획 거리의 출처가 저장까지 간다 (#1256 · `PRD §15.2`).
 *
 * `estimated`는 폼의 임시 상태였고 저장하면 사라졌다 — 저장된 항차에는 「좌표 기반 추정 거리」
 * 표시가 붙을 수 없었다(#1052 ⓷). 이제 폼이 출처를 싣고, 목록은 서버가 돌려준 출처가
 * `COORDINATE_ESTIMATE`일 때만 같은 문구를 붙인다. **`null`(「모른다」)에는 붙이지 않는다** —
 * 직접 입력한 값에 「추정」이 붙는 것이 `PRD §0.3`이 금하는 거짓말이다.
 */
describe('계획 거리의 출처 (#1256)', () => {
  const withSource = (source: DistanceSource | null): ManagedVoyage => ({
    ...IN_PROGRESS,
    plannedDistanceSource: source,
  })
  const PORTS = [
    { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
    { locode: 'SGKEP', name: 'SINGAPORE', name_ko: '싱가포르', country_code: 'SG', lat: 1.2833, lon: 103.85 },
  ]

  async function openEstimatedForm() {
    const create = vi.fn(async (_vesselId: string, _draft: VoyageDraft) => IN_PROGRESS)
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({
          create,
          greatCircle: vi.fn(async () => 2470.2),
          samplePorts: vi.fn(async () => PORTS),
        })}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: '항차 추가' }))
    await waitFor(() => expect(document.querySelectorAll('#vy-ports option')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'BUSAN' } })
    fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'SINGAPORE' } })
    fireEvent.click(await screen.findByRole('button', { name: '좌표 기반 추정 거리로 채우기' }))
    await screen.findByText(/좌표 기반 추정 거리 — /)
    fireEvent.change(screen.getByLabelText('항차 번호'), { target: { value: '2026-10' } })
    fireEvent.change(screen.getByLabelText(/계획 속력/), { target: { value: '14' } })
    fireEvent.change(screen.getByLabelText(/계획 연료 1/), { target: { value: '331' } })
    return create
  }

  it('좌표로 채운 거리를 그대로 저장하면 COORDINATE_ESTIMATE를 보낸다', async () => {
    const create = await openEstimatedForm()

    fireEvent.click(screen.getByRole('button', { name: '항차 만들기' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][1].plannedDistanceSource).toBe('COORDINATE_ESTIMATE')
  })

  it('채운 거리를 고쳐서 저장하면 USER_INPUT을 보낸다 — 사용자가 넣은 값은 추정이 아니다', async () => {
    const create = await openEstimatedForm()
    fireEvent.change(screen.getByLabelText(/계획 거리/), { target: { value: '2600' } })

    fireEvent.click(screen.getByRole('button', { name: '항차 만들기' }))

    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][1].plannedDistanceSource).toBe('USER_INPUT')
  })

  it('저장된 항차의 출처가 COORDINATE_ESTIMATE면 목록에 같은 문구가 붙는다', async () => {
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({
          list: vi.fn(async () => ({
            voyages: [withSource('COORDINATE_ESTIMATE')],
            fuelTypes: ['HFO'],
            nextCursor: null,
            hasMore: false,
          })),
        })}
      />,
    )

    expect(await screen.findByText(/좌표 기반 추정 거리 — /)).toBeTruthy()
  })

  /**
   * 목록의 안내는 그 자리에서 따를 수 있는 말이어야 한다 (#1354).
   *
   * 목록에는 계획 거리를 고치는 경로가 없다. 문구 자체가 아니라 **성질**을 본다(`AGENTS §4.6`) —
   * 입력 칸 문구와 달라야 하고, 고치라는 요청이 없어야 하며, 정본 표기로 시작해야 한다.
   */
  it('목록의 안내는 고치라고 하지 않는다 — 목록에는 고칠 경로가 없다', async () => {
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({
          list: vi.fn(async () => ({
            voyages: [withSource('COORDINATE_ESTIMATE')],
            fuelTypes: ['HFO'],
            nextCursor: null,
            hasMore: false,
          })),
        })}
      />,
    )

    const note = (await screen.findByText(/좌표 기반 추정 거리 — /)).textContent ?? ''
    expect(note).not.toBe(ESTIMATED_DISTANCE_HINT)
    expect(note).not.toMatch(/고쳐|수정해|입력해/)
    expect(note.startsWith('좌표 기반 추정 거리')).toBe(true)
  })

  it.each([null, 'USER_INPUT'] as const)(
    '출처가 %s이면 아무것도 붙이지 않는다 — 모르는 것과 직접 입력에 「추정」을 달지 않는다',
    async (source) => {
      render(
        <VoyagePanel
          vesselId="ves-1"
          provider={stubProvider({
            list: vi.fn(async () => ({
              voyages: [withSource(source)],
              fuelTypes: ['HFO'],
              nextCursor: null,
              hasMore: false,
            })),
          })}
        />,
      )

      await screen.findByText('2026-01')
      expect(screen.queryByText(/좌표 기반 추정 거리 — /)).toBeNull()
    },
  )
})

/**
 * CSV 형식 안내는 접혀 있고 열면 그대로 보인다 (#1415).
 *
 * 필수 7 · 선택 2 · 제한 조건이 본문에 늘 펼쳐져 있었다. `<details>`로 접되 **내용은 바꾸지
 * 않는다** — 필수 컬럼은 `REQUIRED_COLUMNS`에서 그대로 읽고(`importRules.test.ts`가 값을
 * 지킨다), 선택 컬럼 안내(#906)도 남는다.
 */
describe('CSV 형식 안내 (#1415)', () => {
  it('형식 안내가 「형식 보기」 안에 접혀 있다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={stubProvider()} />)
    const section = await screen.findByRole('region', { name: 'CSV 가져오기' })

    const summary = within(section).getByText('형식 보기')
    const details = summary.closest('details') as HTMLDetailsElement
    expect(details).not.toBeNull()
    expect(details.open).toBe(false)
    // 필수·선택 안내가 모두 그 안에 있다 — 하나라도 밖에 남으면 접은 의미가 없다.
    expect(within(details).getByText(/필수 컬럼/)).toBeTruthy()
    expect(within(details).getByText(/선택 컬럼/)).toBeTruthy()
  })
})

/**
 * 실시간 CII에서 넘어오면 그 항차의 실적 폼이 열려 있다 (#1540).
 *
 * 실시간 CII의 「이 항차 실적 입력」은 `?actuals=<항차 id>`로 선박 상세에 온다. 받는 쪽이
 * 폼을 열지 않으면 사용자는 항차 목록에서 같은 항차를 다시 찾아 「실적 입력」을 눌러야
 * 한다 — 링크가 한 일이 없다. 실적을 넣을 수 없는 상태(계획)는 열지 않는다.
 */
describe('실적 폼 바로 열기 (#1540)', () => {
  const PLANNED: ManagedVoyage = { ...IN_PROGRESS, id: 'v-2', voyageNo: '2026-02', status: 'PLANNED' }

  function providerWith(voyages: ManagedVoyage[]) {
    return stubProvider({
      list: vi.fn(async () => ({ voyages, fuelTypes: ['HFO', 'MDO'], nextCursor: null, hasMore: false })),
    })
  }

  it('지정한 진행 중 항차의 실적 폼이 열리고 첫 칸에 초점이 간다', async () => {
    render(
      <VoyagePanel vesselId="ves-1" provider={providerWith([IN_PROGRESS, PLANNED])} openActualsFor="v-1" />,
    )
    const save = await screen.findByRole('button', { name: '실적 저장' })
    const row = save.closest('li') as HTMLLIElement
    expect(row.id).toBe('voyage-v-1')
    await waitFor(() => expect(document.activeElement?.closest('li')).toBe(row))
    expect(document.activeElement?.tagName).toBe('INPUT')
  })

  it('지정하지 않으면 열리지 않는다 — 종전 동작', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={providerWith([IN_PROGRESS])} />)
    await screen.findByRole('button', { name: '실적 입력' })
    expect(screen.queryByRole('button', { name: '실적 저장' })).toBeNull()
  })

  it('계획 상태 항차는 지정해도 열지 않는다 — 실적을 넣을 수 없다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={providerWith([PLANNED])} openActualsFor="v-2" />)
    await screen.findByText('2026-02')
    expect(screen.queryByRole('button', { name: '실적 저장' })).toBeNull()
  })
})

/**
 * 입력을 열 수 없는 항차도 카드로는 데려간다 (#1549).
 *
 * 데이터 점검의 대체 계산 · 이상치 행은 **확정 항차**가 많다. `#1540`은 실적을 넣을 수 있는
 * 항차에서만 스크롤·초점을 줘서, 그대로 이으면 도착해도 맨 위에 머물렀다. 그리고 데려갈
 * 항차가 목록에 없으면 조용히 있지 않고 그 사실을 말한다.
 */
describe('항차 카드로 데려가기 (#1549)', () => {
  const CONFIRMED: ManagedVoyage = {
    ...IN_PROGRESS,
    id: 'v-3',
    voyageNo: '2026-03',
    status: 'CONFIRMED',
  }

  function pages(first: ManagedVoyage[], hasMore: boolean, second: ManagedVoyage[] = []) {
    return stubProvider({
      list: vi.fn(async (_vesselId: string, cursor: string | null) =>
        cursor === null
          ? { voyages: first, fuelTypes: ['HFO'], nextCursor: hasMore ? 'c-2' : null, hasMore }
          : { voyages: second, fuelTypes: ['HFO'], nextCursor: null, hasMore: false },
      ),
    })
  }

  it('확정 항차는 입력을 열지 않고 카드에 초점을 둔다', async () => {
    render(
      <VoyagePanel vesselId="ves-1" provider={pages([IN_PROGRESS, CONFIRMED], false)} openActualsFor="v-3" />,
    )
    await screen.findByText('2026-03')
    const row = document.getElementById('voyage-v-3') as HTMLLIElement
    await waitFor(() => expect(document.activeElement).toBe(row))
    expect(row.className).toContain('vy__row--target')
    expect(screen.queryByRole('button', { name: '실적 저장' })).toBeNull()
  })

  it('지정하지 않은 카드는 초점을 받을 수 없고 표시도 없다 — 탭 순서가 그대로다', async () => {
    render(
      <VoyagePanel vesselId="ves-1" provider={pages([IN_PROGRESS, CONFIRMED], false)} openActualsFor="v-3" />,
    )
    await screen.findByText('2026-03')
    const other = document.getElementById('voyage-v-1') as HTMLLIElement
    expect(other.hasAttribute('tabindex')).toBe(false)
    expect(other.className).not.toContain('vy__row--target')
  })

  it('다음 페이지가 있으면 「더 보기」로 부르라고 하고, 불러오면 그 항차로 간다', async () => {
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={pages([IN_PROGRESS], true, [CONFIRMED])}
        openActualsFor="v-3"
      />,
    )
    expect(await screen.findByText(/아직 불러오지 않은 목록에 있을 수 있습니다/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '더 보기' }))
    await screen.findByText('2026-03')
    const row = document.getElementById('voyage-v-3') as HTMLLIElement
    await waitFor(() => expect(document.activeElement).toBe(row))
    expect(screen.queryByText(/아직 불러오지 않은 목록에/)).toBeNull()
  })

  it('다음 페이지도 없으면 기록에 없다고 말한다', async () => {
    render(<VoyagePanel vesselId="ves-1" provider={pages([IN_PROGRESS], false)} openActualsFor="gone" />)
    expect(await screen.findByText(/이 선박의 항차 기록에 없습니다/)).toBeTruthy()
  })

  it('목록을 못 받았으면 오류만 말한다 — 「기록에 없다」를 겹쳐 말하지 않는다', async () => {
    const provider = stubProvider({
      list: vi.fn(async () => {
        throw new Error('항차를 불러오지 못했습니다.')
      }),
    })
    render(<VoyagePanel vesselId="ves-1" provider={provider} openActualsFor="v-3" />)
    expect(await screen.findByText('항차를 불러오지 못했습니다.')).toBeTruthy()
    expect(screen.queryByText(/찾는 항차가/)).toBeNull()
  })

  it('찾았거나 지정하지 않았으면 아무 말도 하지 않는다', async () => {
    const { unmount } = render(
      <VoyagePanel vesselId="ves-1" provider={pages([IN_PROGRESS], true)} openActualsFor="v-1" />,
    )
    await screen.findByText('2026-01')
    expect(screen.queryByText(/찾는 항차가/)).toBeNull()
    unmount()

    render(<VoyagePanel vesselId="ves-1" provider={pages([IN_PROGRESS], true)} />)
    await screen.findByText('2026-01')
    expect(screen.queryByText(/찾는 항차가/)).toBeNull()
  })
})

/**
 * 카드마다 다음에 누를 것 하나가 주 버튼이다 (#1551).
 *
 * 규칙(`primaryAction`)은 `voyageRules.test.ts`가 상태별로 본다. 여기서는 **화면이 그 규칙을
 * 따르는가** — 채움 버튼이 많아야 하나이고, 맨 앞에 있고, 취소는 텍스트 버튼인가를 본다.
 */
describe('항차 카드의 주 버튼 (#1551)', () => {
  const FUELED: ManagedVoyage = {
    ...IN_PROGRESS,
    fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331, actualFuelTon: 320 }],
  }
  const COMPLETED_NO_DISTANCE: ManagedVoyage = {
    ...FUELED,
    status: 'COMPLETED',
    inclusionPolicy: 'INCLUDE_AS_ACTUAL',
  }
  const CONFIRMED: ManagedVoyage = {
    ...COMPLETED_NO_DISTANCE,
    status: 'CONFIRMED',
    actualDistanceNm: 2290,
  }

  function renderOne(voyage: ManagedVoyage, over: Partial<VoyageManagementProvider> = {}) {
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({
          list: vi.fn(async () => ({ voyages: [voyage], fuelTypes: ['HFO'], nextCursor: null, hasMore: false })),
          ...over,
        })}
      />,
    )
  }

  const row = () => document.getElementById('voyage-v-1') as HTMLLIElement
  const primaries = () => Array.from(row().querySelectorAll('.vy__primary'))
  const actionsFirst = () => row().querySelector('.vy__row-actions button') as HTMLButtonElement

  it('항해 중 · 연료 실적 없음 — 「실적 입력」이 주 버튼이고, 막힌 완료의 사유가 그것을 가리킨다', async () => {
    renderOne(IN_PROGRESS)
    const actuals = await screen.findByRole('button', { name: '실적 입력' })
    expect(primaries()).toEqual([actuals])
    expect(actionsFirst()).toBe(actuals)

    const complete = screen.getByRole('button', { name: '항해 완료로' }) as HTMLButtonElement
    expect(complete.disabled).toBe(true)
    expect(complete.className).not.toContain('vy__primary')
    expect(document.getElementById(complete.getAttribute('aria-describedby') ?? '')?.textContent).toMatch(
      /「실적 입력」/,
    )
  })

  it('항해 중 · 연료 실적 있음 — 「항해 완료로」가 주 버튼이고 맨 앞이다', async () => {
    renderOne(FUELED)
    const complete = await screen.findByRole('button', { name: '항해 완료로' })
    expect(primaries()).toEqual([complete])
    expect(actionsFirst()).toBe(complete)
    expect(screen.getByRole('button', { name: '실적 입력' }).className).not.toContain('vy__primary')
  })

  it('「실적 입력」을 열면 채움을 내린다 — 할 일은 폼 안의 「실적 저장」이다', async () => {
    renderOne(IN_PROGRESS)
    fireEvent.click(await screen.findByRole('button', { name: '실적 입력' }))
    expect(screen.getByRole('button', { name: '실적 닫기' }).className).not.toContain('vy__primary')
    expect(primaries()).toEqual([])
  })

  it('완료 · 실제 거리 없음 — 확정은 누르기 전에 사유를 내고 「실적 입력」이 주 버튼이다', async () => {
    renderOne(COMPLETED_NO_DISTANCE)
    const confirm = (await screen.findByRole('button', { name: '실적 확정으로' })) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    expect(screen.getByText(/실제 거리를 넣어야 실적을 확정할 수 있습니다/)).toBeTruthy()
    expect(primaries()).toEqual([screen.getByRole('button', { name: '실적 입력' })])
  })

  it('실적 확정 — 다음 단계가 없어 채움 버튼이 없다', async () => {
    renderOne(CONFIRMED)
    await screen.findByRole('button', { name: '보관됨으로' })
    expect(primaries()).toEqual([])
  })

  it('취소는 텍스트 버튼 「이 항차 취소」이고, 확인 줄을 거쳐 취소된다 (#1598)', async () => {
    const transition = vi.fn(async () => IN_PROGRESS)
    renderOne(IN_PROGRESS, { transition })
    const cancel = await screen.findByRole('button', { name: '이 항차 취소' })
    expect(cancel.className).toBe('vy__text-action')
    expect(screen.queryByRole('button', { name: '취소됨으로' })).toBeNull()

    fireEvent.click(cancel)
    expect(transition).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '취소하기' }))
    await waitFor(() => expect(transition).toHaveBeenCalledWith(IN_PROGRESS, 'CANCELLED'))
  })

  it('취소할 수 없는 상태에는 없다', async () => {
    renderOne(CONFIRMED)
    await screen.findByRole('button', { name: '보관됨으로' })
    expect(screen.queryByRole('button', { name: '이 항차 취소' })).toBeNull()
  })
})

describe('되돌릴 수 없는 전환 · 확정 되돌리기는 한 번 더 묻는다 (#1598 · `API_SPEC §3.5`)', () => {
  const CONFIRMED: ManagedVoyage = {
    ...IN_PROGRESS,
    status: 'CONFIRMED',
    inclusionPolicy: 'INCLUDE_AS_ACTUAL',
    actualDistanceNm: 2290,
    fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331, actualFuelTon: 320 }],
  }
  const FUELED: ManagedVoyage = {
    ...IN_PROGRESS,
    fuelUses: [{ fuelType: 'HFO', plannedFuelTon: 331, actualFuelTon: 320 }],
  }

  function renderOne(voyage: ManagedVoyage, transition = vi.fn(async () => voyage)) {
    render(
      <VoyagePanel
        vesselId="ves-1"
        provider={stubProvider({
          list: vi.fn(async () => ({ voyages: [voyage], fuelTypes: ['HFO'], nextCursor: null, hasMore: false })),
          transition,
        })}
      />,
    )
    return transition
  }
  const caution = () => document.querySelector('.vy__caution') as HTMLElement | null

  it('확정 항차는 「항해 완료로」가 아니라 「확정 되돌리기」 텍스트 버튼이다', async () => {
    renderOne(CONFIRMED)
    const revert = await screen.findByRole('button', { name: '확정 되돌리기' })
    expect(revert.className).toBe('vy__text-action')
    expect(screen.queryByRole('button', { name: '항해 완료로' })).toBeNull()
    // 보관은 종전 틀 그대로
    expect(screen.getByRole('button', { name: '보관됨으로' })).toBeTruthy()
  })

  it('누르면 바로 되돌리지 않고, 무엇이 달라지는지 적은 확인 줄을 연다', async () => {
    const transition = renderOne(CONFIRMED)
    const revert = await screen.findByRole('button', { name: '확정 되돌리기' })
    fireEvent.click(revert)

    expect(transition).not.toHaveBeenCalled()
    const group = within(caution()!)
    expect(caution()!.getAttribute('role')).toBe('group')
    expect(screen.getByRole('group', { name: /감사 기록에 남습니다/ })).toBe(caution())
    expect(revert.getAttribute('aria-expanded')).toBe('true')
    // 초점은 안전한 쪽에 먼저 간다
    expect(document.activeElement).toBe(group.getByRole('button', { name: '그만두기' }))

    fireEvent.click(group.getByRole('button', { name: '확정 되돌리기' }))
    await waitFor(() => expect(transition).toHaveBeenCalledWith(CONFIRMED, 'COMPLETED'))
    expect(caution()).toBeNull()
  })

  it('「그만두기」 · Escape는 아무것도 하지 않고 누른 버튼으로 초점을 돌려준다', async () => {
    const transition = renderOne(CONFIRMED)
    const archive = await screen.findByRole('button', { name: '보관됨으로' })

    fireEvent.click(archive)
    expect(within(caution()!).getByText(/보관한 항차는 되돌릴 수 없고/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '그만두기' }))
    expect(caution()).toBeNull()
    expect(document.activeElement).toBe(archive)

    fireEvent.click(archive)
    fireEvent.keyDown(screen.getByRole('button', { name: '그만두기' }), { key: 'Escape' })
    expect(caution()).toBeNull()
    expect(document.activeElement).toBe(archive)
    expect(transition).not.toHaveBeenCalled()
  })

  it('보관도 확인 줄을 거쳐 전환된다', async () => {
    const transition = renderOne(CONFIRMED)
    fireEvent.click(await screen.findByRole('button', { name: '보관됨으로' }))
    fireEvent.click(screen.getByRole('button', { name: '보관하기' }))
    await waitFor(() => expect(transition).toHaveBeenCalledWith(CONFIRMED, 'ARCHIVED'))
  })

  it('정방향 전환은 종전처럼 바로 간다 — 확인 줄이 없다', async () => {
    const transition = renderOne(FUELED)
    fireEvent.click(await screen.findByRole('button', { name: '항해 완료로' }))
    expect(caution()).toBeNull()
    await waitFor(() => expect(transition).toHaveBeenCalledWith(FUELED, 'COMPLETED'))
  })
})
