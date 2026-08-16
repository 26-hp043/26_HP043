import type { ReactElement } from 'react'
import type { ScreenId } from '../screens'

/**
 * 사이드바 아이콘.
 *
 * ## 인라인 SVG를 쓰는 이유
 *
 * 아이콘 폰트·외부 스프라이트는 네트워크에 의존한다. 오프라인 시연에서 조용히
 * 네모 상자로 떨어지므로 컴포넌트로 들고 있는다. 획 두께는 디자이너 토큰
 * `icon.stroke`(1.5px)를 CSS에서 먹인다 — 여기서는 형태만 정의한다.
 *
 * ## 아이콘만으로 항목을 구분하지 않는다
 *
 * 사이드바는 아이콘 + 한글 레이블 + 영문 레이블 셋을 함께 보여 준다. 접힘 상태
 * (`§7.2`, MVP 범위 밖)가 붙기 전까지 아이콘은 **보조 채널**이다.
 */

type IconProps = { className?: string }

/** 대시보드 — 4분할 타일. */
function DashboardIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </svg>
  )
}

/** CII 예측 — 상승 추세선. */
function ForecastIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3.5 16.5 9 10.5l4 4 7.5-8" />
      <path d="M20.5 6.5h-4.2M20.5 6.5v4.2" />
    </svg>
  )
}

/** 항로 비교 — 갈라지는 두 경로. */
function CompareIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 19c5 0 5-7 10-7h6" />
      <path d="M4 5c5 0 5 7 10 7" />
      <path d="M17.5 9 20.5 12l-3 3" />
    </svg>
  )
}

/** 연간 등급 관리 — 달력. */
function AnnualIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
      <path d="M3.5 9.5h17M8 3.5v3M16 3.5v3" />
    </svg>
  )
}

/** 선박 등록 — 선체 실루엣. */
function VesselIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3 16.5c1.6 0 1.6 1.6 3.2 1.6s1.6-1.6 3.2-1.6 1.6 1.6 3.2 1.6 1.6-1.6 3.2-1.6 1.6 1.6 3.2 1.6" />
      <path d="M5 13.5 6 9h12l-1.6 4.5z" />
      <path d="M12 9V5.5" />
    </svg>
  )
}

/** 선박 상세 / 실시간 — 위치 핀. */
function LocationIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 21s6.5-6.1 6.5-10.4A6.5 6.5 0 0 0 5.5 10.6C5.5 14.9 12 21 12 21z" />
      <circle cx="12" cy="10.4" r="2.4" />
    </svg>
  )
}

/** 보고서 — 문서. */
function ReportIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M6 3.5h8l4.5 4.5v12.5H6z" />
      <path d="M14 3.5V8h4.5M9 12.5h6M9 16h6" />
    </svg>
  )
}

/** 설정 — 톱니. */
function SettingsIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.8v2.4M12 18.8v2.4M21.2 12h-2.4M5.2 12H2.8M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2 5.5 5.5" />
    </svg>
  )
}

const ICONS: Partial<Record<ScreenId, (p: IconProps) => ReactElement>> = {
  MAINBOARD: DashboardIcon,
  CII_FORECAST: ForecastIcon,
  ROUTE_COMPARISON: CompareIcon,
  ANNUAL_GRADE: AnnualIcon,
  VESSEL_REGISTRATION: VesselIcon,
  VESSEL_DETAIL: LocationIcon,
  REALTIME_CII: LocationIcon,
  REPORTS: ReportIcon,
  SETTINGS: SettingsIcon,
}

export function NavIcon({ id }: { id: ScreenId }) {
  const Icon = ICONS[id]
  if (!Icon) return <span className="app-shell__nav-icon" aria-hidden="true" />
  return <Icon className="app-shell__nav-icon" />
}

/** 상단바 — 선박 컨텍스트. */
export function ShipGlyph() {
  return <VesselIcon className="app-shell__util-icon" />
}

/** 상단바 — 항차 컨텍스트. */
export function VoyageGlyph() {
  return <LocationIcon className="app-shell__util-icon" />
}

/** 상단바 — 알림. */
export function BellGlyph() {
  return (
    <svg className="app-shell__util-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M18 16.5V11a6 6 0 1 0-12 0v5.5L4.5 18.5h15z" />
      <path d="M10 21h4" />
    </svg>
  )
}
