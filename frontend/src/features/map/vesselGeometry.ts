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

import type { MapModeInput } from './renderer'

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

/** 선체 비율 — 길이 1을 기준으로 한 폭·깊이. 실선(實船)의 대략적인 비이며 정밀값이 아니다. */
export const HULL_PROPORTIONS = { beam: 0.34, draft: 0.16, freeboard: 0.12 } as const

interface Outline {
  readonly z: number
  /** 선수(+Y)에서 시계 방향으로 도는 닫힌 다각형. 길이 1, 중심 원점 기준. */
  readonly points: readonly (readonly [number, number])[]
}

/**
 * 선체 단면 둘 — 갑판(위)과 선저(아래).
 *
 * 사각뿔과 달리 **선수가 뾰족하고 선미가 잘려 있어**, 방향이 회전 없이도 읽힌다.
 *
 * 점을 다섯에서 **일곱**으로 늘렸다 (`#1932`). 다섯은 선수에서 현측까지가 직선 하나라
 * 위에서 보면 **화살표**로 읽혔다 — 실선은 뱃머리에서 어깨(shoulder)까지 한 번 꺾이고
 * 거기서 평행부(parallel middle body)가 길게 이어진다. 그 꺾임이 「화살표」와 「배」를
 * 가른다. 선미도 살짝 좁혀 **앞뒤가 다르게** 보이게 했다.
 */
const DECK: Outline = {
  z: HULL_PROPORTIONS.freeboard,
  points: [
    [0, 0.5],        // 선수
    [0.11, 0.33],    // 어깨 — 여기서 한 번 꺾인다
    [0.17, 0.1],
    [0.17, -0.34],   // 평행부 끝
    [0.13, -0.44],   // 선미 — 좁힌다
    [-0.13, -0.44],
    [-0.17, -0.34],
  ],
}
const KEEL: Outline = {
  z: -HULL_PROPORTIONS.draft,
  points: [
    [0, 0.38],
    [0.06, 0.28],
    [0.1, 0.06],
    [0.1, -0.3],
    [0.07, -0.4],
    [-0.07, -0.4],
    [-0.1, -0.3],
  ],
}

/**
 * 선교(deckhouse) — 선미 쪽에 올리는 상자. **모든 모드에 둔다** (`#1932`).
 *
 * 종전에는 추적 모드에만 있었는데, 위에서 내려다보는 선대 지도에서 **선체만으로는
 * 두께가 읽히지 않았다** — 갑판이 평평한 한 장이라 그림자가 생기지 않는다. 선교가
 * 서면 빛이 한 면에 걸려 **배가 입체로 보이고**, 그 위치(선미 쪽)가 앞뒤를 한 번 더 말한다.
 */
const DECKHOUSE = { halfBeam: 0.09, from: -0.36, to: -0.18, height: 0.22 } as const

/** 연돌(funnel) — 선교 위 작은 상자. 추적 모드에서만 쓴다(예산 안). */
const FUNNEL = { halfBeam: 0.035, from: -0.3, to: -0.24, height: 0.14 } as const

function pushTriangle(
  out: number[],
  a: readonly [number, number, number],
  b: readonly [number, number, number],
  c: readonly [number, number, number],
): void {
  out.push(...a, ...b, ...c)
}

function fanIndices(count: number): readonly (readonly [number, number, number])[] {
  const triangles: [number, number, number][] = []
  for (let i = 1; i < count - 1; i += 1) triangles.push([0, i, i + 1])
  return triangles
}

/**
 * 선박 mesh의 정점 배열(삼각형 목록). 단위는 **길이 1**이며 호출부가 미터로 키운다.
 *
 * 앞은 `+Y`, 위는 `+Z`다(`VESSEL_GEOMETRY_BUDGET.forwardAxis`). 원점은 흘수선 중앙이라
 * 좌표에 그대로 놓으면 수면에 앉는다.
 */
export function vesselHullVertices(mode: MapModeInput['mode']): Float32Array {
  const out: number[] = []
  const deck = DECK.points
  const keel = KEEL.points
  const count = deck.length

  // 옆면 — 갑판과 선저를 잇는 사각형 다섯을 삼각형 열로 편다.
  for (let i = 0; i < count; i += 1) {
    const next = (i + 1) % count
    const d0: [number, number, number] = [deck[i][0], deck[i][1], DECK.z]
    const d1: [number, number, number] = [deck[next][0], deck[next][1], DECK.z]
    const k0: [number, number, number] = [keel[i][0], keel[i][1], KEEL.z]
    const k1: [number, number, number] = [keel[next][0], keel[next][1], KEEL.z]
    pushTriangle(out, d0, k0, k1)
    pushTriangle(out, d0, k1, d1)
  }

  // 갑판(위)과 선저(아래) — 오각형이라 삼각형 셋씩이다.
  for (const [a, b, c] of fanIndices(count)) {
    pushTriangle(out, [deck[a][0], deck[a][1], DECK.z], [deck[b][0], deck[b][1], DECK.z], [deck[c][0], deck[c][1], DECK.z])
    pushTriangle(out, [keel[a][0], keel[a][1], KEEL.z], [keel[c][0], keel[c][1], KEEL.z], [keel[b][0], keel[b][1], KEEL.z])
  }

  // 선교 — 예산이 넉넉한 추적 모드에서만. 옆에서 볼 때 배의 앞뒤를 한 번 더 말해 준다.
  // 상부 구조 — 상자 하나를 올리는 일이 두 번이라 함수로 묶는다.
  const box = (spec: { halfBeam: number; from: number; to: number; height: number }, base: number) => {
    const { halfBeam: w, from, to, height } = spec
    const top = base + height
    const corners: [number, number][] = [[w, to], [w, from], [-w, from], [-w, to]]
    for (let i = 0; i < corners.length; i += 1) {
      const next = (i + 1) % corners.length
      const b0: [number, number, number] = [corners[i][0], corners[i][1], base]
      const b1: [number, number, number] = [corners[next][0], corners[next][1], base]
      const t0: [number, number, number] = [corners[i][0], corners[i][1], top]
      const t1: [number, number, number] = [corners[next][0], corners[next][1], top]
      pushTriangle(out, b0, b1, t1)
      pushTriangle(out, b0, t1, t0)
    }
    const roof = corners.map(([x, y]): [number, number, number] => [x, y, top])
    pushTriangle(out, roof[0], roof[1], roof[2])
    pushTriangle(out, roof[0], roof[2], roof[3])
    return top
  }

  // 선교는 모든 모드에 둔다 — 위에서 내려다볼 때 두께를 만드는 것이 이 면이다.
  const bridgeTop = box(DECKHOUSE, DECK.z)
  // 연돌은 추적 모드에만. 가까이서 볼 때 배의 앞뒤를 한 번 더 말한다.
  if (mode !== 'fleet') box(FUNNEL, bridgeTop)

  return new Float32Array(out)
}

/** 그 형상이 쓰는 삼각형 수. 예산 대조에 쓴다. */
export function vesselTriangleCount(mode: MapModeInput['mode']): number {
  return vesselHullVertices(mode).length / 9
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
