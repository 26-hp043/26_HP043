// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { VesselDetail } from './VesselDetail'
import type { CiiYear, VesselDetail as Detail, VesselDetailProvider } from './types'

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

describe('등급이 없어도 누적값은 보인다 (#876)', () => {
  /**
   * 서버가 실적·기준·항차 수를 다 줬는데 **등급 하나가 null**이면 종전 게이트가
   * 그 전부를 버리고 「올해 등록된 항차 실적이 없습니다」를 냈다.
   *
   * ⚠️ **등급 null은 비정상이 아니다** — `API_SPEC §2.7`이 `rating: string | null`로
   * 규정하고, `#834`(RO_RO 여객선 고속선의 등급 경계 누락)가 그 조건을 실재시킨다.
   * 실적이 있는데 없다고 말하면 사용자는 항차를 다시 등록하려 한다.
   */
  const YEAR_WITHOUT_RATING: CiiYear = {
    regulationYear: 2026,
    status: 'IN_PROGRESS' as const,
    dataAvailable: true,
    reason: null,
    attainedCii: '8.979907',
    requiredCii: '9.512340',
    rating: null,
    voyageCount: 17,
    inProgressVoyageCount: 0,
    totalDistanceNm: '10620.00',
    totalFuelTon: '199.10',
  }

  function withYear(year: CiiYear) {
    return stub({ load: vi.fn().mockResolvedValue({ ...DETAIL, years: [year] }) })
  }

  /** 같은 값이 연도별 이력 표에도 나오므로 YTD 카드로 좁혀 본다. */
  async function ytdCard(container: HTMLElement) {
    let card: Element | null = null
    await waitFor(() => {
      card = container.querySelector('.ytd')
      expect(card).toBeTruthy()
    })
    return within(card as unknown as HTMLElement)
  }

  it('등급이 null이어도 실적·기준·항차 수가 그대로 나온다', async () => {
    const { container } = renderAt(withYear(YEAR_WITHOUT_RATING))
    const card = await ytdCard(container)

    // `DESIGN_SYSTEM §4.1` — CII는 소수 3자리.
    expect(card.getByText('8.980')).toBeTruthy()
    expect(card.getByText('9.512')).toBeTruthy()
    expect(card.getByText('17')).toBeTruthy()
    // 「실적이 없다」는 문구가 나오면 안 된다 — 실적은 있다.
    expect(screen.queryByText(/올해 등록된 항차 실적이 없습니다/)).toBeNull()
  })

  it('등급 자리는 「없음」으로 표시된다 — 빈칸이 아니다', async () => {
    renderAt(withYear(YEAR_WITHOUT_RATING))

    // 배지가 「없음」 변형으로 그려지고 스크린리더에도 그렇게 읽힌다.
    expect(await screen.findByLabelText('올해 누적 등급 없음')).toBeTruthy()
  })

  it('등급이 있으면 종전과 같다', async () => {
    const { container } = renderAt(withYear({ ...YEAR_WITHOUT_RATING, rating: 'C' as const }))

    expect(await screen.findByLabelText('올해 누적 등급 C')).toBeTruthy()
    const card = await ytdCard(container)
    expect(card.getByText('8.980')).toBeTruthy()
  })

  it('데이터 자체가 없으면 종전대로 사유를 말한다', async () => {
    renderAt(
      withYear({
        ...YEAR_WITHOUT_RATING,
        dataAvailable: false,
        reason: 'NO_DATA',
        attainedCii: null,
        requiredCii: null,
        voyageCount: 0,
      }),
    )

    expect(await screen.findByText(/올해 등록된 항차 실적이 없습니다/)).toBeTruthy()
  })

  it('올해 카드의 항차 칸은 「완료 항차」이고 진행분을 함께 적는다 (#987)', async () => {
    /*
     * `voyage_count`는 완료 항차만 센다. 같은 카드의 CII에는 진행 중 항차의 기여분이
     * 들어 있으므로, 완료 수만 적으면 두 값이 가리키는 항차 집합이 어긋나 보인다.
     */
    const { container } = renderAt(withYear({ ...YEAR_WITHOUT_RATING, inProgressVoyageCount: 1 }))
    const card = await ytdCard(container)

    const label = card.getByText('완료 항차')
    expect(label.nextElementSibling?.textContent).toBe('17 (+진행 중 1)')
  })
})
