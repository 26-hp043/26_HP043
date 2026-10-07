import type { RouteCoordinate } from './routeGeometry'

/** `berth`는 **정박 중인 배 옆의 항만**이다 (`#1933`) — 접안 판정이 아니라 자리 표시다. */
type PortRole = 'departure' | 'destination' | 'waypoint' | 'berth'

export interface PortMarkerModel {
  readonly id: string
  readonly role: PortRole
  readonly label: string
  readonly coordinate: RouteCoordinate
  readonly appearance?: 'fleet'
  /**
   * 이 항만에 **들어갈 장면이 있는가** (`#1933` · `harborScenes.ts`).
   *
   * 종전에는 선대 핀이 무조건 그림(`role="img"`)이라 **항만이 있어도 들어갈 길이
   * 없었다.** 장면이 없는 항까지 누를 수 있게 하면 눌러도 아무 일이 없다 —
   * 그래서 있는 것만 버튼이 된다.
   */
  readonly enterable?: boolean
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
    const name = marker.label ? `항구 ${marker.label}` : '항구'
    const moored = marker.role === 'berth' ? ' · 정박 중인 선박이 있습니다' : ''
    // 들어갈 장면이 있으면 **버튼**이다 (`#1933`). 없으면 종전처럼 그림으로 둔다 —
    // 누를 수 있게만 해 두면 눌러도 아무 일이 없고, 그것이 고장으로 읽힌다.
    if (marker.enterable && marker.onActivate) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'fleetmap__port fleetmap__port--enterable'
      button.setAttribute('aria-label', `${name}${moored} · 항만 장면 열기`)
      button.addEventListener('click', marker.onActivate)
      return button
    }
    const element = document.createElement('span')
    element.className = 'fleetmap__port'
    element.setAttribute('role', 'img')
    element.setAttribute('aria-label', `${name}${moored}`)
    return element
  }
  const element = document.createElement(marker.onActivate ? 'button' : 'div')
  element.className = `map-port map-port--${marker.role}`
  element.setAttribute('aria-label', `${marker.label} · ${marker.role === 'departure' ? '출발항' : marker.role === 'destination' ? '도착항' : marker.role === 'berth' ? '정박 항만' : '경유항'}`)
  if (!marker.onActivate) element.setAttribute('role', 'img')
  /*
   * 위치 핀 (10/7 디자인 결정) — 원 안 글자(「출」 「도」 「경」)는 작은 지도에서 읽히지 않았다.
   * 핀 모양으로 「여기」를 말하고, 역할은 이름표 앞에 글자로 붙인다(「출발 부산」).
   * 핀 색은 역할로 갈린다: 출발 · 도착은 브랜드 남색, 경유는 우회선과 같은 색.
   */
  const pin = document.createElement('span')
  pin.className = 'map-port__pin'
  pin.innerHTML =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M12 22s-7-6.2-7-12a7 7 0 1 1 14 0c0 5.8-7 12-7 12z" fill="currentColor" stroke="var(--color-surface)" stroke-width="1.5"/>' +
    '<circle cx="12" cy="10" r="2.6" fill="var(--color-surface)"/></svg>'
  pin.setAttribute('aria-hidden', 'true')
  const role = marker.role === 'departure' ? '출발' : marker.role === 'destination' ? '도착' : marker.role === 'berth' ? '정박' : '경유'
  const label = document.createElement('span')
  label.className = 'map-port__label'
  const roleText = document.createElement('b')
  roleText.className = 'map-port__role'
  roleText.textContent = role
  label.append(roleText, ` ${marker.label}`)
  label.setAttribute('aria-hidden', 'true')
  element.append(pin, label)
  if (marker.onActivate) element.addEventListener('click', () => {
    // pointer 활성화도 keyboard와 같은 focus 출발점을 남겨 Harbor 복귀 위치를 보존한다.
    element.focus()
    marker.onActivate?.()
  })
  return element
}
