import type { RouteSource, WaypointRouteDerivation } from './routeGeometry'

type RouteDisclosureMode = 'fleet' | 'comparison' | 'playback'
type RouteDisclosureKind = 'DIRECT' | 'DETOUR'

interface RouteDisclosureInput {
  readonly mode: RouteDisclosureMode
  readonly source: RouteSource
  readonly kinds: readonly RouteDisclosureKind[]
  readonly derivation?: WaypointRouteDerivation
}

interface RouteDisclosure {
  readonly visibleText: string
  readonly accessibleText: string
}

/**
 * 지도별 문구가 출처와 용도를 다르게 말하지 않도록 만드는 공용 표시 정책이다.
 * DIRECT/DETOUR는 선의 의미이고 source는 좌표의 출처이므로 서로 대신하지 않는다.
 */
export function routeDisclosure({ mode, source, kinds, derivation }: RouteDisclosureInput): RouteDisclosure {
  const routeKind = kinds.includes('DETOUR')
    ? '직항선과 사용자가 선택한 경유점을 지나는 우회선을 표시합니다.'
    : mode === 'fleet'
      ? '진행 중 항차의 항로선을 표시합니다.'
      : '직항 항로선을 표시합니다.'
  const context = derivation?.kind === 'WAYPOINT'
    ? 'provider가 명시적으로 제공한 계획 waypoint 순서를 이은 선입니다. 실제 운항 결과가 아닙니다.'
    : mode === 'playback' ? '재생 위치와 이동은 provider가 명시한 좌표의 시각화입니다.' : routeKind
  const planNotice = derivation?.kind === 'WAYPOINT' ? '' : ' 실제 항해 계획이 아닙니다.'
  const text = `${source.label} 기반의 표시용 항로입니다. ${context}${planNotice} CII 계산 거리의 근거가 아니며, AIS 실제 운항 궤적이 아닙니다.`
  return { visibleText: text, accessibleText: text }
}
