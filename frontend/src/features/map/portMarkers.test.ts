// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { mergePortMarkers, portLabelPlacement, portMarkerElement, type PortMarkerModel } from './portMarkers'

const marker = (label: string): PortMarkerModel => ({ id: label, role: 'destination', label, coordinate: [129, 35] })

describe('공용 항만 marker', () => {
  it('화면 좌·중앙·우 edge collision에서 label을 안쪽으로 배치한다', () => {
    expect(portLabelPlacement(5, 400)).toBe('start')
    expect(portLabelPlacement(200, 400)).toBe('center')
    expect(portLabelPlacement(395, 400)).toBe('end')
  })

  it('다중 선박의 같은 목적항을 label 하나로 합친다', () => {
    expect(mergePortMarkers([marker('부산'), marker('BUSAN')])).toMatchObject([{ label: '부산 · BUSAN' }])
  })

  it('역할을 색이 아닌 출·도·경 문자와 ARIA로 구분한다', () => {
    const element = portMarkerElement(marker('부산'))
    expect(element.textContent).toContain('도')
    expect(element.getAttribute('aria-label')).toContain('도착항')
    expect(element.className).not.toMatch(/grade|rating/)
  })

  it('진입 동작이 있으면 button으로 만들고 keyboard click과 focus를 제공한다', () => {
    const onActivate = vi.fn()
    const element = portMarkerElement({ ...marker('부산'), onActivate })
    expect(element.tagName).toBe('BUTTON')
    document.body.append(element)
    element.click()
    expect(document.activeElement).toBe(element)
    expect(onActivate).toHaveBeenCalledTimes(1)
  })

  it('모바일 label은 viewport 폭 안으로 제한하는 CSS 계약을 유지한다', () => {
    const css = readFileSync(join(process.cwd(), 'src/features/map/MapMarkers.css'), 'utf8')
    expect(css).toMatch(/@media \(max-width: 40rem\)[\s\S]*\.map-port__label\s*{\s*max-width: 6rem/)
    expect(css).toContain('var(--text-secondary)')
    expect(css).not.toMatch(/#[0-9a-f]{3,8}/i)
  })
})

/**
 * 들어갈 장면이 있는 항구 핀은 **버튼**이다 (`#1933`).
 *
 * 종전 선대 핀은 무조건 `role="img"`였다 — 항만 장면이 저장소에 있는데 **대시보드에서는
 * 들어갈 길이 없었다.** 키보드 사용자에게는 존재조차 드러나지 않는다.
 */
describe('항만으로 들어가는 핀 (#1933)', () => {
  const base = { id: 'fleet:KRPUS:35.1,129.0', label: '부산', coordinate: [129.0, 35.1] as const }

  it('장면이 있고 동작이 있으면 버튼이다', () => {
    const onActivate = vi.fn()
    const element = portMarkerElement({
      ...base, role: 'berth', appearance: 'fleet', enterable: true, onActivate,
    })
    expect(element.tagName).toBe('BUTTON')
    expect(element.getAttribute('aria-label')).toContain('항만 장면 열기')
    // 정박 중이라는 사실도 낭독에 담는다 — 왜 이 항만이 떴는지가 거기서 갈린다.
    expect(element.getAttribute('aria-label')).toContain('정박')
    element.dispatchEvent(new MouseEvent('click'))
    expect(onActivate).toHaveBeenCalled()
  })

  it('장면이 없으면 그림으로 남는다', () => {
    const element = portMarkerElement({ ...base, role: 'berth', appearance: 'fleet', enterable: false })
    expect(element.tagName).toBe('SPAN')
    expect(element.getAttribute('role')).toBe('img')
  })
})
