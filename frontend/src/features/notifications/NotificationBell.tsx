import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { useI18n, useTextLang } from '../../i18n/core'
import { BellGlyph } from '../../layout/NavIcons'
import { loadNotifications } from './apiProvider'
import { LEVEL_LABEL, notificationAction, notificationFact } from './notificationRules'
import type { NotificationSnapshot } from './types'
import './NotificationBell.css'

/**
 * 상단바 종 버튼 — 지금 걸려 있는 알림 (`DESIGN_SYSTEM §7.2` 「알림」 · `§16` 항목 10 · #2204).
 *
 * 종전에는 알림 체계가 없어 `disabled` + 「준비 중」이었다(`#771` ⑽). 이제 서버의
 * `GET /fleet/notifications`(`API_SPEC §2.19`)를 받아 개수와 목록을 보인다.
 *
 * - **상태 목록이다** — 읽음 · 안 읽음이 없다. 그래서 펼쳐도 숫자가 줄지 않는다. 해결되면
 *   다음 조회에서 사라진다
 * - **받는 때** — 셸이 뜰 때 한 번, 그리고 펼칠 때마다. 경로를 옮길 때마다 받지 않는다 —
 *   선대 요약과 같은 계산이라 화면마다 다시 부르면 그만큼 느려진다
 * - 숫자 배지는 **중립색**이다(`§2.3` 경고색은 한 자리에 한 번 — 목록 안 단계 글자가 쓴다).
 *   0이면 숫자를 두지 않는다
 * - 여닫기는 계정 메뉴와 같은 **disclosure**다(`aria-expanded` · `aria-controls` · Esc로 닫고
 *   초점을 버튼으로 되돌림 · 바깥 클릭 · 경로 이동으로 닫힘). 항목은 메뉴 항목이 아니라 글과
 *   링크라 `role="menu"`를 쓰지 않는다
 */
export function NotificationBell({
  load = loadNotifications,
}: {
  /** 테스트가 서버 대신 넣는다. */
  load?: () => Promise<NotificationSnapshot>
}) {
  const { t } = useI18n()
  const textLang = useTextLang()
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState<NotificationSnapshot | null>(null)
  const [failed, setFailed] = useState(false)
  const panelId = useId()
  const titleId = useId()
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()

  const refresh = useCallback(() => {
    let alive = true
    load()
      .then((next) => {
        if (!alive) return
        setSnapshot(next)
        setFailed(false)
      })
      .catch(() => {
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
    }
  }, [load])

  // 셸이 뜰 때 한 번.
  useEffect(() => refresh(), [refresh])

  // 경로가 바뀌면 닫는다 — 항목 링크를 누른 뒤 목록이 막 도착한 화면을 가리지 않게.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- 경로(라우터)가 바뀌면 닫는 동기화 — 열린 상태는 사용자 조작이라 파생값으로 둘 수 없다
    setOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      trigger.current?.focus()
    }
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

  const total = snapshot?.counts.total ?? 0

  return (
    <div className="notification-bell" ref={root}>
      <button
        type="button"
        ref={trigger}
        className="app-shell__iconbtn notification-bell__trigger"
        lang={textLang}
        aria-label={t('shell.notification.aria', { count: String(total) })}
        title={t('shell.notification.title')}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          // 펼칠 때마다 다시 받는다 — 방금 실적을 확정했으면 그 줄이 사라져 있어야 한다.
          if (!open) refresh()
          setOpen((was) => !was)
        }}
        data-testid="notification-trigger"
      >
        <BellGlyph />
        {total > 0 ? (
          <span className="notification-bell__count" aria-hidden="true">
            {total}
          </span>
        ) : null}
      </button>

      <div
        className="notification-bell__panel"
        id={panelId}
        hidden={!open}
        role="region"
        aria-labelledby={titleId}
        data-testid="notification-panel"
      >
        <p className="notification-bell__title" id={titleId} lang={textLang}>
          {t('shell.notification.title')}
        </p>
        {failed && snapshot === null ? (
          <p className="notification-bell__note" lang={textLang}>
            {t('shell.notification.failed')}
          </p>
        ) : snapshot !== null && snapshot.items.length === 0 ? (
          <p className="notification-bell__note" lang={textLang}>
            {t('shell.notification.empty')}
          </p>
        ) : (
          <ul className="notification-bell__list">
            {(snapshot?.items ?? []).map((item) => {
              const action = notificationAction(item)
              return (
                <li
                  key={`${item.kind}-${item.vesselId}-${item.reason ?? ''}-${item.voyageId ?? ''}`}
                  className="notification-bell__item"
                >
                  <span
                    className={`notification-bell__level notification-bell__level--${item.level.toLowerCase()}`}
                  >
                    {LEVEL_LABEL[item.level]}
                  </span>
                  <span className="notification-bell__vessel">{item.vesselName}</span>
                  <span className="notification-bell__fact">{notificationFact(item)}</span>
                  <Link className="notification-bell__action" to={action.to}>
                    {action.label}
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
