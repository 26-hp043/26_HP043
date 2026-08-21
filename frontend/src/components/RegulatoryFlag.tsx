import { riskReasonText } from '../features/fleet/fleetRules'
import type { RiskReason } from '../features/fleet/types'
import './RegulatoryFlag.css'

/**
 * 규제 플래그 — `DESIGN_SYSTEM §8` (`#485` ④).
 *
 * ## 등급 배지와 왜 나누는가
 *
 * `§8`이 이유를 적고 있다.
 *
 * > D 3년 연속·E 1년차 등 규제 트리거는 등급과 **별개 정보**다. 같은 D등급이라도
 * > 1년차와 3년차는 배지가 동일해야 하고 플래그만 달라야 한다
 *
 * 서버도 두 축을 이미 갈라 내려준다 — `risk_level`(표시용 4단계)과
 * `risk_reasons`(규제 트리거)는 **다른 것을 본다**(`API_SPEC §2.8`).
 * C등급이어도 여유가 없으면 `risk_level`은 `HIGH`지만 규제 의무는 없고,
 * D등급 3년차는 여유와 무관하게 의무가 생긴다.
 *
 * **데이터는 갈라져 있는데 화면이 합쳐 보이던 상태**를 이 컴포넌트가 푼다.
 *
 * ## 등급 색을 쓰지 않는다
 *
 * `GradeBadge` 옆에 놓이므로 등급 색(`--cii-*`)을 쓰면 **두 배지가 같은 축을
 * 말하는 것처럼 읽힌다.** 시맨틱 Danger를 쓴다 — 규제 의무가 발생한 상태이고,
 * `DataConfidenceBadge`가 같은 자리에서 시맨틱 색을 쓰기로 한 것과 같은 규율이다.
 *
 * ## 짧은 라벨 + 전체 문구
 *
 * 배지 옆 좁은 자리라 라벨은 사유만 짧게 낸다. 규제 근거를 담은 전체 문구
 * (`riskReasonText`)는 `title`과 `aria-label`로 간다 — 목록에서 스무 척을
 * 훑을 때 한 줄이 두 줄로 접히면 표가 무너진다.
 */

/** 사유별 짧은 라벨. 전체 문구는 `fleetRules.riskReasonText`가 소유한다. */
const SHORT_LABEL: Record<RiskReason, string> = {
  E_THIS_YEAR: 'E 1년차',
  D_THIRD_YEAR: 'D 3년 연속',
}

interface RegulatoryFlagProps {
  reason: RiskReason
  /** 어느 선박의 플래그인지 — 목록에서 읽힐 때 대상이 없으면 뜻이 없다. */
  vesselName?: string
}

export function RegulatoryFlag({ reason, vesselName }: RegulatoryFlagProps) {
  const full = riskReasonText(reason)
  const label = vesselName ? `${vesselName} — ${full}` : full

  return (
    <span
      className={`regulatory-flag regulatory-flag--${reason.toLowerCase()}`}
      role="img"
      aria-label={label}
      title={full}
    >
      {SHORT_LABEL[reason]}
    </span>
  )
}

/**
 * 플래그 여러 개를 나란히 낸다.
 *
 * `risk_reasons`는 배열이다 — E 1년차와 D 3년 연속이 동시에 성립하지는 않지만,
 * `PRD §3.3.7`이 트리거를 더 늘릴 수 있으므로 화면이 **하나만 그리도록 굳히지
 * 않는다.** 비어 있으면 아무것도 그리지 않는다.
 */
export function RegulatoryFlags({
  reasons,
  vesselName,
}: {
  reasons: readonly RiskReason[]
  vesselName?: string
}) {
  if (reasons.length === 0) return null
  return (
    <>
      {reasons.map((reason) => (
        <RegulatoryFlag key={reason} reason={reason} vesselName={vesselName} />
      ))}
    </>
  )
}
