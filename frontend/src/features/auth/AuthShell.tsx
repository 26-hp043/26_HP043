import type { ReactNode } from 'react'
import './AuthShell.css'
import { BrandLogo } from '../../components/BrandLogo'

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
 * ## 면책 문구와 서비스 소개는 로그인 화면에만 둔다
 *
 * `UIFLOW §0`이 「서비스 소개 및 면책 문구」를 **로그인 화면**의 구성 요소로
 * 규정한다. 회원가입·비밀번호 찾기는 서비스 설명 자리가 아니므로 둘 다 선택
 * 인자로 두었다. **깃발 하나로 묶지 않은 이유**는 이름이 하는 일을 가리기
 * 때문이다 — `disclaimer`는 `PRD §0.3` 문구를, `intro`는 소개 블록을 켠다.
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
  /** `PRD §0.3` 면책 문구 노출 여부. 로그인 화면만 `true`. */
  disclaimer?: boolean
  /** 브랜드 판의 서비스 소개 블록 노출 여부(`UIFLOW §0`). 로그인 화면만 `true`. */
  intro?: boolean
  children: ReactNode
  /** 카드 아래 보조 링크 줄. */
  footer?: ReactNode
}

/**
 * 브랜드 판이 소개하는 세 계층.
 *
 * 문구는 **`UIFLOW §2.1` 계층 구조도에서 그대로 가져왔다**(`AGENTS §3`).
 * 여기서 새로 쓰면 사이드바·대시보드가 설명하는 것과 어긋난다.
 */
const TIERS = [
  { tier: '선대', detail: '내 배 전체 · 위험 선박 경고' },
  { tier: '선박', detail: '연도별 CII 이력 · 올해 누적(YTD) · 현재 위치·상태' },
  { tier: '항차', detail: '항해 중 누적값 · 연말 예상 등급 · 정박 반영' },
] as const

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
      <aside className="auth-brand-panel">
        <p className="auth-brand">
          <BrandLogo />
          {/* 사이드바(`AppShell`)와 같은 문구를 쓴다 — 한쪽만 바뀌면 어긋난다. */}
          <span className="auth-brand-sub">선대 CII 상시 관리</span>
        </p>

        {intro ? (
          <div className="auth-intro">
            <p className="auth-intro-lead">
              항차 CII 추정, 운항 시나리오 비교, 연간 등급 시뮬레이션을 하나의 화면에서
              확인합니다.
            </p>
            <ul className="auth-tiers">
              {TIERS.map(({ tier, detail }) => (
                <li className="auth-tier" key={tier}>
                  <span className="auth-tier-name">{tier}</span>
                  <span className="auth-tier-detail">{detail}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </aside>

      {/* 우: 종전 카드 그대로. 폼과 링크의 구조는 바뀌지 않는다. */}
      <div className="auth-column">
        <section className="auth-card" aria-labelledby="auth-title">
          <h1 id="auth-title" className="auth-title">
            {title}
          </h1>
          {description ? <p className="auth-description">{description}</p> : null}

          {disclaimer ? (
            /*
             * PRD §0.3 원문. 결과 화면 하단 배너(§6.3)와 같은 문구군이며
             * 로그인 화면에도 노출한다(UIFLOW §0).
             */
            <p className="auth-disclaimer" role="note">
              본 결과는 공개 데이터, 사용자 입력값, 추정 모델을 기반으로 한 참고용
              예측값입니다. 규제 제출용 공식 CII 계산 결과가 아니며, 최종 운항 판단은
              사용자에게 있습니다.
            </p>
          ) : null}

          {children}
        </section>

        {footer ? <p className="auth-footer">{footer}</p> : null}
      </div>
    </main>
  )
}

/**
 * 입력 한 칸.
 *
 * 오류를 `aria-describedby`로 연결하고 `aria-invalid`를 세운다 — 색만으로 오류를
 * 표시하면 스크린 리더 사용자가 무엇이 잘못됐는지 알 수 없다(`DESIGN_SYSTEM §14`).
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
}: {
  id: string
  label: string
  type: 'email' | 'password' | 'text'
  value: string
  onChange: (value: string) => void
  error?: string
  autoComplete?: string
  hint?: string
}) {
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="auth-field">
      <label className="auth-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={error ? 'auth-input auth-input--error' : 'auth-input'}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      {hint ? (
        <p className="auth-hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="auth-error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
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
