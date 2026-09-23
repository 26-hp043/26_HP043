// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { initialPanelOpen } from './panelState'

/**
 * 지도 위 패널의 첫 상태 (#1824).
 *
 * ## 무엇을 잠그나
 *
 * ⑴ **좁은 화면은 접힌 채로 시작한다** — 360 패널이 1100에서는 지도에 남길 것이
 * 거의 없다. ⑵ **한 번이라도 접거나 편 사람의 선택이 폭보다 앞선다.** ⑶ 저장이
 * 막힌 환경에서도 화면이 선다 — 사생활 보호 창에서 `localStorage`가 던진다.
 */
const KEY = 'bluelog.fleet.panelOpen'

afterEach(() => {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // 정리에 실패해도 다음 검사가 자기 값을 덮어쓴다.
  }
  vi.restoreAllMocks()
})

describe('패널 첫 상태 (#1824)', () => {
  it('넓은 화면은 펼친 채로 시작한다', () => {
    expect(initialPanelOpen(1440)).toBe(true)
  })

  it('1100 이하는 접힌 채로 시작한다', () => {
    expect(initialPanelOpen(1100)).toBe(false)
    expect(initialPanelOpen(720)).toBe(false)
  })

  it('경계는 1100이다 — 그 위는 펼친다', () => {
    expect(initialPanelOpen(1101)).toBe(true)
  })

  it('⚠️ 저장된 선택이 화면 폭보다 앞선다', () => {
    window.localStorage.setItem(KEY, 'false')
    expect(initialPanelOpen(1920), '접어 둔 사람에게 다시 펼쳐 주지 않는다').toBe(false)

    window.localStorage.setItem(KEY, 'true')
    expect(initialPanelOpen(720), '좁은 화면에서 일부러 편 사람의 선택도 남는다').toBe(true)
  })

  it('저장을 못 읽어도 폭으로 정한다 — 던지지 않는다', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('사생활 보호 창')
    })
    expect(() => initialPanelOpen(1440)).not.toThrow()
    expect(initialPanelOpen(1440)).toBe(true)
    expect(initialPanelOpen(800)).toBe(false)
  })
})
