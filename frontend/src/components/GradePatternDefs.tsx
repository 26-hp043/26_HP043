/**
 * 등급 패턴 SVG defs — DESIGN_SYSTEM.md §15.1에서 그대로 복사했다.
 *
 * §15.1은 이 패턴을 "배지·스택 바에서 공유한다"고 규정하므로 공통 셸에 한 번만
 * 심어 두고, 이후 화면(#136 등)이 `fill="url(#grade-c)"`로 참조한다.
 *
 * §14 접근성: "패턴 없는 등급 표시는 구현 금지" — 색만으로 A~E를 구분하면
 * 적록색맹에서 A(녹)와 E(적)가 무너진다. A등급은 solid이므로 정의하지 않는다(§15.1).
 *
 * §15의 "하드코딩 hex 금지"는 컴포넌트 스타일 규칙이며, 아래 hex는 §15.1 원본
 * 마크업의 값을 그대로 옮긴 것이다(각각 `--color-grade-b-on` · `--color-grade-c-on`과
 * 동일한 값). 정본 스니펫을 임의로 재작성하지 않는다(AGENTS.md §3).
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
            stroke="#173404"
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
            stroke="#412402"
            strokeWidth="1.2"
            opacity=".45"
          />
        </pattern>
        <pattern id="grade-d" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.2" fill="#ffffff" opacity=".5" />
        </pattern>
        <pattern id="grade-e" width="6" height="6" patternUnits="userSpaceOnUse">
          <path
            d="M0 0L6 6M6 0L0 6"
            stroke="#ffffff"
            strokeWidth="1"
            opacity=".45"
          />
        </pattern>
      </defs>
    </svg>
  )
}
