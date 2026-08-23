import { gradePatternUrl } from '../../components/gradePattern'
import type { Rating } from '../voyage-cii/types'
import { VESSEL_GRID, VESSEL_PATHS } from '../../components/vesselShape'

/**
 * 선박 한 척을 나타내는 **차트 마크** — 등급 분포 픽토그램의 낱개.
 *
 * ## `§12` 아이콘이 아니다
 *
 * `§12`는 아이콘을 「라인 · stroke 1.5–1.6 · **단색(text-muted 또는 accent)**」으로
 * 제한한다. 이 마크는 **면을 등급색으로 채운다** — 그 규격을 따르지 않는다.
 *
 * 아이콘이 아니라 **데이터 마크**이기 때문이다. 하는 일이 `PositionChart`의 선박 점과
 * 같다 — 선박 하나를 나타내고 색이 그 선박의 YTD 등급을 말한다. `§2.4.4`가 「지도
 * 마커」를 패턴 대상으로 명시한 그 자리이며, 여기서는 점 대신 배 모양을 쓸 뿐이다.
 *
 * **모양을 바꾼 이유는 가시성이다.** 4px 무늬가 얇은 막대 안에서는 뭉개져 읽히지
 * 않았다. 28px 실루엣 안에서는 무늬가 일곱 번 반복되어 형태로 드러난다.
 *
 * ## 패턴을 끄지 않는다
 *
 * `§2.4.4` — 「`showPattern`의 기본값은 `true`이고 끄는 쪽이 예외다」. 3색 체계는
 * 적록색맹에서 초록·주황·빨강이 모두 황갈색으로 수렴해 5색보다 오히려 취약하다.
 * A는 solid라 패턴이 없다(`§15.1`).
 *
 * 무늬는 셸이 한 번 그리는 `GradePatternDefs`를 참조한다 — 자산이 두 벌이 되면
 * 서로 다른 무늬를 그리게 된다(`§15.1`). 실루엣 경로도 같은 이유로 `components/vesselShape.ts`에
 * 한 벌만 둔다 — 선박 카드·위치 개략도가 같은 모양을 쓴다.
 *
 * ## 이름을 붙이지 않는다
 *
 * 낱개는 `aria-hidden`이다. 스무 개가 각각 「선박」으로 읽히면 목록을 읽는 것보다
 * 나쁘다 — 이름은 묶음(`GradeDistribution`)이 등급별로 한 번만 붙인다.
 */
export function VesselGlyph({ rating, size = 28 }: { rating: Rating; size?: number }) {
  const pattern = gradePatternUrl(rating)
  const fill = `var(--cii-${rating.toLowerCase()}-fill)`

  return (
    <svg
      className="dist__glyph"
      viewBox={`0 0 ${VESSEL_GRID} ${VESSEL_GRID}`}
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      {/*
        선체 · 선실 · 연돌을 한 덩어리로 둔다. 조각마다 색을 달리하면 등급색이
        무엇을 가리키는지 흐려진다 — 이 마크가 말하는 것은 등급 하나다.
      */}
      <g className="dist__glyph-body" fill={fill}>
        {VESSEL_PATHS.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
      {/*
        같은 형태를 무늬로 한 번 더 덮는다 — `PositionChart`가 점에 쓰는 방식과 같다.
        채움 위에 겹치는 것이라 형태가 어긋나면 안 되므로 경로를 그대로 반복한다.
      */}
      {pattern ? (
        <g fill={pattern}>
          {VESSEL_PATHS.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
      ) : null}
    </svg>
  )
}
