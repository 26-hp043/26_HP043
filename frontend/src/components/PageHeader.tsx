import type { ReactNode } from 'react'
import { SCREEN_BY_ID, type ScreenId } from '../screens'
import './PageHeader.css'

/**
 * 화면 제목 — 모든 화면이 같은 급으로, 같은 이름으로 쓴다.
 *
 * ## 왜 한 곳에서 그리는가
 *
 * 종전에는 화면마다 제 손으로 제목을 그렸고, **세 갈래로 갈려 있었다.**
 *
 * | | 화면 |
 * |---|---|
 * | `h1` (28px) | 대시보드 · 보고서 · 선박 관리 · 설정 |
 * | `h2` (20px) | 연간 등급 관리 — **한 단 작았다** |
 * | 없음 | CII 예측 · 항로 비교 |
 *
 * 제목이 없는 두 화면은 **카드 제목이 화면 제목 자리를 대신**하고 있었다. 그래서
 * 「칸 안에 제목이 있는 화면과 없는 화면」이 섞여 보였고, 실제로 그렇게 보였다.
 *
 * ## 이름은 `screens.ts`가 소유한다
 *
 * 사이드바가 이미 그 값을 쓴다. 화면이 제 이름을 따로 적으면 **네비게이션에서 부른
 * 이름과 도착한 화면의 이름이 달라진다** — 실제로 「연간 등급 관리」를 눌러 들어가면
 * 「연간 CII 시뮬레이션」이 떠 있었다.
 *
 * `screens.ts`는 `UIFLOW.md`에서 옮겨 온 것이므로, 여기서 이름을 다시 적는 것은
 * 정본을 세 번째로 복제하는 일이 된다.
 *
 * ## 쓰지 않는 자리
 *
 * **드릴다운 화면(선박 상세 · 실시간 CII)은 대상이 아니다.** 그 화면의 제목은
 * 선박 이름이며, 「선박 상세」라는 고정 이름보다 그쪽이 사용자가 찾는 정보다.
 * 사이드바에 없는 화면이라 이름이 갈릴 일도 없다.
 */
interface PageHeaderProps {
  screen: ScreenId
  /** 부제·기준 시각 등 제목 아래에 붙는 것. 화면마다 다르므로 여기서 정하지 않는다. */
  children?: ReactNode
}

export function PageHeader({ screen, children }: PageHeaderProps) {
  const meta = SCREEN_BY_ID[screen]

  return (
    <header className="page-head">
      <h1 className="page-head__title">
        {meta.label}
        {/* `§14` — 한국어 라벨 + 영문 약어 병기. 영문은 보조라 크기·굵기를 낮춘다. */}
        <span className="page-head__title-en" lang="en">
          {meta.labelEn}
        </span>
      </h1>
      {children}
    </header>
  )
}
