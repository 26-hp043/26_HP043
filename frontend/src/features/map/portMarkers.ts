import type { RouteCoordinate } from './routeGeometry'

type PortRole = 'departure' | 'destination' | 'waypoint'

export interface PortMarkerModel {
  readonly id: string
  readonly role: PortRole
  readonly label: string
  readonly coordinate: RouteCoordinate
  readonly appearance?: 'fleet'
  readonly onActivate?: () => void
}

type PortLabelPlacement = 'start' | 'center' | 'end'

/** 화면 가장자리에서는 label이 viewport 안쪽으로 향하게 한다. */
export function portLabelPlacement(screenX: number, viewportWidth: number): PortLabelPlacement {
  const edge = Math.min(80, viewportWidth * 0.2)
  if (screenX < edge) return 'start'
  if (screenX > viewportWidth - edge) return 'end'
  return 'center'
}

/** 같은 역할·좌표의 중복 목적항은 label 하나로 합쳐 마커가 겹치지 않게 한다. */
export function mergePortMarkers(markers: readonly PortMarkerModel[]): readonly PortMarkerModel[] {
  const merged = new Map<string, PortMarkerModel>()
  for (const marker of markers) {
    const key = `${marker.role}:${marker.coordinate[0]}:${marker.coordinate[1]}`
    const previous = merged.get(key)
    if (!previous) merged.set(key, marker)
    else if (!previous.label.split(' · ').includes(marker.label)) {
      merged.set(key, { ...previous, label: `${previous.label} · ${marker.label}` })
    }
  }
  return [...merged.values()]
}

export function portMarkerElement(marker: PortMarkerModel): HTMLElement {
  if (marker.appearance === 'fleet') {
    const element = document.createElement('span')
    element.className = 'fleetmap__port'
    element.setAttribute('role', 'img')
    element.setAttribute('aria-label', marker.label ? `항구 ${marker.label}` : '항구')
    return element
  }
  const element = document.createElement(marker.onActivate ? 'button' : 'div')
  element.className = `map-port map-port--${marker.role}`
  element.setAttribute('aria-label', `${marker.label} · ${marker.role === 'departure' ? '출발항' : marker.role === 'destination' ? '도착항' : '경유항'}`)
  if (!marker.onActivate) element.setAttribute('role', 'img')
  const pin = document.createElement('span')
  pin.className = 'map-port__pin'
  pin.textContent = marker.role === 'departure' ? '출' : marker.role === 'destination' ? '도' : '경'
  pin.setAttribute('aria-hidden', 'true')
  const label = document.createElement('span')
  label.className = 'map-port__label'
  label.textContent = marker.label
  label.setAttribute('aria-hidden', 'true')
  element.append(pin, label)
  if (marker.onActivate) element.addEventListener('click', () => {
    // pointer 활성화도 keyboard와 같은 focus 출발점을 남겨 Harbor 복귀 위치를 보존한다.
    element.focus()
    marker.onActivate?.()
  })
  return element
}
