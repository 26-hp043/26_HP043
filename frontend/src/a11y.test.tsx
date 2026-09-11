// @vitest-environment jsdom
import './test/renderSetup'

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router'
import { AppShell } from './layout/AppShell'
import { EMPTY_SHELL_CONTEXT, type ShellContext } from './layout/shellContext'
import { NAV_ORDER, SCREEN_BY_ID } from './screens'
import { DisclaimerBanner } from './components/DisclaimerBanner'
import { GradeScaleBar } from './components/GradeScaleBar'
import { GradeDistribution } from './features/fleet/GradeDistribution'
import { AnnualSimulation } from './features/annual-simulation/AnnualSimulation'
import { ANNUAL_COPY } from './features/annual-simulation/copy'
import { riskLabel } from './features/voyage-cii/resultRules'
import type { RiskLevel } from './features/voyage-cii/types'

/**
 * 접근성 케이스 4종 — `TEST_PLAN §7` · `PRD §16.4` · `#68`.
 *
 * ## 무엇을 잠그는가
 *
 * `#68`의 2026-08-29 검토가 확인한 대로 **구현은 네 성질을 이미 지키고 있었고 케이스만
 * 없었다.** 그래서 이 파일은 새 동작을 넣는 것이 아니라 **지켜지고 있는 성질이 되돌아가는
 * 것**을 막는다 — 색을 빼도 위험도가 읽히는가, Tab으로 주요 동작에 닿는가, 확률 차트의
 * 값이 글로도 있는가, 결과 화면마다 면책이 있는가.
 *
 * ## 도구를 얹지 않는다
 *
 * `axe-core`·`vitest-axe`는 넣지 않았다. 네 케이스는 전부 **이 제품의 규칙**(등급 색 옆에
 * 문자·패턴, 비활성 항목은 링크가 아님, 차트 값의 문자 사본, 면책 상시 노출)이라 범용
 * 검사기가 알 수 있는 것이 아니고, 의존성은 `#235`의 범위 핀 원칙에 걸린다.
 *
 * 대비(4.5:1)는 여기서 재지 않는다 — `styles/tokens.sync.test.ts`가 모든 문자 토큰 × 모든
 * 표면을 이미 잰다(`§0.2` 제약 6). 같은 것을 두 곳에서 재면 한쪽이 낡는다.
 *
 * 케이스: A11Y-001 · A11Y-002 · A11Y-003 · A11Y-004 (`TEST_PLAN §14.5`)
 */

/*
 * `jsdom` 환경에서는 `import.meta.url`이 file 스킴이 아니라 경로로 쓸 수 없다
 * (`features/auth/AuthShell.test.tsx`와 같은 이유). vitest는 `frontend/`에서 돌므로
 * 작업 폴더 기준으로 잡는다.
 */
const SRC = join(process.cwd(), 'src')
const ROOT = join(process.cwd(), '..')

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

// ── A11Y-001 위험도 색상 제거 — 텍스트만으로 위험도 이해 가능 ────────────────

