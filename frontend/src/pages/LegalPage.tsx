import { useEffect, type ReactNode } from 'react'
import { Link } from 'react-router'
import { BrandLogo } from '../components/BrandLogo'
import {
  INVITE_CODE_HINT,
  ROLE_DESCRIPTION,
  ROLE_LABEL,
  WITHDRAWAL_NOTICE,
} from '../features/auth/authRules'
import { SCREEN_BY_ID } from '../screens'
import './LegalPage.css'

/**
 * 이용약관 · 개인정보처리방침 (`UIFLOW 0-5` · `0-6` · `PRD §5.1`).
 *
 * ## 무엇을 적고 무엇을 적지 않는가
 *
 * **코드와 정본에서 확인되는 사실만 적는다.** 가입을 받는 서비스인데 두 문서가 열리는
 * 경로가 없었다. 그렇다고 사업자 정보 · 보관 기간 · 책임자 같은 법적 항목을 지어내면
 * 사실이 아닌 문서가 된다. 그런 칸은 {@link Todo}로 **「입력 필요」라고 보이게** 남긴다 —
 * 빈칸이 보여야 채울 사람이 찾는다.
 *
 * 문구 가운데 정본이 원문을 확정한 것(탈퇴 고지 · 초대 코드 안내 · 역할 설명)은
 * `authRules.ts`에서 가져온다 — 여기서 다시 적으면 정본이 바뀔 때 이 문서만 낡는다
 * (`AGENTS §4.6`).
 */

/** 운영 주체가 정해야 채울 수 있는 칸. 화면에 「입력 필요」로 보인다. */
function Todo({ children }: { children: ReactNode }) {
  return (
    <span className="legal__todo">
      <span className="legal__todo-tag">입력 필요</span> {children}
    </span>
  )
}

function LegalLayout({
  title,
  other,
  children,
}: {
  title: string
  other: { path: string; label: string }
  children: ReactNode
}) {
  // 셸 밖 화면이라 `AppShell`이 탭 제목을 붙이지 않는다 — 셸과 같은 「화면 · BlueLog」 꼴로 둔다.
  useEffect(() => {
    const previous = document.title
    document.title = `${title} · BlueLog`
    return () => {
      document.title = previous
    }
  }, [title])
  return (
    <div className="legal">
      <header className="legal__bar">
        <Link to={SCREEN_BY_ID.LOGIN.path} className="legal__brand" aria-label="BlueLog 로그인 화면으로">
          <BrandLogo />
        </Link>
        <nav className="legal__nav" aria-label="약관 문서">
          <Link to={other.path}>{other.label}</Link>
          <Link to={SCREEN_BY_ID.LOGIN.path}>로그인</Link>
        </nav>
      </header>
      <main className="legal__main">
        <article className="legal__doc" aria-labelledby="legal-title">
          <h1 id="legal-title" className="legal__title">
            {title}
          </h1>
          <dl className="legal__meta">
            <div>
              <dt>시행일</dt>
              <dd>
                <Todo>시행 날짜</Todo>
              </dd>
            </div>
            <div>
              <dt>운영 주체</dt>
              <dd>
                <Todo>운영자(사업자) 이름 · 연락처</Todo>
              </dd>
            </div>
          </dl>
          <p className="legal__draft" role="note">
            이 문서는 초안입니다. 「입력 필요」로 표시된 칸은 운영 주체가 확정한 뒤 채웁니다.
          </p>
          {children}
        </article>
      </main>
    </div>
  )
}

export function TermsPage() {
  return (
    <LegalLayout
      title={SCREEN_BY_ID.TERMS.label}
      other={{ path: SCREEN_BY_ID.PRIVACY.path, label: SCREEN_BY_ID.PRIVACY.label }}
    >
      <section>
        <h2>1. 서비스가 하는 일</h2>
        <p>
          BlueLog는 선사가 입력한 선박 제원 · 항차 기록과 공개 데이터를 바탕으로 선박의 CII(탄소집약도
          지표)를 추정하고, 올해 등급이 어디로 갈지 예측하는 웹 서비스입니다.
        </p>
        <p>
          화면의 계산 결과는 참고용 예측값이며 규제 제출용 공식 CII 계산 결과가 아닙니다. 최종 운항
          판단은 이용자에게 있습니다. 공식 등급은 연말 DCS 보고 · 검증을 거쳐 확정됩니다.
        </p>
      </section>

      <section>
        <h2>2. 계정</h2>
        <ul>
          <li>이메일과 비밀번호로 가입합니다. {INVITE_CODE_HINT}</li>
          <li>가입한 이메일은 바꿀 수 없습니다.</li>
          <li>
            새 계정은 {ROLE_LABEL.FIELD} 역할로 시작하며, 역할은 {ROLE_LABEL.ADMIN}가 바꿉니다.{' '}
            {ROLE_DESCRIPTION}
          </li>
        </ul>
      </section>

      <section>
        <h2>3. 탈퇴</h2>
        <p>설정의 「탈퇴하기」에서 언제든 탈퇴할 수 있습니다. {WITHDRAWAL_NOTICE}</p>
        <p>
          보존되는 기록과 지워지는 기록은{' '}
          <Link to={SCREEN_BY_ID.PRIVACY.path}>개인정보처리방침</Link> 4항에 적었습니다.
        </p>
      </section>

      <section>
        <h2>4. 이용자의 의무와 금지 행위</h2>
        <p>
          <Todo>계정 공유 · 부정 이용 등 금지 행위와 위반 시 조치</Todo>
        </p>
      </section>

      <section>
        <h2>5. 서비스 변경 · 중단과 약관 변경</h2>
        <p>
          <Todo>변경 · 중단 시 고지 방법과 기간</Todo>
        </p>
      </section>

      <section>
        <h2>6. 책임의 한계 · 분쟁 해결</h2>
        <p>
          <Todo>책임 제한 범위 · 준거법 · 관할 법원</Todo>
        </p>
      </section>
    </LegalLayout>
  )
}

