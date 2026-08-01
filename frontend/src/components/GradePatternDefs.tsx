/**
 * 등급 패턴 SVG defs — `DESIGN_SYSTEM.md` §15.1.
 *
 * §15.1은 이 패턴을 "배지·스택 바에서 공유한다"고 규정하므로 공통 셸에 한 번만
 * 심어 두고, 이후 화면(#136 등)이 `fill="url(#grade-c)"`로 참조한다.
 *
 * §14 접근성: "패턴 없는 등급 표시는 구현 금지" — 색만으로 A~E를 구분하면
 * 적록색맹에서 A(녹)와 E(적)가 무너진다. A등급은 solid이므로 정의하지 않는다(§15.1).
 *
 * **§15.1 원문 스니펫은 hex를 인라인으로 담고 있으나, 같은 §15의 규칙
 * "컴포넌트는 토큰만 참조한다. 하드코딩 hex 금지"가 예시를 규율하므로 토큰 참조로
 * 옮겼다.** 값은 바뀌지 않는다 — 네 hex가 각각 아래 토큰과 동일하다.
 *
 * | §15.1 원문 | 토큰 |
 * |---|---|
 * | `#173404` (grade-b line stroke) | `--color-grade-b-on` |
 * | `#412402` (grade-c line stroke) | `--color-grade-c-on` |
 * | `#ffffff` (grade-d circle fill)  | `--color-grade-d-on` |
 * | `#ffffff` (grade-e path stroke)  | `--color-grade-e-on` |
 *
 * ⚠️ `<defs>`를 참조하는 요소는 아직 없다(#133은 스캐폴드). 커스텀 프로퍼티가
 * 패턴 내부까지 실제로 적용되는지는 등급 배지를 구현하는 **#136에서 시각 검증**한다.
 */
export function GradePatternDefs() {
  return (
    <svg width="0" height="0" aria-hidden="true" focusable="false">
      <defs>
        <pattern
          id="grade-b"
          width="6"
          height="6"
          patternTransform="rotate(45)"
          patternUnits="userSpaceOnUse"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="6"
            stroke="var(--color-grade-b-on)"
            strokeWidth="1.2"
            opacity=".45"
          />
        </pattern>
        <pattern
          id="grade-c"
          width="4"
          height="4"
          patternTransform="rotate(-45)"
          patternUnits="userSpaceOnUse"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="4"
            stroke="var(--color-grade-c-on)"
            strokeWidth="1.2"
            opacity=".45"
          />
        </pattern>
        <pattern id="grade-d" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.2" fill="var(--color-grade-d-on)" opacity=".5" />
        </pattern>
        <pattern id="grade-e" width="6" height="6" patternUnits="userSpaceOnUse">
          <path
            d="M0 0L6 6M6 0L0 6"
            stroke="var(--color-grade-e-on)"
            strokeWidth="1"
            opacity=".45"
          />
        </pattern>
      </defs>
    </svg>
  )
}
