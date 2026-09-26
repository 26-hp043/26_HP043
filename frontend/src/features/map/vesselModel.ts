import type { MapModeInput } from './renderer'
import type { RouteCoordinate } from './routeGeometry'

export interface GlobeVesselModel {
  readonly id: string
  readonly coordinate: RouteCoordinate
  /** 진북 0°, 시계 방향. 값이 없으면 방향을 추정하지 않는다. */
  readonly heading: number | null
  readonly wake?: { readonly active: boolean; readonly speedKnots: number } | null
  /**
   * 올해 누적 등급 (`#1917`). 선체 색이 이 값을 따른다 — 평면 마커가 쓰던 등급 색을
   * 3D 선체가 이어받는다. 없으면 중립색이고, **문자 채널은 마커 배지가 계속 맡는다**
   * (`DESIGN_SYSTEM §14` — 등급을 색으로만 말하지 않는다).
   */
  readonly rating?: string | null
}

export type GlobeVesselLayerModel = MapModeInput & {
  readonly vessels: readonly GlobeVesselModel[]
}

/** 외부 GLB 없이 저장소 소유 geometry로 고정한 저폴리 LOD 계약이다. */
export const VESSEL_GEOMETRY_BUDGET = {
  forwardAxis: '+Y', unit: 'meter', origin: 'waterline-center',
  /*
   * 예산 (`#1935`).
   *
   * 값이 두 번 올랐다 — 24(사각뿔 하나 · `#1907`) → 40(어깨 꺾임 + 선교 · `#1932`) →
   * 지금. 실험에서 사람이 고른 형상을 되살리며(`#1935`) **컨테이너 적재**가 들어왔기
   * 때문이다. 멀리서 배를 배로 읽게 하는 것은 뱃머리 각도가 아니라 **실루엣**이고,
   * 그 「쌓임」을 만드는 것이 화물이다.
   *
   * 삼각형 300개는 GPU에게 아무것도 아니다 — 이 숫자가 지키는 것은 성능이 아니라
   * **저장소 소유**다: 외부 GLB·텍스처가 0이고, 형상이 코드 안에 있어 재배포 출처가
   * 닫힌다. 실제 부품 수는 `vesselParts.test.ts`가 이 값과 대조한다.
   */
  fleetTriangles: 300, trackingTriangles: 320, textureBytes: 0, assetBytes: 0,
} as const

export function normalizedHeading(value: number | null): number | null {
  return value !== null && Number.isFinite(value) ? ((value % 360) + 360) % 360 : null
}

/** 실제 속도가 있고 재생 중이며 motion 정책이 허용할 때만 wake를 만든다. */
export function vesselWake(speedKnots: number | null | undefined, moving: boolean, animate: boolean): GlobeVesselModel['wake'] {
  if (speedKnots === null || speedKnots === undefined || !Number.isFinite(speedKnots) || speedKnots <= 0) return null
  return { active: moving && animate, speedKnots }
}
