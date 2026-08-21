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
 * ## 색에 걸린 문제를 숨기지 않는다
 *
 * `§8`은 *「등급 색을 쓰지 않는다 — 시맨틱 Warning/Danger를 쓴다」*고 정했다.
 * 그런데 **`--color-warning`은 `--cii-c-fill`의 별칭**이다 — 디자이너 세트에
 * warning이 없어 C등급 색을 그대로 쓰고 있다(`tokens.css` 주석).
 *
 * 정본이 지시한 대로 시맨틱 Warning을 쓰되, 값이 등급 색과 같다는 사실은
 * **토큰 세트의 공백**이지 화면이 우회할 문제가 아니다. 대신 등급 배지가
 * **채움형**인 것과 달리 이 배지는 **테두리형**이라, 값이 같아도 형태로 갈린다.
 * (`DESIGN_SYSTEM §16 항목 3` 중립색 팔레트 조정에 함께 올릴 항목.)
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
