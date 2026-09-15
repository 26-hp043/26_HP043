import { describe, expect, it, vi } from 'vitest'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from './basemap'

/**
 * 지도 자산 판정 (`#763`).
 *
 * **자산이 없을 때 개략도로 떨어지는 것**이 이 모듈의 존재 이유다(ⓑ 결정). 판정이
 * 틀리면 위치 화면이 통째로 빈다.
 */
/**
 * `hasBasemap`이 보는 만큼만 갖춘 응답 — `ok`와 `content-type`이다 (`#1144`).
 *
 * 종전 모의는 `{ ok: true }` 하나였고, 그 모양이 **실제로 문제가 된 응답**
 * (SPA fallback의 `200 text/html`)과 구분되지 않아 결함을 정답으로 들고 있었다.
 */
function respond(ok: boolean, contentType: string | null) {
  return { ok, headers: { get: (name: string) => (name === 'content-type' ? contentType : null) } }
}

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
    const fetchImpl = vi.fn().mockResolvedValue(respond(true, 'application/octet-stream'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(true)
    // 83 MB를 확인용으로 당기지 않는다 — `HEAD`다.
    expect(fetchImpl).toHaveBeenCalledWith(BASEMAP_URL, { method: 'HEAD' })
  })

  it('404면 false — 개략도로 떨어진다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(respond(false, 'text/html'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('SPA fallback의 200 text/html은 false다 (#1144)', async () => {
    // 이것이 실제로 겪은 모양이다 — Vite도 nginx의 `try_files … /index.html`도
    // 없는 경로에 index.html을 200으로 돌려준다. 상태 코드만 보면 「있다」가 되고,
    // 그러면 개략도로 떨어지지 않아 **지도 배경도 선박 마커도 없는 회색 사각형**만
    // 남는다(maplibre의 `load`가 오지 않아 마커를 붙이는 자리가 실행되지 않는다).
    const fetchImpl = vi.fn().mockResolvedValue(respond(true, 'text/html'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('charset이 붙은 text/html도 false다', async () => {
    // 실제 응답은 `text/html; charset=utf-8`로 온다 — 문자열 비교로는 못 잡는다.
    const fetchImpl = vi.fn().mockResolvedValue(respond(true, 'text/html; charset=utf-8'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('content-type이 없으면 있는 것으로 본다', async () => {
    // 헤더를 주지 않는 정적 서버가 있다. 그 경우까지 없음으로 접으면 자산이 실제로
    // 있는 환경에서 지도가 사라진다 — 놓치는 쪽이 잘못 끄는 쪽보다 낫다.
    const fetchImpl = vi.fn().mockResolvedValue(respond(true, null))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(true)
  })

  it('네트워크가 끊겨도 던지지 않는다', async () => {
    // 던지면 대시보드 전체가 실패한다. 지도가 없는 것은 **오류가 아니라 상태**다.
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('offline'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })
})
