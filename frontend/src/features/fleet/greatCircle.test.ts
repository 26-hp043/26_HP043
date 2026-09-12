import { describe, expect, it } from 'vitest'
import { greatCirclePath } from './greatCircle'

/**
 * 대권 항로선 (`#763`).
 *
 * 보는 것은 **직선과 다른가**와 **날짜변경선에서 되돌아가지 않는가** 둘이다. 이 둘이
 * 틀리면 화면이 배가 가지 않는 길을 그린다.
 */
describe('대권 항로선 (#763)', () => {
  it('같은 점이면 점 하나다 — 0으로 나누지 않는다', () => {
    expect(greatCirclePath(35.1, 129.03, 35.1, 129.03)).toEqual([[129.03, 35.1]])
  })

  it('양 끝이 출발·도착과 같다', () => {
    const path = greatCirclePath(35.1, 129.0333, 1.2833, 103.85)

    expect(path[0][0]).toBeCloseTo(129.0333, 4)
    expect(path[0][1]).toBeCloseTo(35.1, 4)
    expect(path[path.length - 1][0]).toBeCloseTo(103.85, 4)
    expect(path[path.length - 1][1]).toBeCloseTo(1.2833, 4)
  })

  it('직선이 아니다 — 중간점이 위도 평균보다 북쪽으로 휜다', () => {
    /*
     * 부산(35.1N) → 로테르담(51.9N)은 **고위도로 휘는 것이 최단 경로**다. 화면상
     * 직선으로 이으면 두 위도의 평균쯤을 지나는데, 대권은 그보다 훨씬 북쪽을 지난다.
     * 이 검사가 없으면 직선으로 바꿔 놓아도 아무도 모른다.
     */
    const path = greatCirclePath(35.1, 129.0333, 51.9, 4.4833)
    const middle = path[Math.floor(path.length / 2)]
    const straightMean = (35.1 + 51.9) / 2

    expect(middle[1]).toBeGreaterThan(straightMean + 5)
  })

  it('날짜변경선을 넘어도 경도가 되돌아가지 않는다', () => {
    /*
     * 경도는 `+180`에서 `-180`으로 튄다. 그대로 두면 태평양을 건너는 항로가
     * **유라시아를 가로질러 반대편으로 가는 선**이 된다. 180 밖으로 연장해 이어 둔다.
     */
    const path = greatCirclePath(35.0, 140.0, 37.8, -122.4)

    for (let i = 1; i < path.length; i += 1) {
      expect(Math.abs(path[i][0] - path[i - 1][0])).toBeLessThan(180)
    }
    // 실제로 180을 넘겨 이어 붙였는지 — 넘지 않으면 위 검사는 아무것도 보지 않는다.
    expect(Math.max(...path.map((point) => point[0]))).toBeGreaterThan(180)
  })
})
