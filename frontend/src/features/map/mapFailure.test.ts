import { describe, expect, it } from 'vitest'
import { classifyMapFailure } from './mapFailure'

describe('지도 실패 분류', () => {
  it.each([
    ['asset-missing', 'PMTiles 지도 자산', 'pmtiles'],
    ['webgl-unavailable', 'WebGL unavailable', 'webgl'],
    ['Error', 'GLB decode failed', 'glb'],
    ['Error', 'Three 항만 renderer failed', 'three'],
    ['route-failed', 'route request failed', 'route'],
    ['Error', 'unknown', 'renderer'],
  ] as const)('%s/%s → %s', (name, message, kind) => {
    const error = new Error(message); error.name = name
    expect(classifyMapFailure(error).kind).toBe(kind)
  })
})
