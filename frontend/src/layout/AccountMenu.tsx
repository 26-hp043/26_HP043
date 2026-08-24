import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { SCREEN_BY_ID } from '../screens'
import { isEmailVerified } from '../features/auth/authRules'
import type { CurrentUser } from '../auth/session'
import './AccountMenu.css'

/**
 * 상단바 계정 영역 (#717).
 *
 * ## 왜 disclosure이고 `role="menu"`가 아닌가
 *
 * `role="menu"`를 선언하면 **화살표 이동·Home·End·타입어헤드까지 구현해야 한다** —
 * 스크린 리더가 그 키보드 모델을 전제로 안내하기 때문이다. 여기 담기는 조작은
 * 「설정」 링크 **하나**뿐이라 그 계약을 질 이유가 없다.
 *
 * 그래서 버튼 하나가 패널 하나를 여닫는 **disclosure**로 둔다 —
 * `aria-expanded` + `aria-controls`. Tab 이동만으로 충분히 닿는다.
 *
 * ## 패널을 항상 렌더하고 `hidden`으로 감춘다
 *
 * `aria-controls`는 **존재하는 id**를 가리켜야 한다. 닫혔을 때 패널을 아예 그리지
 * 않으면 그 참조가 끊긴 id를 가리키게 된다.
 *
 * ## 편집은 넣지 않는다
 *
 * 표시 이름·비밀번호 폼은 설정 화면의 `AccountPanel`이 소유한다. 여기에 같은 폼을
 * 두면 **입력 규칙이 두 벌**이 되고, 한쪽만 고쳐 갈린다 — 이 저장소가 카드 규격과
 * 셸 여백에서 이미 겪은 형태다. 여기는 **요약과 진입로**만 맡는다.
 */

/** 아바타 이니셜. 이메일이면 로컬파트 첫 글자를 쓴다. */
function initialOf(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase()
}

export function AccountMenu({ user }: { user: CurrentUser }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const root = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()

  /*
   * 경로가 바뀌면 닫는다. 「설정」을 누른 뒤에도 패널이 남아 있으면 **막 도착한
   * 화면의 오른쪽 위를 자기가 가린다.**
   */
  useEffect(() => {
    setOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    /*
     * `mousedown`이지 `click`이 아니다. `click`으로 잡으면 패널 안의 링크를 누를 때
     * 바깥 판정이 먼저 돌아 패널이 사라지고 **링크가 눌리지 않는 경우**가 생긴다.
     */
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }

    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const label = user.displayName ?? user.email
  const verified = isEmailVerified(user.emailVerifiedAt)

  return (
    <div className="account-menu" ref={root}>
      <button
        type="button"
        className="account-menu__trigger"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((was) => !was)}
        data-testid="account-trigger"
      >
        <span className="account-menu__avatar" aria-hidden="true">
          {initialOf(label)}
        </span>
        <span className="account-menu__name">{label}</span>
        <ChevronGlyph />
      </button>

      <div
        className="account-menu__panel"
        id={panelId}
        hidden={!open}
        data-testid="account-panel"
      >
        <p className="account-menu__panel-name">
          {user.displayName ?? '표시 이름 없음'}
        </p>
        <p className="account-menu__panel-email">{user.email}</p>
        {/*
          인증 상태에 색을 주지 않는다. 쓸 만한 경고색 별칭(`--color-warning-text`)이
          현재 `--cii-c-fill`(등급 C)을 가리켜, 등급 문자 없이 쓰면 `§0.2` 제약 2를
          어긴다. 미인증은 셸 상단 배너가 이미 상시로 알린다.
        */}
        <p className="account-menu__verify">
          {verified ? '이메일 인증 완료' : '이메일 인증 대기'}
        </p>

        <Link className="account-menu__link" to={SCREEN_BY_ID.SETTINGS.path}>
          <span>설정</span>
          <span className="account-menu__link-sub">계정 정보 · 비밀번호</span>
        </Link>
      </div>
    </div>
  )
}

/** 여닫힘 표시. 장식이므로 `aria-hidden`이며, 이름이 라벨을 이미 맡는다 (§14). */
function ChevronGlyph() {
  return (
    <svg
      className="account-menu__chevron"
      viewBox="0 0 20 20"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M6 8l4 4 4-4" />
    </svg>
  )
}
