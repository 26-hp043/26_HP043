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
 * 확장(240) 상태의 사이드바는 아이콘과 레이블을 함께 보여 주고, 거기서 아이콘은
 * **보조 채널**이다. 창 폭 `1100px` 이하의 축소(64) 상태에서는 아이콘만 보인다
 * (`DESIGN_SYSTEM §7.2` · `#1885`) — 그때도 레이블은 지우지 않고 시각적으로만 감춰
 * (`AppShell.css`) 낭독되는 이름은 남는다. 그래서 항목마다 서로 다른 아이콘을 둔다.
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

/** 함대 감축 계획 — 내려가는 추세와 기준선. */
function ReductionIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3.5 7.5 9 13l4-4 7.5 7.5" />
      <path d="M20.5 16.5v-4.2M20.5 16.5h-4.2M3.5 20.5h17" />
    </svg>
  )
}

/** 데이터 점검 — 목록과 확인 표시. */
function CheckListIcon(props: IconProps) {
  return (
    <svg {...props} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 6.5 5.5 8 8 5.5M4 12.5 5.5 14 8 11.5M4 18.5 5.5 20 8 17.5" />
      <path d="M11 7h9.5M11 13h9.5M11 19h9.5" />
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
  /*
   * 사이드바에 있는 것은 **선박 관리**인데 아이콘은 선박 등록에 붙어 있었다.
   * 선박 등록은 `OFF_NAV_ORDER`라 `NavIcon`이 불릴 일이 없으므로, **아이콘이
   * 있는 화면은 안 그려지고 그려지는 화면은 아이콘이 없는** 상태였다.
   * 등록 항목은 남겨 둔다 — 나중에 사이드바로 올라오면 그대로 쓴다.
   */
  VESSEL_MANAGEMENT: VesselIcon,
  VESSEL_REGISTRATION: VesselIcon,
  VESSEL_DETAIL: LocationIcon,
  REALTIME_CII: LocationIcon,
  FLEET_REDUCTION: ReductionIcon,
  DATA_QUALITY: CheckListIcon,
  REPORTS: ReportIcon,
  SETTINGS: SettingsIcon,
}

/**
 * 잠긴 항목의 자물쇠 배지 — **축소(64) 상태에서만** 보인다 (`#1978`).
 *
 * 펼친 상태에서는 「준비 중」·「사무직 전용」 태그가 이유까지 말하므로 배지를 두지 않는다.
 * 축소되면 그 태그가 시각적으로 감춰져(`#1885`) 잠긴 항목을 가르는 **화면 채널이 색
 * 하나**가 되는데, 그 색차가 활성 ↔ 비활성 `1.87:1`로 비텍스트 기준(3:1)에도 못 미친다.
 * 배지는 색 말고 **형태** 채널 하나를 더한다 (`DESIGN_SYSTEM §0.2` 제약 3 · `§14`).
 *
 * **「준비 중」과 「사무직 전용」에 다른 글리프를 주지 않는다** — 64px 폭에서 11px 글리프
 * 둘은 서로 구분되지 않는다. 배지는 「지금 누를 수 없음」 하나만 말하고, 이유는 낭독
 * (감춰진 태그)과 펼친 상태가 맡는다. 그래서 `aria-hidden`이다 — 읽히면 이름 뒤에
 * 뜻 없는 소리가 하나 더 붙는다.
 */
export function LockBadge() {
  return (
    <svg
      className="app-shell__nav-lock"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </svg>
  )
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
