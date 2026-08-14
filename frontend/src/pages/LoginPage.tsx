import { Link, Navigate, useSearchParams } from 'react-router'
import { DEFAULT_PATH } from '../screens'
import { loginUrl, useAuthUser } from '../auth/session'
import './LoginPage.css'

/**
 * 로그인 화면 — `UIFLOW.md` §0 (#278).
 *
 * - 서비스 소개 및 면책 문구(PRD §0.3 원문) + `구글 계정으로 계속하기` 버튼 단일.
 * - 버튼은 백엔드 `/auth/login`으로 **전체 페이지 이동**한다 — 구글 인증 화면을
 *   거치는 OIDC 흐름이라 SPA 라우팅 밖으로 나갔다가 `redirect_to`로 돌아온다.
 * - `?next=`로 전달된 복귀 경로를 `redirect_to`에 그대로 실어 왕복 보존한다.
 *   가드가 미인증 리다이렉트 시 원래 가려던 경로를 여기에 싣는다.
 * - 이미 로그인돼 있으면(`useAuthUser`) next 또는 기본 화면으로 바로 보낸다.
 */

/** 앱 내부 경로만 복귀 경로로 인정한다 — 서버(#274)와 같은 open redirect 방어. */
function safeNext(raw: string | null): string | null {
  if (raw && raw.startsWith('/') && !raw.startsWith('//')) return raw
  return null
}

export function LoginPage() {
  const [searchParams] = useSearchParams()
  const user = useAuthUser()
  const next = safeNext(searchParams.get('next'))

  if (user) {
    return <Navigate to={next ?? DEFAULT_PATH} replace />
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <p className="login-brand">
          <span className="login-brand-name">BlueLog</span>
          <span className="login-brand-sub">CII 예측 · 운항 의사결정 보조</span>
        </p>

        <h1 id="login-title" className="login-title">
          중소선사를 위한 CII 예측 플랫폼
        </h1>
        <p className="login-description">
          항차 CII 추정, 운항 시나리오 비교, 연간 등급 시뮬레이션을 하나의 화면에서
          확인합니다.
        </p>

        {/* PRD §0.3 — 제품 기본 원칙의 면책 문구 원문. 결과 화면 하단 배너(§6.3)와
            같은 문구군이며 로그인 화면에도 노출한다(UIFLOW §0 「서비스 소개 및 면책 문구」). */}
        <p className="login-disclaimer" role="note">
          본 결과는 공개 데이터, 사용자 입력값, 추정 모델을 기반으로 한 참고용
          예측값입니다. 규제 제출용 공식 CII 계산 결과가 아니며, 최종 운항 판단은
          사용자에게 있습니다.
        </p>

        <a
          className="login-button"
          href={loginUrl(next ?? DEFAULT_PATH)}
          data-testid="login-google-button"
        >
          구글 계정으로 계속하기
        </a>
      </section>
    </main>
  )
}

/**
 * 로그인 실패 화면 — `UIFLOW.md` §0-1 (#278).
 *
 * 실패 사유 안내 + 재시도 버튼. 재시도는 `0. 로그인 화면`로 돌아간다(UIFLOW).
 */
export function LoginFailurePage() {
  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-failure-title">
        <h1 id="login-failure-title" className="login-title">
          로그인하지 못했습니다
        </h1>
        <p className="login-description">
          로그인에 실패했습니다. 잠시 후 다시 시도해 주세요.
        </p>
        <Link className="login-button" to="/login" data-testid="login-retry-button">
          다시 시도하기
        </Link>
      </section>
    </main>
  )
}
