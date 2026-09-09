// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { VesselManagement } from './VesselManagement'

/**
 * 최초 조회 중 본문이 비지 않는다 (#824 ⑷).
 *
 * ## 무엇이 문제였나
 *
 * `loading`을 읽는 렌더 분기가 **「더 보기」 버튼뿐**이었고, 그 버튼은 `hasMore`일
 * 때만 존재한다. 그래서 첫 로드 동안
 *
 * - 오류도 없고(`loadError === null`)
 * - 빈 상태도 없고(`!loading`으로 배제)
 * - 목록도 없어(`vessels.length > 0`으로 배제)
 *
 * **머리말과 링크 두 개만 남았다.** 사용자는 선박이 등록되지 않은 화면으로 읽는다.
 * 다른 목록 화면은 전부 이 자리를 채운다(`FleetDashboard`·`VoyagePanel`·
 * `NotUnderwayPanel`).
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('선박 관리 최초 조회 중 화면이 비지 않는다 (#824 ⑷)', () => {
  it('목록이 오기 전에 「불러오는 중」을 말한다', async () => {
    let release: ((value: Response) => void) | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        // 선박 목록만 늦춘다 — 결함이 보이는 구간이 정확히 그 사이다.
        return new Promise<Response>((resolve) => {
          release = resolve
        })
      }),
    )

    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/선박 목록을 불러오는 중입니다/)).toBeTruthy()

    await act(async () => {
      release?.(jsonResponse({ data: [], meta: {} }))
    })

    // 다 받은 뒤에는 「없음」으로 바뀐다 — 두 문구가 겹쳐 있으면 안 된다.
    await waitFor(() =>
      expect(screen.queryByText(/선박 목록을 불러오는 중입니다/)).toBeNull(),
    )
  })
})
