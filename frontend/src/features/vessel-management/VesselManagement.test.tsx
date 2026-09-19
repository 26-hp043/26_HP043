// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

/*
 * ── 진행 중인 조작은 선박 id에 묶인다 (#1102 ⑴·⑵·⑶) ──────────────────────
 *
 * 종전에는 수정 폼 하나·`saving` 하나·`deletingId` 하나가 화면 전체의 상태였다.
 * 응답이 오기 전에 다른 선박의 조작이 시작되면 먼저 온 응답이 **나중 선박의 상태**를
 * 건드렸다. 아래 검사는 그 시나리오를 그대로 재현한다 — 응답을 손에 쥐고(deferred)
 * 그 사이에 다른 배를 만진 뒤 응답을 풀어 준다.
 */

interface Deferred {
  resolve: (response: Response) => void
  promise: Promise<Response>
}

function deferred(): Deferred {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((r) => {
    resolve = r
  })
  return { resolve, promise }
}

function rawVessel(id: string, name: string) {
  return {
    id: `00000000-0000-4000-8000-0000000000${id}`,
    imo_number: `90000${id}`,
    name,
    ship_type: 'BULK_CARRIER',
    deadweight: 50000,
    gross_tonnage: 30000,
    is_cii_applicable_hint: true,
    reference_speed_kn: null,
    reference_daily_foc_ton: null,
    block_coefficient: null,
    call_sign: null,
    default_fuel_type: null,
    underway_state: 'NOT_UNDER_WAY',
    detail_status: null,
  }
}

const A = rawVessel('01', '알파호')
const B = rawVessel('02', '브라보호')

/**
 * URL·method별로 응답을 정한다. 값이 `Deferred`면 검사가 풀어 줄 때까지 기다린다.
 * 정해지지 않은 요청은 실패시킨다 — 조용히 200을 주면 검사가 무엇을 보는지 흐려진다.
 */
function stubFetch(
  routes: Record<string, Response | Deferred>,
  meta: Record<string, unknown> = {},
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/parameters/fuel-types')) {
        return jsonResponse({
          data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
        })
      }
      const method = init?.method ?? 'GET'
      const key = `${method} ${url.replace(/^.*\/api\/v1/, '')}`
      const route = routes[key]
      if (route === undefined) {
        if (key === 'GET /vessels') return jsonResponse({ data: [A, B], meta })
        throw new Error(`stub에 없는 요청: ${key}`)
      }
      return 'promise' in route ? route.promise : route
    }),
  )
}

function renderScreen() {
  render(
    <MemoryRouter>
      <VesselManagement />
    </MemoryRouter>,
  )
}

/** 선박 이름이 있는 행. 버튼·폼은 행 안에서 찾는다 — 화면에 같은 이름의 버튼이 여럿이다. */
function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest('li.vm__item')
  if (!(row instanceof HTMLElement)) throw new Error(`${name}의 행이 없다`)
  return row
}

