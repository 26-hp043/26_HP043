// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VesselDetail } from './VesselDetail'
import type { VesselDetail as Detail, VesselDetailProvider } from './types'

/**
 * 진행 중 항차가 없을 때 실시간 CII 링크가 거짓 신호를 주지 않는다 (`#588`).
 *
 * 종전에는 `underwayState === 'UNDER_WAY'`로 링크를 그렸다. 그 값은 **표시 상태**이고
 * 진행 중 항차의 존재와 별개라, **운항 중으로 표시된 선박에 항차가 없는 상태**에서
 * 사용자가 「있다」고 읽고 눌렀는데 없었다(`#587`이 그 데이터를 드러냈다).
 *
 * 여기서 고정하는 것은 셋이다.
 *
 * * 항차가 없으면 **누를 수 있는 링크가 그려지지 않는다**
 * * 그때 **왜 없는지와 무엇을 하면 열리는지**가 화면에 있다
 * * **조회 실패를 「있다」로 읽지 않는다** — 실패가 거짓 신호로 되돌아오면 안 된다
 */

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
    // 운항 중으로 표시되지만 진행 중 항차는 없을 수 있다 — 이 이슈의 상태다.
    underwayState: 'UNDER_WAY',
    detailStatus: 'SAILING',
    lat: '35.1',
    lon: '129.0',
    positionUpdatedAt: null,
  },
  capacityBasis: 'DWT',
  years: [],
  asOf: '2026-08-23T00:00:00Z',
}

function stub(over: Partial<VesselDetailProvider> = {}): VesselDetailProvider {
  return {
    load: vi.fn().mockResolvedValue(DETAIL),
    findInProgressVoyage: vi.fn().mockResolvedValue(null),
    updatePosition: vi.fn(),
    ...over,
  }
}

