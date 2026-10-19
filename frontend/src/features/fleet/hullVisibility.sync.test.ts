import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 평면 SVG 배를 언제 감추는가 (`#2531`).
 *
 * 3D 선체가 그리는 동안에는 SVG 배를 감춘다 — 같은 자리에 배가 둘이 된다(`#1917`). 종전에는
 * 그 조건을 **기기 성능**(`mapQualityPolicy().globe`)으로 정했는데, 선체는 지구본에서만
 * 올라가 **평면 첫 화면(`#2292`)에서 배가 등급 배지만 남았다.** 렌더러 검사도 마커 검사도
 * 각자는 초록이었다 — 두 파일이 같은 조건을 보지 않는다는 것이 결함이었다.
 *
 * 그래서 조건을 하나로 묶는다: 렌더러가 선체 layer를 실제로 올린 뒤 지도 요소에 다는 표시,
 * 그리고 CSS가 그 표시를 볼 때만 감춘다. 여기서는 ⑴ 표시의 이름·값이 두 파일에서 같은가
 * ⑵ 그 표시 밖에서 SVG 배를 감추는 규칙이 없는가 ⑶ 마커가 기기 성능으로 다시 갈리지 않는가를 본다.
 */
const read = (path: string) =>
  readFileSync(join(process.cwd(), 'src/features', path), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')

const css = read('fleet/FleetMap.css')
const renderer = read('map/mapLibreRenderer.ts')
const fleetMap = read('fleet/FleetMap.tsx')

/** `display: none`을 거는 규칙의 선택자 가운데 마커 SVG를 가리키는 것. */
function hidingSelectors(source: string): string[] {
  const found: string[] = []
  for (const [, selectors, body] of source.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (!/(?:^|;)\s*display:\s*none/.test(body)) continue
    for (const selector of selectors.split(',').map((s) => s.trim())) {
      if (/\.fleetmap__marker[^\s]*\s+svg/.test(selector)) found.push(selector)
    }
  }
  return found
}

describe('SVG 배를 감추는 조건 (#2531)', () => {
  it('렌더러가 선체를 올리면 지도 요소에 표시를 단다', () => {
    expect(renderer).toMatch(/target\.dataset\.vesselHulls = 'on'/)
  })

  it('CSS는 그 표시가 있을 때만 SVG 배를 감춘다 — 이름과 값이 렌더러와 같다', () => {
    const selectors = hidingSelectors(css)
    expect(selectors.length).toBeGreaterThan(0)
    for (const selector of selectors) expect(selector).toMatch(/^\[data-vessel-hulls='on'\]\s/)
  })

  it('마커는 기기 성능으로 SVG 배를 가르지 않는다', () => {
    // 성능 판정은 렌더러가 선체를 올릴지 정할 때 한 번만 본다(`quality.globe`).
    expect(fleetMap).not.toMatch(/mapQualityPolicy/)
    expect(fleetMap).not.toMatch(/fleetmap__marker--hull3d/)
  })
})
