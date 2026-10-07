// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { VesselManagement } from './VesselManagement'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'
import * as session from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { unavailableHint, unavailableText, ytdCiiText } from '../fleet/fleetRules'
import { MISSING } from './listRules'
import { FUEL_LIST_FAILED_HINT } from '../parameters/fuelCatalog'
import {
  GRADE_FAILED_LINE,
  GRADE_REFRESH_FAILED_TEXT,
  GRADE_RETRY_TEXT,
  GRADE_SORT_DISABLED_REASON,
  GRADE_SORT_DISABLED_SUFFIX,
} from './gradeLookup'

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
    hasAvatar: false,
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
              imo_number: '9000015',
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
    const name = await screen.findByText('샘플 벌크선')
    const row = name.closest('.vm__item') as HTMLElement
    expect(within(row).queryByRole('button', { name: '수정' })).toBeNull()
    expect(within(row).queryByRole('button', { name: '삭제' })).toBeNull()
    // 10/7 — 수정·삭제가 ⋯ 메뉴로 들어갔다. 메뉴 자체가 없어야 한다.
    expect(within(row).queryByRole('button', { name: /더보기$/ })).toBeNull()
    // 등록 버튼 가드(#1353)도 같은 문구를 쓰므로 이 화면에는 두 번 나타난다 — 행 안으로 좁혀 확인한다.
    expect(within(row).getByText(OFFICE_ONLY_ACTION_HINT)).toBeTruthy()
  })

  it('사무직: 두 버튼이 그대로 있다', async () => {
    stubOneVessel()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText('샘플 벌크선')
    // 10/7 — 두 동작은 행 끝 ⋯ 메뉴 안에 있다. 메뉴를 열면 둘 다 보인다.
    const toggle = screen.getByRole('button', { name: '샘플 벌크선 더보기' })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('button', { name: '제원 수정' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '삭제' })).toBeTruthy()
    expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()
  })
})

/**
 * 「선박 등록」도 같은 가드를 쓴다 (`API_SPEC §1.2` · #1353). 종전에는 같은 줄의 수정·삭제만
 * `office`로 막히고 등록 링크만 열려 있어, 현장직이 눌러 사무직 전용 화면
 * (`/vessel-registration`)으로 넘어갔다가 「이 화면은 사무직 계정만 쓸 수 있습니다」를
 * 보고서야 되돌아와야 했다.
 */
