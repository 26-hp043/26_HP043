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
 * ## 면책 문구는 로그인 화면에만 둔다
 *
 * `UIFLOW §0`이 「서비스 소개 및 면책 문구」를 **로그인 화면**의 구성 요소로
 * 규정한다. 회원가입·비밀번호 찾기는 서비스 설명 자리가 아니므로 `disclaimer`를
 * 선택 인자로 두었다.
 */

interface AuthShellProps {
  title: string
  description?: string
  /** `PRD §0.3` 면책 문구 노출 여부. 로그인 화면만 `true`. */
  disclaimer?: boolean
  children: ReactNode
  /** 카드 아래 보조 링크 줄. */
  footer?: ReactNode
}

export function AuthShell({
  title,
  description,
  disclaimer = false,
  children,
  footer,
}: AuthShellProps) {
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <p className="auth-brand">
          <BrandLogo />
          {/* 사이드바(`AppShell`)와 같은 문구를 쓴다 — 한쪽만 바뀌면 어긋난다. */}
          <span className="auth-brand-sub">선대 CII 상시 관리</span>
        </p>

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
