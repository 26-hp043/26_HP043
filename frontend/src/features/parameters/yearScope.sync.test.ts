/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 어느 화면이 올해 이후 연도를 빼는가 (#1584).
 *
 * ## 왜 소스로 보나
 *
 * 화면마다 렌더 검사를 두면 일곱 화면의 대역(provider · 셸 · 선박 목록)을 모두 세워야
 * 한다. 여기서 지키려는 것은 **어느 화면이 어느 쪽에 속하는가** 한 가지이고, 그것은
 * 호출부 한 줄에 드러난다. 규칙 자체(`displayYears`)는 `yearCatalog.test.ts`, 훅을 거친
 * 실제 선택지는 `DataQuality.test.tsx`가 본다. `deadCss.test.ts` · `launcherReserve.sync.test.ts`와
 * 같은 이유로 소스를 읽는다.
 *
 * 화면이 늘면 두 목록 중 하나에 넣는다 — 어느 쪽도 아니면 아래 마지막 검사가 잡는다.
 */
const FEATURES = join(fileURLToPath(new URL('.', import.meta.url)), '..')

/** 조회 화면 — 실적이 있을 수 없는 해를 고르면 언제나 빈 결과다 */
const LOOK_BACK = [
  'data-quality/DataQuality.tsx',
  'reports/ReportsView.tsx',
  'voyage-management/ExportCsv.tsx',
  'fleet-reduction/FleetReduction.tsx',
]

/** 계획을 짜는 화면 — 다음 해를 고를 수 있어야 한다 */
const PLANNING = [
  'voyage-cii/VoyageCiiForm.tsx',
  'annual-simulation/AnnualSimulation.tsx',
  'scenario-comparison/ScenarioComparison.tsx',
]

function calls(path: string): string[] {
  const src = readFileSync(join(FEATURES, path), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
  return src.match(/useYearOptions\([^)]*\)/g) ?? []
}

describe('연도 선택지의 범위 — 조회 화면만 올해까지 (#1584)', () => {
  it.each(LOOK_BACK)('%s 는 올해 이후를 뺀다', (path) => {
    const found = calls(path)
    expect(found).toHaveLength(1)
    expect(found[0]).toMatch(/throughCurrentYear:\s*true/)
  })

  it.each(PLANNING)('%s 는 미래 연도를 남긴다', (path) => {
    const found = calls(path)
    expect(found).toHaveLength(1)
    expect(found[0]).not.toMatch(/throughCurrentYear/)
  })

  it('훅을 부르는 화면은 모두 두 목록 중 하나에 있다', () => {
    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((entry) => {
        const full = join(dir, entry)
        if (statSync(full).isDirectory()) return walk(full)
        return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
      })
    const callers = walk(FEATURES)
      .map((full) => relative(FEATURES, full).split('\\').join('/'))
      .filter((path) => path !== 'parameters/yearCatalog.ts' && calls(path).length > 0)
      .sort()
    expect(callers).toEqual([...LOOK_BACK, ...PLANNING].sort())
  })
})
