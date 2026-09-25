import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const read = (path: string) => readFileSync(join(SOURCE_ROOT, path), 'utf8')

describe('지도 엔진 module boundary', () => {
  it('Fleet와 Comparison 제품 화면은 MapLibre나 Three를 직접 import하지 않는다', () => {
    for (const path of ['fleet/FleetMap.tsx', 'scenario-comparison/VoyageRouteMap.tsx']) {
      expect(read(path)).not.toMatch(/from ['"](?:maplibre-gl|three)/)
    }
  })

  it('Comparison은 FleetMap 구현을 직접 import하지 않는다', () => {
    const comparison = read('scenario-comparison/VoyageRouteMap.tsx')
    expect(comparison).not.toContain('../fleet/FleetMap')
    expect(comparison).not.toContain('../map/RouteMap')
  })

  it('Three 항만 renderer는 정적 import가 아니라 lazy boundary 뒤에 있다', () => {
    const loader = read('map/harborRenderer.ts')
    expect(loader).toContain("await import('./harborSceneRenderer')")
    expect(loader).not.toMatch(/^import .*harborSceneRenderer/m)
    expect(read('map/harborSceneRenderer.ts')).toContain("from 'three'")
  })

  it('Three 선박 layer도 MapLibre adapter의 lazy boundary 뒤에 있다', () => {
    const adapter = read('map/mapLibreRenderer.ts')
    const playback = read('map/playbackRenderer.ts')
    expect(adapter).toContain("import('./vesselLayer')")
    expect(playback).toContain("import('./vesselLayer')")
    expect(adapter).not.toMatch(/^import \* as THREE/m)
    expect(read('map/vesselLayer.ts')).toContain("from 'three'")
  })

  it('UIFLOW 2-3 제품 화면은 실험 component가 아니라 공용 playback 경계만 연결한다', () => {
    const annualProductFiles = ['annual-simulation/AnnualSimulation.tsx']
      .map((path) => read(path))
      .join('\n')
    expect(annualProductFiles).not.toMatch(/SimulationMap25D|experiments\//)
    expect(annualProductFiles).toContain("./visualization/AnnualPlayback")
  })

  it('인증 뒤 제품 route가 세 공용 지도 경계와 Annual provider를 실제로 연결한다', () => {
    expect(read('../App.tsx')).toContain('<AnnualGradePage />')
    const annualPage = read('../pages/AnnualGradePage.tsx')
    expect(annualPage).toContain('annualProductMapGeometryProvider')
    expect(annualPage).toContain('mapGeometryProvider={annualProductMapGeometryProvider}')
    expect(read('fleet/FleetDashboard.tsx')).toContain('<FleetMap')
    expect(read('scenario-comparison/ScenarioComparison.tsx')).toContain('<VoyageRouteMap')
  })
})
