/**
 * 지도 위 3D 선박의 **부품 명세** (`#1935`).
 *
 * ## 실험에서 사람이 고른 형상을 되살린다
 *
 * `#1907`이 지우기 전, 항만 미니어처 실험
 * (`annual-simulation/visualization/experiments/miniature3d/main.ts`)이 배를 이렇게 세웠다 —
 * **8각으로 테이퍼진 선체 · 갑판 널 · 선미 선교 · 컨테이너 적재**. 제품으로 옮기면서
 * 그 형상은 사라지고 사각뿔 하나가 남았고(`#1907`), 그 뒤로 배가 배로 보이지 않았다
 * (`#1917` 크기·투영·컬링 · `#1932` 어깨·선교). 형상 자체를 실험 쪽으로 되돌린다.
 *
 * 멀리서 배를 배로 읽게 하는 것은 **뱃머리 각도가 아니라 실루엣**이다 — 길쭉한 선체
 * 위에 무언가 쌓여 있고 한쪽 끝에 탑이 선 모양. 컨테이너가 그 「쌓임」을 만든다.
 *
 * ## 왜 명세를 따로 두는가
 *
 * three 기본 도형(Box·Cylinder)으로 세우면 감기 방향·법선을 라이브러리가 맡아 준다 —
 * `#1917`에서 정점을 손으로 적다 **면이 컬링돼 배가 통째로 사라진** 일을 되풀이하지
 * 않는다. 대신 **치수와 자리**는 여기 데이터로 두어, WebGL 없이 검사할 수 있게 한다
 * (`vesselParts.test.ts`가 비율·부품 구성·예산을 본다).
 *
 * 단위는 **선체 길이 1**이다. 위는 `+Y`, **앞은 `+Z`** — 호출부가 화면 방위에 맞춰 돌린다.
 *
 * ⚠️ 앞을 `+Z`로 두는 것은 화면 쪽 사정이다. 눕히는 회전(`X`축 90°)이 `+Z`를 화면
 * **위**로 보내므로, 그래야 뱃머리가 위를 향한다 — `-Z`로 두면 배가 앞뒤로 뒤집혀
 * **선교가 뱃머리에 선다**(`#1935`에서 실제로 그랬다).
 */

import type { MapModeInput } from './renderer'

/** 부품이 맡는 자리. 색을 고르는 기준이며, 등급 색은 **선체 하나**가 받는다. */
type VesselPartRole = 'hull' | 'deck' | 'bridge' | 'cargo' | 'funnel'

export interface VesselPart {
  readonly role: VesselPartRole
  /** `prism`은 8각 기둥(실험의 `CylinderGeometry(…, 8)`), 그 밖은 상자다. */
  readonly shape: 'prism' | 'box'
  /** 가로(폭) · 세로(높이) · 앞뒤(길이). 선체 길이 1 기준. */
  readonly size: readonly [number, number, number]
  /** 중심 위치. 원점은 **흘수선 중앙**이라 그대로 놓으면 수면에 앉는다. */
  readonly at: readonly [number, number, number]
  /** `cargo`만 쓴다 — 같은 색이 줄줄이 서지 않게 흩는 값이다. */
  readonly tint?: number
}

/** 실험이 쓰던 비율을 길이 1로 환산한 값이다(실험 선체 길이 ≈ 8.4 · 폭 ≈ 2.6). */
const HULL = { beam: 0.3, depth: 0.14 } as const
const DECK = { beam: 0.24, thickness: 0.02 } as const
const BRIDGE = { beam: 0.19, height: 0.19, length: 0.14 } as const
const FUNNEL = { beam: 0.06, height: 0.1, length: 0.06 } as const

/** 컨테이너 한 칸. 실험의 `[2.2, 1.55, 2.9]`를 길이 1로 환산했다. */
const BOX = { beam: 0.095, height: 0.066, length: 0.125 } as const
/** 적재 배치 — 실험은 3열 × 2단 × 4줄이었다. 지도에서는 2단 × 3줄이면 실루엣이 선다. */
const STACK = { rows: 3, layers: 2, columns: 3 } as const

