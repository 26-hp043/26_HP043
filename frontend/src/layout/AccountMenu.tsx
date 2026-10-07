import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { Avatar } from '../components/Avatar'
import { Link, useLocation } from 'react-router'
import { SCREEN_BY_ID } from '../screens'
import { isEmailVerified } from '../features/auth/authRules'
import type { CurrentUser } from '../auth/session'
import './AccountMenu.css'
import { ChevronDown } from 'lucide-react'
import { Icon } from '../components/Icon'
import { useI18n, useTextLang } from '../i18n/core'
import { ThemeToggle } from '../theme/ThemeToggle'
import { LanguageToggle } from '../i18n/LanguageToggle'
import { roleKey } from './accountRole'

/**
 * 계정 영역 — 사이드바 로고 아래 사용자 카드 (#717 · #2203).
 *
 * ## 사이드바로 옮겼다 (#2203 · `DESIGN_SYSTEM §7.2`)
 *
 * 종전에는 상단바 오른쪽 끝에 아바타 · 이름 버튼과 로그아웃이 있었다. 누구의 화면인지,
 * 어떤 역할로 보고 있는지가 그 작은 버튼에만 나왔다. 이제 **카드가 표시이자 메뉴 트리거**
 * 다 — 카드(아바타 · 이름 · 역할)를 누르면 이 패널이 열린다. 「카드는 표시만 + 상단바
 * 메뉴 유지」는 같은 이름 · 사진이 두 자리에 생겨 택하지 않았다(rlatnals4114 결정).
 *
 * - 역할은 계정의 `role`(현장직 · 사무직 · 관리자)이다. **둘러보기 계정은 「둘러보기」**
 *   다 — 둘러보기는 서비스를 다 보이려고 `ADMIN`이라, 「관리자」로 적으면 심사위원이
 *   자기 권한으로 읽는다(`isTour` · `API_SPEC §1.2.5a`)
 * - 로그아웃은 **패널 안 맨 아래**다. 종전에는 시연에서 한 번에 누르려고 밖에 따로 두었다
 * - 사이드바가 축소(64)되면 아바타만 보이고 이름 · 역할은 **시각적으로만** 감춘다 —
 *   버튼의 이름이 그 글자에서 나오므로 지우면 낭독할 이름이 없어진다(`§7.2` 축소 규칙)
 *
 * ## 패널은 화면 기준으로 띄운다(`position: fixed`)
 *
 * 사이드바는 세로로 넘치면 스스로 스크롤한다(`overflow-y: auto`). 그 안에서 절대 위치로
 * 띄우면 패널이 사이드바 상자에 **잘린다** — 특히 축소(64) 상태에서는 패널 대부분이
 * 사이드바 밖이다. 그래서 열 때 카드의 위치를 재서 화면 좌표로 놓는다.
 *
 * ## 왜 disclosure이고 `role="menu"`가 아닌가
 *
 * `role="menu"`를 선언하면 **화살표 이동·Home·End·타입어헤드까지 구현해야 한다** —
 * 스크린 리더가 그 키보드 모델을 전제로 안내하기 때문이다.
 *
 * 그래서 버튼 하나가 패널 하나를 여닫는 **disclosure**로 둔다 —
 * `aria-expanded` + `aria-controls`. Tab 이동만으로 충분히 닿는다.
 *
 * 진짜 이유는 **여기 담긴 것이 메뉴 항목이 아니라는 것**이다 — 테마·언어는 누르면
 * 닫히는 명령이 아니라 **그 자리에 머무르는 선택**(`radiogroup`)이고, `role="menu"` 안의
 * `radiogroup`은 화살표 키의 소유자가 둘이 된다.
 *
 * ## 패널을 항상 렌더하고 `hidden`으로 감춘다
 *
 * `aria-controls`는 **존재하는 id**를 가리켜야 한다. 닫혔을 때 패널을 아예 그리지
 * 않으면 그 참조가 끊긴 id를 가리키게 된다.
 *
 * ## 편집은 넣지 않는다
 *
 * 표시 이름·비밀번호 폼은 설정 화면의 `AccountPanel`이 소유한다. 여기에 같은 폼을
 * 두면 **입력 규칙이 두 벌**이 되고, 한쪽만 고쳐 갈린다. 여기는 **요약과 진입로**만 맡는다.
 */

