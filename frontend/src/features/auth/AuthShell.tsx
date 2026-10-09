import { useState, type ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Icon } from '../../components/Icon'
import { GradeBadge } from '../../components/GradeBadge'
import './AuthShell.css'
import { BrandLogo } from '../../components/BrandLogo'
import { Field } from '../../components/Field'
import { BeomiFigure, BeomiSea } from './BeomiScene'
import { SCREEN_BY_ID } from '../../screens'

/**
 * 인증 화면 공통 껍데기 — 로그인·회원가입·비밀번호 찾기·이메일 인증이 공유한다.
 *
 * 네 화면이 각자 브랜드 블록과 면책 문구를 그리면, 문구가 바뀔 때 **한 곳만 고쳐
 * 나머지가 낡는다.** 실제로 이 프로젝트에서 사이드바 태그라인만 바꾸고 로그인
 * 화면을 빠뜨린 적이 있다.
 *
 * ## 좌우 2단 (`#608`)
 *
 * 종전에는 가운데 카드 하나였다. `UIFLOW §0`이 로그인 화면의 구성 요소로 요구하는
 * 「서비스 소개」가 **제목·설명문 두 줄로만** 존재해 화면이 비어 보였다.
 * 좌측 브랜드 판에 소개를 옮기고, 우측에 종전 카드를 둔다.
 *
 * ## 서비스 소개는 로그인에만, 면책 문구는 로그인과 회원가입에 둔다
 *
 * `UIFLOW §0`이 「서비스 소개 및 면책 문구」를 **로그인 화면**(`0`)의, 「면책 문구」를
 * **회원가입**(`0-1`)의 구성 요소로 규정한다(#1455). 비밀번호 찾기·이메일 인증은
 * 둘 다 적지 않는다. 그래서 둘을 선택 인자로 두었다. **깃발 하나로 묶지 않은
 * 이유**가 바로 회원가입이다 — 소개는 빼고 면책은 켜야 한다. `disclaimer`는
 * `PRD §0.3` 문구를, `intro`는 소개 블록을 켠다.
 *
 * ## 브랜드 판은 모든 인증 화면에 나온다
 *
 * 판 자체(로고·태그라인)는 네 화면이 공유한다. 로그인에만 두면 회원가입에서
 * 레이아웃이 통째로 바뀌어 **다른 서비스로 넘어온 것처럼 보인다.** 판 안의
 * **소개 본문만** `intro`로 가른다.
 */

interface AuthShellProps {
  title: string
  description?: string
  /** `PRD §0.3` 면책 문구 노출 여부. 로그인·회원가입 화면이 `true`(`UIFLOW §0`). */
  disclaimer?: boolean
  /** 브랜드 판의 서비스 소개 문구 · 범이 노출 여부(`UIFLOW §0`). 로그인 화면만 `true`. 화면 예시는 넷 모두에 있다. */
  intro?: boolean
  children: ReactNode
  /** 카드 아래 보조 링크 줄. */
  footer?: ReactNode
}

/*
 * 화면 예시 — 대시보드 「확인할 선박」 두 행 (`UIFLOW 2-4` · 시연 데이터의 샘플 선박).
 *
 * 첫 화면에 **제품이 실제로 내놓는 것**을 보인다. 종전에는 이 자리가 「선대 · 선박 · 항차」
 * 계층 세 줄이었는데, 무엇을 보여 주는 서비스인지가 글로만 남았다. 대시보드의 같은 행 —
 * 누적 등급 · 이유 · 다음 작업 — 을 그대로 줄여 둔다. 등급 배지는 제품의 그 컴포넌트다.
 *
 * ⚠️ **실측이 아니라 예시다.** 그래서 캡션에 「화면 예시」를 적는다 — 판매 수치나 고객 수처럼
 * 읽히면 안 된다. 값은 시연 시드의 샘플 선박에서 왔고, 바뀌어도 예시라는 성질은 같다.
 */
const PREVIEW_ROWS = [
  {
    vessel: 'CHEOYONG GRACE',
    rating: 'E',
    value: '8.214',
    why: 'E등급 1년차 · 시정조치계획 대상',
    next: '함대 감축 계획 세우기',
  },
  {
    vessel: 'TAEHWA BREEZE',
    rating: 'C',
    value: '7.146',
    why: 'D등급까지 39일',
    next: '연말 등급 보기',
  },
] as const

