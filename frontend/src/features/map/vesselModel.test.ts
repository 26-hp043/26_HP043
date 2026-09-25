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
    /*
     * 잠그는 것은 **저폴리 · 저장소 소유**다 — 외부 GLB·텍스처가 0인가, 그리고 삼각형이
     * 「지도에 쓰는 기호」 범위에 머무는가.
     *
     * 상한을 24에서 **48**로 올렸다 (`#1932`). 24는 사각뿔 하나를 전제한 값이었고, 그
     * 형상은 위에서 보면 화살표라 배로 읽히지 않았다 — 어깨에서 꺾이는 선체(24) + 선교(12)가
     * 최소 구성이다. **형상 자체의 예산 준수는** `vesselGeometry.test.ts`가 실제 정점 수로 본다.
     */
    expect(VESSEL_GEOMETRY_BUDGET).toMatchObject({ forwardAxis: '+Y', textureBytes: 0, assetBytes: 0 })
    expect(VESSEL_GEOMETRY_BUDGET.fleetTriangles).toBeLessThanOrEqual(48)
    expect(VESSEL_GEOMETRY_BUDGET.trackingTriangles).toBeLessThanOrEqual(96)
  })
})