describe('역할 — 「선박 등록」 버튼도 같은 가드를 쓴다 (#1353)', () => {
  function stubEmptyList() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        return jsonResponse({ data: [], meta: {} })
      }),
    )
  }

  it('현장직: 「선박 등록」 대신 안내 문구, 링크는 없다', async () => {
    stubRole('FIELD')
    stubEmptyList()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText(OFFICE_ONLY_ACTION_HINT)
    expect(screen.queryByRole('link', { name: '선박 등록' })).toBeNull()
  })

  it('사무직: 「선박 등록」 링크가 그대로 있다', async () => {
    stubEmptyList()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByRole('link', { name: '선박 등록' })
    expect(screen.queryByText(OFFICE_ONLY_ACTION_HINT)).toBeNull()
  })

  it('관리자: 「선박 등록」 링크가 그대로 있다 — ADMIN은 OFFICE의 상위집합 (#1301)', async () => {
    stubRole('ADMIN')
    stubEmptyList()
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByRole('link', { name: '선박 등록' })
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

/*
 * ── 10/7 개편 (#2316) ─────────────────────────────────────────────────
 *
 * 수정·삭제가 행 끝 ⋯ 메뉴(「제원 수정」·「삭제」)로 들어갔고, 수정 폼은 목록 오른쪽
 * 패널(`aside.vm-edit`) **한 장**이 됐다 — 한 번에 한 척이다. 아래 도우미가 그 조작을
 * 대신한다. 검사의 의도(응답은 요청 당시 선박에만 · 삭제는 확인을 받는다 · 오류는 그 칸에)는
 * 종전 그대로다.
 */

/** 그 행의 ⋯ 메뉴 버튼. 이름은 선박명을 담는다 — 행마다 같은 아이콘이라 이름으로 가른다. */
function menuToggle(name: string): HTMLButtonElement {
  return within(rowOf(name)).getByRole('button', { name: `${name} 더보기` }) as HTMLButtonElement
}

function chooseFromMenu(name: string, item: '제원 수정' | '삭제') {
  fireEvent.click(menuToggle(name))
  fireEvent.click(within(rowOf(name)).getByRole('button', { name: item }))
}

/** ⋯ → 「제원 수정」. 오른쪽 패널이 그 선박으로 열린다. */
const editFrom = (name: string) => chooseFromMenu(name, '제원 수정')
/** ⋯ → 「삭제」. 확인(`confirm`)을 거친다. */
const deleteFrom = (name: string) => chooseFromMenu(name, '삭제')

/** 제원 수정 패널 — 화면에 하나뿐이다. */
function editPanel(): HTMLElement {
  const panel = document.querySelector('aside.vm-edit')
  if (!(panel instanceof HTMLElement)) throw new Error('제원 수정 패널이 열려 있지 않다')
  return panel
}

/** 패널이 지금 어느 선박의 것인지 — 머리 제목이 선박명을 담는다. */
const panelTitle = () => within(editPanel()).getByRole('heading').textContent ?? ''

describe('⑴ A 저장 중 B 「수정」 — 응답은 요청 당시 선박에만 반영된다 (#1102)', () => {
  it('A 저장 성공이 B의 폼을 닫지 않는다 — 입력이 남는다', async () => {
    const patchA = deferred()
    stubFetch({ [`PATCH /vessels/${A.id}`]: patchA })
    renderScreen()
    await screen.findByText('알파호')

    editFrom('알파호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))
    await within(editPanel()).findByRole('button', { name: '저장 중…' })

    // 응답이 오기 전에 B의 폼을 연다. 패널은 한 장이라 B로 바뀐다.
    editFrom('브라보호')
    expect(panelTitle()).toContain('브라보호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), {
      target: { value: '브라보호 개명' },
    })

    await act(async () => {
      patchA.resolve(jsonResponse({ data: { ...A, name: '알파호 개명' } }))
    })

    // A는 목록에 반영되고 안내가 뜬다.
    expect(await screen.findByText('알파호 개명')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('알파호 개명')
    // B의 폼은 그대로, 입력도 그대로다 — 종전에는 여기서 사라졌다.
    expect(panelTitle()).toContain('브라보호')
    const bName = within(editPanel()).getByLabelText('선명') as HTMLInputElement
    expect(bName.value).toBe('브라보호 개명')
  })

  it('A의 422가 B의 폼에 붙지 않는다 — 폼 밖에 A의 이름으로 알린다', async () => {
    const patchA = deferred()
    stubFetch({ [`PATCH /vessels/${A.id}`]: patchA })
    renderScreen()
    await screen.findByText('알파호')

    editFrom('알파호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))
    await within(editPanel()).findByRole('button', { name: '저장 중…' })

    editFrom('브라보호')

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
    // 패널은 B의 것이고, B의 폼(선명 칸)에는 오류가 없다.
    expect(panelTitle()).toContain('브라보호')
    const bForm = editPanel()
    expect(within(bForm).queryByRole('alert')).toBeNull()
    /*
     * **「invalid가 아니다」를 단언한다 — 표현을 단언하지 않는다** (`#936`).
     *
     * 종전 코드는 `aria-invalid={key in errors}`라 오류가 없어도 `"false"`를 내보냈다.
     * 공용 `Field`는 오류일 때만 붙인다(`AuthField`가 쓰던 방식) — ARIA상 **속성 부재가
     * 곧 `false`**이므로 의미는 같다. 검사의 의도는 「B 칸에 A의 오류가 붙지 않았다」이지
     * 어느 표현을 쓰느냐가 아니다.
     */
    expect(within(bForm).getByLabelText('선명').getAttribute('aria-invalid')).not.toBe('true')
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

    editFrom('알파호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))

    const alert = await within(editPanel()).findByRole('alert')
    expect(alert.textContent).toBe('선명이 너무 깁니다.')
    // 폼 밖 안내는 없다 — 같은 실패를 두 번 말하지 않는다.
    expect(screen.queryByText(/알파호의 정보를 저장하지 못했습니다/)).toBeNull()
  })
})

describe('⑵ 삭제 진행 상태는 선박별이다 (#1102)', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', () => true)
  })

  /*
   * 10/7 — 삭제 중에는 그 행의 ⋯ 메뉴 버튼이 잠긴다(종전의 「삭제 중…」 버튼 자리).
   * 문구가 아니라 **잠김(`disabled`)** 을 본다 — 다시 눌러 404를 받지 않게 하는 것이 의도다.
   */
  it('A 삭제가 끝나도 B의 삭제 중 잠김은 풀리지 않는다', async () => {
    const delA = deferred()
    const delB = deferred()
    stubFetch({ [`DELETE /vessels/${A.id}`]: delA, [`DELETE /vessels/${B.id}`]: delB })
    renderScreen()
    await screen.findByText('알파호')

    deleteFrom('알파호')
    // A가 삭제 중이어도 B의 메뉴는 열린다 — 잠김은 선박별이다.
    expect(menuToggle('브라보호').disabled).toBe(false)
    deleteFrom('브라보호')
    expect(menuToggle('알파호').disabled).toBe(true)
    expect(menuToggle('브라보호').disabled).toBe(true)

    await act(async () => {
      delA.resolve(jsonResponse(null, 204))
    })

    // A는 사라지고, B는 **여전히** 삭제 중이다 — 종전에는 여기서 「삭제」로 돌아가
    // 다시 누르면 404였다.
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    expect(menuToggle('브라보호').disabled).toBe(true)

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

    deleteFrom('알파호')
    expect(await screen.findByText('항차가 이 선박을 참조합니다.')).toBeTruthy()
    // 실패한 배는 목록에 남고 메뉴는 다시 열린다.
    expect(menuToggle('알파호').disabled).toBe(false)

    deleteFrom('브라보호')
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

    deleteFrom('알파호')
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    deleteFrom('브라보호')
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
 *
 * **10/7 개편(#2316)** — 경고 줄 자체가 없어지고 「데이터」 칸이 그 자리를 맡았다. 칸에는
 * 빠진 항목의 **짧은 이름**만 보이고, 막히는 결과 문장은 `title`과 `sr-only`로 간다.
 * 지키는 것은 같다 — 행 높이를 쌓지 않는다 · 결과 문장을 잃지 않는다.
 */
describe('제원 경고 — 데이터 칸 한 자리에 (#1277 · #2316)', () => {
  function stubBareVessel() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).includes('/parameters/fuel-types')) return jsonResponse({ data: [] })
        return jsonResponse({
          data: [
            {
              id: '00000000-0000-4000-8000-000000000009',
              imo_number: '9000091',
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

  /** 그 배 행의 「데이터」 칸. */
  async function dataCell(container: HTMLElement): Promise<HTMLElement> {
    await screen.findByText('제원 없는 배')
    const cell = container.querySelector('li.vm__item .vm__data')
    expect(cell).toBeTruthy()
    return cell as HTMLElement
  }

  /** 눈에 보이는 글자만 — `sr-only`를 뺀다. */
  function visibleText(el: Element): string {
    return [...el.childNodes]
      .map((node) =>
        node instanceof Element
          ? node.classList.contains('sr-only')
            ? ''
            : visibleText(node)
          : (node.textContent ?? ''),
      )
      .join('')
  }

  it('⚠️ 이유 둘이 한 요소에 들어간다 — 줄이 쌓이면 행 높이가 갈린다', async () => {
    stubBareVessel()
    const { container } = render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )

    /*
     * 10/7(#2316) — 행 아래 경고 줄이 「데이터」 칸 하나로 바뀌었다. 결과 문장 둘은 그 칸의
     * `title`(툴팁)과 `sr-only`에 **한 덩어리로** 들어간다. 리스트로 되돌아가면 깨진다.
     */
    const cell = await dataCell(container)
    const why = cell.getAttribute('title') ?? ''
    expect(why).toMatch(/CII 등급을 산출할 수 없습니다/)
    expect(why).toContain('감속 민감도가 산출되지 않습니다')
    expect(cell.querySelector('li')).toBeNull()
    // 행 밖에 따로 경고 줄을 세우지 않는다 — 행 높이를 지키는 것이 이 검사의 의도다.
    expect(container.querySelector('.vm__blocked')).toBeNull()
  })

  it('보이는 것은 빠진 항목의 짧은 이름 — 막히는 결과 문장은 보조 기술·툴팁 몫이다', async () => {
    stubBareVessel()
    const { container } = render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )

    const cell = await dataCell(container)
    const shown = visibleText(cell)
    // 결과 문장은 눈에 보이지 않는다 — 칸은 훑는 자리다.
    expect(shown).not.toMatch(/CII 등급을 산출할 수 없습니다/)
    // 이름은 짧은 형태다 — 수정 패널의 긴 라벨을 그대로 쓰지 않는다.
    expect(shown).not.toContain('재화중량톤수(DWT)')
    expect(shown).not.toContain('기준 일일 연료소모량')
    expect(shown.trim()).not.toBe('')

    // 결과 문장은 sr-only로 남아 있다 (`#511` 이후의 문장을 잃지 않는다).
    const hidden = [...cell.querySelectorAll('.sr-only')].map((n) => n.textContent).join('')
    expect(hidden).toMatch(/CII 등급을 산출할 수 없습니다/)
    expect(hidden).toContain('감속 민감도가 산출되지 않습니다')
  })

  it('제원이 다 찬 배의 데이터 칸은 빈 배와 다른 말이고, 결과 문장을 달지 않는다', async () => {
    const full = rawVessel('03', '가득호')
    stubFetch({
      'GET /vessels': jsonResponse({
        data: [{ ...full, reference_speed_kn: 14, reference_daily_foc_ton: 20 }, A],
      }),
    })
    renderScreen()
    await screen.findByText('가득호')
    const cellOf = (name: string) => rowOf(name).querySelector('.vm__data') as HTMLElement
    expect(visibleText(cellOf('가득호'))).not.toBe(visibleText(cellOf('알파호')))
    expect(cellOf('가득호').getAttribute('title')).toBeNull()
    expect(cellOf('알파호').getAttribute('title')).not.toBeNull()
  })
})

/**
 * 제원 미비 필터 칩 (`#1424`).
 *
 * 종전에는 미비 선박만 보려면 정렬밖에 없었다. 칩을 더했으되, **누를 수 있다는 것만으로
 * 끝나지 않는다** — 걸러 놓은 상태가 화면에 남고, 0척이어도 막다른 곳이 아니어야 한다.
 */
describe('제원 미비 필터 칩 (#1424)', () => {
  /** A·B는 기준속도·일일 연료가 비어 있다. 여기에 제원이 다 찬 배를 하나 더한다. */
  const FULL = {
    ...rawVessel('03', '가득호'),
    reference_speed_kn: 14,
    reference_daily_foc_ton: 20,
  }

  const chip = () => screen.getByTestId('spec-gap-filter')
  const names = () =>
    Array.from(document.querySelectorAll('li.vm__item .vm__name')).map((el) => el.textContent)

  it('누르면 미비 선박만 남고, 다시 누르면 전체가 나온다', async () => {
    stubFetch({ 'GET /vessels': jsonResponse({ data: [A, B, FULL] }) })
    renderScreen()
    await screen.findByText('알파호')

    expect(chip().textContent).toContain('2')
    expect(chip().getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(chip())

    expect(chip().getAttribute('aria-pressed')).toBe('true')
    expect(names()).not.toContain('가득호')
    expect(names()).toContain('알파호')

    fireEvent.click(chip())

    expect(chip().getAttribute('aria-pressed')).toBe('false')
    expect(names()).toContain('가득호')
  })

  it('걸러 놓은 상태를 화면이 말한다 — 제목은 계속 불러온 수를 말하기 때문이다', async () => {
    stubFetch({ 'GET /vessels': jsonResponse({ data: [A, B, FULL] }) })
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(chip())

    // 제목은 불러오기의 사실이라 그대로다 — 그 간극을 한 줄이 받는다.
    expect(screen.getByText(/선박 3척/)).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('2')
  })

  it('0척이어도 칩이 남아 있고, 눌러도 막다른 곳이 아니다', async () => {
    stubFetch({ 'GET /vessels': jsonResponse({ data: [FULL] }) })
    renderScreen()
    await screen.findByText('가득호')

    // 자리가 사라지면 「그런 기능이 없다」로 읽힌다. 비활성도 아니다 — §14.
    expect(chip().textContent).toContain('0')
    expect((chip() as HTMLButtonElement).disabled).toBe(false)

    fireEvent.click(chip())

    expect(names()).toEqual([])
    // 빈 목록만 남기지 않는다 — 되돌아가는 길을 문장이 말한다.
    expect(screen.getByRole('status').textContent).toMatch(/다시 누르/)
  })
})


/**
 * 검색 · 선종은 **서버가 거른다** (#1783).
 *
 * 화면에서 거르면 받은 페이지 안에서만 맞아, 찾는 배가 다음 페이지에 있으면
 * 「없다」와 「이 페이지에 없다」가 **같은 모양**이 된다 — `#1741`이 선박 상세 항차
 * 목록에서 화면 정렬을 거절한 이유와 같다.
 */
describe('조회 조건은 쿼리로 간다 (#1783)', () => {
  /**
   * `/vessels` GET을 전부 받아 주고 부른 주소를 모은다. `rows`는 부른 경로를 받는다 —
   * 커서 페이지에 첫 페이지와 같은 배를 돌려주면 같은 key가 두 번 그려진다 (#1616).
   */
  function stubVessels(rows: (path: string) => unknown[]) {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/parameters/fuel-types')) return jsonResponse({ data: [] })
        if ((init?.method ?? 'GET') === 'GET' && url.includes('/vessels')) {
          const path = url.replace(/^.*\/api\/v1/, '')
          urls.push(path)
          return jsonResponse({ data: rows(path), meta: { next_cursor: 'c1', has_more: true } })
        }
        throw new Error(`stub에 없는 요청: ${init?.method ?? 'GET'} ${url}`)
      }),
    )
    return urls
  }

  const search = () => screen.getByTestId('vessel-search') as HTMLInputElement

  it('검색어가 `search` 쿼리로 간다 — 입력이 멈춘 뒤 한 번만', async () => {
    const urls = stubVessels(() => [A, B])
    renderScreen()
    await screen.findByText('알파호')
    expect(urls).toHaveLength(1)

    // 글자마다 보내면 「알파」를 치는 동안 조회가 두 번 나간다.
    fireEvent.change(search(), { target: { value: '알' } })
    fireEvent.change(search(), { target: { value: '알파' } })

    await waitFor(() => expect(urls).toHaveLength(2), { timeout: 2000 })
    expect(decodeURIComponent(urls[1])).toContain('search=알파')
    expect(urls[1]).not.toContain('cursor=')
  })

  it('선종을 고르면 `ship_type`이 간다', async () => {
    const urls = stubVessels(() => [A, B])
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.change(screen.getByTestId('vessel-ship-type'), {
      target: { value: 'BULK_CARRIER' },
    })

    await waitFor(() => expect(urls).toHaveLength(2))
    expect(urls[1]).toContain('ship_type=BULK_CARRIER')
  })

  it('조건이 바뀌면 커서를 버린다 — 다른 조건의 커서는 엉뚱한 자리를 가리킨다', async () => {
    // 커서 페이지는 앞 페이지를 다시 주지 않는다 — 실서버와 같은 모양으로 다른 배를 준다.
    const urls = stubVessels((path) => (path.includes('cursor=') ? [rawVessel('04', '델타호')] : [A, B]))
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.click(await screen.findByRole('button', { name: /더 보기/ }))
    await waitFor(() => expect(urls[1]).toContain('cursor=c1'))

    fireEvent.change(screen.getByTestId('vessel-ship-type'), {
      target: { value: 'BULK_CARRIER' },
    })

    await waitFor(() => expect(urls).toHaveLength(3))
    expect(urls[2]).not.toContain('cursor=')
  })

  it('조건에 걸려 빈 목록이면 「등록된 선박이 없습니다」로 말하지 않는다', async () => {
    let empty = false
    stubVessels(() => (empty ? [] : [A, B]))
    renderScreen()
    await screen.findByText('알파호')

    empty = true
    fireEvent.change(screen.getByTestId('vessel-ship-type'), {
      target: { value: 'BULK_CARRIER' },
    })

    /*
     * 두 상태에서 사용자가 할 일이 정반대다 — 배를 등록한다 ↔ 조건을 지운다.
     */
    expect(await screen.findByText(/조건에 맞는 선박이 없습니다/)).toBeTruthy()
    expect(screen.queryByText(/등록된 선박이 없습니다/)).toBeNull()
  })

  it('걸린 조건이 보이고, 지우면 전체로 돌아간다', async () => {
    const urls = stubVessels(() => [A, B])
    renderScreen()
    await screen.findByText('알파호')

    fireEvent.change(search(), { target: { value: '알파' } })
    await waitFor(() => expect(urls).toHaveLength(2), { timeout: 2000 })

    // 걸어 놓고 잊는 것이 필터의 주된 사고다 — 무엇이 걸렸는지 화면이 말한다.
    const chip = await screen.findByRole('button', { name: /검색 「알파」/ })
    fireEvent.click(chip)

    await waitFor(() => expect(search().value).toBe(''))
    await waitFor(() => expect(urls).toHaveLength(3))
    expect(urls[2]).not.toContain('search=')
  })

  it('조건에 걸려 목록이 비어도 조건을 지울 수 있다 — 도구 줄이 카드 밖이다', async () => {
    let empty = false
    stubVessels(() => (empty ? [] : [A, B]))
    renderScreen()
    await screen.findByText('알파호')

    empty = true
    fireEvent.change(screen.getByTestId('vessel-ship-type'), {
      target: { value: 'BULK_CARRIER' },
    })
    await screen.findByText(/조건에 맞는 선박이 없습니다/)

    // 카드가 사라져도 검색칸·선종·걸린 조건은 남아 있다.
    expect(screen.getByTestId('vessel-search')).toBeTruthy()
    expect(screen.getByRole('button', { name: /선종 벌크선/ })).toBeTruthy()
  })
})

/**
 * 올해 누적 등급 열 (#2018).
 *
 * 등급은 `/vessels`가 아니라 대시보드와 같은 `/fleet/summary`에서 받아 **선박 번호로
 * 찾아 붙인다**(`gradeLookup.ts`). 화면에서 지키는 것:
 *
 * - 요약이 실패해도 **목록은 뜬다** — 이 화면의 일은 제원을 고치는 것이다
 * - 「받지 못함」과 서버 사유(「실적 없음」 등)를 **다른 말**로 그린다
 * - 검색·선종은 요약과 무관하게 `/vessels`가 거른다 — 조건이 바뀌어도 요약을 다시 받지 않는다
 *
 * 문구는 리터럴로 단언하지 않는다(`AGENTS §4.6`) — 대시보드 문구 함수와 **같은 값인지**,
 * 서로 **다른지**를 본다.
 */
describe('올해 누적 등급 열 (#2018)', () => {
  const RATED_ID = '00000000-0000-4000-8000-00000000000a'
  const SPEC_ID = '00000000-0000-4000-8000-00000000000b'
  const NEW_ID = '00000000-0000-4000-8000-00000000000c'

  function listVessel(id: string, name: string) {
    return {
      id,
      imo_number: `9${id.slice(-6)}`,
      name,
      ship_type: 'BULK_CARRIER',
      deadweight: 50000,
      gross_tonnage: 30000,
      is_cii_applicable_hint: true,
      reference_speed_kn: 12,
      reference_daily_foc_ton: 20,
      block_coefficient: null,
      call_sign: null,
      default_fuel_type: 'HFO',
      underway_state: 'NOT_UNDER_WAY',
      detail_status: null,
    }
  }

  function summaryVessel(id: string, name: string, rating: string | null, reason: string | null) {
    return {
      vessel_id: id,
      name,
      ship_type: 'BULK_CARRIER',
      imo_number: '9000015',
      underway_state: null,
      detail_status: null,
      current_lat: null,
      current_lon: null,
      position_updated_at: null,
      data_available: rating !== null,
      unavailable_reason: reason,
      ytd_attained_cii: rating === null ? null : '5.123456',
      ytd_required_cii: rating === null ? null : '5.000000',
      ytd_rating: rating,
      risk_level: null,
      risk_reasons: [],
      days_to_d: null,
      days_to_d_reason: null,
    }
  }

  const DEFAULT_SUMMARY = () => [
    summaryVessel(RATED_ID, '가등급호', 'E', null),
    summaryVessel(SPEC_ID, '나제원호', null, 'MISSING_SPEC'),
  ]

  function summaryResponse(vessels = DEFAULT_SUMMARY()) {
    return jsonResponse({
      data: {
        as_of: '2026-09-28T00:00:00Z',
        regulation_year: 2026,
        summary: { total: vessels.length },
        vessels,
      },
      meta: { has_more: false, next_cursor: null },
    })
  }

  /**
   * `summaryReplies`는 **두 번째 요약 요청부터** 차례로 쓴다(제원 저장 뒤 다시 받기).
   * 첫 요청은 `summaryStatus` · `summaryVessels`를 따른다 — `firstSummary`를 주면 그 응답을 쥔다.
   */
  function stubServer({
    summaryStatus = 200,
    summaryVessels,
    listVessels,
    summaryReplies = [],
    firstSummary,
  }: {
    summaryStatus?: number
    summaryVessels?: ReturnType<typeof summaryVessel>[]
    listVessels?: ReturnType<typeof listVessel>[]
    summaryReplies?: (Response | Deferred)[]
    firstSummary?: Deferred
  } = {}) {
    const urls: string[] = []
    let summaryCalls = 0
    const list = listVessels ?? [
      listVessel(NEW_ID, '다신규호'),
      listVessel(SPEC_ID, '나제원호'),
      listVessel(RATED_ID, '가등급호'),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        urls.push(url)
        if (url.includes('/parameters/fuel-types')) {
          return jsonResponse({
            data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
          })
        }
        if (url.includes('/fleet/summary')) {
          summaryCalls += 1
          if (summaryCalls === 1 && firstSummary !== undefined) return firstSummary.promise
          if (summaryCalls > 1 && summaryReplies.length > 0) {
            const reply = summaryReplies.shift()!
            return 'promise' in reply ? reply.promise : reply
          }
          if (summaryStatus !== 200) {
            return jsonResponse({ error: { code: 'INTERNAL_ERROR' } }, summaryStatus)
          }
          return summaryResponse(summaryVessels)
        }
        if (init?.method === 'PATCH') {
          const id = url.split('/').pop()
          const target = list.find((v) => v.id === id)!
          return jsonResponse({ data: { ...target, reference_speed_kn: 13 } })
        }
        return jsonResponse({ data: list, meta: {} })
      }),
    )
    return urls
  }

  async function renderScreen() {
    render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText('가등급호')
  }

  const gradeCell = (name: string) =>
    (screen.getByText(name).closest('.vm__item') as HTMLElement).querySelector(
      '.vm__grade',
    ) as HTMLElement

  it('값이 있는 배는 등급 배지와 누적 CII, 값이 없는 배는 대시보드와 같은 사유를 보인다', async () => {
    stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))

    expect(within(gradeCell('가등급호')).getByRole('img', { name: /E/ })).toBeTruthy()
    expect(gradeCell('가등급호').textContent).toContain(ytdCiiText('5.123456'))

    const spec = gradeCell('나제원호')
    expect(spec.dataset.gradeState).toBe('unavailable')
    // 대시보드 문구 함수와 같은 값이다 — 베끼면 두 화면이 갈린다.
    expect(spec.textContent).toContain(unavailableText('MISSING_SPEC'))
    // 배지 대신 문구다 — 배지(img)가 없다.
    expect(within(spec).queryByRole('img')).toBeNull()
    // 할 일 문장(`unavailableHint`)은 행에 넣지 않는다 — 화면에도, 낭독에도, 툴팁에도 (디자인 ⑵).
    expect(spec.textContent).not.toContain(unavailableHint('MISSING_SPEC'))
    expect(spec.getAttribute('title')).toBeNull()
    expect(document.body.textContent).not.toContain(unavailableHint('MISSING_SPEC'))

    // 요약에 없는 배(요약 뒤 등록 등)는 받지 못함도 계산 못 함도 아니다.
    expect(gradeCell('다신규호').dataset.gradeState).toBe('absent')
  })

  const REASONS = ['NO_DATA', 'MISSING_SPEC', 'NO_PARAMETERS', 'CALCULATION_ERROR'] as const

  it('요약이 실패해도 목록은 뜨고, 등급 칸은 `—`만 — 받지 못한 사실은 목록 위 한 줄이 한 번 말한다', async () => {
    stubServer({ summaryStatus: 500 })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('failed'))

    // 목록은 그대로 — 세 척 모두 있고 수정·삭제 메뉴도 있다. 화면 단위 오류가 아니다.
    expect(screen.getByText('나제원호')).toBeTruthy()
    expect(screen.getByText('다신규호')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /더보기$/ })).toHaveLength(3)
    expect(screen.queryByRole('alert')).toBeNull()

    // 칸은 세 척 모두 같은 `—` — 값이 없는 다른 칸(기준속도 등)과 같은 표시다.
    const cells = ['가등급호', '나제원호', '다신규호'].map((name) => gradeCell(name))
    for (const cell of cells) {
      expect(cell.dataset.gradeState).toBe('failed')
      expect(cell.textContent?.replace('올해 누적 등급', '').trim()).toBe(MISSING)
    }

    // 목록 위 한 줄은 **하나**이고 행 안에 있지 않다.
    const lines = screen.getAllByTestId('grade-failed-line')
    expect(lines).toHaveLength(1)
    expect(lines[0].closest('.vm__list')).toBeNull()
    const lineText = (lines[0].textContent ?? '').replace(GRADE_RETRY_TEXT, '').trim()
    // 그 문장은 행에 반복되지 않는다.
    for (const cell of cells) expect(cell.textContent).not.toContain(lineText)

    // 「받지 못함」과 「계산하지 못함」이 문장에서 갈린다 — 서버 사유 문구를 쓰지 않는다.
    for (const reason of REASONS) {
      expect(lineText).not.toContain(unavailableText(reason))
      expect(lineText).not.toBe(unavailableHint(reason))
    }
  })

  it('받지 못했을 때 「다시 시도」(텍스트 버튼)가 요약을 다시 묻고, 성공하면 한 줄이 걷힌다', async () => {
    const urls = stubServer({ summaryStatus: 500, summaryReplies: [summaryResponse()] })
    await renderScreen()
    const line = await screen.findByTestId('grade-failed-line')
    const retry = within(line).getByRole('button', { name: GRADE_RETRY_TEXT })
    expect(retry.className).toContain('vm__retry')

    fireEvent.click(retry)
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    expect(urls.filter((u) => u.includes('/fleet/summary'))).toHaveLength(2)
    expect(screen.queryByTestId('grade-failed-line')).toBeNull()
  })

  it('받지 못한 동안 등급순 선택지는 잠기고 사유를 함께 낸다 (DESIGN_SYSTEM §14)', async () => {
    stubServer({ summaryStatus: 500 })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('failed'))

    const option = screen
      .getByTestId('vessel-sort')
      .querySelector('option[value="grade"]') as HTMLOptionElement
    expect(option.disabled).toBe(true)
    // 잠긴 선택지는 짧은 꼬리를 달고, 사유 문장은 목록 위 한 줄이 갖는다 — 정렬 칸이
    // 그 줄을 가리켜 낭독에도 닿는다. 이름만 남은 잠긴 선택지는 왜 안 되는지 말하지 않는다.
    expect(option.textContent).toContain(GRADE_SORT_DISABLED_SUFFIX)
    const describedBy = screen.getByTestId('vessel-sort').getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    const reasonLine = document.getElementById(describedBy!)
    expect(reasonLine!.closest('[data-testid="grade-failed-line"]')).toBe(
      screen.getByTestId('grade-failed-line'),
    )
    expect(reasonLine!.textContent).toContain(GRADE_SORT_DISABLED_REASON)
    // 다른 정렬은 그대로 쓸 수 있다.
    const others = [...screen.getByTestId('vessel-sort').querySelectorAll('option')].filter(
      (o) => o.value !== 'grade',
    )
    expect(others.every((o) => !o.disabled)).toBe(true)
  })

  it('받았으면 등급순 선택지는 열려 있다', async () => {
    stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    const option = screen
      .getByTestId('vessel-sort')
      .querySelector('option[value="grade"]') as HTMLOptionElement
    expect(option.disabled).toBe(false)
    expect(option.textContent).not.toContain(GRADE_SORT_DISABLED_SUFFIX)
    expect(screen.getByTestId('vessel-sort').getAttribute('aria-describedby')).toBeNull()
  })

  /**
   * 칸 순서 · 머리글 정렬 (디자인 ⑴ · `#2015`).
   *
   * 목록은 `<table>`이 아니라 `<ul>` + 그리드라 `test/tableColumns.ts`(thead 기준)를 쓸 수
   * 없다 — 같은 대조를 머리줄(`.vm__head`)의 칸과 각 행(`.vm__row`)의 같은 번째 칸으로 한다.
   */
  /*
   * 10/7 개편(#2316)으로 열이 다섯이 됐다 — 선종은 이름 아래 제원 줄로 들어가고, 등급 칸은
   * 머리글 「올해 누적」으로 「선박」과 「운항」 사이에 선다. 지키는 것은 그대로다:
   * 등급 칸이 선박 바로 다음이고, 머리글과 값이 같은 열·같은 정렬 클래스다.
   */
  it('등급 칸(「올해 누적」)은 「선박」 다음 · 「운항」 앞이고, 머리글과 값이 같은 정렬 클래스를 받는다', async () => {
    stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))

    const heads = [...document.querySelectorAll('.vm__head > *')]
    const labels = heads.map((el) => (el.textContent ?? '').trim())
    const at = labels.indexOf('올해 누적')
    expect(at).toBeGreaterThan(0)
    expect(labels[at - 1]).toBe('선박')
    expect(labels[at + 1]).toBe('운항')

    // 같은 번째 칸이 행마다 등급 칸이다 — 머리글과 값이 한 열에 선다.
    const rows = [...document.querySelectorAll('.vm__row')]
    expect(rows).toHaveLength(3)
    for (const row of rows) {
      expect(row.children[at].classList.contains('vm__grade')).toBe(true)
      // 머리글과 값이 **같은** 정렬 클래스 — 한쪽에만 걸면 `#2015`다.
      expect(row.children[at].classList.contains('vm__num')).toBe(
        heads[at].classList.contains('vm__num'),
      )
    }
    expect(heads[at].classList.contains('vm__num')).toBe(true)
    // 기준 CII는 싣지 않는다 — 요약 응답의 `ytd_required_cii`(5.000000)가 칸에 없다.
    expect(gradeCell('가등급호').textContent).not.toContain(ytdCiiText('5.000000'))
  })

  it('선종 조건은 `/vessels`가 거르고, 요약은 다시 받지 않는다', async () => {
    const urls = stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))

    fireEvent.change(screen.getByTestId('vessel-ship-type'), {
      target: { value: 'BULK_CARRIER' },
    })
    await waitFor(() =>
      expect(urls.some((u) => u.includes('/vessels?') && u.includes('ship_type=BULK_CARRIER'))).toBe(
        true,
      ),
    )
    expect(urls.filter((u) => u.includes('/fleet/summary'))).toHaveLength(1)
    // 요약에는 목록 조건을 보내지 않는다 — 그 경로에는 검색·선종 필터가 없다(`API_SPEC §2.8`).
    expect(urls.find((u) => u.includes('/fleet/summary'))).not.toContain('ship_type')
  })

  it('등급 나쁜 순 — E가 위, 등급이 없는 배는 아래', async () => {
    stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))

    fireEvent.change(screen.getByTestId('vessel-sort'), { target: { value: 'grade' } })
    const names = [...document.querySelectorAll('.vm__item .vm__name')].map((el) => el.textContent)
    expect(names[0]).toBe('가등급호')
  })

  it('등급 나쁜 순 — 등급이 없는 배는 목록 이름순보다 앞서도 끝으로 간다', async () => {
    const A_ID = '00000000-0000-4000-8000-00000000000d'
    stubServer({
      // 목록 순서상 등급 없는 배가 맨 앞이다 — 그래도 끝으로 가야 한다.
      listVessels: [
        listVessel(NEW_ID, '다신규호'),
        listVessel(SPEC_ID, '나제원호'),
        listVessel(A_ID, '라에이호'),
        listVessel(RATED_ID, '가등급호'),
      ],
      summaryVessels: [
        summaryVessel(RATED_ID, '가등급호', 'E', null),
        summaryVessel(A_ID, '라에이호', 'A', null),
        summaryVessel(SPEC_ID, '나제원호', null, 'MISSING_SPEC'),
      ],
    })
    await renderScreen()
    await waitFor(() => expect(gradeCell('라에이호').dataset.gradeState).toBe('rated'))

    fireEvent.change(screen.getByTestId('vessel-sort'), { target: { value: 'grade' } })
    const names = [...document.querySelectorAll('.vm__item .vm__name')].map((el) => el.textContent)
    expect(names.slice(0, 2)).toEqual(['가등급호', '라에이호'])
    expect(new Set(names.slice(2))).toEqual(new Set(['나제원호', '다신규호']))
  })

  /** 가등급호의 제원을 저장한다 — 기준속도만 바꾼다. */
  async function saveRatedVessel() {
    editFrom('가등급호')
    fireEvent.change(within(editPanel()).getByLabelText(/기준속도/), {
      target: { value: '13' },
    })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))
    await screen.findByText(/가등급호의 정보를 저장했습니다/)
  }

  it('제원을 저장하면 요약을 다시 받는다', async () => {
    const urls = stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))

    await saveRatedVessel()
    await waitFor(() =>
      expect(urls.filter((u) => u.includes('/fleet/summary'))).toHaveLength(2),
    )
  })

  it('다시 받는 동안 값이 있던 칸은 「불러오는 중」으로 되돌아가지 않고, 등급순도 흩어지지 않는다', async () => {
    const refetch = deferred()
    stubServer({ summaryReplies: [refetch] })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    fireEvent.change(screen.getByTestId('vessel-sort'), { target: { value: 'grade' } })

    await saveRatedVessel()
    // 응답을 쥐고 있는 동안 — 직전 표가 그대로다.
    expect(gradeCell('가등급호').dataset.gradeState).toBe('rated')
    expect(gradeCell('나제원호').dataset.gradeState).toBe('unavailable')
    const names = [...document.querySelectorAll('.vm__item .vm__name')].map((el) => el.textContent)
    expect(names[0]).toBe('가등급호')

    await act(async () => {
      refetch.resolve(
        summaryResponse([
          summaryVessel(RATED_ID, '가등급호', 'D', null),
          summaryVessel(SPEC_ID, '나제원호', null, 'MISSING_SPEC'),
        ]),
      )
    })
    // 응답이 오면 새 표로 바뀐다.
    await waitFor(() =>
      expect(within(gradeCell('가등급호')).getByRole('img', { name: /D/ })).toBeTruthy(),
    )
  })

  it('다시 받기가 실패하면 직전 값을 지우지 않고, 새로 고치지 못했다는 한 줄만 더한다', async () => {
    stubServer({ summaryReplies: [jsonResponse({ error: { code: 'INTERNAL_ERROR' } }, 500)] })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    expect(screen.queryByTestId('grade-failed-line')).toBeNull()

    await saveRatedVessel()
    const line = await screen.findByTestId('grade-failed-line')
    // 처음 받기 실패와 다른 문장이다 — 칸이 빈 것이 아니라 직전 값이 남아 있다.
    expect(line.textContent).not.toContain(GRADE_FAILED_LINE)
    expect(within(line).getByRole('button', { name: GRADE_RETRY_TEXT })).toBeTruthy()
    // 칸은 「받지 못함」이 아니라 직전 값 그대로다.
    expect(gradeCell('가등급호').dataset.gradeState).toBe('rated')
    expect(within(gradeCell('가등급호')).getByRole('img', { name: /E/ })).toBeTruthy()
    expect(gradeCell('나제원호').dataset.gradeState).toBe('unavailable')
  })

  /** 낭독되는 글 — 이름이 붙은 그림(`role="img"`)은 그 이름으로, 나머지는 글자로 읽는다. */
  function spokenText(el: Element): string {
    if (el.getAttribute('role') === 'img') return el.getAttribute('aria-label') ?? ''
    return [...el.childNodes]
      .map((node) => (node instanceof Element ? spokenText(node) : (node.textContent ?? '')))
      .join('')
  }

  it('값이 있는 칸은 「올해 누적 등급」을 한 번만 읽는다 — 배지 이름이 이미 말한다', async () => {
    stubServer()
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    expect(spokenText(gradeCell('가등급호')).split('올해 누적 등급')).toHaveLength(2)
    // 값이 없는 칸은 배지가 없어 접두어를 그대로 둔다 — 역시 한 번이다.
    expect(spokenText(gradeCell('나제원호')).split('올해 누적 등급')).toHaveLength(2)
  })

  it('다시 받기 실패 줄은 낭독에 알리고(role="status"), 처음 받기 실패 줄은 알리지 않는다', async () => {
    stubServer({ summaryReplies: [jsonResponse({ error: { code: 'INTERNAL_ERROR' } }, 500)] })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('rated'))
    await saveRatedVessel()
    const refreshLine = await screen.findByTestId('grade-failed-line')
    const status = within(refreshLine).getByRole('status')
    expect(status.textContent).toContain(GRADE_REFRESH_FAILED_TEXT)
    // 알림은 문장만 — 버튼 이름까지 읽지 않는다.
    expect(status.textContent).not.toContain(GRADE_RETRY_TEXT)
  })

  it('처음 받기 실패 줄에는 낭독 알림이 없다', async () => {
    stubServer({ summaryStatus: 500 })
    await renderScreen()
    const line = await screen.findByTestId('grade-failed-line')
    expect(within(line).queryByRole('status')).toBeNull()
  })

  it('잠긴 등급순의 사유(`aria-describedby`)는 문장만 가리키고 「다시 시도」를 포함하지 않는다', async () => {
    stubServer({ summaryStatus: 500 })
    await renderScreen()
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('failed'))
    const describedBy = screen.getByTestId('vessel-sort').getAttribute('aria-describedby')
    const reason = document.getElementById(describedBy!)!
    expect(reason.textContent).toContain(GRADE_SORT_DISABLED_REASON)
    expect(reason.textContent).not.toContain(GRADE_RETRY_TEXT)
    expect(reason.querySelector('button')).toBeNull()
  })

  it('받는 동안 등급순을 골랐는데 받지 못하면 기본 정렬로 되돌아간다', async () => {
    const first = deferred()
    stubServer({ firstSummary: first })
    await renderScreen()
    const select = screen.getByTestId('vessel-sort') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'grade' } })
    expect(select.value).toBe('grade')

    await act(async () => {
      first.resolve(jsonResponse({ error: { code: 'INTERNAL_ERROR' } }, 500))
    })
    await waitFor(() => expect(gradeCell('가등급호').dataset.gradeState).toBe('failed'))
    // 잠긴 선택지가 선택된 채로 남지 않는다 — 기본값(`useState` 초기값)으로 돌아간다.
    expect(select.value).toBe('gaps')
    expect((select.querySelector('option[value="grade"]') as HTMLOptionElement).disabled).toBe(true)
  })

  it('응답을 기다리는 중에 화면을 떠나면, 늦게 온 응답은 아무것도 갱신하지 않는다', async () => {
    const first = deferred()
    stubServer({ firstSummary: first })
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = render(
      <MemoryRouter>
        <VesselManagement />
      </MemoryRouter>,
    )
    await screen.findByText('가등급호')
    unmount()
    await act(async () => {
      first.resolve(summaryResponse())
    })
    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })

  it('앞 요청이 늦게 와도 뒤 요청의 표를 덮지 않는다 — 「다시 시도」 뒤 저장으로 겹친 두 요청', async () => {
    const retryReply = deferred()
    const saveReply = deferred()
    stubServer({ summaryStatus: 500, summaryReplies: [retryReply, saveReply] })
    await renderScreen()
    const line = await screen.findByTestId('grade-failed-line')
    fireEvent.click(within(line).getByRole('button', { name: GRADE_RETRY_TEXT }))
    await saveRatedVessel()

    // 뒤 요청(저장 뒤 다시 받기)이 먼저 온다 — D.
    await act(async () => {
      saveReply.resolve(
        summaryResponse([
          summaryVessel(RATED_ID, '가등급호', 'D', null),
          summaryVessel(SPEC_ID, '나제원호', null, 'MISSING_SPEC'),
        ]),
      )
    })
    await waitFor(() =>
      expect(within(gradeCell('가등급호')).getByRole('img', { name: /D/ })).toBeTruthy(),
    )
    // 앞 요청(다시 시도)이 뒤늦게 온다 — E. 버린다.
    await act(async () => {
      retryReply.resolve(summaryResponse())
    })
    expect(within(gradeCell('가등급호')).getByRole('img', { name: /D/ })).toBeTruthy()
    expect(within(gradeCell('가등급호')).queryByRole('img', { name: /E/ })).toBeNull()
  })

  it('공식 등급이 아님을 알리는 면책 배너가 있다 (PRD §3.3.7 각주 · §6.3)', async () => {
    stubServer()
    await renderScreen()
    expect(screen.getByRole('note')).toBeTruthy()
  })
})

