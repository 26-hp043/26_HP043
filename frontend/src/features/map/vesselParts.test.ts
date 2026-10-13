/**
 * 지도 위 3D 선박의 **형상** (`#1935`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 화면 회귀 테스트)
 *
 * 형상이 세 번 바뀌었다 — 사각뿔(`#1907`) → 어깨 꺾인 선체 + 선교(`#1932`) → **실험이
 * 쓰던 구성**(`#1935`). 실험(항만 미니어처)은 선체 위에 갑판 널을 깔고 컨테이너를 쌓고
 * 선미에 탑을 세웠고, 사람이 그 형상을 골랐다.
 *
 * 멀리서 배를 배로 읽게 하는 것은 **뱃머리 각도가 아니라 실루엣**이다 — 길쭉한 몸 위에
 * 무언가 쌓여 있고 한쪽 끝에 탑이 선 모양. 여기서 잠그는 것이 그 실루엣의 뼈대다.
 */

import * as THREE from 'three'
import { describe, expect, it } from 'vitest'

import { CARGO_COLOR_TOKENS, vesselParts, vesselTriangleCount, type VesselPart } from './vesselParts'
import { VESSEL_GEOMETRY_BUDGET } from './vesselModel'

const roles = (mode: 'fleet' | 'comparison' | 'playback') =>
  vesselParts(mode).map((part) => part.role)

describe('실루엣 — 실험이 고른 구성', () => {
  it('선체 · 갑판 · 선교 · 화물이 모두 있다', () => {
    // 넷 중 하나라도 빠지면 배가 아니라 **막대**가 된다 — `#1907`의 사각뿔이 그랬다.
    const fleet = roles('fleet')
    expect(fleet).toContain('hull')
    expect(fleet).toContain('deck')
    expect(fleet).toContain('bridge')
    expect(fleet).toContain('cargo')
  })

  it('화물이 쌓여 있다 — 한 층이 아니다', () => {
    // 「쌓임」이 실루엣을 만든다. 한 층이면 갑판에 무늬만 깐 것과 같다.
    const cargo = vesselParts('fleet').filter((part) => part.role === 'cargo')
    const levels = new Set(cargo.map((part) => part.at[1].toFixed(4)))
    expect(cargo.length).toBeGreaterThan(6)
    expect(levels.size).toBeGreaterThan(1)
  })

  it('선교가 화물보다 높고 선미 쪽에 있다', () => {
    // 그 탑이 앞뒤를 말한다 — 화물에 묻히면 어느 쪽이 뒤인지 사라진다.
    const parts = vesselParts('fleet')
    const bridge = parts.find((part) => part.role === 'bridge')!
    const cargoTop = Math.max(...parts.filter((p) => p.role === 'cargo').map((p) => p.at[1] + p.size[1] / 2))
    expect(bridge.at[1] + bridge.size[1] / 2).toBeGreaterThan(cargoTop)
    // 앞은 `+Z`다 — 선교는 뒤(`-Z`)에 선다. 뒤집히면 **선교가 뱃머리에 선다**.
    expect(bridge.at[2]).toBeLessThan(0)
  })

  it('선체가 가장 길고, 갑판은 선체보다 좁다', () => {
    /*
     * 위에서 내려다보는 지도라 갑판이 넓으면 선체를 덮는다. 선체는 **등급 색**을 받는
     * 면이므로, 덮이면 지도에서 등급을 읽을 채널이 사라진다 — 에서 실제로
     * 색이 양 끝에만 남았다. 좁혀 두면 등급 색이 배 둘레 테두리로 보인다.
     */
    const parts = vesselParts('fleet')
    const hull = parts.find((part) => part.role === 'hull')!
    const deck = parts.find((part) => part.role === 'deck')!
    expect(hull.size[2]).toBe(1)
    expect(deck.size[0]).toBeLessThan(hull.size[0])
    expect(deck.size[2]).toBeLessThan(hull.size[2])
  })

  it('선체는 8각 기둥이다 — 옆면이 꺾여 결이 보인다', () => {
    // 실험이 `CylinderGeometry(…, 8)`을 눕혀 쓴 그대로다. 상자면 면이 넷뿐이라 납작하다.
    expect(vesselParts('fleet').find((part) => part.role === 'hull')?.shape).toBe('prism')
  })

  it('추적 모드에만 연돌이 선다', () => {
    // 지도에서는 44px이라 보이지 않는 크기다 — 가까이 보는 화면에서만 얹는다.
    expect(roles('fleet')).not.toContain('funnel')
    expect(roles('playback')).toContain('funnel')
  })
})

/** `vesselLayer.ts`의 `shapeFor`와 같은 three 도형으로 삼각형을 센다. */
const realTriangles = (part: VesselPart): number => {
  const [x, y, z] = part.size
  const geometry = part.shape === 'box'
    ? new THREE.BoxGeometry(x, y, z)
    : new THREE.CylinderGeometry(x / 2, (x / 2) * 0.72, z, 8, 1)
  return (geometry.index ? geometry.index.count : geometry.attributes.position.count) / 3
}

describe('예산과 색', () => {
  it('계산한 삼각형 수가 three로 실제 만든 geometry와 같다', () => {
    // 28로 세어 실제(32)보다 4 적던 것을 잡는다 — 예산 안이라 예산 검사는 통과했다(`#2454`).
    for (const mode of ['fleet', 'comparison', 'playback'] as const) {
      const real = vesselParts(mode).reduce((sum, part) => sum + realTriangles(part), 0)
      expect(vesselTriangleCount(mode)).toBe(real)
    }
  })

  it('계약 상수가 부품 명세와 같은 좌표 약속을 적는다', () => {
    // 선체가 가장 길게 뻗는 축이 선수 축이고, 그 길이가 단위(1)다.
    const hull = vesselParts('fleet').find((part) => part.role === 'hull')!
    const longest = hull.size.indexOf(Math.max(...hull.size))
    expect(VESSEL_GEOMETRY_BUDGET.forwardAxis).toBe(['+X', '+Y', '+Z'][longest])
    expect(Math.max(...hull.size)).toBe(1)
    expect(VESSEL_GEOMETRY_BUDGET.unit).toBe('hull-length')
  })

  it('삼각형이 예산 안에 든다', () => {
    expect(vesselTriangleCount('fleet')).toBeLessThanOrEqual(VESSEL_GEOMETRY_BUDGET.fleetTriangles)
    for (const mode of ['comparison', 'playback'] as const) {
      expect(vesselTriangleCount(mode)).toBeLessThanOrEqual(VESSEL_GEOMETRY_BUDGET.trackingTriangles)
    }
  })

  it('외부 asset이 0이다', () => {
    // 이 숫자가 지키는 것은 성능이 아니라 **저장소 소유**다 — 형상이 코드 안에 있다.
    expect(VESSEL_GEOMETRY_BUDGET.textureBytes).toBe(0)
    expect(VESSEL_GEOMETRY_BUDGET.assetBytes).toBe(0)
  })

  it('화물 색은 이미 있는 토큰만 쓴다', () => {
    // 새 색을 만들지 않는다(`DESIGN_SYSTEM §0.2`). 실험의 임의 다섯 색은 제품에 쓸 수 없다.
    expect(CARGO_COLOR_TOKENS.length).toBeGreaterThan(1)
    for (const token of CARGO_COLOR_TOKENS) expect(token.startsWith('--')).toBe(true)
  })

  it('화물 색이 한 가지로 몰리지 않는다', () => {
    const tints = new Set(vesselParts('fleet').filter((p) => p.role === 'cargo').map((p) => p.tint))
    expect(tints.size).toBeGreaterThan(1)
  })
})
