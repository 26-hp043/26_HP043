import './BrandLogo.css'

/**
 * 브랜드 로고 — 사이드바(`AppShell`)와 인증 화면(`AuthShell`)이 공유한다.
 *
 * ## 왜 컴포넌트로 두는가
 *
 * 두 화면이 각자 `<img>`를 그리면 **테마 전환 규칙이 두 벌**이 되고 한쪽만 고쳐
 * 어긋난다. 제품명이 텍스트였을 때 실제로 그런 일이 있었다 — 사이드바 태그라인만
 * 바꾸고 로그인 화면을 빠뜨렸다(`AuthShell` 주석).
 *
 * ## 왜 파일 두 장인가
 *
 * 테마는 **세 상태**다 — `data-theme="dark"` · `data-theme="light"` · **미선택**.
 * 미선택일 때만 OS(`prefers-color-scheme`)를 따른다(`index.html` 주석).
 * 한 장을 CSS `filter`로 반전하면 네이비와 액센트가 **함께** 뒤집혀 브랜드가 깨진다.
 * 색이 다른 두 파일을 두고 CSS가 고른다.
 *
 * 숨는 쪽은 `display: none`이라 접근성 트리에서도 빠진다 — 대체 텍스트가 두 번
 * 읽히지 않는다.
 *
 * ## 크기는 쓰는 쪽이 정한다
 *
 * prop을 받지 않는다. 부모가 `--brand-logo-height`를 주면 그 높이로 그린다.
 * 사이드바와 인증 카드는 적정 크기가 달라서, 크기를 이 컴포넌트가 알 이유가 없다.
 */
export function BrandLogo() {
  return (
    <span className="brand-logo">
      <img
        className="brand-logo__img brand-logo__img--light"
        src="/brand/bluelog-logo-light.svg"
        alt="BlueLog"
      />
      <img
        className="brand-logo__img brand-logo__img--dark"
        src="/brand/bluelog-logo-dark.svg"
        alt="BlueLog"
      />
    </span>
  )
}
