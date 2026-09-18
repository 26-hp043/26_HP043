import { describe, expect, it, vi } from 'vitest'
import { BASEMAP_FONTS_URL, BASEMAP_URL, MAX_ZOOM, hasBasemap } from './basemap'

/**
 * 지도 자산 판정 (`#763`).
 *
 * **자산이 없을 때 개략도로 떨어지는 것**이 이 모듈의 존재 이유다(ⓑ 결정). 판정이
 * 틀리면 위치 화면이 통째로 빈다.
 */
/** PMTiles 아카이브의 첫 7바이트. */
const MAGIC = new Uint8Array([0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73])

/**
 * `hasBasemap`이 보는 만큼만 갖춘 응답 — 상태 코드와 앞머리 바이트다 (`#1144`).
 *
 * 종전 모의는 `{ ok: true }` 하나였고, 그 모양이 **실제로 문제가 된 응답**
 * (SPA fallback의 `200` + `index.html`)과 구분되지 않아 결함을 정답으로 들고 있었다.
 */
function respond(status: number, body: Uint8Array) {
  return {
    status,
    body: { cancel: vi.fn().mockResolvedValue(undefined) },
    arrayBuffer: () => Promise.resolve(body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength)),
  }
}

/** SPA fallback이 돌려주는 `index.html`의 앞머리. */
const HTML = new TextEncoder().encode('<!doctype html>\n<html lang="ko">')

describe('지도 자산 (#763)', () => {
  it('자산은 우리 오리진이다 — 키도 외부 호스트도 없다', () => {
    // 온라인 타일을 쓰면 ⑴ 무료 티어가 대부분 비상업 전용이고 ⑵ 키가 번들에 박히며
    // ⑶ 심사장 인터넷이 보장되지 않는다(`#791`).
    expect(BASEMAP_URL.startsWith('/')).toBe(true)
    expect(BASEMAP_FONTS_URL.startsWith('/')).toBe(true)
    expect(`${BASEMAP_URL}${BASEMAP_FONTS_URL}`).not.toMatch(/https?:|\bkey=|\bapikey/i)
  })

  it('확대 상한이 z6이다 — 자산의 z5에 한 단만 얹는다 (#985)', () => {
    /*
     * 상한을 누르는 근거가 **둘**이고 좁은 쪽을 따른다.
     *
     * ⓥ **위치 데이터가 받치지 못한다.** 지금 좌표는 사람이 찍은 한 점이다.
     *   z12까지 열면 한 달 전에 손으로 찍은 점이 부두 하나를 정확히 가리키는
     *   것처럼 보인다. AIS(`#764`)가 붙으면 올린다.
     * ⓦ **자산이 z5까지다** (`#985`). 배포처가 파일 하나를 25 MiB로 막아 전 세계
     *   z0–z5만 담는다. 그 위로는 마지막 층을 늘려 보여 주므로(overzoom) 깨지지는
     *   않지만 해안선이 뭉툭해진다 — 한 단이 한계다.
     *
     * 종전 값 `10`은 자산이 항만 z7–z10까지 담는다는 전제였고, 그 전제가 바뀌었다.
     * **자산의 줌 상한을 바꾸면 이 값도 함께 바꿔야 한다** — 한쪽만 바꾸면 화면이
     * 깨지지 않은 채 흐려지기만 하므로 알아채기 어렵다.
     */
    expect(MAX_ZOOM).toBe(6)
  })

  it('있으면 true — 매직 넘버가 맞는다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(respond(206, MAGIC))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(true)
    // 80 MB를 확인용으로 당기지 않는다 — 앞 7바이트만 받는다.
    expect(fetchImpl).toHaveBeenCalledWith(BASEMAP_URL, { headers: { Range: 'bytes=0-6' } })
  })

  it('404면 false — 개략도로 떨어진다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(respond(404, new Uint8Array()))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('SPA fallback의 200 index.html은 false다 (#1144)', async () => {
    // 이것이 실제로 겪은 모양이다 — Vite도 nginx의 `try_files … /index.html`도
    // 없는 경로에 index.html을 200으로 돌려준다. 상태 코드만 보면 「있다」가 되고,
    // 그러면 개략도로 떨어지지 않아 **지도 배경도 선박 마커도 없는 회색 사각형**만
    // 남는다(maplibre의 `load`가 오지 않아 마커를 붙이는 자리가 실행되지 않는다).
    const fetchImpl = vi.fn().mockResolvedValue(respond(200, HTML))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('206인데 내용이 HTML이면 false다', async () => {
    // Range를 받아 주면서 fallback 본문을 주는 서버도 있을 수 있다.
    const fetchImpl = vi.fn().mockResolvedValue(respond(206, HTML))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('Range를 지원하지 않으면(200) 본문을 끌어오지 않고 false다', async () => {
    // 200이면 80 MB가 딸려 온다 — 읽지 않고 끊어야 한다.
    // PMTiles는 Range로 파일 일부만 읽으므로 이런 서버에서는 어차피 지도가 뜨지 않는다.
    const response = respond(200, MAGIC)
    const fetchImpl = vi.fn().mockResolvedValue(response)

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
    expect(response.body.cancel).toHaveBeenCalled()
  })

  it('앞머리가 잘려 오면 false다', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(respond(206, MAGIC.slice(0, 3)))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })

  it('네트워크가 끊겨도 던지지 않는다', async () => {
    // 던지면 대시보드 전체가 실패한다. 지도가 없는 것은 **오류가 아니라 상태**다.
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('offline'))

    await expect(hasBasemap(fetchImpl as unknown as typeof fetch)).resolves.toBe(false)
  })
})
