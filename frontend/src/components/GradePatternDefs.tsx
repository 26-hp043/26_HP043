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
 * | `#173404` (grade-b line stroke) | `--cii-b-bg` |
 * | `#412402` (grade-c line stroke) | `--cii-c-bg` |
 * | `#ffffff` (grade-d circle fill)  | `--cii-d-bg` |
 * | `#ffffff` (grade-e path stroke)  | `--cii-e-bg` |
 *
 * ⚠️ 규격 미갱신 — `§15.1`은 간격 4px 통일과 C·D 패턴 교체를 규정하나,
 * 현재 이 패턴을 참조하는 화면이 없어 시각 검증이 불가하다. 지도 마커·차트
 * 등급 밴드 구현 시 함께 처리한다.
 *
 * 자동 테스트로는 이 확인을 대신할 수 없다. `gradePatternUrl()`은 참조 문자열만
 * 잠그고, **패턴이 실제로 칠해지는지는 렌더 결과를 봐야** 알 수 있다.
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
            stroke="var(--cii-b-bg)"
            strokeWidth="1.2"
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
            stroke="var(--cii-c-bg)"
            strokeWidth="1.2"
          />
        </pattern>
        <pattern id="grade-d" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.2" fill="var(--cii-d-bg)" />
        </pattern>
        <pattern id="grade-e" width="6" height="6" patternUnits="userSpaceOnUse">
          <path
            d="M0 0L6 6M6 0L0 6"
            stroke="var(--cii-e-bg)"
            strokeWidth="1"
          />
        </pattern>
      </defs>
    </svg>
  )
}
