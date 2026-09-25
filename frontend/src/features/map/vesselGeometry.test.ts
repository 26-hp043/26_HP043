/**
 * 3D 선박의 형상·크기 규칙 (`#1917`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 화면 회귀 테스트)
 *
 * **크기가 이 파일의 요점이다.** 종전 선체는 실측 42 m 고정이었고, 지도가 도는 줌(2~6)에서
 * 1픽셀이 수 km라 **한 픽셀도 차지하지 못했다.** layer는 정상으로 돌았고 콘솔도 조용했다 —
 * 사람이 본 것은 그 위에 얹힌 평면 SVG 마커였다. 그래서 「3D가 안 나온다」로 보였다.
 *
 * 형상은 `vesselParts.test.ts`가 본다 (`#1935`) — 여기는 **크기와 색**이다.
 */

import { describe, expect, it } from 'vitest'

import { metersPerPixel, ratingColorToken, vesselLengthMeters } from './vesselGeometry'

/** 부산 앞바다. 화면에서 실제로 쓰는 위도다. */
const BUSAN_LAT = 35.1

describe('크기 — 화면에서 읽히는 기호다', () => {
  it('먼 줌에서 배가 화면에 남는다', () => {
    // 줌 2에서 1픽셀은 약 16 km다. 실제 선박 180 m는 0.01픽셀이라 보이지 않는다 —
    // 종전 구현(42 m 고정)이 정확히 이 상태였다.
    const perPixel = metersPerPixel(2, BUSAN_LAT)
    expect(perPixel).toBeGreaterThan(10_000)
    expect(180 / perPixel).toBeLessThan(0.05)

    // 그래서 길이를 화면 기준으로 잡는다 — 30픽셀 남짓이 된다.
    const pixels = vesselLengthMeters(2, BUSAN_LAT) / perPixel
    expect(pixels).toBeGreaterThan(20)
    expect(pixels).toBeLessThan(45)
  })

  it('줌을 바꿔도 화면 크기가 유지된다', () => {
    const sizes = [2, 3, 4, 5, 6].map(
      (zoom) => vesselLengthMeters(zoom, BUSAN_LAT) / metersPerPixel(zoom, BUSAN_LAT),
    )
    for (const pixels of sizes) expect(Math.round(pixels)).toBe(Math.round(sizes[0]))
  })

  it('아주 깊은 줌에서는 실제 길이로 떨어진다', () => {
    // 항만 장면처럼 파고들면 기호가 축척에 가까워진다 — 30픽셀 기호가 실선보다 작아지는
    // 지점부터는 실제 길이(180 m)를 쓴다. 기호가 부두보다 커지는 것을 막는다.
    expect(vesselLengthMeters(16, BUSAN_LAT)).toBe(180)
  })

  it('고위도에서도 같은 화면 크기다', () => {
    // `metersPerPixel`이 위도를 보지 않으면 북쪽 배가 커진다(메르카토르).
    const low = vesselLengthMeters(4, 1.3) / metersPerPixel(4, 1.3)
    const high = vesselLengthMeters(4, 60) / metersPerPixel(4, 60)
    expect(Math.round(low)).toBe(Math.round(high))
  })
})

describe('등급 색 — 토큰을 가리킨다', () => {
  it('등급마다 있는 토큰을 고른다', () => {
    // 새 색을 만들지 않는다(`DESIGN_SYSTEM §0.2`) — 이름이 틀리면 화면이 중립색으로 떨어진다.
    expect(ratingColorToken('A')).toBe('--cii-a-fill')
    expect(ratingColorToken('e')).toBe('--cii-e-fill')
  })

  it('등급이 없거나 모르는 값이면 색을 지어내지 않는다', () => {
    expect(ratingColorToken(null)).toBeNull()
    expect(ratingColorToken('F')).toBeNull()
    expect(ratingColorToken('')).toBeNull()
  })
})
