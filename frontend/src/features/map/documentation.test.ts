import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const GUIDE_PATH = resolve(process.cwd(), '../docs/MAP_VISUALIZATION_GUIDE.md')
const guide = readFileSync(GUIDE_PATH, 'utf8')

describe('3D 지도 운영 문서', () => {
  it('화면별 truth와 서로 바꿔 쓸 수 없는 데이터 의미를 기록한다', () => {
    expect(guide).toContain('현재 위치 스냅샷')
    expect(guide).toContain('AnnualMapGeometryProvider')
    expect(guide).toContain('WAYPOINT')
    expect(guide).toContain('CII 계산 거리')
    expect(guide).toContain('AIS 실제 궤적')
  })

  it('항만 안전 한계와 QA 진입점을 기록한다', () => {
    expect(guide).toMatch(/접안 위치/)
    expect(guide).toMatch(/수심/)
    expect(guide).toContain('/map-smoke.html?autoplay=1#annual-playback-scene')
    expect(guide).toContain('npm run test:map-smoke')
  })

  it('문서의 저장소 내부 Markdown 링크가 실제 파일을 가리킨다', () => {
    const links = [...guide.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)]
      .map((match) => match[1])
      .filter((href) => !href.startsWith('http') && !href.startsWith('#'))
      .map((href) => decodeURIComponent(href.split('#')[0]))

    expect(links.length).toBeGreaterThan(0)
    for (const href of links) {
      expect(existsSync(resolve(dirname(GUIDE_PATH), href)), href).toBe(true)
    }
  })
})
