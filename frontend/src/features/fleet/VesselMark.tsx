import { VesselGlyph } from './VesselGlyph'
import { unavailableHint } from './fleetRules'
import type { FleetVessel } from './types'

/**
 * 선대 목록의 선박 마크 — 배 실루엣 + 등급 문자 (`#701` ④).
 *
 * ## `GradeBadge`를 대신한다
 *
 * 종전 카드는 축이 셋인 배지(`GradeBadge` · `RegulatoryFlags` · `ApplicabilityBadge`)를
 * **전부 이름 위에 가로로 깔았다.** 셋은 각각 다른 축이 맞지만(`§8` · `#485` · `#653`)
 * 같은 무게로 이름보다 먼저 오니, 「선박 리스트가 잘 안 보인다」가 나왔다.
 *
 * 이 마크가 등급을 맡아 **왼쪽 열로 빠지면** 이름이 첫 줄로 올라온다.
 *
 * ## 세 채널을 그대로 유지한다
 *
 * `§14`는 등급을 **색 단독으로** 전달하는 것을 금한다. 이 마크는 배지가 쓰던 세
 * 채널을 그대로 쓴다.
 *
 * | 채널 | 어디에 |
 * |---|---|
 * | 색 | 실루엣 채움 (`--cii-*-fill`) |
 * | 패턴 | 실루엣 위 무늬 (`§2.4.4` · `§15.1`) |
 * | 문자 | 마크 아래 등급 글자 |
 *
 * ## 왜 배 모양인가
 *
 * 같은 화면 위쪽 등급 분포가 **배 한 척 = 마크 하나**로 이미 그리고 있다. 목록에서
 * 다른 그림을 쓰면 두 블록이 서로 다른 언어가 된다. **위에서 배운 것을 아래에서
 * 그대로 쓰게 하는 것**이 이 재사용의 목적이다.
 *
 * ## 등급이 없는 선박
 *
 * 배 모양을 그리지 않는다 — 중립색 배를 그리면 **등급이 있는데 옅은 것**으로 읽힌다.
 * 자리를 비우지도 않는다(열이 어긋난다). `—`와 사유를 남긴다(`#419`).
 */
export function VesselMark({ vessel }: { vessel: FleetVessel }) {
  if (vessel.ytdRating === null) {
    return (
      <span
        className="vessel__mark vessel__mark--none"
        aria-label={`${vessel.name} — ${unavailableHint(vessel.unavailableReason)}`}
      >
        —
      </span>
    )
  }

  return (
    <span
      className="vessel__mark"
      role="img"
      aria-label={`${vessel.name} 올해 누적 등급 ${vessel.ytdRating}`}
    >
      <VesselGlyph rating={vessel.ytdRating} size={36} />
      {/* 문자는 색·패턴과 **함께** 있어야 한다 (`§14`). 마크의 일부이지 라벨이 아니다. */}
      <b className={`vessel__mark-grade vessel__mark-grade--${vessel.ytdRating.toLowerCase()}`}>
        {vessel.ytdRating}
      </b>
    </span>
  )
}