function EntryPreview() {
  return (
    <figure className="auth-preview">
      <figcaption className="auth-preview-cap">화면 예시 · 대시보드 「확인할 선박」</figcaption>
      {/* 예시라 누를 수 없다 — 「다음 작업」도 링크가 아니라 글자다. */}
      <ul className="auth-preview-card">
        {PREVIEW_ROWS.map((row) => (
          <li className="auth-preview-row" key={row.vessel}>
            <span className="auth-preview-vessel">{row.vessel}</span>
            <span className="auth-preview-grade">
              <GradeBadge rating={row.rating} size="sm" />
              <span className="auth-preview-value">{row.value}</span>
            </span>
            <span className="auth-preview-why">{row.why}</span>
            <span className="auth-preview-next">{row.next}</span>
          </li>
        ))}
      </ul>
    </figure>
  )
}

/*
 * 언어 선택 칸을 두지 않는다 (2026-09-22 결정 · `#1525` · `rlatnals4114`).
 *
 * 인증 화면(로그인 · 회원가입 · 비밀번호 재설정)에는 **언어에 따라 바뀌는 문자열이 없다** —
 * 사전(`i18n/ko.ts`)은 상단바·계정 메뉴만 다루고, 영문 병기(`useShowsLabelEn`)도 여기엔 없다.
 * 칸을 두면 **눌러도 이 화면은 바뀌지 않는** 컨트롤이 된다. 언어는 로그인 뒤 계정 메뉴에서 바꾼다.
 * 인증 화면 문구가 사전에 들어오면 그때 다시 연다. `AuthShell.test.tsx`가 칸의 부재를 잠근다.
 */
export function AuthShell({
  title,
  description,
  disclaimer = false,
  intro = false,
  children,
  footer,
}: AuthShellProps) {
  return (
    <main className="auth-page">
      {/*
       * 좌: 브랜드 판. 장식이 아니라 `UIFLOW §0`이 요구하는 「서비스 소개」의 자리다.
       * 1100px 이하에서는 **숨기지 않고 접는다** — 확정 문서 3-3.
       */}
      <aside className={intro ? 'auth-brand-panel auth-brand-panel--scene' : 'auth-brand-panel'}>
        {/*
          `#2076` — 로그인 화면에서만 판이 바다가 된다. 소개 블록과 **같은 깃발**로
          가르는 이유는, 1100px 이하에서 판이 상단 띠로 접힐 때(확정 3-3) 소개와
          함께 사라져야 하기 때문이다 — 띠에 바다만 남으면 로고 옆에서 거품이 올라간다.
        */}
        {intro ? <BeomiSea /> : null}

        <p className="auth-brand">
          <BrandLogo />
          {/* 사이드바(`AppShell`)와 같은 문구를 쓴다 — 한쪽만 바뀌면 어긋난다. */}
          <span className="auth-brand-sub">선대 CII 상시 관리</span>
        </p>

        {intro ? (
          <div className="auth-intro">
            {/*
              소개 문구는 **화면 문구**라 디자인 소관이다(`AGENTS §4.6`). `UIFLOW §0`은
              로그인 화면에 「서비스 소개」가 **있을 것**만 요구하고 문장을 정하지 않는다.

              종전 문구는 기능 세 개를 나열했는데, 그 나열은 **바로 아래 계층 목록이
              이미 하고 있었다**(`#2084`). 같은 말을 두 번 하는 대신 **왜 지금 보는지**를
              적는다 — 등급은 연말에 확정되지만 그 등급을 가르는 결정은 항차마다 내려진다.

              「예측」·「추정」은 `PRD §0.3` 면책과 같은 말씨다 — 확정값으로 읽히는
              표현을 쓰지 않는다(`PRD` COR-1).
            */}
            <div className="auth-intro-text">
              <p className="auth-intro-lead">
                CII 등급은 연말에 확정되지만, 등급을 가르는 결정은 항차마다 내려집니다.
              </p>
              <p className="auth-intro-body">
                BlueLog는 항차가 쌓는 CII를 운항 중에 추정하고, 올해가 어느 등급으로 끝날지
                예측합니다. 속도와 항로를 고르기 전에 그 결과를 견줘 봅니다.
              </p>
            </div>
            <EntryPreview />
          </div>
        ) : (
          /*
            소개가 없는 화면(가입 · 재설정 · 인증)도 판이 비지 않게 같은 화면 예시를 둔다 — 종전에는
            남색 판 가운데 로고 한 줄이라 화면의 절반이 비어 있었다. 좁은 폭에서 소개와 함께 접힌다.
          */
          <div className="auth-preview-wrap">
            <EntryPreview />
          </div>
        )}

        {/*
          범이는 **소개 뒤**에 온다 (`#2157`). 판의 flex 항목이라 남은 높이를 받아
          가므로, 소개가 길어지면 그림이 그만큼 작아진다 — 겹칠 수가 없다.
          종전에는 물과 함께 띄워 두고 높이를 상수로 줬고, 좁은 폭에서 계층 목록
          셋째 줄이 범이 모자 위에 그려졌다.
        */}
        {intro ? <BeomiFigure /> : null}
      </aside>

      {/* 우: 종전 카드 그대로. 폼과 링크의 구조는 바뀌지 않는다. */}
      <div className="auth-column">
        <section className="auth-card" aria-labelledby="auth-title">
          <h1 id="auth-title" className="auth-title">
            {title}
          </h1>
          {description ? <p className="auth-description">{description}</p> : null}

          {children}

          {disclaimer ? (
            /*
             * PRD §0.3 원문. 결과 화면 하단 배너(§6.3)와 같은 문구군이며
             * 로그인·회원가입 화면에도 노출한다(UIFLOW §0 `0` · `0-1`).
             *
             * ## 폼 **아래**다 (#1425)
             *
             * 종전에는 카드 맨 위, 제목 바로 다음이었다. 로그인하러 온 사람의 첫
             * 시선이 로그인 버튼이 아니라 **네 줄짜리 고지**에 갔고, 매번 읽히지
             * 않은 채 지나가는 자리였다.
             *
             * **문구도 노출 여부도 그대로다.** `UIFLOW §0`은 로그인 화면에 면책이
             * **있을 것**만 요구하고 위치를 정하지 않으며, `DESIGN_SYSTEM §13`의
             * 「결과 화면 하단」은 결과 화면 규정이다 — 그 규정을 여기에 끌어다
             * 쓰지 않는다. 다만 **하단이 면책의 자리**라는 그 판단과 방향은 같다.
             *
             * 카드 **안**에 둔다. 밖(`auth-footer` 아래)으로 내면 회원가입 링크
             * 뒤에 붙어 카드와 무관한 꼬리말로 읽힌다.
             */
            <p className="auth-disclaimer" role="note">
              본 결과는 공개 데이터, 사용자 입력값, 추정 모델을 기반으로 한 참고용
              예측값입니다. 규제 제출용 공식 CII 계산 결과가 아니며, 최종 운항 판단은
              사용자에게 있습니다.
            </p>
          ) : null}
        </section>

        {footer ? <p className="auth-footer">{footer}</p> : null}

        {/*
          0-5 · 0-6 — 인증 화면 넷 모두에서 가입 전에 열 수 있어야 한다. 라우터 링크가 아니라
          보통 링크다 — 이 셸은 라우터 밖에서도 그려지고(검사), 문서로 가는 길은 화면 상태를
          이어 갈 이유가 없다.
        */}
        <nav className="auth-legal" aria-label="약관 문서">
          <a href={SCREEN_BY_ID.TERMS.path}>{SCREEN_BY_ID.TERMS.label}</a>
          <a href={SCREEN_BY_ID.PRIVACY.path}>{SCREEN_BY_ID.PRIVACY.label}</a>
        </nav>
      </div>
    </main>
  )
}

