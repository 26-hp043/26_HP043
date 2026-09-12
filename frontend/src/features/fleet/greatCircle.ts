/**
 * 대권 항로선 (`#763`).
 *
 * ## 왜 직선이 아닌가
 *
 * 지도는 웹 메르카토르다. 두 항 사이를 화면상 직선으로 이으면 **실제 배가 가는 길과
 * 다르다** — 부산→로테르담처럼 긴 구간은 고위도로 휘는 것이 최단 경로인데, 직선으로
 * 그리면 적도 쪽으로 처진 길을 가는 것처럼 보인다.
 *
 * 그래서 구면 위의 최단 경로(대권)를 **여러 점으로 쪼개** 이어 그린다. 점을 촘촘히
 * 찍을수록 곡선이 매끄럽지만, 항로선 하나에 수백 점은 필요 없다.
 *
 * ⚠️ **이것은 「예상 항로」가 아니라 「최단 경로」다.** 실제 항해는 해협·수심·기상을
 * 피해 간다. waypoint가 생기면(`#766` ⑷) 그것으로 대체된다.
 */

/**
 * 한 구간을 몇 점으로 쪼갤 것인가. 32면 지구 반바퀴도 눈에 각이 보이지 않는다.
 *
 * 내보내지 않는다 — 이 파일 밖에서 쓰이지 않는다(`#594` 미참조 export 규율).
 */
const SEGMENTS = 32

const RAD = Math.PI / 180
const DEG = 180 / Math.PI

/** 대권 위의 점 목록 `[lon, lat][]`. GeoJSON 좌표 순서(경도 먼저)다. */
export function greatCirclePath(
  fromLat: number,
  fromLon: number,
  toLat: number,
  toLon: number,
  segments: number = SEGMENTS,
): [number, number][] {
  const φ1 = fromLat * RAD
  const λ1 = fromLon * RAD
  const φ2 = toLat * RAD
  const λ2 = toLon * RAD

  const sinΔφ = Math.sin((φ2 - φ1) / 2)
  const sinΔλ = Math.sin((λ2 - λ1) / 2)
  const a = sinΔφ * sinΔφ + Math.cos(φ1) * Math.cos(φ2) * sinΔλ * sinΔλ
  const δ = 2 * Math.asin(Math.min(1, Math.sqrt(a)))

  // 같은 점이거나 사실상 붙어 있으면 쪼갤 것이 없다 — 0으로 나누는 것을 막는다.
  if (δ < 1e-9) return [[fromLon, fromLat]]

  const points: [number, number][] = []
  for (let i = 0; i <= segments; i += 1) {
    const f = i / segments
    const A = Math.sin((1 - f) * δ) / Math.sin(δ)
    const B = Math.sin(f * δ) / Math.sin(δ)
    const x = A * Math.cos(φ1) * Math.cos(λ1) + B * Math.cos(φ2) * Math.cos(λ2)
    const y = A * Math.cos(φ1) * Math.sin(λ1) + B * Math.cos(φ2) * Math.sin(λ2)
    const z = A * Math.sin(φ1) + B * Math.sin(φ2)
    points.push([Math.atan2(y, x) * DEG, Math.atan2(z, Math.sqrt(x * x + y * y)) * DEG])
  }
  return unwrapAntimeridian(points)
}

/**
 * 날짜변경선을 넘는 구간이 **지도를 가로질러 되돌아가는 선**으로 그려지는 것을 막는다.
 *
 * 경도는 `+180`에서 `-180`으로 튄다. 그대로 이으면 태평양을 건너는 항로가 **유라시아
 * 대륙을 가로질러 반대편으로 가는 선**이 된다. 누적 오프셋을 더해 경도를 `180` 밖으로
 * 연장하면(MapLibre가 허용한다) 선이 이어진 채로 그려진다.
 */
function unwrapAntimeridian(points: [number, number][]): [number, number][] {
  let offset = 0
  return points.map((point, index) => {
    if (index > 0) {
      const delta = point[0] - points[index - 1][0]
      if (delta > 180) offset -= 360
      else if (delta < -180) offset += 360
    }
    return [point[0] + offset, point[1]] as [number, number]
  })
}