/**
 * 목록을 바꾸면 셸에 알린다 (#2119).
 *
 * 상단 선박 선택기의 목록은 셸이 mount할 때 한 번 부른다(`#1643`). 이 화면이 선명을
 * 바꾸거나 선박을 지우고도 알리지 않아, 선택기에 **옛 이름과 지운 배**가 새로고침할
 * 때까지 남았다. 셸 대역을 넣어 호출 자체를 본다 — 화면 안의 목록은 이미 맞게 바뀌므로
 * 화면만 봐서는 드러나지 않는다.
 */
describe('목록을 바꾸면 상단 선택기를 다시 부르게 한다 (#2119)', () => {
  function renderInShell(shell: ShellContext) {
    render(
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={shell} />}>
            <Route path="/" element={<VesselManagement />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  function shellWith(vesselId: string | null) {
    const refreshVessels = vi.fn()
    const selectVesselId = vi.fn()
    return { shell: { ...EMPTY_SHELL_CONTEXT, vesselId, refreshVessels, selectVesselId }, refreshVessels, selectVesselId }
  }

  beforeEach(() => {
    vi.stubGlobal('confirm', () => true)
  })

  it('저장에 성공하면 부른다 — 실패하면 부르지 않는다', async () => {
    const { shell, refreshVessels } = shellWith(null)
    stubFetch({
      [`PATCH /vessels/${A.id}`]: jsonResponse({ data: { ...A, name: '알파호 개명' } }),
      [`PATCH /vessels/${B.id}`]: jsonResponse(
        { error: { code: 'VALIDATION_ERROR', message: '선명이 너무 깁니다.', details: [{ field: 'name' }] } },
        422,
      ),
    })
    renderInShell(shell)
    await screen.findByText('알파호')

    editFrom('브라보호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), { target: { value: '브라보호 개명' } })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))
    await within(editPanel()).findByRole('alert')
    expect(refreshVessels).not.toHaveBeenCalled()

    editFrom('알파호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), { target: { value: '알파호 개명' } })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))
    await screen.findByText('알파호 개명')
    expect(refreshVessels).toHaveBeenCalledTimes(1)
  })

  it('삭제에 성공하면 부른다 — 선택돼 있지 않던 배라면 선택은 건드리지 않는다', async () => {
    const { shell, refreshVessels, selectVesselId } = shellWith(B.id)
    stubFetch({ [`DELETE /vessels/${A.id}`]: jsonResponse(null, 204) })
    renderInShell(shell)
    await screen.findByText('알파호')

    deleteFrom('알파호')
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    expect(refreshVessels).toHaveBeenCalledTimes(1)
    expect(selectVesselId).not.toHaveBeenCalled()
  })

  it('지운 배가 상단에서 선택돼 있었으면 선택을 푼다', async () => {
    const { shell, refreshVessels, selectVesselId } = shellWith(A.id)
    stubFetch({ [`DELETE /vessels/${A.id}`]: jsonResponse(null, 204) })
    renderInShell(shell)
    await screen.findByText('알파호')

    deleteFrom('알파호')
    await waitFor(() => expect(screen.queryByText('알파호')).toBeNull())
    expect(selectVesselId).toHaveBeenCalledWith(null)
    expect(refreshVessels).toHaveBeenCalledTimes(1)
  })

  it('삭제에 실패하면 부르지 않는다', async () => {
    const { shell, refreshVessels, selectVesselId } = shellWith(A.id)
    stubFetch({
      [`DELETE /vessels/${A.id}`]: jsonResponse({ error: { code: 'CONFLICT', message: '지울 수 없습니다.' } }, 409),
    })
    renderInShell(shell)
    await screen.findByText('알파호')

    deleteFrom('알파호')
    await screen.findByText('지울 수 없습니다.')
    expect(refreshVessels).not.toHaveBeenCalled()
    expect(selectVesselId).not.toHaveBeenCalled()
  })
})

describe('서버 오류의 자리와 연료 목록 실패 (#2126)', () => {
  it('폼에 없는 field의 422는 폼 상단 일반 오류로 보인다 — 문구가 사라지지 않는다', async () => {
    stubFetch({
      [`PATCH /vessels/${A.id}`]: jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'SERVER-SAID-THIS',
            details: [{ field: 'not_a_form_field' }],
          },
        },
        422,
      ),
    })
    renderScreen()
    await screen.findByText('알파호')

    editFrom('알파호')
    fireEvent.change(within(editPanel()).getByLabelText('선명'), {
      target: { value: '알파호 개명' },
    })
    fireEvent.click(within(editPanel()).getByRole('button', { name: '저장' }))

    const alert = await within(editPanel()).findByRole('alert')
    expect(alert.textContent).toContain('SERVER-SAID-THIS')
    // 폼 밖에 같은 실패를 한 번 더 말하지 않는다.
    expect(screen.queryByText(/알파호의 정보를 저장하지 못했습니다/)).toBeNull()
  })

  it('연료 목록을 받지 못해도 「기본 연료」 칸은 실제 값을 말하고 목록 실패를 함께 알린다', async () => {
    const withFuel = { ...A, default_fuel_type: 'HFO' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/fuel-types')) return jsonResponse({}, 500)
        return jsonResponse({ data: [withFuel], meta: {} })
      }),
    )
    renderScreen()
    await screen.findByText('알파호')
    editFrom('알파호')

    const select = (await within(editPanel()).findByLabelText('기본 연료')) as HTMLSelectElement
    // 상태 값(HFO)이 그대로이고, 화면이 고른 옵션도 그 값이다 — 첫 옵션(실패 안내)이 아니다.
    expect(select.value).toBe('HFO')
    expect(select.selectedOptions[0]?.value).toBe('HFO')
    // 목록 실패는 칸 곁에 따로 적힌다.
    await within(editPanel()).findByText(FUEL_LIST_FAILED_HINT)
  })
})