/**
 * 로그인 폼의 입력 한 칸 — 공용 `Field` 위의 얇은 층이다 (`#936`).
 *
 * 배선(`aria-invalid`·`aria-describedby`·`role="alert"`)은 `Field`가 준다.
 * 여기 남는 것은 이 화면의 입력칸 모양과 `type`·`autoComplete`뿐이다.
 */
export function AuthField({
  id,
  label,
  type,
  value,
  onChange,
  error,
  autoComplete,
  hint,
  revealable = false,
}: {
  id: string
  label: string
  type: 'email' | 'password' | 'text'
  value: string
  onChange: (value: string) => void
  error?: string
  autoComplete?: string
  hint?: string
  /** 비밀번호 보기 단추 (10/7) — 누르는 동안이 아니라 눌러서 켜고 끈다. */
  revealable?: boolean
}) {
  const [shown, setShown] = useState(false)
  /*
   * 배선은 공용 `Field`가 준다 (`#936` · `§8.4`). 여기 남는 것은 **로그인 폼의
   * 입력칸 모양**뿐이다 — 호출부 열 곳은 그대로 둔다.
   */
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) =>
        revealable && type === 'password' ? (
          <span className="auth-input-wrap">
            <input
              {...control}
              className="auth-input auth-input--reveal"
              type={shown ? 'text' : 'password'}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              autoComplete={autoComplete}
            />
            <button
              type="button"
              className="auth-reveal"
              aria-label={shown ? '비밀번호 숨기기' : '비밀번호 보기'}
              aria-pressed={shown}
              onClick={() => setShown((was) => !was)}
            >
              <Icon glyph={shown ? EyeOff : Eye} size="inline" />
            </button>
          </span>
        ) : (
          <input
            {...control}
            className="auth-input"
            type={type}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoComplete={autoComplete}
          />
        )
      }
    </Field>
  )
}

/** 폼 전체 오류 — 서버가 준 문구를 그대로 보여 준다. */
export function AuthAlert({ tone, children }: { tone: 'error' | 'ok'; children: ReactNode }) {
  return (
    <p className={`auth-alert auth-alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  )
}