/**
 * 이 모드의 선박을 이루는 부품들.
 *
 * `fleet`은 지도에서 44px 남짓이라 **실루엣만 읽힌다** — 선체·갑판·선교·컨테이너까지다.
 * 추적 모드는 가까이서 보므로 연돌을 하나 더 얹는다.
 */
export function vesselParts(mode: MapModeInput['mode']): readonly VesselPart[] {
  const parts: VesselPart[] = []

  // 선체 — 8각 기둥을 눕힌다. 위가 넓고 아래가 좁아(테이퍼) 옆에서 배의 결이 보인다.
  parts.push({ role: 'hull', shape: 'prism', size: [HULL.beam, HULL.depth, 1], at: [0, 0, 0] })
  /*
   * 갑판 널 — 선체보다 **좁다**.
   *
   * 위에서 내려다보는 지도라 갑판이 넓으면 선체를 덮는다. 선체는 **등급 색**을 받는
   * 면이므로(`vesselLayer.ts`), 덮이면 지도에서 등급을 읽을 채널이 사라진다. 좁혀 두면
   * 등급 색이 배 둘레를 감싸는 테두리로 남는다 — 실선의 불워크가 그렇게 보인다.
   */
  parts.push({
    role: 'deck', shape: 'box',
    size: [DECK.beam, DECK.thickness, 0.92],
    at: [0, HULL.depth / 2, 0],
  })

  // 선교 — 선미(`-Z`) 쪽. 앞뒤를 말하는 것이 이 탑이다.
  const deckTop = HULL.depth / 2 + DECK.thickness
  parts.push({
    role: 'bridge', shape: 'box',
    size: [BRIDGE.beam, BRIDGE.height, BRIDGE.length],
    at: [0, deckTop + BRIDGE.height / 2, -0.34],
  })

  // 컨테이너 — 실루엣에 「쌓임」을 준다. 멀리서 배를 배로 읽게 하는 것이 이 덩어리다.
  for (let row = 0; row < STACK.rows; row += 1) {
    for (let layer = 0; layer < STACK.layers; layer += 1) {
      for (let column = 0; column < STACK.columns; column += 1) {
        parts.push({
          role: 'cargo', shape: 'box',
          size: [BOX.beam, BOX.height, BOX.length],
          at: [
            (row - (STACK.rows - 1) / 2) * (BOX.beam + 0.005),
            deckTop + BOX.height / 2 + layer * BOX.height,
            (column - (STACK.columns - 1) / 2) * (BOX.length + 0.01) + 0.06,
          ],
          tint: (row + layer + column) % 5,
        })
      }
    }
  }

  if (mode !== 'fleet') {
    parts.push({
      role: 'funnel', shape: 'box',
      size: [FUNNEL.beam, FUNNEL.height, FUNNEL.length],
      at: [0, deckTop + BRIDGE.height + FUNNEL.height / 2, -0.36],
    })
  }

  return parts
}

/** 삼각형 수 — 상자는 12, 8각 기둥은 옆 16 + 뚜껑 12다. 예산 대조에 쓴다. */
export function vesselTriangleCount(mode: MapModeInput['mode']): number {
  return vesselParts(mode).reduce((sum, part) => sum + (part.shape === 'box' ? 12 : 28), 0)
}

/**
 * 화물 색 토큰 (`#1935`).
 *
 * **새 색을 만들지 않는다**(`DESIGN_SYSTEM §0.2`). 실험은 임의의 다섯 색을 썼지만 제품에서는
 * 쓸 수 없다 — 이미 있는 중립·표면 토큰을 돌려 쓴다. 등급 색은 **선체**가 받으므로
 * 화물이 등급으로 읽힐 일은 없다.
 */
export const CARGO_COLOR_TOKENS = [
  '--surface-card',
  '--surface-inset',
  '--surface-page',
  '--color-border-control',
] as const
