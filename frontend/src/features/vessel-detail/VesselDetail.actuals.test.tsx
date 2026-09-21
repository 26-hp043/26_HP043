// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VesselDetail } from './VesselDetail'
import type { VesselDetail as Detail, VesselDetailProvider } from './types'

/**
 * `?actuals=<항차 id>`가 항차 패널까지 간다 (#1540).
 *
 * 실시간 CII의 「이 항차 실적 입력」이 붙이는 값이다(`voyageActualsPath`). 패널이 폼을 여는
 * 것은 `VoyagePanel.test.tsx`가 보고, 여기서는 **주소의 값이 패널에 닿는가**만 본다 — 이
 * 다리가 끊기면 링크를 눌러도 아무 폼도 열리지 않는다. 패널은 자체 조회를 하므로 대역으로
 * 바꿔 받은 값만 적게 한다.
 */
vi.mock('../voyage-management/VoyagePanel', () => ({
  VoyagePanel: (props: { vesselId: string; openActualsFor?: string | null }) => (
    <p data-testid="voyage-panel">{`${props.vesselId}|${props.openActualsFor ?? '(없음)'}`}</p>
  ),
}))

const DETAIL: Detail = {
  vessel: {
    id: 'v-1',
    name: '샘플 벌크선',
    imoNumber: '0000012',
    shipType: 'BULK_CARRIER',
    deadweight: '50000',
    grossTonnage: '30000',
    isCiiApplicableHint: true,
    referenceSpeedKn: '12.00',
    referenceDailyFocTon: '23.04',
    defaultFuelType: null,
    underwayState: 'UNDER_WAY',
    detailStatus: 'SAILING',
    lat: null,
    lon: null,
    positionUpdatedAt: null,
  },
  capacityBasis: 'DWT',
  years: [],
  asOf: '2026-08-23T00:00:00Z',
}

function renderAt(url: string) {
  const provider: VesselDetailProvider = {
    load: vi.fn().mockResolvedValue(DETAIL),
    findInProgressVoyage: vi.fn().mockResolvedValue(null),
    updatePosition: vi.fn(),
  }
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/vessels/:vesselId" element={<VesselDetail provider={provider} />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('실적 바로 열기 주소 (#1540)', () => {
  it('actuals 값을 항차 패널에 넘긴다', async () => {
    renderAt('/vessels/v-1?actuals=vy-9')
    expect((await screen.findByTestId('voyage-panel')).textContent).toBe('v-1|vy-9')
  })

  it('없으면 아무 항차도 지정하지 않는다', async () => {
    renderAt('/vessels/v-1')
    expect((await screen.findByTestId('voyage-panel')).textContent).toBe('v-1|(없음)')
  })
})
