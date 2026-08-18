/**
 * 등급 패턴 SVG defs — `DESIGN_SYSTEM §15.1`.
 *
 * §15.1은 이 패턴을 화면 여러 곳에서 공유한다고 규정하므로 공통 셸(`AppShell`)에 한 번만
 * 심어 두고, 이후 화면이 `fill="url(#grade-c)"`로 참조한다. 참조 문자열은
 * `gradePatternUrl()`이 만든다.
 *
 * ## 어디에 쓰는가 — §2.4.4
 *
 * §2.4.4는 패턴을 **등급 문자가 없는 자리에서 필수**로 요구한다. 색만으로 A~E를
 * 구분하면 적록색맹에서 무너지기 때문이다. 등급 fill 토큰은 사실상 3색 체계라
 * (A·B 초록 · C 주황 · D·E 빨강) 세 색상군이 모두 황갈색으로 수렴한다.
 *
 * - **문자가 없는 자리** — 선박 위치 개략도의 마커(`PositionChart`) 등. 패턴 필수.
 * - **문자가 있는 자리** — 등급 배지·칩(`GradeBadge` · `GradeChip`). 문자가 이미
 *   색 외 보조 채널이라 패턴을 겹치면 작은 크기에서 판독만 나빠진다. 쓰지 않는다.
 *
 * ## 규격 — §15.1
 *
 * | 등급 | 무늬 | 타일 |
 * |---|---|---|
 * | A | 없음 (solid) | — |
 * | B | 45° 사선 ╱ | 4px |
 * | C | 도트 | 4px |
 * | D | 135° 사선 ╲ | 4px |
 * | E | 크로스해치 | 4px |
 *
 * 타일은 네 등급 모두 **4px로 통일**한다. 간격이 등급마다 다르면 「촘촘함」이
 * 무늬와 뒤엉킨 두 번째 변수가 되어, 마커처럼 작은 자리에서 오히려 구분을 흐린다.
 *
 * A는 정의하지 않는다 — 「패턴 없음」 자체가 A의 식별 표시다.
 *
 * ## 색은 토큰으로 참조한다
 *
 * §15.1 원문 스니펫은 hex를 인라인으로 담고 있으나, 같은 §15의 규칙 "컴포넌트는
 * 토큰만 참조한다. 하드코딩 hex 금지"가 예시를 규율하므로 토큰 참조로 옮겼다.
 * 무늬 색은 등급 `bg`다 — **`bg`는 `fill`의 반대편 끝**이라(라이트에서 `fill`이 진하면
 * `bg`가 옅고, 다크에서 정확히 뒤집힌다) fill 위 대비가 두 테마 모두에서 유지된다.
 * 흰색을 박아 두면 다크에서 밝아진 fill 위에 흰 무늬가 얹혀 사라진다.
 *
 * `opacity`는 쓰지 않는다 — 깔리는 fill 색에 따라 결과가 달라져 두 모드에서
 * 일관되지 않는다.
 *
 * ## 검증
 *
 * 자동 테스트로는 이 파일을 검증할 수 없다. `gradePatternUrl()` 테스트는 참조
 * 문자열만 잠그고, **패턴이 실제로 칠해지는지는 렌더 결과를 봐야** 알 수 있다.
 *
 * 특히 **토큰 이름이 틀려도 조용히 실패한다.** 해석되지 않는 `var()`는 `fill`에서
 * 검정으로, `stroke`에서 `none`으로 떨어진다 — 사선·크로스해치는 아무것도 그려지지
 * 않고, 도트만 엉뚱한 검정으로 나온다. 토큰을 손대면 반드시 눈으로 확인한다.
 *
 * ✅ **시각 검증 — 2026-08-18.** 라이트·다크 양쪽에서 A(solid) · B(╱) · C(도트) ·
 * D(╲) · E(크로스해치)가 `PositionChart` 마커 크기에서 서로 다른 무늬로 그려지고,
 * 커스텀 프로퍼티가 `<pattern>` 내부까지 적용되는 것을 브라우저에서 확인했다.
 */
export function GradePatternDefs() {
  return (
    <svg width="0" height="0" aria-hidden="true" focusable="false">
      <defs>
        {/* B — 45° 사선 ╱ */}
        <pattern
          id="grade-b"
          width="4"
          height="4"
          patternTransform="rotate(45)"
          patternUnits="userSpaceOnUse"
        >
          <line x1="0" y1="0" x2="0" y2="4" stroke="var(--cii-b-bg)" strokeWidth="1.2" />
        </pattern>
        {/* C — 도트 */}
        <pattern id="grade-c" width="4" height="4" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.2" fill="var(--cii-c-bg)" />
        </pattern>
        {/* D — 135° 사선 ╲ */}
        <pattern
          id="grade-d"
          width="4"
          height="4"
          patternTransform="rotate(-45)"
          patternUnits="userSpaceOnUse"
        >
          <line x1="0" y1="0" x2="0" y2="4" stroke="var(--cii-d-bg)" strokeWidth="1.2" />
        </pattern>
        {/* E — 크로스해치 */}
        <pattern id="grade-e" width="4" height="4" patternUnits="userSpaceOnUse">
          <path d="M0 0L4 4M4 0L0 4" stroke="var(--cii-e-bg)" strokeWidth="1" />
        </pattern>
      </defs>
    </svg>
  )
}