describe('⑴ A 저장 중 B 「수정」 — 응답은 요청 당시 선박에만 반영된다 (#1102)', () => {
  it('A 저장 성공이 B의 폼을 닫지 않는다 — 입력이 남는다', async () => {
    const patchA = deferred()
    stubFetch({ [`PATCH /vessels/${A.id}`]: patchA })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '수정' }))
    fireEvent.change(within(rowOf('알파호')).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '저장' }))
    await within(rowOf('알파호')).findByRole('button', { name: '저장 중…' })

    // 응답이 오기 전에 B의 폼을 연다. 이 시점에 A의 폼은 닫힌다(폼은 하나다).
    fireEvent.click(within(rowOf('브라보호')).getByRole('button', { name: '수정' }))
    fireEvent.change(within(rowOf('브라보호')).getByLabelText('선명'), {
      target: { value: '브라보호 개명' },
    })

    await act(async () => {
      patchA.resolve(jsonResponse({ data: { ...A, name: '알파호 개명' } }))
    })

    // A는 목록에 반영되고 안내가 뜬다.
    expect(await screen.findByText('알파호 개명')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('알파호 개명')
    // B의 폼은 그대로, 입력도 그대로다 — 종전에는 여기서 사라졌다.
    const bName = within(rowOf('브라보호')).getByLabelText('선명') as HTMLInputElement
    expect(bName.value).toBe('브라보호 개명')
  })

  it('A의 422가 B의 폼에 붙지 않는다 — 폼 밖에 A의 이름으로 알린다', async () => {
    const patchA = deferred()
    stubFetch({ [`PATCH /vessels/${A.id}`]: patchA })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '수정' }))
    fireEvent.change(within(rowOf('알파호')).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '저장' }))
    await within(rowOf('알파호')).findByRole('button', { name: '저장 중…' })

    fireEvent.click(within(rowOf('브라보호')).getByRole('button', { name: '수정' }))

    await act(async () => {
      patchA.resolve(
        jsonResponse(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: '선명이 너무 깁니다.',
              details: [{ field: 'name' }],
            },
          },
          422,
        ),
      )
    })

    // 폼 밖에서 A의 이름으로 실패를 말한다 — 조용히 버리면 A가 저장된 줄 안다.
    expect(await screen.findByText(/알파호.*선명이 너무 깁니다/)).toBeTruthy()
    // B의 폼(선명 칸)에는 오류가 없다.
    const bRow = rowOf('브라보호')
    expect(within(bRow).queryByRole('alert')).toBeNull()
    /*
     * **「invalid가 아니다」를 단언한다 — 표현을 단언하지 않는다** (`#936`).
     *
     * 종전 코드는 `aria-invalid={key in errors}`라 오류가 없어도 `"false"`를 내보냈다.
     * 공용 `Field`는 오류일 때만 붙인다(`AuthField`가 쓰던 방식) — ARIA상 **속성 부재가
     * 곧 `false`**이므로 의미는 같다. 검사의 의도는 「B 칸에 A의 오류가 붙지 않았다」이지
     * 어느 표현을 쓰느냐가 아니다.
     */
    expect(within(bRow).getByLabelText('선명').getAttribute('aria-invalid')).not.toBe('true')
  })

  it('폼이 아직 그 선박이면 오류는 종전대로 폼 안 그 칸에 붙는다', async () => {
    stubFetch({
      [`PATCH /vessels/${A.id}`]: jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: '선명이 너무 깁니다.',
            details: [{ field: 'name' }],
          },
        },
        422,
      ),
    })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '수정' }))
    fireEvent.change(within(rowOf('알파호')).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '저장' }))

    const alert = await within(rowOf('알파호')).findByRole('alert')
    expect(alert.textContent).toBe('선명이 너무 깁니다.')
    // 폼 밖 안내는 없다 — 같은 실패를 두 번 말하지 않는다.
    expect(screen.queryByText(/알파호의 정보를 저장하지 못했습니다/)).toBeNull()
  })
})

describe('⑵ 삭제 진행 상태는 선박별이다 (#1102)', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', () => true)
  })

  it('A 삭제가 끝나도 B의 「삭제 중…」은 풀리지 않는다', async () => {
    const delA = deferred()
    const delB = deferred()
    stubFetch({ [`DELETE /vessels/${A.id}`]: delA, [`DELETE /vessels/${B.id}`]: delB })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '삭제' }))
    fireEvent.click(within(rowOf('브라보호')).getByRole('button', { name: '삭제' }))
    expect(within(rowOf('알파호')).getByRole('button', { name: '삭제 중…' })).toBeTruthy()
    expect(within(rowOf('브라보호')).getByRole('button', { name: '삭제 중…' })).toBeTruthy()

    await act(async () => {
      delA.resolve(jsonResponse(null, 204))
    })

    // A는 사라지고, B는 **여전히** 삭제 중이다 — 종전에는 여기서 「삭제」로 돌아가
    // 다시 누르면 404였다.
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    const bButton = within(rowOf('브라보호')).getByRole('button', { name: '삭제 중…' })
    expect((bButton as HTMLButtonElement).disabled).toBe(true)

    await act(async () => {
      delB.resolve(jsonResponse(null, 204))
    })
    await waitFor(() => expect(screen.queryByText('브라보호')).toBeNull())
  })

  it('삭제 실패는 다음 조작이 시작되면 사라진다 — 성공 안내와 나란히 남지 않는다', async () => {
    stubFetch({
      [`DELETE /vessels/${A.id}`]: jsonResponse(
        { error: { code: 'CONFLICT', message: '항차가 이 선박을 참조합니다.' } },
        409,
      ),
      [`DELETE /vessels/${B.id}`]: jsonResponse(null, 204),
    })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '삭제' }))
    expect(await screen.findByText('항차가 이 선박을 참조합니다.')).toBeTruthy()
    // 실패한 배는 목록에 남고 버튼은 다시 「삭제」다.
    expect(within(rowOf('알파호')).getByRole('button', { name: '삭제' })).toBeTruthy()

    fireEvent.click(within(rowOf('브라보호')).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(screen.queryByText('브라보호')).toBeNull())
    expect(screen.getByRole('status').textContent).toContain('브라보호')
    expect(screen.queryByText('항차가 이 선박을 참조합니다.')).toBeNull()
  })
})

