// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    })),
    ...over,
  }
}

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