describe('A11Y-001 — 위험도는 색 없이도 읽힌다', () => {
  const LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

  it('위험도 4단계 전부가 한글 라벨 + 코드 문자를 낸다', () => {
    /*
     * 화면 5곳(기능①·②·③·실시간 2곳)이 전부 `riskLabel()`을 거쳐 이 문자를 놓는다.
     * 색은 그 옆의 채널일 뿐이다 — `DESIGN_SYSTEM §2.5` (b).
     */
    for (const level of LEVELS) {
      const { text } = riskLabel(level)
      expect(text, level).toMatch(/^[가-힣]+ (LOW|MEDIUM|HIGH|CRITICAL)$/)
      expect(text).toContain(level)
    }
  })

  it('높음·심각은 아이콘을 두 번째 보조 채널로 갖는다 — §2.5 (b)', () => {
    expect(riskLabel('HIGH').withIcon).toBe(true)
    expect(riskLabel('CRITICAL').withIcon).toBe(true)
    expect(riskLabel('LOW').withIcon).toBe(false)
  })

  it('등급 스케일 바는 문자가 없는 자리라 등급마다 패턴을 겹친다 — §14 · §2.4.4', () => {
    /*
     * 등급 색만 있는 막대는 적록색맹에서 세 색상군이 황갈색으로 수렴한다. 문자를 놓을 수
     * 없는 막대는 **패턴**이 보조 채널이다. `A`만 solid(패턴 없음)라 `§2.4.4`가 정한 대로
     * 나머지 네 등급에 패턴이 있어야 한다.
     */
    const { container } = render(
      <GradeScaleBar
        ratioToRequired="0.98758"
        boundaries={{ d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18' }}
        rating="C"
        valueLabel="98.8%"
        label="기준 대비 위치"
      />,
    )
    const bands = container.querySelectorAll('.grade-scale-bar__band')
    expect(bands).toHaveLength(5)
    const patterned = container.querySelectorAll('.grade-scale-bar__band .grade-scale-bar__pattern')
    expect(patterned).toHaveLength(4)
    // 막대 전체는 보조기술에 문자로 읽힌다 — 등급과 기준 대비 값.
    const track = screen.getByRole('img', { name: /현재 등급 C, 기준 대비 98\.8%/ })
    expect(track).toBeTruthy()
  })
})

// ── A11Y-002 키보드 이동 — Tab 키로 주요 액션 접근 가능 ─────────────────────

describe('A11Y-002 — Tab 키로 주요 액션에 닿는다', () => {
  function stubShellServer() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/auth/me')) {
          return jsonResponse({ data: { id: 'u1', email: 'a@b.c', display_name: '테스터' } })
        }
        if (url.includes('/vessels') && url.includes('/voyages')) return jsonResponse({ data: [] })
        if (url.includes('/vessels')) {
          return jsonResponse({
            data: [{ id: '00000000-0000-4000-8000-000000000001', name: '샘플 벌크선', ship_type: 'BULK_CARRIER' }],
          })
        }
        return jsonResponse({ data: [] })
      }),
    )
  }

  function renderShell() {
    const path = SCREEN_BY_ID.MAINBOARD.path
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path={path} element={<div>본문</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('첫 Tab은 본문 바로가기에 닿고, 그다음부터 사이드바 항목이 차례로 초점을 받는다', async () => {
    stubShellServer()
    renderShell()
    await waitFor(() => expect(screen.getByText('샘플 벌크선')).toBeTruthy())

    const user = userEvent.setup()
    await user.tab()
    expect(document.activeElement?.className).toContain('skip-link')

    // `NAV_ORDER`의 구현된 화면은 전부 링크라 Tab 순서에 들어온다.
    const navLinks = NAV_ORDER.filter((id) => SCREEN_BY_ID[id].implemented)
    for (const id of navLinks) {
      await user.tab()
      const active = document.activeElement as HTMLElement | null
      expect(active?.tagName, id).toBe('A')
      expect(active?.getAttribute('href'), id).toBe(SCREEN_BY_ID[id].path)
    }
  })

  it('비활성 항목은 링크가 아니라 초점을 받지 않는다 — 스크린리더에 「이동 가능」으로 노출되지 않는다', async () => {
    stubShellServer()
    const { container } = renderShell()
    await waitFor(() => expect(screen.getByText('샘플 벌크선')).toBeTruthy())

    for (const disabled of container.querySelectorAll('.app-shell__nav-link--disabled')) {
      expect(disabled.tagName).not.toBe('A')
      expect(disabled.getAttribute('href')).toBeNull()
      expect(disabled.getAttribute('tabindex')).toBeNull()
      expect(disabled.getAttribute('aria-disabled')).toBe('true')
    }
  })

  it('주요 동작은 전부 초점을 받는 요소다 — 클릭 전용 div가 없다', async () => {
    /*
     * `onClick`을 단 요소가 `button`·`a`·폼 컨트롤이 아니면 키보드로는 누를 수 없다.
     * 셸의 상단바(선박·항차·알림·계정)와 사이드바를 렌더한 상태에서 본다.
     */
    stubShellServer()
    const { container } = renderShell()
    await waitFor(() => expect(screen.getByText('샘플 벌크선')).toBeTruthy())

    const interactive = container.querySelectorAll('button, a[href], select, input')
    expect(interactive.length).toBeGreaterThan(NAV_ORDER.length)
    for (const el of container.querySelectorAll('[role="button"]')) {
      expect(el.getAttribute('tabindex'), el.outerHTML).toBe('0')
    }
  })
})