function renderAt(provider: VesselDetailProvider) {
  return render(
    <MemoryRouter initialEntries={['/vessels/v-1']}>
      <Routes>
        <Route path="/vessels/:vesselId" element={<VesselDetail provider={provider} />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('실시간 CII 링크 (#588)', () => {
  it('진행 중 항차가 없으면 누를 수 있는 링크를 그리지 않는다', async () => {
    renderAt(stub())

    const label = await screen.findByText(/진행 중 항차의 실시간 CII 보기/)
    // 운항 상태는 UNDER_WAY인데도 링크가 아니어야 한다 — 그것이 이 이슈다.
    expect(label.closest('a')).toBeNull()
  })

  it('왜 없는지와 무엇을 하면 열리는지를 적는다', async () => {
    renderAt(stub())

    const why = await screen.findByText(/진행 중 항차가 없습니다/)
    expect(why.textContent).toContain('항차 기록')
  })

  it('진행 중 항차가 있으면 링크를 그린다', async () => {
    renderAt(stub({ findInProgressVoyage: vi.fn().mockResolvedValue({ id: 'vy-1', voyageNo: 'V-1' }) }))

    const link = await screen.findByRole('link', { name: /실시간 CII 보기/ })
    expect(link.getAttribute('href')).toBe('/vessels/v-1/voyages/current')
  })

  it('조회가 실패하면 링크를 그리지 않는다 — 실패를 「있다」로 읽지 않는다', async () => {
    renderAt(stub({ findInProgressVoyage: vi.fn().mockRejectedValue(new Error('boom')) }))

    await screen.findByText(/진행 중 항차가 없습니다/)
    expect(screen.queryByRole('link', { name: /실시간 CII 보기/ })).toBeNull()
  })

  it('확인 전에는 없다고 단정하지 않는다', async () => {
    let resolve: (v: null) => void = () => {}
    const pending = new Promise<null>((r) => {
      resolve = r
    })
    renderAt(stub({ findInProgressVoyage: vi.fn().mockReturnValue(pending) }))

    await screen.findByText(/진행 중 항차 확인 중/)
    expect(screen.queryByText(/진행 중 항차가 없습니다/)).toBeNull()

    resolve(null)
    await waitFor(() => expect(screen.getByText(/진행 중 항차가 없습니다/)).toBeDefined())
  })
})

/**
 * 위치 개략도 (#723).
 *
 * 「현재 위치」가 `35.1, 129.0`이라는 **숫자**로만 있었다. 좌표를 숫자로 읽을 수 있는
 * 사람은 없으므로 그림을 함께 둔다.
 *
 * 여기서 잠그는 것은 둘이다 — **좌표가 있으면 그린다**, 그리고 **없으면 빈 그림을
 * 그리지 않는다.** 두 번째가 중요하다. 좌표 없는 배에 빈 상자가 뜨면 「위치를 못
 * 불러왔다」로 읽히는데, 사실은 **입력된 적이 없는** 것이다(`#705`가 대시보드에서
 * 같은 구분을 세웠다).
 */
describe('위치 개략도 (#723)', () => {
  it('좌표가 있으면 그림을 그린다', async () => {
    const { container } = renderAt(stub())
    await waitFor(() => {
      expect(container.querySelector('.position-chart')).not.toBeNull()
    })
  })

  it('좌표가 없으면 그림 자리를 만들지 않는다', async () => {
    const noPosition: Detail = {
      ...DETAIL,
      vessel: { ...DETAIL.vessel, lat: null, lon: null, positionUpdatedAt: null },
    }
    const { container } = renderAt(
      stub({ load: vi.fn().mockResolvedValue(noPosition) }),
    )

    // 화면이 뜬 것을 먼저 확인한다 — 아직 로딩 중이라 없는 것과 구분해야 한다.
    await waitFor(() => {
      expect(screen.getByText('현재 상태')).toBeDefined()
    })
    expect(container.querySelector('.vd__map')).toBeNull()
  })
})

/*
 * 제원 수치가 `DESIGN_SYSTEM §4.2`를 지킨다 (#822).
 *
 * 종전에는 서버 문자열을 **그대로** 그리고 단위를 리터럴로 박았다. 같은 값이 화면마다
 * 달랐다 — 시드의 기준 속력 `18.00`이 이 화면에서는 `18`, 선박 관리 목록에서는
 * `18.0 kn`이었다.
 */
describe('제원 표시 자릿수·단위 (#822)', () => {
  it('기준 속력이 1자리로, 단위는 상수에서 온다', async () => {
    renderAt(
      stub({
        load: vi.fn().mockResolvedValue({
          ...DETAIL,
          vessel: { ...DETAIL.vessel, referenceSpeedKn: '18.00' },
        }),
      }),
    )

    // 종전에는 `18 kn`(서버 문자열 그대로 + 리터럴 단위)이었다.
    expect(await screen.findByText('18.0 kn')).toBeTruthy()
  })

  it('기준 일일 연료에 천단위 구분자가 붙는다 — `GROUPED_FIELDS`', async () => {
    renderAt(
      stub({
        load: vi.fn().mockResolvedValue({
          ...DETAIL,
          vessel: { ...DETAIL.vessel, referenceDailyFocTon: '1234.50' },
        }),
      }),
    )

    // 종전에는 `1234.5 t`였다 — 구분자가 없어 자리 수를 세야 읽혔다.
    expect(await screen.findByText('1,234.5 t')).toBeTruthy()
  })

  it('값이 없으면 「—」다 — 포매터가 빈 문자열을 만들지 않는다', async () => {
    renderAt(
      stub({
        load: vi.fn().mockResolvedValue({
          ...DETAIL,
          vessel: { ...DETAIL.vessel, referenceSpeedKn: null, referenceDailyFocTon: null },
        }),
      }),
    )

    await screen.findByText(/기준 속력/)
    // 단위만 덩그러니 남는 `— kn` 같은 상태가 되면 안 된다.
    expect(screen.queryByText(/^\s*kn\s*$/)).toBeNull()
  })
})
