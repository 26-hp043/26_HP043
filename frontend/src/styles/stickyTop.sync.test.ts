/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 「상단바가 차지하는 띠」를 여러 파일이 **같은 식으로** 적는다 (#1790).
 *
 * ## 무엇을 지키나
 *
 * sticky 상단바는 위 틈(`--shell-gutter`) 아래에 붙고 최소 높이가 `56px`이므로, 그 아래에
 * 서려면 `틈 + 56 + 틈`만큼을 비워야 한다. 이 값을 쓰는 자리가 다섯이다 — 입력 기둥 셋
 * (`§8.7`)과 보고서의 문서 높이, 그리고 `#1790`이 더한 `main`의 `scroll-margin`.
 *
 * ## 왜 검사인가
 *
 * `56`이 **`AppShell.css`의 `min-height`와 다섯 파일의 `calc()`에 각각 한 벌씩** 있다.
 * 상단바 높이를 바꾸면 그중 한 곳만 따라가도 화면은 깨지지 않는다 — 기둥이 조금 어긋나
 * 붙거나, 제목이 상단바에 반쯤 덮일 뿐이다. 그래서 눈으로는 발견되지 않는다.
 *
 * ⚠️ 값을 토큰 하나로 합치는 것이 본래 맞다. 그것은 다섯 파일을 함께 고치는 일이라
 * `#1790`의 범위 밖이고, **그때까지 어긋나지 않게** 여기서 잠근다.
 */
const SRC = join(process.cwd(), 'src')

const read = (path: string) =>
  readFileSync(join(SRC, path), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

/** 「위 틈 · 2 + 상단바 최소 높이」를 적는 자리. */
const USERS = [
  { name: '셸 본문의 초점 자리 (#1790)', file: 'layout/AppShell.css' },
  { name: 'CII 예측 입력 기둥', file: 'pages/CiiForecastPage.css' },
  { name: '연간 등급 관리 입력 기둥', file: 'features/annual-simulation/AnnualSimulation.css' },
  { name: '항로 비교 입력 기둥', file: 'features/scenario-comparison/ScenarioComparison.css' },
  { name: '보고서 조건 기둥', file: 'features/reports/ReportsView.css' },
] as const

/** `calc(var(--shell-gutter, …) * 2 + <n>px)`의 `<n>`들. */
function barHeights(css: string): number[] {
  return [
    ...css.matchAll(/calc\(\s*var\(--shell-gutter(?:[^()]|\([^()]*\))*\)\s*\*\s*2\s*\+\s*(\d+)px\s*\)/g),
  ].map((m) => Number(m[1]))
}

describe('상단바가 차지하는 띠는 한 값이다 (#1790)', () => {
  const shell = read('layout/AppShell.css')

  it('상단바의 최소 높이를 읽을 수 있다', () => {
    expect(/\.app-shell__topbar\s*\{[^}]*min-height:\s*56px/.test(shell)).toBe(true)
  })

  it.each(USERS)('$name — 그 높이를 그대로 쓴다', ({ file }) => {
    const found = barHeights(read(file))
    expect(found.length, `${file}에 「틈 · 2 + 상단바」 식이 없다`).toBeGreaterThan(0)
    for (const height of found) expect(height).toBe(56)
  })

  it('셸 본문이 초점을 받을 때 상단바 아래에 선다 — 없으면 제목이 덮인다', () => {
    expect(
      /\.app-shell__main\s*\{[^}]*scroll-margin-block-start:\s*calc\(/.test(shell),
      'AppShell.css의 `.app-shell__main`에 `scroll-margin-block-start`가 없다',
    ).toBe(true)
  })
})
