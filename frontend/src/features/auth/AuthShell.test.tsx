// @vitest-environment jsdom
import '../../test/renderSetup'

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AuthShell } from './AuthShell'

/*
 * `jsdom` 환경에서는 `import.meta.url`이 file 스킴이 아니라 `fileURLToPath`가 던진다.
 * 이 파일은 **렌더와 CSS 규칙을 함께** 봐야 해서 환경을 node로 돌릴 수 없다 —
 * vitest는 `frontend/`에서 돌므로 작업 폴더 기준 경로를 쓴다.
 */
const css = readFileSync(join(process.cwd(), 'src/features/auth/AuthShell.css'), 'utf-8')
/** 규칙 검사가 설명 문장에 걸리지 않게 한다 — `#831`·`#829`·`#694`에서 세 번 밟았다. */
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '')

describe('AuthShell 브랜드 판 — #608', () => {
  it('브랜드 판은 네 인증 화면에 모두 나온다', () => {
    /*
     * 로그인에만 두면 회원가입으로 넘어갈 때 레이아웃이 통째로 바뀌어
     * **다른 서비스로 온 것처럼 보인다.** 판은 공통, 소개 본문만 가른다.
     */
    const { container } = render(<AuthShell title="회원가입">폼</AuthShell>)
    expect(container.querySelector('.auth-brand-panel')).not.toBeNull()
    // `getByText`는 없으면 던진다 — 이 저장소에는 jest-dom 매처가 없다.
    expect(screen.getByText('선대 CII 상시 관리')).not.toBeNull()
  })

  it('서비스 소개는 intro를 켠 화면에만 나온다 — UIFLOW §0', () => {
    const { container, rerender } = render(<AuthShell title="회원가입">폼</AuthShell>)
    expect(container.querySelector('.auth-intro')).toBeNull()

    rerender(
      <AuthShell title="로그인" intro>
        폼
      </AuthShell>,
    )
    expect(container.querySelector('.auth-intro')).not.toBeNull()
  })

  it('세 계층 문구가 UIFLOW §2.1 구조도 그대로다', () => {
    /*
     * 여기서 새로 쓰면 사이드바·대시보드가 설명하는 것과 어긋난다.
     * 값이 아니라 **상위 문서에서 복사한 문장**임을 고정한다 (`AGENTS §3`).
     */
    render(
      <AuthShell title="로그인" intro>
        폼
      </AuthShell>,
    )
    for (const [tier, detail] of [
      ['선대', '내 배 전체 · 위험 선박 경고'],
      ['선박', '연도별 CII 이력 · 올해 누적(YTD) · 현재 위치·상태'],
      ['항차', '항해 중 누적값 · 연말 예상 등급 · 정박 반영'],
    ]) {
      expect(screen.getByText(tier)).not.toBeNull()
      expect(screen.getByText(detail)).not.toBeNull()
    }
  })

  it('면책 문구는 intro와 별개로 켜진다 — PRD §0.3', () => {
    /*
     * 깃발 하나로 묶으면 「소개만 빼고 면책은 남기는」 화면을 만들 수 없다.
     * 두 규정(`UIFLOW §0` · `PRD §0.3`)이 각자 자기 자리를 가진다.
     */
    const { container, rerender } = render(
      <AuthShell title="로그인" intro>
        폼
      </AuthShell>,
    )
    expect(container.querySelector('.auth-disclaimer')).toBeNull()

    rerender(
      <AuthShell title="로그인" disclaimer>
        폼
      </AuthShell>,
    )
    expect(container.querySelector('.auth-disclaimer')).not.toBeNull()
  })

  /**
   * 면책 문구는 **폼 아래**다 (`#1425`).
   *
   * 종전에는 카드 맨 위라, 로그인하러 온 사람의 첫 시선이 로그인 버튼이 아니라 네
   * 줄짜리 고지에 갔다. `UIFLOW §0`은 로그인 화면에 면책이 **있을 것**만 요구하고
   * 위치를 정하지 않는다.
   *
   * **문구는 보지 않는다** — `PRD §0.3` 정본이라 이 검사가 잠글 것이 아니고, 위에
   * 노출 여부를 보는 검사가 따로 있다. 여기서 보는 것은 **순서**뿐이다.
   */
  it('면책 문구가 폼보다 뒤에 온다 — 첫 시선이 고지에 가지 않는다 (#1425)', () => {
    const { container } = render(
      <AuthShell title="로그인" disclaimer>
        <form>
          <button type="submit">로그인</button>
        </form>
      </AuthShell>,
    )

    const card = container.querySelector('.auth-card')
    const note = container.querySelector('.auth-disclaimer')
    const submit = container.querySelector('button[type="submit"]')
    expect(note).not.toBeNull()
    expect(submit).not.toBeNull()

    /*
     * `DOCUMENT_POSITION_FOLLOWING` — 면책이 버튼 **뒤**에 있다. 화면 순서와 낭독
     * 순서가 같은 것이 요점이라 CSS가 아니라 DOM 순서를 본다.
     */
    expect(
      submit!.compareDocumentPosition(note!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    // 카드 **안**이다 — 밖으로 내면 회원가입 링크 뒤의 꼬리말로 읽힌다.
    expect(note!.closest('.auth-card')).toBe(card)
  })

  it('제목은 카드 안에 있고 판 밖이다 — aria-labelledby가 카드를 가리킨다', () => {
    /*
     * 판이 `<aside>`라 보조 기술이 「본문 밖」으로 읽는다. 제목이 판으로 넘어가면
     * 카드가 이름 없는 영역이 된다.
     */
    const { container } = render(<AuthShell title="로그인">폼</AuthShell>)
    const card = container.querySelector('.auth-card')
    expect(card?.getAttribute('aria-labelledby')).toBe('auth-title')
    expect(card?.querySelector('#auth-title')?.textContent).toBe('로그인')
  })

  it('1100px 이하에서 판을 숨기지 않고 접는다 — 확정 3-3', () => {
    /*
     * 숨기면 좁은 화면에서 **로고와 서비스 이름이 통째로 사라진다.**
     * 접는 것은 소개 본문뿐이고 판 자체는 상단 띠로 남는다.
     */
    const media = rules.slice(rules.indexOf('@media (width <= 1100px)'))
    const body = media.slice(0, media.indexOf('\n}\n\n'))

    expect(body).toContain('.auth-intro')
    // 판 자체를 없애는 규칙이 있으면 「접음」이 아니라 「숨김」이다.
    expect(body).not.toMatch(/\.auth-brand-panel\s*\{[^}]*display:\s*none/)
  })

  it('판 위 로고는 어두운 배경용 한 장으로 고정한다 — 확정 3-2', () => {
    /*
     * `BrandLogo`는 테마에 따라 고르는데 이 판은 테마와 무관하게 어둡다.
     * 그대로 두면 라이트에서 **어두운 로고가 어두운 면에** 얹힌다.
     */
    expect(rules).toMatch(/\.auth-brand-panel \.brand-logo__img--light\s*\{\s*display:\s*none/)
    expect(rules).toMatch(/\.auth-brand-panel \.brand-logo__img--dark\s*\{\s*display:\s*block/)
  })

  it('한국어 문장에 word-break: keep-all이 걸려 있다', () => {
    // 어절 안에서 끊으면 읽기 어렵다 (`DESIGN_SYSTEM §3`).
    for (const selector of ['.auth-intro-lead', '.auth-tier']) {
      const rule = rules.slice(rules.indexOf(`${selector} {`))
      expect(rule.slice(0, rule.indexOf('}'))).toContain('word-break: keep-all')
    }
  })

  it('판에 hex를 직접 적지 않는다 — DESIGN_SYSTEM §15', () => {
    // 색은 토큰으로만 들어온다. 값은 Figma가 소유한다.
    expect(rules).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

describe('미인증 배너 — 등급 색을 쓰지 않는다 (#748)', () => {
  it('배너 규칙이 등급 토큰에도, Warning 계열(`--color-warning*`)에도 닿지 않는다', () => {
    /*
     * `§0.2` 제약 2 — 등급 색은 A~E 문자나 등급 축 라벨과 함께만 나타난다. 이 배너는
     * 이메일 인증 안내라 둘 다 없다.
     *
     * Warning 계열을 함께 막는 것은 `#748` 당시 `--color-warning`·`--color-warning-text`가
     * `--cii-c-fill`을 가리켰기 때문이다. `#1022` 이후 둘은 `--semantic-warning` 쪽이지만,
     * 배너 색은 `§2.3` 「안내 배너」 = Info로 정해져 있다(아래 테스트). Warning으로 옮기는
     * 것은 이름 교체가 아니라 디자인 결정이므로 이 단언은 그대로 둔다.
     */
    const banner = [...rules.matchAll(/([^{}]*verify-banner[^{}]*)\{([^}]*)\}/g)]
    expect(banner.length, '.verify-banner 규칙을 찾지 못했습니다').toBeGreaterThan(0)
    for (const [, selector, body] of banner) {
      expect(body, selector.trim()).not.toMatch(/var\(--cii-|var\(--color-warning/)
    }
  })

  it('안내 배너는 `§2.3` Info 스트라이프다 — `§8` 상태색 좌측 스트라이프', () => {
    const [, body] = /\.verify-banner\s*\{([^}]*)\}/.exec(rules) ?? []
    expect(body).toMatch(/border-left:\s*3px solid var\(--color-info\)/)
    expect(body).toMatch(/border-radius:\s*0/)
  })
})

describe('언어 선택 칸 — 인증 화면에는 두지 않는다 (#1525)', () => {
  it('셸에 언어 radiogroup이 없다 — 눌러도 바뀌는 문자열이 없는 화면이다', () => {
    /*
     * 2026-09-22 결정. 인증 화면 문구가 사전(`i18n/ko.ts`)에 들어오면 이 검사를 지우고
     * 칸을 둔다 — 그때까지는 누르면 아무것도 바뀌지 않는 컨트롤이 된다.
     */
    render(<AuthShell title="로그인">폼</AuthShell>)
    expect(screen.queryByRole('radiogroup')).toBeNull()
  })
})
