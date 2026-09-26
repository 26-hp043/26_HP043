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
     * 잠그는 것은 **저장소 소유**다 — 외부 GLB·텍스처가 0인가.
     *
     * 삼각형 상한은 24(사각뿔 · `#1907`) → 48(`#1932`) → **400**(`#1935`)으로 올랐다.
     * 실험에서 사람이 고른 형상을 되살리며 컨테이너 적재가 들어왔기 때문이다 — 멀리서
     * 배를 배로 읽게 하는 것은 뱃머리 각도가 아니라 **실루엣**이고, 그 「쌓임」을
     * 만드는 것이 화물이다. 수백 개는 GPU에게 아무것도 아니다.
     *
     * **형상 자체의 예산 준수는** `vesselParts.test.ts`가 실제 부품 수로 본다.
     */
    expect(VESSEL_GEOMETRY_BUDGET).toMatchObject({ forwardAxis: '+Y', textureBytes: 0, assetBytes: 0 })
    expect(VESSEL_GEOMETRY_BUDGET.fleetTriangles).toBeLessThanOrEqual(400)
    expect(VESSEL_GEOMETRY_BUDGET.trackingTriangles).toBeLessThanOrEqual(500)
  })
})
