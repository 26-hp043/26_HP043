import { describe, expect, it } from 'vitest'
import { normalizedHeading, vesselWake, VESSEL_GEOMETRY_BUDGET } from './vesselModel'

describe('공용 3D 선박 asset·LOD 계약', () => {
  it('진북 heading을 정규화하고 결측을 추정하지 않는다', () => {
    expect(normalizedHeading(370)).toBe(10)
    expect(normalizedHeading(-10)).toBe(350)
    expect(normalizedHeading(null)).toBeNull()
  })

  it('실제 속도·재생·motion 정책이 모두 있을 때만 wake를 활성화한다', () => {
    expect(vesselWake(12, true, true)).toEqual({ active: true, speedKnots: 12 })
    expect(vesselWake(12, false, true)).toEqual({ active: false, speedKnots: 12 })
    expect(vesselWake(12, true, false)).toEqual({ active: false, speedKnots: 12 })
    expect(vesselWake(null, true, true)).toBeNull()
    expect(vesselWake(Number.NaN, true, true)).toBeNull()
  })

  it('외부 texture·asset 없이 fleet budget 안의 절차형 geometry를 쓴다', () => {
    expect(VESSEL_GEOMETRY_BUDGET).toMatchObject({ forwardAxis: '+Y', textureBytes: 0, assetBytes: 0 })
    expect(VESSEL_GEOMETRY_BUDGET.fleetTriangles).toBeLessThanOrEqual(24)
  })
})