// ── A11Y-003 차트 대체 표 — 확률 차트에 표 요약 제공 ─────────────────────────

describe('A11Y-003 — 확률 차트의 값이 글로도 있다', () => {
  const VESSEL_ID = '00000000-0000-4000-8000-000000000001'
  const PROBABILITIES = { A: '0.0200', B: '0.2800', C: '0.5500', D: '0.1300', E: '0.0200' }

  function simulationBody() {
    return {
      data: {
        simulation_id: 'sim-a11y',
        deterministic: {
          projected_attained_cii: '5.0248000000',
          projected_rating: 'C',
          completed_voyage_count: 8,
          remaining_voyage_count: 4,
          completed_M_gco2: '6290280000',
          completed_W_capacity_nm: '1260000000',
          planned_M_gco2: '3145140000',
          planned_W_capacity_nm: '630000000',
        },
        monte_carlo: {
          rng_metadata: {
            seed_entropy: '12345',
            bit_generator: 'PCG64DXSM',
            numpy_version: '2.1.0',
            python_version: '3.12.4',
            platform: 'Linux',
          },
          runs: 5000,
          rating_probabilities: PROBABILITIES,
          target_success_probability: '0.3000',
          target_rating: 'B',
          p10: '4.7100',
          p50: '5.0400',
          p90: '5.4200',
          mean_cii: '5.0600',
        },
        risk_level: 'HIGH',
        sensitivity_analysis: { interaction_note: '개별 효과만 표시합니다.' },
        snapshot: { snapshot_id: 'snap-1', created_at: '2026-08-17T00:00:00Z', voyage_count: 12 },
      },
      calculation_run_id: 'run-a11y',
      warnings: [],
    }
  }

  function stubAnnualServer() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        const url = String(input)
        if (url.includes('/parameters/regulation-years')) return jsonResponse({ data: [{ year: 2026 }] })
        if (url.includes('/annual-simulations')) return jsonResponse(simulationBody())
        return jsonResponse({ data: {} })
      }),
    )
  }

  async function renderAndRun() {
    const value: ShellContext = {
      ...EMPTY_SHELL_CONTEXT,
      vesselId: VESSEL_ID,
      vessels: [{ id: VESSEL_ID, displayName: '샘플 벌크선', shipType: 'BULK_CARRIER' }],
      vesselsState: 'ready',
    }
    render(
      <MemoryRouter initialEntries={['/annual']}>
        <Routes>
          <Route element={<Outlet context={value} />}>
            <Route path="/annual" element={<AnnualSimulation />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    /*
     * 기본 연도가 **선택된 뒤** 실행한다 — 선택지가 그려진 것만으로는 부족하다. 기본값은
     * 목록이 온 다음 effect가 고르므로 그 사이에 누르면 실행이 거부된다. 선택지가 그려진 뒤
     * `act`로 effect를 비운다(`features/annual-simulation/AnnualSimulation.test.tsx`의
     * `runOnce`와 같은 이유 · 같은 순서).
     */
    await screen.findByRole('option', { name: '2026' })
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: ANNUAL_COPY.submit }))
    await screen.findByText(ANNUAL_COPY.probabilityTitle)
  }

  it('등급 확률 스택 바의 다섯 값이 범례에 글로 전부 있다', async () => {
    stubAnnualServer()
    await renderAndRun()

    const legend = document.querySelector('.annual-sim__legend')
    expect(legend).not.toBeNull()
    const rows = [...legend!.querySelectorAll('li')].map((li) => li.textContent?.trim())
    expect(rows).toHaveLength(5)
    for (const [rating, probability] of Object.entries(PROBABILITIES)) {
      const percent = (Number(probability) * 100).toFixed(1)
      expect(rows.find((row) => row?.startsWith(rating)), rating).toContain(`${percent}%`)
    }
  })

  it('스택 바 자체도 보조기술에 값을 읽어 준다 — 구간마다 이름이 있다', async () => {
    stubAnnualServer()
    await renderAndRun()

    const stack = screen.getByRole('group', { name: new RegExp(ANNUAL_COPY.probabilityTitle) })
    const segments = stack.querySelectorAll('[role="img"][aria-label]')
    expect(segments).toHaveLength(5)
    for (const seg of segments) {
      expect(seg.getAttribute('aria-label')).toMatch(/^[A-E] \d+(\.\d+)?%$/)
    }
  })

  it('선대 등급 분포 막대도 구간마다 척수를 글로 낸다', () => {
    render(<GradeDistribution distribution={{ A: 1, B: 2, C: 3, D: 0, E: 1 }} />)
    const labelled = screen.getAllByRole('img', { name: /[A-E]등급 \d+척/ })
    expect(labelled.length).toBeGreaterThanOrEqual(4)
  })
})

