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
  fleetTriangles: 24, trackingTriangles: 48, textureBytes: 0, assetBytes: 0,
} as const

export function normalizedHeading(value: number | null): number | null {
  return value !== null && Number.isFinite(value) ? ((value % 360) + 360) % 360 : null
}

/** 실제 속도가 있고 재생 중이며 motion 정책이 허용할 때만 wake를 만든다. */
export function vesselWake(speedKnots: number | null | undefined, moving: boolean, animate: boolean): GlobeVesselModel['wake'] {
  if (speedKnots === null || speedKnots === undefined || !Number.isFinite(speedKnots) || speedKnots <= 0) return null
  return { active: moving && animate, speedKnots }
}