export function PrivacyPage() {
  return (
    <LegalLayout
      title={SCREEN_BY_ID.PRIVACY.label}
      other={{ path: SCREEN_BY_ID.TERMS.path, label: SCREEN_BY_ID.TERMS.label }}
    >
      <section>
        <h2>1. 처리하는 개인정보</h2>
        <table className="legal__table">
          <caption className="sr-only">처리하는 개인정보 항목</caption>
          <thead>
            <tr>
              <th scope="col">언제</th>
              <th scope="col">항목</th>
              <th scope="col">필수 여부</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">가입할 때</th>
              <td>이메일 · 비밀번호(되돌릴 수 없는 형태로 바꿔 저장 — Argon2)</td>
              <td>필수</td>
            </tr>
            <tr>
              <th scope="row">가입할 때</th>
              <td>표시 이름 · 초대 코드</td>
              <td>선택</td>
            </tr>
            <tr>
              <th scope="row">설정에서</th>
              <td>프로필 이미지</td>
              <td>선택</td>
            </tr>
            <tr>
              <th scope="row">이용하는 동안</th>
              <td>
                로그인 세션 쿠키 · 계산 · 설정 변경 등 주요 작업의 기록(누가 · 언제) · AI 어시스턴트 대화
                내용
              </td>
              <td>자동</td>
            </tr>
          </tbody>
        </table>
        <p>
          이용자가 입력하는 선박 제원 · 항차 · 연료 기록은 회사의 업무 정보이며 위 계정에 연결되어
          저장됩니다.
        </p>
      </section>

      <section>
        <h2>2. 이용 목적</h2>
        <ul>
          <li>계정 생성 · 로그인 · 이메일 인증 · 비밀번호 재설정</li>
          <li>입력한 선박 · 항차 기록과 계산 결과를 계정에 연결해 보여 주기</li>
          <li>
            보안 — 같은 이메일로 로그인에 연속 실패하면 응답을 늦추고, 주요 작업을 감사 기록으로
            남깁니다
          </li>
        </ul>
      </section>

      <section>
        <h2>3. 쿠키</h2>
        <p>
          로그인 상태를 유지하는 세션 쿠키 하나를 씁니다. 자바스크립트가 읽을 수 없고(HttpOnly) 보안
          연결에서만 전송됩니다(Secure · SameSite=Lax). 광고 · 방문 분석 쿠키는 쓰지 않습니다.
        </p>
      </section>

      <section>
        <h2>4. 보관과 파기</h2>
        <ul>
          <li>AI 어시스턴트 대화는 90일이 지나면 지웁니다.</li>
          <li>
            탈퇴하면 대화와 프로필 이미지를 바로 지웁니다. 계정은 탈퇴 상태로 표시되고, 그 계정이 남긴
            계산 · 감사 기록은 규제 대응의 근거라 보존됩니다.
          </li>
          <li>
            <Todo>탈퇴 계정의 이메일 등 계정 정보 보관 기간 · 백업 보관 기간</Todo>
          </li>
        </ul>
      </section>

      <section>
        <h2>5. 처리 위탁 · 국외 이전</h2>
        <table className="legal__table">
          <caption className="sr-only">처리를 맡기는 곳</caption>
          <thead>
            <tr>
              <th scope="col">맡기는 일</th>
              <th scope="col">업체</th>
              <th scope="col">넘어가는 정보</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">화면 제공</th>
              <td>Cloudflare (Cloudflare Pages)</td>
              <td>접속 요청(IP 주소 등 통신 정보)</td>
            </tr>
            <tr>
              <th scope="row">서버 · 데이터베이스 운영</th>
              <td>
                Oracle Cloud Infrastructure <Todo>리전(국가)</Todo>
              </td>
              <td>위 1항 전부</td>
            </tr>
            <tr>
              <th scope="row">인증 · 재설정 메일 발송</th>
              <td>
                <Todo>메일 발송 업체</Todo>
              </td>
              <td>이메일 주소</td>
            </tr>
            <tr>
              <th scope="row">AI 어시스턴트 답변 생성</th>
              <td>
                <Todo>외부 언어모델 공급자</Todo>
              </td>
              <td>
                직접 입력한 질문과 계산 결과 수치 · 등급만 보냅니다. 선박명 · IMO 번호 · 항구 · 연료량 ·
                사용자 식별자는 보내지 않습니다.
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>6. 이용자의 권리</h2>
        <ul>
          <li>설정에서 표시 이름 · 비밀번호 · 프로필 이미지를 바꾸거나 지울 수 있습니다.</li>
          <li>설정의 「탈퇴하기」로 계정을 지울 수 있습니다.</li>
          <li>
            <Todo>열람 · 정정 · 처리정지 요청 창구와 처리 기한</Todo>
          </li>
        </ul>
      </section>

      <section>
        <h2>7. 개인정보 보호책임자</h2>
        <p>
          <Todo>책임자 이름 · 직책 · 연락처</Todo>
        </p>
      </section>
    </LegalLayout>
  )
}
