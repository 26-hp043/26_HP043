/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 「상단바가 차지하는 띠」는 **토큰 하나**다 (#1790 · #1884).
 *
 * ## 무엇을 지키나
 *
 * sticky 상단바는 위 틈(`--shell-gutter`) 아래에 붙고 최소 높이가 `--shell-topbar-height`이므로,
 * 그 아래에 서려면 `틈 + 높이 + 틈`(`--shell-topbar-offset`)만큼을 비워야 한다. 이 값을 쓰는
 * 자리가 여럿이다 — 입력 기둥 셋(`§8.7`) · 보고서의 문서 높이 · `#1790`이 더한 `main`의
 * `scroll-margin` · `#1791`이 더한 설정 두 절.
 *
 * ## 왜 검사인가
 *
 * 종전(`#1790`)에는 높이 리터럴이 `AppShell.css`의 `min-height`와 위 파일들의 `calc()`에
 * **각각 한 벌씩** 있어 같은 식인지 대조했다. 한 곳만 따라가도 화면은 깨지지 않는다 — 기둥이
 * 조금 어긋나 붙거나 제목이 반쯤 덮일 뿐이라 눈으로는 발견되지 않는다. `#1884`가 토큰으로
 * 합쳤고, 이제는 **리터럴이 토큰 정의 한 곳에만 있는가**와 **각 자리가 토큰을 읽는가**를 본다.
 */
const SRC = join(process.cwd(), 'src')

const read = (path: string) =>
  readFileSync(join(SRC, path), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return entry === 'node_modules' ? [] : cssFiles(full)
    return entry.endsWith('.css') ? [full] : []
  })
}

/** 「위 틈 · 2 + 상단바 높이」를 쓰는 자리. */
const USERS = [
  { name: '셸 본문의 초점 자리 (#1790)', file: 'layout/AppShell.css' },
  { name: 'CII 예측 입력 기둥', file: 'pages/CiiForecastPage.css' },
  { name: '연간 등급 관리 입력 기둥', file: 'features/annual-simulation/AnnualSimulation.css' },
  { name: '항로 비교 입력 기둥', file: 'features/scenario-comparison/ScenarioComparison.css' },
  { name: '보고서 조건 기둥', file: 'features/reports/ReportsView.css' },
  { name: '설정 계정 절 (#1791)', file: 'features/account/AccountPanel.css' },
  { name: '설정 규제 기준값 절 (#1791)', file: 'features/parameters/RegulationParametersSection.css' },
] as const

describe('상단바가 차지하는 띠는 토큰 하나다 (#1790 · #1884)', () => {
  const shell = read('layout/AppShell.css')

  it('높이 리터럴은 토큰 정의 한 곳에만 있다 — 주석을 뺀 모든 CSS에서', () => {
    const found = cssFiles(SRC).flatMap((file) =>
      read(relative(SRC, file))
        .split('\n')
        .filter((line) => /\b56px\b/.test(line))
        .map((line) => `${relative(SRC, file)}: ${line.trim()}`),
    )
    expect(found).toEqual(['layout/AppShell.css: --shell-topbar-height: 56px;'])
  })

  it('띠 토큰은 틈 · 2 + 높이 토큰이다', () => {
    expect(shell).toMatch(
      /--shell-topbar-offset:\s*calc\(var\(--shell-gutter\)\s*\*\s*2\s*\+\s*var\(--shell-topbar-height\)\)/,
    )
  })

  it('상단바의 최소 높이가 그 토큰이다', () => {
    expect(/\.app-shell__topbar\s*\{[^}]*min-height:\s*var\(--shell-topbar-height\)/.test(shell)).toBe(true)
  })

  it.each(USERS)('$name — 띠 토큰을 읽는다', ({ file }) => {
    expect(read(file), `${file}이 --shell-topbar-offset을 쓰지 않는다`).toContain('var(--shell-topbar-offset)')
  })

  it('셸 본문이 초점을 받을 때 상단바 아래에 선다 — 없으면 제목이 덮인다', () => {
    expect(
      /\.app-shell__main\s*\{[^}]*scroll-margin-block-start:\s*var\(--shell-topbar-offset\)/.test(shell),
      'AppShell.css의 `.app-shell__main`에 `scroll-margin-block-start`가 없다',
    ).toBe(true)
  })
})
