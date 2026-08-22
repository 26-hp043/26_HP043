// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { VoyageCiiForm } from './VoyageCiiForm'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'

/**
 * 기능① 입력 폼의 **배선** 검증 (#557).
 *
 * ## 이 파일이 보는 층
 *
 * 규칙(`formRules.ts`)과 데이터 경계(`yearCatalog`·`fuelCatalog`)는 각각 순수 함수·
 * provider 테스트가 이미 잠근다. **여기서 보는 것은 그 사이의 배선**이다 — 효과가
 * 실제로 도는가, 받은 목록이 셀렉트에 들어가는가, 효과가 한 번만 도는가.
 *
 * 그 층은 종전에 **아무 테스트도 없었다.** 화면 PR이 「브라우저에서 확인하지
 * 못했습니다」를 여섯 번 연속 한계로 적은 자리가 정확히 여기다.
 *
 * ## 서버는 `fetch` 스텁으로 흉내 낸다
 *
 * 경로별로 응답을 나눈다. 실제 서버 형태는 각 provider 테스트가 잠그므로 여기서는
 * **화면이 그 값을 어떻게 쓰는지**만 본다.
 */

interface Call {
  url: string
}

function stubServer() {
  const calls: Call[] = []
  const fetchImpl = vi.fn(async (input: unknown) => {
    const url = String(input)
    calls.push({ url })
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: [{ year: 2026 }, { year: 2027 }, { year: 2030 }] })
    }
    if (url.includes('/parameters/fuel-types')) {
      return jsonResponse({
        data: [
          { code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true },
          { code: 'LNG', display_name: '액화천연가스', cf: '2.750', unit: 't', is_active: true },
        ],
      })
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return { calls, fetchImpl }
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

/** 셸이 내려주는 컨텍스트를 흉내 낸 라우트. 화면은 `useOutletContext`로 읽는다. */
function renderForm(context: Partial<ShellContext> = {}) {
  const value: ShellContext = {
    ...EMPTY_SHELL_CONTEXT,
    vesselId: '00000000-0000-4000-8000-000000000001',
    vessels: [
      { id: '00000000-0000-4000-8000-000000000001', displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' },
    ],
    vesselsState: 'ready',
    selectVesselId: () => {},
    ...context,
  }
  return render(
    <MemoryRouter initialEntries={['/voyage-cii']}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/voyage-cii" element={<VoyageCiiForm />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('연도 셀렉트 — 서버 목록이 화면에 들어간다', () => {
  it('규제연도 옵션이 서버가 준 값으로 채워진다', async () => {
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/규제연도/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '2026',
      '2027',
      '2030',
    ])
  })
})

describe('연료 셀렉트 — 서버 목록이 화면에 들어간다 (#542 · #568)', () => {
  it('연료 옵션이 서버가 준 값으로 채워진다', async () => {
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/연료 종류/)
    // 첫 옵션은 「선택해 주세요」다.
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    // **서버가 주는 것은 코드 집합이고, 이름은 화면이 붙인다** (`#598`).
    // 종전에는 `display_name`을 그대로 그려 `Heavy Fuel Oil (HFO)`가 나왔다.
    expect(select.textContent).toContain('중유 (HFO)')
    expect(select.textContent).toContain('액화천연가스 (LNG)')
    // 서버 목록에 없는 연료는 나오지 않는다 — 이름을 화면이 갖는다고 8종이
    // 전부 나오면 고정표로 돌아간 것이다.
    expect(select.textContent).not.toContain('메탄올')
  })

  it('종전 고정표 8종이 아니라 서버가 준 2종만 나온다', async () => {
    // 고정표(`referenceTable.ts`)를 읽던 시절에는 서버 목록과 무관하게 늘 8종이었다.
    stubServer()

    renderForm()

    const select = await screen.findByLabelText(/연료 종류/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    expect(select.textContent).not.toContain('메탄올')
    // 서버가 준 `display_name`(여기서는 「고유황유」)은 화면에 그대로 나가지 않는다 —
    // `MEPC.364(79)` 원문 표기가 실리는 자리라 표시 문구와 별개다 (`AGENTS §4.6`).
    expect(select.textContent).not.toContain('고유황유')
  })
})

describe('효과가 한 번만 돈다 — 무한 루프 회귀 (#484 · #557)', () => {
  /*
   * `#484`가 무한 렌더 루프를 **설계로** 막았다(값의 정체성 고정 + 참조로 최신값 읽기).
   * 그 설계가 실제로 한 번만 도는지는 확인된 적이 없다 — 이슈 본문이 그 사실을 적었다.
   *
   * 루프가 생기면 같은 GET이 끝없이 나가므로 **호출 횟수**가 그 신호다.
   */
  it('연도·연료 조회가 각각 한 번씩만 나간다', async () => {
    const { calls } = stubServer()

    renderForm()

    await screen.findByLabelText(/규제연도/)
    await screen.findByLabelText(/연료 종류/)
    // 효과가 다시 돌 시간을 준다. 루프가 있으면 이 사이에 호출이 쌓인다.
    await new Promise((resolve) => setTimeout(resolve, 120))

    const years = calls.filter((c) => c.url.includes('regulation-years'))
    const fuels = calls.filter((c) => c.url.includes('fuel-types'))
    expect(years).toHaveLength(1)
    expect(fuels).toHaveLength(1)
  })
})

describe('선박이 없으면 조회하지 않는다', () => {
  it('셸이 선박을 안 주면 연도 조회가 나가지 않는다', async () => {
    const { calls } = stubServer()

    renderForm({ vesselId: null, vessels: [], vesselsState: 'ready' })
    await new Promise((resolve) => setTimeout(resolve, 120))

    expect(calls.filter((c) => c.url.includes('regulation-years'))).toHaveLength(0)
  })
})
