import type * as maplibregl from 'maplibre-gl'
import './projectionToggle.css'

/**
 * 지구본 ↔ 평면 전환 (`#1976`).
 *
 * `#1907`(PR `#1908`)이 지도를 지구본으로 바꾼 뒤 사용자는 평면 지도로 돌아갈 길이 없었다.
 * 투영은 기기 성능이 정했다(`quality.ts` — `low`면 평면, 그 밖은 지구본).
 *
 * ## 정한 것 (2026-09-27 사용자 결정 · `#1976`)
 *
 * - **`low` 기기에는 버튼을 두지 않는다** — 성능이 낮거나 「움직임 줄이기」를 켠 사람에게 평면만
 *   보여 주는 지금 판단을 지킨다. 그 판단은 이 파일이 아니라 렌더러가 버튼을 달지 말지로 한다.
 * - **처음 열면 지구본**이다. 사용자가 고른 뒤에는 그 방식으로 다시 연다.
 * - 버튼의 **자리·모양은 개발 임시안**이다 — 지도 컨트롤 자리(`DESIGN_SYSTEM §9.5`)는 디자인
 *   담당 소관이라 검토를 받는다.
 */
export type MapProjection = 'globe' | 'mercator'

/** 브라우저에만 남는 편의 기억이다 — 서버에 가지 않고, 못 읽으면 기본값(지구본)으로 연다. */
const PROJECTION_STORAGE_KEY = 'bluelog.map.projection'

export function readProjectionPreference(): MapProjection {
  try {
    return globalThis.localStorage?.getItem(PROJECTION_STORAGE_KEY) === 'mercator' ? 'mercator' : 'globe'
  } catch {
    // 저장소를 막은 환경(사생활 보호 창 등) — 기본값으로 연다.
    return 'globe'
  }
}

export function writeProjectionPreference(projection: MapProjection): void {
  try {
    globalThis.localStorage?.setItem(PROJECTION_STORAGE_KEY, projection)
  } catch {
    // 기억하지 못해도 이번 화면에서는 바뀐 채로 쓴다.
  }
}

/**
 * 버튼 문구 — **누르면 무엇이 되는가**를 말한다. 지금 상태를 말하면(「지구본」) 그것이
 * 상태인지 누를 동작인지 헷갈린다. 표시 문구(`AGENTS §4.6`) · 개발 임시안.
 */
function projectionToggleText(current: MapProjection): { readonly label: string; readonly name: string } {
  return current === 'globe'
    ? { label: '평면', name: '평면 지도로 보기' }
    : { label: '지구본', name: '지구본으로 보기' }
}

/**
 * 지도 오른쪽 위 컨트롤 묶음에 붙는 버튼 하나 (`maplibregl.IControl`).
 *
 * 확대·축소 버튼(`NavigationControl`)과 같은 묶음 모양(`maplibregl-ctrl-group`)을 쓴다 —
 * 지도의 조작은 한 자리에 모인다.
 */
export class ProjectionToggleControl implements maplibregl.IControl {
  private container: HTMLDivElement | null = null
  private button: HTMLButtonElement | null = null
  private current: MapProjection
  private readonly onToggle: (next: MapProjection) => void

  constructor(initial: MapProjection, onToggle: (next: MapProjection) => void) {
    this.current = initial
    this.onToggle = onToggle
  }

  onAdd(): HTMLElement {
    const container = document.createElement('div')
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group bluelog-projection'
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'bluelog-projection__toggle'
    button.addEventListener('click', () => {
      this.onToggle(this.current === 'globe' ? 'mercator' : 'globe')
    })
    container.append(button)
    this.container = container
    this.button = button
    this.render()
    return container
  }

  onRemove(): void {
    this.container?.remove()
    this.container = null
    this.button = null
  }

  /** 렌더러가 실제로 바꾼 뒤 알린다 — 전환이 실패하면 버튼도 그대로 남는다. */
  setCurrent(projection: MapProjection): void {
    this.current = projection
    this.render()
  }

  private render(): void {
    if (this.button === null) return
    const text = projectionToggleText(this.current)
    this.button.textContent = text.label
    this.button.setAttribute('aria-label', text.name)
    this.button.title = text.name
    this.button.dataset.projection = this.current
  }
}
