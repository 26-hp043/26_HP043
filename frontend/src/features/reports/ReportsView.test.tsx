// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ReportsView } from './ReportsView'
import type { ReportsProvider, VesselOption, VoyageOption } from './types'

/**
 * 보고서 화면의 **조회 상태 3상태** (#824 ⑵).
 *
 * ## 무엇이 문제였나
 *
 * 항차 재조회에 **이 저장소에서 유일하게 취소 플래그가 없었다**(다른 열 곳은 전부
 * 갖고 있다). 게다가 단발이 아니라 **커서 전량 순회**라 응답 시간이 항차 수에
 * 비례한다. 세 결함이 겹쳐 있었다.
 *
 * - **경합** — 항차가 많은 A → 적은 B로 전환하면 **B가 먼저 오고 A가 덮어쓴다.**
 *   선박 셀렉트는 B인데 항차 셀렉트는 A의 항차이고, 그대로 만들면 **선박 B 화면에서
 *   선박 A의 문서**가 나오거나 404/422가 난다.
 * - **잔류** — `setVoyages(null)`이 없어 두 번째 선박부터 「불러오는 중」이 영영 안
 *   뜬다. 사용자는 A의 항차를 B의 것으로 읽는다.
 * - **실패 은폐** — `.catch(() => setVoyages([]))` → 항차가 1,000건이어도 「이 선박에
 *   등록된 항차가 없습니다」.
 *
 * ⚠️ **같은 파일이 스스로 세운 규칙을 어기고 있었다** — 선박·연도 셀렉트는 「불러오는
 * 중」과 「없음」을 구분한다(`#613`). 항차 셀렉트만 예외였다.
 */

const VESSELS: VesselOption[] = [
  { id: 'v-a', name: 'STAR SKIPPER', imoNumber: '9876543' },
  { id: 'v-b', name: 'PAN HORIZON', imoNumber: '9876544' },
]

function voyage(id: string, no: string): VoyageOption {
  return {
    id,
    voyageNo: no,
    status: 'CONFIRMED',
    regulationYear: 2026,
    departurePortName: 'BUSAN',
    arrivalPortName: 'SINGAPORE',
    reportable: true,
  }
}

const A_VOYAGES = [voyage('a-1', 'A-2026-01')]
const B_VOYAGES = [voyage('b-1', 'B-2026-01')]

function stub(over: Partial<ReportsProvider> = {}): ReportsProvider {
  return {
    listVessels: vi.fn(async () => VESSELS),
    listVoyages: vi.fn(async () => A_VOYAGES),
    previewHtml: vi.fn(async () => '<p>preview</p>'),
    download: vi.fn(async () => 'report.pdf'),
    ...over,
  }
}

/** 「항차 완료」로 바꾼다 — 항차 셀렉트는 그때만 그려진다. */
async function chooseVoyageKind() {
  fireEvent.click(await screen.findByTestId('kind-voyage'))
}

/** 선박 셀렉트. 라벨이 `<span>`이라 `data-testid`로 잡는다(화면의 기존 관례). */
function vesselSelect(): HTMLSelectElement {
  return screen.getByTestId('vessel-select') as HTMLSelectElement
}

describe('선박을 바꾸면 항차 목록이 어긋나지 않는다 (#824 ⑵)', () => {
  it('늦게 도착한 옛 선박의 항차가 새 선박 화면을 덮지 않는다', async () => {
    let releaseA: ((rows: VoyageOption[]) => void) | null = null
    const provider = stub({
      listVoyages: vi.fn(async (vesselId: string) => {
        if (vesselId === 'v-a') {
          return new Promise<VoyageOption[]>((resolve) => {
            releaseA = resolve
          })
        }
        return B_VOYAGES
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })
    // A가 아직 응답하지 않은 채 B로 넘어간다.
    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })
    expect(await screen.findByText(/B-2026-01/)).toBeTruthy()

    // 이제서야 A가 돌아온다. 종전에는 이 한 줄이 B의 목록을 덮었다.
    await import('@testing-library/react').then(({ act }) =>
      act(async () => {
        releaseA?.(A_VOYAGES)
      }),
    )

    expect(screen.getByText(/B-2026-01/)).toBeTruthy()
    expect(screen.queryByText(/A-2026-01/)).toBeNull()
  })

  it('전환 직후 「불러오는 중」이 다시 뜬다 — 옛 항차가 남지 않는다', async () => {
    let releaseB: ((rows: VoyageOption[]) => void) | null = null
    const provider = stub({
      listVoyages: vi.fn(async (vesselId: string) => {
        if (vesselId === 'v-a') return A_VOYAGES
        return new Promise<VoyageOption[]>((resolve) => {
          releaseB = resolve
        })
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })
    expect(await screen.findByText(/A-2026-01/)).toBeTruthy()

    fireEvent.change(vesselSelect(), { target: { value: 'v-b' } })

    /*
     * 종전에는 `setVoyages(null)`이 없어 **두 번째 선박부터 이 문구가 영영 안 떴고**,
     * 사용자는 A의 항차를 B의 것으로 읽었다.
     */
    expect(await screen.findByText(/항차 목록을 불러오는 중입니다/)).toBeTruthy()
    expect(screen.queryByText(/A-2026-01/)).toBeNull()

    await import('@testing-library/react').then(({ act }) =>
      act(async () => {
        releaseB?.(B_VOYAGES)
      }),
    )
    expect(await screen.findByText(/B-2026-01/)).toBeTruthy()
  })

  it('조회 실패를 「항차 없음」으로 말하지 않는다', async () => {
    const provider = stub({
      listVoyages: vi.fn(async () => {
        throw new Error('서버 오류')
      }),
    })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect().querySelectorAll('option').length).toBeGreaterThan(1))
    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })

    /*
     * ⚠️ 종전에는 실패도 `[]`라 **항차가 1,000건이어도** 「등록된 항차가 없습니다」로
     * 나갔다 — 원인이 뒤바뀐다.
     */
    expect(await screen.findByText(/항차 목록을 불러오지 못했습니다/)).toBeTruthy()
    expect(screen.queryByText(/등록된 항차가 없습니다/)).toBeNull()
  })

  it('진짜로 항차가 없으면 종전대로 「없음」이다', async () => {
    const provider = stub({ listVoyages: vi.fn(async () => []) })
    render(<ReportsView provider={provider} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect().querySelectorAll('option').length).toBeGreaterThan(1))
    fireEvent.change(vesselSelect(), { target: { value: 'v-a' } })

    expect(await screen.findByText(/등록된 항차가 없습니다/)).toBeTruthy()
    expect(screen.queryByText(/불러오지 못했습니다/)).toBeNull()
  })

  it('선박을 고르기 전에는 「불러오는 중」을 말하지 않는다', async () => {
    render(<ReportsView provider={stub()} />)
    await chooseVoyageKind()

    await waitFor(() => expect(vesselSelect()).toBeTruthy())
    expect(screen.queryByText(/항차 목록을 불러오는 중/)).toBeNull()
  })
})