// ── A11Y-004 Disclaimer 가시성 — 모든 결과 화면에 면책 문구 표시 ───────────────

describe('A11Y-004 — 결과 화면마다 면책 문구가 있다', () => {
  /*
   * 「결과 화면」은 계산·집계 값을 보여 주는 화면 전부다 — `UIFLOW §2`의 계층 화면
   * (대시보드 · 선박 상세 · 실시간 CII · 보고서)과 기능①·②·③ 페이지. 인증·설정·
   * 선박 관리·등록은 값을 계산하지 않아 대상이 아니다(`PRD §0.3` 「모든 결과 화면」).
   */
  const RESULT_SCREENS: Array<{ file: string; branches: number }> = [
    // 대시보드는 결과를 그리는 분기가 **둘**이다 — 선박 0척 안내와 정상 그리드. 둘 다
    // 결과 화면이라 배너가 두 번 있어야 한다. 하나만 빠지면 파일 단위 검사는 못 잡는다.
    { file: 'features/fleet/FleetDashboard.tsx', branches: 2 },
    { file: 'features/vessel-detail/VesselDetail.tsx', branches: 1 },
    { file: 'features/realtime-cii/RealtimeCiiView.tsx', branches: 1 },
    { file: 'features/reports/ReportsView.tsx', branches: 1 },
    { file: 'pages/CiiForecastPage.tsx', branches: 1 },
    { file: 'pages/RouteComparisonPage.tsx', branches: 1 },
    { file: 'pages/AnnualGradePage.tsx', branches: 1 },
  ]

  it('결과 화면 7종이 전부 DisclaimerBanner를 그린다 — 결과 분기마다', () => {
    for (const { file, branches } of RESULT_SCREENS) {
      const source = readFileSync(join(SRC, file), 'utf-8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:])\/\/.*$/gm, '$1')
      const found = source.match(/<DisclaimerBanner\b/g)?.length ?? 0
      expect(found, file).toBeGreaterThanOrEqual(branches)
    }
  })

  it('면책 문구는 role="note"로 읽히고 PRD §6.3 원문과 같다', () => {
    render(<DisclaimerBanner />)
    const note = screen.getByRole('note')
    const prd = readFileSync(join(ROOT, 'PRD.md'), 'utf-8')
    const row = prd.split('\n').find((line) => line.startsWith('| 모든 결과 화면 |'))
    expect(row, 'PRD §6.3 「모든 결과 화면」 행').toBeDefined()
    const canonical = /`([^`]+)`/.exec(row as string)?.[1]
    expect(note.textContent).toBe(canonical)
  })

  it('서버 문구가 오면 그것을 쓰고, 비면 원문으로 돌아간다 — 빈 배너가 나가지 않는다', () => {
    const { unmount } = render(<DisclaimerBanner text="서버가 보낸 면책" />)
    expect(screen.getByRole('note').textContent).toBe('서버가 보낸 면책')
    unmount()
    render(<DisclaimerBanner text="   " />)
    expect(screen.getByRole('note').textContent?.length).toBeGreaterThan(10)
  })
})
