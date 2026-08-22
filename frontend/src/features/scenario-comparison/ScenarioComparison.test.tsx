// @vitest-environment jsdom
import '../../test/renderSetup'

import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { ScenarioComparison } from './ScenarioComparison'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from '../../layout/shellContext'

/**
 * 항로 비교 화면의 **선택지 배선** (#632).
 *
 * 이 화면만 규제연도를 자유 입력으로 받았다. 다른 두 화면(`VoyageCiiForm`·
 * `AnnualSimulation`)은 서버 목록으로 셀렉트를 만드는데, 여기서는 텍스트 입력이라
 * **파라미터가 없는 해를 넣을 수 있었고 그때 서버가 `PARAMETER_ERROR`로 거부**했다.
 *
 * `#236`이 「선박·연도·연료」 세 축을 고치며 연도만 유예했고, `#534`가 두 화면을
 * 옮기며 이 화면을 빠뜨린 것이다.
 *
 * 구성은 `VoyageCiiForm.test.tsx`와 같다 — 규칙과 데이터 경계는 각각 순수 함수·
 * provider 테스트가 잠그고, **여기서는 그 사이의 배선**만 본다.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function stubServer(years: number[] = [2026, 2027, 2030]) {
  const fetchImpl = vi.fn(async (input: unknown) => {
    const url = String(input)
    if (url.includes('/parameters/regulation-years')) {
      return jsonResponse({ data: years.map((year) => ({ year })) })
    }
    if (url.includes('/parameters/fuel-types')) {
      return jsonResponse({
        data: [{ code: 'HFO', display_name: '고유황유', cf: '3.114', unit: 't', is_active: true }],
      })
    }
    return jsonResponse({ data: {} })
  })
  vi.stubGlobal('fetch', fetchImpl)
  return fetchImpl
}

function renderScreen(context: Partial<ShellContext> = {}) {
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
    <MemoryRouter initialEntries={['/scenarios']}>
      <Routes>
        <Route element={<Outlet context={value} />}>
          <Route path="/scenarios" element={<ScenarioComparison />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('규제연도 — 자유 입력이 아니라 서버 목록이다 (#632)', () => {
  it('셀렉트를 그리고 서버가 준 해로 채운다', async () => {
    stubServer()

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    expect(select.tagName).toBe('SELECT')
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(3))
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '2026',
      '2027',
      '2030',
    ])
  })

  it('텍스트 입력이 남아 있지 않다 — 없는 해를 넣을 수 있던 경로다', async () => {
    stubServer()

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    expect(select).not.toHaveProperty('inputMode', 'numeric')
    expect(select.tagName).not.toBe('INPUT')
  })

  it('목록에 없는 해를 고를 수 없다 — 서버가 아는 것만 옵션이다', async () => {
    stubServer([2026, 2027])

    renderScreen()

    const select = await screen.findByLabelText(/규제연도/)
    await waitFor(() => expect(select.querySelectorAll('option')).toHaveLength(2))
    const values = [...select.querySelectorAll('option')].map((o) => (o as HTMLOptionElement).value)
    expect(values).not.toContain('2035')
  })

  it('목록이 비면 「등록된 규제연도가 없습니다」 — 빈 셀렉트를 그리지 않는다', async () => {
    stubServer([])

    renderScreen()

    expect(await screen.findByText(/등록된 규제연도가 없습니다/)).toBeTruthy()
    expect(screen.queryByLabelText(/규제연도/)).toBeNull()
  })

  it('조회가 실패하면 그 사실을 말한다 — 빈 목록과 구분한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        if (String(input).includes('/parameters/regulation-years')) {
          return jsonResponse({ error: { code: 'INTERNAL_ERROR', message: '…' } }, 500)
        }
        return jsonResponse({ data: [] })
      }),
    )

    renderScreen()

    expect(await screen.findByText(/규제연도 목록을 불러오지 못했습니다/)).toBeTruthy()
  })
})