describe('⑶ 불러온 수는 전체 수가 아니다 (#1102)', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', () => true)
  })

  it('뒤 페이지가 남아 있으면 제목이 「불러옴」이고 정렬 범위를 밝힌다', async () => {
    stubFetch({}, { next_cursor: 'c2', has_more: true })
    renderScreen()
    await screen.findByText('알파호')

    expect(screen.getByRole('heading', { name: '선박 2척 불러옴' })).toBeTruthy()
    expect(screen.getByText(/정렬은 불러온 선박 안에서만/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '더 보기' })).toBeTruthy()
  })

  it('다 불러왔으면 제목이 「선박 n척」이고 안내가 없다', async () => {
    stubFetch({}, { next_cursor: null, has_more: false })
    renderScreen()
    await screen.findByText('알파호')

    expect(screen.getByRole('heading', { name: '선박 2척' })).toBeTruthy()
    expect(screen.queryByText(/정렬은 불러온 선박 안에서만/)).toBeNull()
    expect(screen.queryByRole('button', { name: '더 보기' })).toBeNull()
  })

  it('불러온 것을 모두 지웠는데 뒤 페이지가 남았으면 「등록된 선박이 없다」고 하지 않는다', async () => {
    stubFetch(
      {
        [`DELETE /vessels/${A.id}`]: jsonResponse(null, 204),
        [`DELETE /vessels/${B.id}`]: jsonResponse(null, 204),
      },
      { next_cursor: 'c2', has_more: true },
    )
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(within(rowOf('알파호')).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    fireEvent.click(within(rowOf('브라보호')).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(screen.queryByText('브라보호')).toBeNull())

    expect(screen.queryByText(/등록된 선박이 없습니다/)).toBeNull()
    expect(screen.getByText(/불러온 선박을 모두 제거했습니다/)).toBeTruthy()
    // 「더 보기」는 그대로다 — 다음 페이지가 답이다.
    expect(screen.getByRole('button', { name: '더 보기' })).toBeTruthy()
  })
})

/**
 * 제원 경고가 행 리듬을 깨지 않는다 (#1277).
 *
 * `#719`가 완성도 막대를 값 두 칸으로 바꾼 뒤로 **무엇이 비었는지는 열이 말한다** —
 * `용량` · `기준속도` · `일일 연료`에 `—`가 선다. 경고가 그 이름을 다시 적으면서
 * 이유마다 줄을 쌓아, 제원이 빈 행만 두 배 높이가 됐다.
 *
 * 이름은 보조 기술에만 남긴다. `—`가 스크린 리더에서 「비었다」로 읽힌다는 보장이
 * 없어, 그 사용자에게는 `#511` 이후의 문장이 그대로 필요하다.
 */
describe('제원 경고 — 열이 말한 것을 반복하지 않는다 (#1277)', () => {
  function stubBareVessel() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).includes('/parameters/fuel-types')) return jsonResponse({ data: [] })
        return jsonResponse({
          data: [
            {
              id: '00000000-0000-4000-8000-000000000009',
              imo_number: '9000009',
              name: '제원 없는 배',
              ship_type: 'BULK_CARRIER',
              deadweight: null,
              gross_tonnage: null,
              is_cii_applicable_hint: true,
              reference_speed_kn: null,
              reference_daily_foc_ton: null,
              default_fuel_type: null,
              underway_state: 'NOT_UNDER_WAY',
              detail_status: null,
            },
          ],
          meta: {},
        })
      }),
    )
  }

  it('⚠️ 이유 둘이 한 요소에 들어간다 — 줄이 쌓이면 행 높이가 갈린다', async () => {
    stubBareVessel()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )

    const line = (await screen.findByText(/CII 등급을 산출할 수 없습니다/)).closest('p')
    expect(line).toBeTruthy()
    // 같은 요소가 두 결과를 모두 갖는다 = 한 줄이다.
    expect(line?.textContent).toContain('감속 민감도가 산출되지 않습니다')
    // 리스트로 되돌아가면 이 단언이 깨진다.
    expect(line?.querySelector('li')).toBeNull()
  })

  it('보이는 것은 결과뿐 — 빠진 항목 이름은 보조 기술 몫이다', async () => {
    stubBareVessel()
    const { container } = render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )

    await screen.findByText(/CII 등급을 산출할 수 없습니다/)

    // 이름은 sr-only로 남아 있다 (`#511` 이후의 문장을 잃지 않는다).
    const hidden = [...container.querySelectorAll('.vm__blocked .sr-only')].map((n) => n.textContent)
    expect(hidden.join('')).toContain('재화중량톤수(DWT) 없음')
    expect(hidden.join('')).toContain('기준속도 · 기준 일일 연료소모량 없음')
  })
})
