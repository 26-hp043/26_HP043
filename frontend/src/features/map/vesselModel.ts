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
   * 예산을 올렸다 (`#1932` · 24 → 40 · 48 → 64).
   *
   * 종전 값은 **사각뿔 하나**를 전제로 잡은 것이다(`#1907`). 그 형상은 위에서 보면
   * 화살표였고 두께가 읽히지 않았다 — 선대 지도는 배를 **내려다보는** 자리라 갑판이
   * 평평한 한 장이면 빛이 걸리지 않는다. 어깨에서 꺾이는 선체(24) + 선교(12)가
   * 「화살표」와 「배」를 가르는 최소 구성이고, 추적 모드는 연돌(12)을 더 얹는다.
   *
   * 여전히 **저폴리 계약**이다 — 외부 GLB·텍스처는 0이고, 예산을 넘기면
   * `vesselGeometry.test.ts`가 막는다.
   */
  fleetTriangles: 40, trackingTriangles: 64, textureBytes: 0, assetBytes: 0,
} as const

export function normalizedHeading(value: number | null): number | null {
  return value !== null && Number.isFinite(value) ? ((value % 360) + 360) % 360 : null
}

/** 실제 속도가 있고 재생 중이며 motion 정책이 허용할 때만 wake를 만든다. */
export function vesselWake(speedKnots: number | null | undefined, moving: boolean, animate: boolean): GlobeVesselModel['wake'] {
  if (speedKnots === null || speedKnots === undefined || !Number.isFinite(speedKnots) || speedKnots <= 0) return null
  return { active: moving && animate, speedKnots }
}
