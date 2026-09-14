// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { VesselManagement } from './VesselManagement'
import * as session from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'

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

/** 기존 검사는 전부 **사무직** 전제다 — 제원 수정·삭제가 사무직 전용이 됐다 (#672). */
function stubRole(role: session.UserRole) {
  vi.spyOn(session, 'useAuthUser').mockReturnValue({
    id: 'u-1',
    email: 'tester@bluelog.local',
    displayName: null,
    role,
    emailVerifiedAt: null,
  })
}

beforeEach(() => {
  stubRole('OFFICE')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/**
 * 현장직에게는 수정·삭제 버튼이 없다 (`API_SPEC §1.2` · #672). 눌러서 403을 받게 두는 것은
 * 「되는 것처럼 보이는」 것이라 버튼 자리에 짧은 안내만 남긴다.
 */
describe('역할 — 현장직은 제원 수정·삭제를 보지 않는다 (#672)', () => {
  function stubOneVessel() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        return jsonResponse({
          data: [
            {
              id: '00000000-0000-4000-8000-000000000001',
              imo_number: '9000001',
              name: '샘플 벌크선',
              ship_type: 'BULK_CARRIER',
              deadweight: 50000,
              gross_tonnage: 30000,
              is_cii_applicable_hint: true,
              reference_speed_kn: null,
              reference_daily_foc_ton: null,
              default_fuel_type: 'HFO',
              underway_state: 'NOT_UNDER_WAY',
              detail_status: null,
            },
          ],
          meta: {},
        })
      }),
    )
  }

  it('현장직: 「수정」·「삭제」 대신 안내 문구', async () => {
    stubRole('FIELD')
    stubOneVessel()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText('샘플 벌크선')
    expect(screen.queryByRole('button', { name: '수정' })).toBeNull()
    expect(screen.queryByRole('button', { name: '삭제' })).toBeNull()
    expect(screen.getByText(OFFICE_ONLY_ACTION_HINT)).toBeTruthy()
  })

  it('사무직: 두 버튼이 그대로 있다', async () => {
    stubOneVessel()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText('샘플 벌크선')
    expect(screen.getByRole('button', { name: '수정' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '삭제' })).toBeTruthy()
    expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()
  })
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
