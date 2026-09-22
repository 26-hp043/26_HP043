import './DataConfidenceBadge.css'

/**
 * 신뢰도 배지 — `DESIGN_SYSTEM §8` · `§8.1` 🔒 (`#485` ⑤).
 *
 * 등급이 **실측이 아닌 값으로 계산됐음**을 알린다. `GradeBadge` 옆에 놓는다.
 *
 * ## 언제 붙는지는 이 컴포넌트가 정하지 않는다
 *
 * 판정은 `§8.1`이 정본으로 확정했고, 화면 쪽 구현은 `realtimeRules`의
 * `hasSubstitutedInputs`가 소유한다. 이 컴포넌트는 **그리기만** 한다 —
 * 임계가 두 곳에 생기면 어긋났을 때 어느 쪽이 맞는지부터 판단해야 한다.
 *
 * ## 색 — 시맨틱 Warning의 문자 전용 토큰
 *
 * `§8`은 *「등급 색을 쓰지 않는다 — 시맨틱 Warning/Danger를 쓴다」*고 정했다.
 * 색은 CSS가 `--color-warning-text`로 입힌다(`DataConfidenceBadge.css`).
 *
 * - `--color-warning`은 생성 토큰 `--semantic-warning`을 가리킨다.
 * - `--color-warning-text`는 그 **문자용** 토큰이다. 라이트는 `--semantic-warning`이
 *   문자 대비에 모자라 별도 값을 두고, 다크는 `--semantic-warning`을 그대로 쓴다.
 *   값과 대비 근거는 `tokens.css` 「문자로 쓸 때의 시맨틱 색」 주석이 소유한다.
 *
 * 등급 배지가 **채움형**인 것과 달리 이 배지는 **테두리형**이다 — 나란히 놓여도
 * 형태로 「다른 종류」임이 드러난다(`RegulatoryFlag`와 같은 규율).
 *
 * > **이력** — `#1022` 이전에는 Figma 세트에 Warning이 없어 `--color-warning`이
 * > `--cii-c-fill`(등급 C)의 별칭이었고, 이 주석도 그렇게 적고 있었다. 확정 N으로
 * > 생성 토큰이 내려오면서 그 별칭은 없어졌다. 등급 색과 시맨틱 색이 실제로
 * > 겹치지 않는지(`§0.2` 제약 2)의 실측은 `#1022`가 따로 다룬다 — 이 주석은 그것을
 * > 보증하지 않는다.
 */
interface DataConfidenceBadgeProps {
  /** 무엇이 대체됐는지. 짧은 라벨만 남으면 사용자가 고칠 대상을 알 수 없다. */
  detail: string
}

const LABEL = '추정 포함'

export function DataConfidenceBadge({ detail }: DataConfidenceBadgeProps) {
  return (
    <span
      className="data-confidence-badge"
      role="img"
      aria-label={`${LABEL} — ${detail}`}
      title={detail}
    >
      {LABEL}
    </span>
  )
}
