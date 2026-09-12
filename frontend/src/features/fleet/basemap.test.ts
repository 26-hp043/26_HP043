import { describe, expect, it, vi } from 'vitest'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from './basemap'

/**
 * 지도 자산 판정 (`#763`).
 *
 * **자산이 없을 때 개략도로 떨어지는 것**이 이 모듈의 존재 이유다(ⓑ 결정). 판정이
 * 틀리면 위치 화면이 통째로 빈다.
 */
describe('지도 자산 (#763)', () => {
  it('자산은 우리 오리진이다 — 키도 외부 호스트도 없다', () => {
    // 온라인 타일을 쓰면 ⑴ 무료 티어가 대부분 비상업 전용이고 ⑵ 키가 번들에 박히며
    // ⑶ 심사장 인터넷이 보장되지 않는다(`#791`).
    expect(BASEMAP_URL.startsWith('/')).toBe(true)
    expect(BASEMAP_FONTS_URL.startsWith('/')).toBe(true)
    expect(`${BASEMAP_URL}${BASEMAP_FONTS_URL}`).not.toMatch(/https?:|\bkey=|\bapikey/i)
  })

  it('확대 상한이 z10이다 — 위치 데이터가 그 이상을 받치지 못한다', () => {
    // 지금 좌표는 사람이 찍은 한 점이다. z12까지 열면 한 달 전에 손으로 찍은 점이
    // 부두 하나를 정확히 가리키는 것처럼 보인다. AIS(`#764`)가 붙으면 올린다.
    expect(MAX_ZOOM).toBe(10)
  })

  it('있으면 true', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true })

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(true)
    // 83 MB를 확인용으로 당기지 않는다 — `HEAD`다.
    expect(fetchImpl).toHaveBeenCalledWith(BASEMAP_URL, { method: 'HEAD' })
  })

  it('404면 false — 개략도로 떨어진다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false })

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('네트워크가 끊겨도 던지지 않는다', async () => {
    // 던지면 대시보드 전체가 실패한다. 지도가 없는 것은 **오류가 아니라 상태**다.
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('offline'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })
})
