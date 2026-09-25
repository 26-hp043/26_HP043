/**
 * 3D 선박의 **형상과 크기**를 정하는 순수 부분 (`#1917`).
 *
 * ## 왜 꺼냈나
 *
 * 종전 선박은 `ConeGeometry(1, 3, 4)`(사각뿔) **한 줄**이었고, 크기를 **실측 42 m**로
 * 잡았다. 지도가 도는 줌은 2~6이고 그때 1픽셀은 수 km다 — **배가 화면에 한 픽셀도
 * 차지하지 못했다.** 3D layer는 정상으로 돌고 있었고, 사람이 본 것은 그 위에 얹힌
 * 평면 SVG 마커뿐이었다.
 *
 * 형상과 크기는 **WebGL 없이 정할 수 있다.** 여기서 배열을 만들고 `vesselLayer.ts`가
 * three의 버퍼로 감싼다 — 그래야 검사가 지오메트리 예산(`VESSEL_GEOMETRY_BUDGET`)과
 * 크기 규칙을 런타임 없이 본다.
 */

/**
 * 화면에서 유지할 선박 길이(px).
 *
 * **크기는 축척이 아니라 기호다.** 줌 2에서 1픽셀이 약 16 km라 실제 선박(180 m 남짓)은
 * 0.01픽셀이 된다 — 어떤 형상을 만들어도 보이지 않는다. 그래서 마커와 같은 규칙을
 * 따른다: **화면에서 읽히는 크기를 유지한다.**
 *
 * 값은 종전 평면 마커(22px)보다 크다 — 3D 선체는 **형상으로** 방향을 말하므로 그만한
 * 자리가 있어야 뱃머리가 보인다. 44px에서 선수·선미·선교가 갈린다(실측).
 *
 * ⚠️ **축척으로 읽히면 안 된다.** 낭독 라벨과 대체 정보는 좌표를 적고, 이 형상은
 * 「여기에 배가 있고 이쪽을 향한다」만 말한다(`DESIGN_SYSTEM §9.5` 마커 규칙과 같다).
 */
export const VESSEL_SCREEN_LENGTH_PX = 44

/** 참고용 실제 길이(m). 줌이 아주 깊어지면(항만 장면) 기호가 축척에 가까워진다. */
const NOMINAL_LOA_M = 180

/** 적도 둘레(m) — MapLibre의 줌 0은 512픽셀에 세계를 담는다. */
const EARTH_CIRCUMFERENCE_M = 40_075_016.686
const TILE_SIZE_PX = 512

/** 그 위도·줌에서 1픽셀이 몇 미터인가. */
export function metersPerPixel(zoom: number, latitudeDeg: number): number {
  const latitude = Math.max(-85, Math.min(85, latitudeDeg))
  const cos = Math.cos((latitude * Math.PI) / 180)
  return (EARTH_CIRCUMFERENCE_M * cos) / (TILE_SIZE_PX * Math.pow(2, zoom))
}

/**
 * 이 줌에서 선박을 **몇 미터로** 그릴 것인가.
 *
 * 실제 길이와 「화면 30px에 해당하는 길이」 중 **큰 쪽**을 쓴다. 먼 줌에서는 화면 크기가
 * 이기고(보인다), 항만처럼 깊이 들어가면 실제 길이가 이긴다(축척에 가까워진다).
 */
export function vesselLengthMeters(zoom: number, latitudeDeg: number): number {
  return Math.max(NOMINAL_LOA_M, VESSEL_SCREEN_LENGTH_PX * metersPerPixel(zoom, latitudeDeg))
}

/**
 * 등급 색을 CSS 토큰에서 읽는다 — **새 색을 만들지 않는다**(`DESIGN_SYSTEM §0.2`).
 *
 * 토큰을 읽으므로 라이트·다크가 저절로 따라온다. 값이 없으면 `null`이고 호출부가
 * 중립색을 쓴다 — 없는 등급을 색으로 지어내지 않는다.
 */
export function ratingColorToken(rating: string | null): string | null {
  if (rating === null) return null
  const key = rating.trim().toLowerCase()
  return /^[a-e]$/.test(key) ? `--cii-${key}-fill` : null
}
