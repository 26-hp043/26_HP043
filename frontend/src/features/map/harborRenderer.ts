import type { MapRenderer } from './renderer'
import { mapQualityPolicy } from './quality'

export interface HarborRendererModel {
  readonly mode: 'playback'
  readonly port: 'busan' | 'singapore'
}

/** Three.js 항만 엔진은 항만 진입 시에만 별도 chunk로 내려받는다. */
export async function loadHarborRenderer(): Promise<MapRenderer<HarborRendererModel>> {
  const quality = mapQualityPolicy()
  if (!quality.harbor3d) {
    const error = new Error(quality.reason ?? '이 환경에서는 3D 항만 장면을 사용하지 않습니다.')
    error.name = 'quality-low'
    throw error
  }
  const module = await import('./harborSceneRenderer')
  return module.harborRenderer
}
