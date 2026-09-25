import { describe, expect, it } from 'vitest'
import { mapQualityPolicy, type MapQualitySignals } from './quality'

const signals = (extra: Partial<MapQualitySignals> = {}): MapQualitySignals => ({
  reducedMotion: false, deviceMemoryGb: 8, hardwareConcurrency: 8,
  webgl2: true, maxTextureSize: 8192, ...extra,
})

describe('지도 quality tier', () => {
  it.each([
    [signals(), 'high'],
    [signals({ deviceMemoryGb: 6 }), 'medium'],
    [signals({ deviceMemoryGb: 2 }), 'low'],
    [signals({ webgl2: false }), 'low'],
    [signals({ reducedMotion: true }), 'low'],
  ] as const)('capability → %s', (input, tier) => expect(mapQualityPolicy({ signals: input }).tier).toBe(tier))

  it('테스트용 override는 capability와 무관하게 결정적이다', () => {
    expect(mapQualityPolicy({ signals: signals({ webgl2: false }), override: 'high' }).tier).toBe('high')
  })

  it('quality는 표현만 바꾸며 route geometry 입력을 받지 않는다', () => {
    expect(mapQualityPolicy({ signals: signals(), override: 'low' })).toMatchObject({ pixelRatioCap: 1, buildingStride: 4, animate: false })
  })
})
