import { seaRouteKey, type SeaRouteState } from '../fleet/seaRoute'
import type { AdaptedRouteRequest } from './adapters'
import { routeLineGeometry } from './routeGeometry'

/** 받아 둔 항로만 renderer GeoJSON으로 바꾼다. 실패한 선을 직선으로 추정하지 않는다. */
export function routeFeatureCollection(
  asks: readonly AdaptedRouteRequest[],
  lines: Readonly<Record<string, SeaRouteState>>,
) {
  return {
    type: 'FeatureCollection' as const,
    features: asks.flatMap((ask) => {
      const line = lines[seaRouteKey(ask.request)]
      if (line === undefined || line === 'failed' || line.coordinates.length < 2) return []
      return [{
        type: 'Feature' as const,
        properties: { name: ask.name, kind: ask.kind },
        geometry: routeLineGeometry(line.coordinates),
      }]
    }),
  }
}