export function AccountMenu({
  user,
  onLogout,
  logoutFailure,
}: {
  user: CurrentUser
  /** 로그아웃 — 셸이 소유한다(실패 문구 · 이동). 여기는 버튼 자리만 맡는다. */
  onLogout: () => void
  /** 로그아웃이 **서버에서** 실패했을 때의 문구 (`#825` ⑵). 없으면 `null`. */
  logoutFailure: string | null
}) {
  const { t } = useI18n()
  const textLang = useTextLang()
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const themeLabelId = useId()
  const languageLabelId = useId()
  const root = useRef<HTMLDivElement>(null)
  /*
   * Escape로 닫을 때 **초점을 여는 버튼으로 되돌린다** (#829 ⑸d · WCAG 2.4.3).
   *
   * 패널은 `hidden={!open}`으로 감춰지는데, 그 안에 초점이 있는 채로 감추면 초점이
   * `<body>`로 떨어진다. 키보드 사용자는 그 자리에서 Tab을 누르면 **문서 맨 앞으로
   * 돌아간다** — 방금 있던 자리를 잃는다.
   */
  const trigger = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()
  /** 패널의 화면 좌표 — 열 때와 창이 바뀔 때 카드 아래로 맞춘다. */
  const [place, setPlace] = useState<{ top?: number; bottom?: number; left: number } | null>(null)

  const measure = useCallback(() => {
    const rect = trigger.current?.getBoundingClientRect()
    if (!rect) return
    // 화면 아래쪽에 있으면 위로 연다 (10/7 · 사이드바 맨 아래 계정 시안)
    setPlace(
      rect.top > window.innerHeight / 2
        ? { bottom: window.innerHeight - rect.top + 8, left: rect.left }
        : { top: rect.bottom + 8, left: rect.left },
    )
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    measure()
    // 사이드바가 스스로 스크롤하거나 창 크기가 바뀌면 카드가 움직인다 — 따라간다.
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, measure])

  /*
   * 경로가 바뀌면 닫는다. 「설정」을 누른 뒤에도 패널이 남아 있으면 **막 도착한
   * 화면의 오른쪽 위를 자기가 가린다.**
   */
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- 경로(라우터)가 바뀌면 닫는 동기화 — 열린 상태는 사용자 조작이라 파생값으로 둘 수 없다
    setOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      // 바깥 클릭으로 닫을 때는 되돌리지 않는다 — 그때 초점은 사용자가 누른 곳에 있다.
      trigger.current?.focus()
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
        ref={trigger}
        className="account-menu__trigger"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((was) => !was)}
        data-testid="account-trigger"
      >
        {/*
          `#2080` — 올린 사진이 있으면 사진, 없으면 머리글자. 모양은 `Avatar` 하나가
          갖는다 — 설정의 「프로필」 절과 이 자리가 각자 원을 그리면 한쪽만 고쳐
          어긋난다.
        */}
        <Avatar className="account-menu__avatar" hasAvatar={user.hasAvatar} name={label} />
        <span className="account-menu__who">
          <span className="account-menu__name">{label}</span>
          {/* 역할 — 둘러보기 계정이면 「둘러보기」 (#2203). 축소(64)에서는 시각적으로만 감춘다. */}
          <span className="account-menu__role" lang={textLang}>
            {t(roleKey(user))}
          </span>
        </span>
        {/* 여닫힘 표시. 장식이므로 라벨을 주지 않는다 — 이름은 버튼이 이미 맡는다 (§14). */}
        <Icon glyph={ChevronDown} className="account-menu__chevron" size="inline" />
      </button>

      <div
        className="account-menu__panel"
        id={panelId}
        hidden={!open}
        style={place === null ? undefined : { top: place.top, bottom: place.bottom, left: place.left }}
        data-testid="account-panel"
      >
        {/*
          이름이 없을 때만 사전 문구가 들어간다 — 그때만 영어일 수 있으므로
          `lang`도 그 경우에만 붙인다 (`#1652`). 사용자 이름은 어느 언어에서나
          입력된 그대로다.
        */}
        <p
          className="account-menu__panel-name"
          lang={user.displayName === null || user.displayName === undefined ? textLang : undefined}
        >
          {user.displayName ?? t('account.noDisplayName')}
        </p>
        <p className="account-menu__panel-email">{user.email}</p>
        {/*
          인증 상태에 색을 주지 않는다. 미인증은 셸 상단 배너가 이미 상시로 알린다.
          (당시에는 경고색(`--color-warning-text`)이 `--cii-c-fill`(등급 C)을 가리켜
          `§0.2` 제약 2에도 걸렸다 — `#1022` 이후 `--semantic-warning` 쪽이다. 여기에
          색을 줄지는 디자인 결정이며 이 주석이 정하지 않는다.)
        */}
        <p className="account-menu__verify" lang={textLang}>
          {verified ? t('account.verified') : t('account.unverified')}
        </p>

        {/*
          테마·언어 (`#1422`). 종전에는 상단바에 그대로 나와 있었는데,
          `DESIGN_SYSTEM §7.2` 🔒이 상단바에 두는 것을 **「선박·항차 · 알림 · 계정」**으로
          닫아 두었다 — 그 밖의 것이 둘 있었다.

          **설정 화면이 아니라 여기다.** 테마와 언어는 「보는 방식」이라 어느 화면에서든
          그 자리에서 바꾸게 된다 — 바꾸려고 화면을 옮겨야 하면 보던 것을 잃는다.
          계정 메뉴는 이미 어느 화면에서나 같은 자리에 있다.

          라벨을 글자로 적는다. 상단바에서는 자리가 없어 아이콘만 두고 `aria-label`로
          이름을 줬는데, 해·달이 무엇을 뜻하는지는 **누르기 전에는 확인할 수 없었다.**
        */}
        <div className="account-menu__settings">
          <div className="account-menu__setting">
            <span className="account-menu__setting-label" id={themeLabelId} lang={textLang}>
              {t('account.theme')}
            </span>
            <ThemeToggle labelledBy={themeLabelId} />
          </div>
          <div className="account-menu__setting">
            <span
              className="account-menu__setting-label"
              id={languageLabelId}
              lang={textLang}
            >
              {t('account.language')}
            </span>
            <LanguageToggle labelledBy={languageLabelId} />
          </div>
        </div>

        <Link className="account-menu__link" to={SCREEN_BY_ID.SETTINGS.path}>
          <span lang={textLang}>{t('account.settings')}</span>
          <span className="account-menu__link-sub" lang={textLang}>
            {t('account.settingsSub')}
          </span>
        </Link>

        {/*
          로그아웃 — 패널 맨 아래 (#2203 결정). 종전에는 상단바에서 한 번에 누르려고 메뉴
          밖에 따로 두었다(`#717`). 무게는 텍스트 버튼 그대로다(`#1266`).
        */}
        <button
          type="button"
          className="account-menu__logout"
          lang={textLang}
          onClick={onLogout}
          data-testid="logout-button"
        >
          {t('shell.logout')}
        </button>
        {/*
          로그아웃이 **서버에서** 실패했음을 알린다 (`#825` ⑵). 실패하면 이동하지 않으므로
          패널이 열린 채로 남고, 버튼 바로 아래에서 다시 누를 수 있다.
        */}
        {logoutFailure !== null ? (
          <p className="account-menu__logout-failure" role="alert">
            {logoutFailure}
          </p>
        ) : null}
      </div>
    </div>
  )
}

