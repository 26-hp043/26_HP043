// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VoyageCiiActions } from './VoyageCiiActions'
import type { ResultState } from './resultRules'
import type { VoyageCiiRequest, VoyageCiiResponse } from './types'
import type { VoyageManagementProvider } from '../voyage-management/apiProvider'
import type { ManagedVoyage } from '../voyage-management/types'

/**
 * 기능① 결과 액션 3종의 **화면 배선** (#891 · `PRD §10.5`).
 *
 * 규칙은 `actionRules.test.ts`가 잠근다. 여기서는 버튼이 **실제로 서버를 부르거나 이동하는가**를
 * 본다 — 규칙만 검사하면 화면이 그것을 부르지 않아도 초록이다(`#823`·`#873`·`#890`과 같은 함정).
 */

const REQUEST: VoyageCiiRequest = {
  vessel_id: 'vessel-1',
  regulation_year: 2026,
  distance_nm: 2300,
  speed_kn: 14,
  fuel_uses: [{ fuel_type: 'HFO', fuel_ton: 184 }],
}

const SUCCESS: ResultState = {
  status: 'success',
  request: REQUEST,
  response: { calculation_run_id: 'run-abcdef12' } as VoyageCiiResponse,
}

const DRAFT: ManagedVoyage = {
  id: 'voy-1',
  voyageNo: '',
  status: 'DRAFT',
  inclusionPolicy: 'EXCLUDE',
  regulationYear: 2026,
  departurePortName: 'Busan',
  arrivalPortName: 'Singapore',
  plannedDistanceNm: 2300,
  plannedSpeedKn: 14,
  actualDistanceNm: null,
  actualAvgSpeedKn: null,
  plannedDepartureAt: null,
  plannedArrivalAt: null,
  actualDepartureAt: null,
  actualArrivalAt: null,
  fuelUses: [],
}

function stubProvider(over: Partial<VoyageManagementProvider> = {}): VoyageManagementProvider {
  return {
    list: vi.fn(),
    create: vi.fn(async () => DRAFT),
    transition: vi.fn(async () => ({ ...DRAFT, status: 'PLANNED' as const })),
    saveActuals: vi.fn(),
    importCsv: vi.fn(),
    exportData: vi.fn(async () => 'calculations_run-abcd.csv'),
    ...over,
  } as unknown as VoyageManagementProvider
}

function renderActions(state: ResultState, provider: VoyageManagementProvider, stale = false) {
  return render(
    <MemoryRouter initialEntries={['/cii']}>
      <Routes>
        <Route
          path="/cii"
          element={<VoyageCiiActions state={state} stale={stale} provider={provider} />}
        />
        <Route path="/annual-grade" element={<p>연간 화면</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function fillPlan() {
  fireEvent.click(screen.getByRole('button', { name: '계획 저장' }))
  fireEvent.change(screen.getByLabelText('출발항'), { target: { value: 'Busan' } })
  fireEvent.change(screen.getByLabelText('도착항'), { target: { value: 'Singapore' } })
  fireEvent.change(screen.getByLabelText('출항 예정 시각'), {
    target: { value: '2026-10-01T09:00' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('기능① 결과 액션 (#891)', () => {
  it('결과가 없으면 아무것도 그리지 않는다', () => {
    const { container } = renderActions({ status: 'idle' }, stubProvider())
    expect(container.querySelector('.voyage-cii-actions')).toBeNull()
  })

  it('계획 저장 — 항차를 만들고 PLANNED로 옮기며 기본은 연간 반영(INCLUDE_AS_PLAN)이다', async () => {
    const provider = stubProvider()
    renderActions(SUCCESS, provider)
    fillPlan()
    fireEvent.click(screen.getByRole('button', { name: '계획으로 저장' }))

    await screen.findByText(/계획 항차로 저장했습니다\. 연간 시뮬레이션의 잔여 계획에 반영됩니다/)
    expect(provider.create).toHaveBeenCalledWith(
      'vessel-1',
      expect.objectContaining({
        departurePortName: 'Busan',
        plannedDistanceNm: '2300',
        regulationYear: '2026',
        plannedArrivalAt: '2026-10-08T05:17',
      }),
    )
    expect(provider.transition).toHaveBeenCalledWith(DRAFT, 'PLANNED', 'INCLUDE_AS_PLAN')
  })

  it('반영을 끄면 EXCLUDE로 옮긴다 — 계획 저장과 연간 반영은 별개다', async () => {
    const provider = stubProvider()
    renderActions(SUCCESS, provider)
    fillPlan()
    fireEvent.click(screen.getByLabelText('연간 시뮬레이션의 잔여 계획에 반영'))
    fireEvent.click(screen.getByRole('button', { name: '계획으로 저장' }))

    await waitFor(() =>
      expect(provider.transition).toHaveBeenCalledWith(DRAFT, 'PLANNED', 'EXCLUDE'),
    )
  })

  it('출발·도착·출항 시각 없이는 서버를 부르지 않는다', () => {
    const provider = stubProvider()
    renderActions(SUCCESS, provider)
    fireEvent.click(screen.getByRole('button', { name: '계획 저장' }))
    fireEvent.click(screen.getByRole('button', { name: '계획으로 저장' }))

    expect(screen.getByText('출발항을 입력하세요.')).toBeTruthy()
    expect(provider.create).not.toHaveBeenCalled()
  })

  it('저장이 실패하면 사유를 알리고 성공한 척하지 않는다', async () => {
    const provider = stubProvider({
      create: vi.fn(async () => {
        throw new Error('출발항이 너무 깁니다.')
      }),
    })
    renderActions(SUCCESS, provider)
    fillPlan()
    fireEvent.click(screen.getByRole('button', { name: '계획으로 저장' }))

    expect((await screen.findByRole('alert')).textContent).toBe('출발항이 너무 깁니다.')
    expect(screen.queryByText(/계획 항차로 저장했습니다/)).toBeNull()
    expect(provider.transition).not.toHaveBeenCalled()
  })

  it('CSV 다운로드 — 이 계산 한 건을 서버 내보내기로 받는다', async () => {
    const provider = stubProvider()
    renderActions(SUCCESS, provider)
    fireEvent.click(screen.getByRole('button', { name: 'CSV 다운로드' }))

    await waitFor(() =>
      expect(provider.exportData).toHaveBeenCalledWith(
        'vessel-1',
        'type=calculations&calculation_run_id=run-abcdef12&format=csv',
        'calculations_run-abcd.csv',
      ),
    )
  })

  it('연간 시뮬레이터에서 보기 — 연간 화면으로 간다', async () => {
    renderActions(SUCCESS, stubProvider())
    fireEvent.click(screen.getByRole('button', { name: '연간 시뮬레이터에서 보기' }))
    expect(await screen.findByText('연간 화면')).toBeTruthy()
  })

  it('입력이 바뀐 상태에서는 세 액션을 막는다 — 화면의 입력과 다른 값이 저장되지 않게', () => {
    renderActions(SUCCESS, stubProvider(), true)
    for (const name of ['계획 저장', '연간 시뮬레이터에서 보기', 'CSV 다운로드']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
  })
})
