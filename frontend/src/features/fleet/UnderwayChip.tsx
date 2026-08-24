import './UnderwayChip.css'
import { detailStatusText, underwayStateText } from './fleetRules'
import type { UnderwayState } from './types'

/**
 * 운항 / 정박 상태 칩 (`#701` ⑤).
 *
 * ## 왜 칩으로 빼는가
 *
 * 종전에는 「벌크선 · 운항 중 · 항해 중」이 12px 회색 한 줄에 점으로 이어져 있어
 * **선종·운항 상태·세부 상태 셋이 같은 무게**였다. 「지금 무엇을 하고 있나」가
 * 선종에 묻혔다.
 *
 * ## 등급색을 쓰지 않는다
 *
 * 운항 상태는 등급과 **다른 축**이다. 등급색을 겹치면 한 축으로 읽히고, 그것은
 * `§0.2` 제약 2(등급 색과 시맨틱 색의 분리)가 막으려는 것과 같은 종류의 혼동이다.
 * 중립색을 쓰고 **형태(아이콘)로 구분**한다.
 *
 * ## 아이콘은 `§12`를 그대로 따른다
 *
 * 이것은 데이터 마크가 아니라 **UI 아이콘**이다 — 값을 나타내지 않고 상태에 이름을
 * 붙인다. 그래서 `§12`의 「라인 · stroke 1.5–1.6 · 단색」을 지킨다. 등급 분포의
 * 배 마크가 `§12`를 따르지 않은 것과 대비되는 자리이며, 그 차이가 곧 둘의 성격 차이다.
 *
 * `§12` — 「의미 전달 아이콘에는 반드시 텍스트 라벨 또는 `aria-label` 병기」.
 * 여기서는 **텍스트 라벨이 항상 옆에 있다.**
 */
/**
 * 운항 상태 칩.
 *
 * ## prop이 `FleetVessel`이 아니다 (#719)
 *
 * 선박 관리(`GET /vessels`)도 같은 두 값을 갖는데 **타입 이름이 다르다.** 칩이
 * `FleetVessel`을 요구하면 쓰는 쪽이 가짜 선대 객체를 만들거나 칩을 베낀다.
 *
 * 필요한 두 필드만 받는 **구조적 타입**으로 넓힌다. `FleetVessel`이 그대로 만족하므로
 * 대시보드 쪽 호출과 테스트는 손대지 않는다.
 */
export function UnderwayChip({
  vessel,
}: {
  vessel: { underwayState: UnderwayState | null; detailStatus: string | null }
}) {
  const state = vessel.underwayState
  const detail = vessel.detailStatus ? detailStatusText(vessel.detailStatus) : null

  return (
    <span className={`vessel__state vessel__state--${(state ?? 'unknown').toLowerCase()}`}>
      {state === 'UNDER_WAY' ? <UnderwayIcon /> : null}
      {state === 'NOT_UNDER_WAY' ? <AnchorIcon /> : null}
      <span>
        {underwayStateText(vessel)}
        {detail ? ` · ${detail}` : ''}
      </span>
    </span>
  )
}

/**
 * 진행 — 뱃머리가 만드는 물살. 방향이 있어 정박과 형태로 갈린다.
 *
 * 선대 요약(`FleetDashboard`)도 같은 아이콘을 쓴다. **아래 카드에서 배운 기호를
 * 위 요약에서 그대로 쓰게 하는 것**이 재사용의 목적이라 여기서 내보낸다.
 */
export function UnderwayIcon() {
  return (
    <svg className="vessel__state-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3 16c2.2 0 2.2-2 4.4-2s2.2 2 4.4 2 2.2-2 4.4-2 2.2 2 4.4 2" />
      <path d="M6.5 10.5 17 6l-2.5 5.2" />
    </svg>
  )
}

/** 정박 — 닻. 세로축과 갈고리라 물살과 겹치지 않는다. 선대 요약도 쓴다. */
export function AnchorIcon() {
  return (
    <svg className="vessel__state-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="5.4" r="2" />
      <path d="M12 7.4V20" />
      <path d="M8 10.2h8" />
      <path d="M4.6 14.6c0 3.5 3.3 5.4 7.4 5.4s7.4-1.9 7.4-5.4" />
    </svg>
  )
}
