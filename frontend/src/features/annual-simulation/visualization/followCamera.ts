import type { RouteCoordinate } from '../../map/routeGeometry'

export type PlaybackCameraMode = 'overview' | 'follow'

interface FollowCameraPort {
  follow(position: RouteCoordinate, bearing: number | null, animate: boolean): void
  showOverview(): void
  subscribeUserInteraction(listener: () => void): () => void
}

export interface FollowCameraController {
  getMode(): PlaybackCameraMode
  setMode(mode: PlaybackCameraMode): void
  setReducedMotion(reduced: boolean): void
  update(position: RouteCoordinate, traveledCoordinates: readonly RouteCoordinate[]): void
  resetView(): void
  destroy(): void
}

function bearing(coordinates: readonly RouteCoordinate[]): number | null {
  if (coordinates.length < 2) return null
  const [fromLongitude, fromLatitude] = coordinates[coordinates.length - 2]
  const [toLongitude, toLatitude] = coordinates[coordinates.length - 1]
  const latitude1 = fromLatitude * Math.PI / 180
  const latitude2 = toLatitude * Math.PI / 180
  const longitudeDelta = ((((toLongitude - fromLongitude) + 540) % 360) - 180) * Math.PI / 180
  const y = Math.sin(longitudeDelta) * Math.cos(latitude2)
  const x = Math.cos(latitude1) * Math.sin(latitude2)
    - Math.sin(latitude1) * Math.cos(latitude2) * Math.cos(longitudeDelta)
  if (x === 0 && y === 0) return null
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

/** 지도 엔진과 분리된 opt-in follow camera 상태를 관리한다. */
export function createFollowCameraController(
  port: FollowCameraPort,
  options: { readonly reducedMotion: boolean; readonly onModeChange?: (mode: PlaybackCameraMode) => void },
): FollowCameraController {
  let mode: PlaybackCameraMode = 'overview'
  let destroyed = false
  let reducedMotion = options.reducedMotion
  const setMode = (next: PlaybackCameraMode) => {
    if (destroyed || mode === next) return
    mode = next
    options.onModeChange?.(mode)
  }
  const unsubscribe = port.subscribeUserInteraction(() => setMode('overview'))
  return {
    getMode: () => mode,
    setMode,
    setReducedMotion(reduced) { reducedMotion = reduced },
    update(position, traveledCoordinates) {
      if (!destroyed && mode === 'follow') {
        port.follow(position, bearing(traveledCoordinates), !reducedMotion)
      }
    },
    resetView() {
      if (destroyed) return
      setMode('overview')
      port.showOverview()
    },
    destroy() {
      if (destroyed) return
      destroyed = true
      unsubscribe()
    },
  }
}
