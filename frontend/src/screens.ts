/**
 * 화면 메타 정의 — `UIFLOW.md` §1·§2에서 옮겼다.
 *
 * **프론트엔드 화면 구조의 기준 문서는 `UIFLOW.md`다.** UIFLOW 헤더가 후속 문서로
 * `프론트엔드 구현 (#133 · #136)`을 지정하고 있고, 화면 흐름·진입 조건의 소유자가
 * 디자인 담당이기 때문이다. 시각 표현은 `DESIGN_SYSTEM.md`가 소유한다(UIFLOW 헤더).
 *
 * ⚠️ `PRD.md` §6.1·§6.2는 아직 7개 화면(SCR-001~007)을 병렬로 정의하고 있어
 * 이 파일과 어긋난다. PRD를 UIFLOW 기준으로 정정하는 것은 별도 이슈에서 처리한다.
 *
 * 범위 밖: `UIFLOW §0`(인증·초기 진입) — #133이 인증을 명시적으로 제외한다.
 *
 * `width`는 `DESIGN_SYSTEM.md` §7.1 폭 정책이다.
 *   - `wide`: 대시보드·차트·비교 화면 → full-bleed(max 1920), 좌우 패딩 32
 *   - `form`: 폼·설정·상세 조회 → max 1440, 좌우 패딩 24
 */

export type ScreenWidth = 'wide' | 'form'

export interface ScreenMeta {
  /** 라우트 경로 */
  path: string
  /** 한국어 라벨 (DESIGN_SYSTEM §14 — 한국어 라벨 + 영문 약어 병기) */
  label: string
  /** 사이드바 보조 표기용 영문 */
  labelEn: string
  /** 출처가 되는 UIFLOW 절 번호 */
  uiflowRef: string
  /** UIFLOW가 기술한 핵심 기능 */
  purpose: string
  width: ScreenWidth
}

/**
 * 화면 ID. 잘못된 문자열이 타입 단계에서 걸리도록 유니온으로 고정한다.
 * UIFLOW는 `SCR-00x` 같은 ID를 부여하지 않으므로 의미 기반 키를 쓰고
 * 출처는 `uiflowRef`로 남긴다.
 */
export type ScreenId =
  | 'MAINBOARD'
  | 'VESSEL_REGISTRATION'
  | 'CII_FORECAST'
  | 'ROUTE_COMPARISON'
  | 'ANNUAL_GRADE'
  | 'FLEET_MONITORING'
  | 'REPORTS'
  | 'SETTINGS'

export const SCREEN_BY_ID = {
  MAINBOARD: {
    path: '/dashboard',
    label: '대시보드',
    labelEn: 'Mainboard',
    uiflowRef: '1-3',
    purpose: '실제 데이터 기반 대시보드 활성화 및 메인 내비게이션 노출',
    width: 'wide',
  },
  VESSEL_REGISTRATION: {
    path: '/vessel-registration',
    label: '선박 등록',
    labelEn: 'Vessel Registration',
    uiflowRef: '1-2',
    purpose: '사용자의 선박 기본 정보 입력 및 시스템 등록',
    width: 'form',
  },
  CII_FORECAST: {
    path: '/voyage-cii',
    label: 'CII 예측',
    labelEn: 'CII Forecast',
    uiflowRef: '2-1',
    purpose: '선박의 탄소집약도지수(CII) 추정값 계산 및 시각화',
    width: 'form',
  },
  ROUTE_COMPARISON: {
    path: '/route-comparison',
    label: '항로 비교',
    labelEn: 'Route Comparison',
    uiflowRef: '2-2',
    purpose: '항로별 예상 소모량 및 탄소 배출량 비교',
    width: 'wide',
  },
  ANNUAL_GRADE: {
    path: '/annual-grade',
    label: '연간 등급 관리',
    labelEn: 'Annual Grade',
    uiflowRef: '2-3',
    purpose: '선박별 연간 누적 CII 등급 및 목표 달성 현황 모니터링',
    width: 'wide',
  },
  FLEET_MONITORING: {
    path: '/fleet',
    label: '선대 모니터링',
    labelEn: 'Fleet Monitoring',
    uiflowRef: '2-4',
    purpose: '관리 대상 선박 전체의 상태 통합 관제',
    width: 'wide',
  },
  REPORTS: {
    path: '/reports',
    label: '보고서',
    labelEn: 'Reports',
    uiflowRef: '2-5',
    purpose: '운항 데이터 기반 보고 문서 생성 및 내보내기',
    width: 'form',
  },
  SETTINGS: {
    path: '/settings',
    label: '설정',
    labelEn: 'Settings',
    uiflowRef: '2-6',
    purpose: '사용자 및 시스템 환경 설정',
    width: 'form',
  },
} as const satisfies Record<ScreenId, ScreenMeta>

/**
 * 사이드바 노출 순서 — `UIFLOW §2`의 *"메인보드 진입 후 좌측 사이드바로 아래
 * 6가지 핵심 기능 화면으로 이동"* 구조를 따른다. 메인보드(1-3)를 맨 위에 두고
 * 기능 6개를 2-1~2-6 순서로 잇는다.
 *
 * **순서를 객체 선언 순서에서 파생하지 않는다.** 순서는 UIFLOW가 정한 의미 있는
 * 정보이므로 명시적으로 적는다.
 */
export const NAV_ORDER = [
  'MAINBOARD',
  'CII_FORECAST',
  'ROUTE_COMPARISON',
  'ANNUAL_GRADE',
  'FLEET_MONITORING',
  'REPORTS',
  'SETTINGS',
] as const satisfies readonly ScreenId[]

/**
 * 사이드바에 노출되지 않는 화면. `UIFLOW §1-2` 선박 등록은 온보딩 흐름
 * (`1-1 정보 미등록 → 1-2 선박 등록 → 1-3 메인보드`)에 속하며 기능 메뉴가 아니다.
 */
export const OFF_NAV_ORDER = ['VESSEL_REGISTRATION'] as const satisfies readonly ScreenId[]

/** 라우팅 대상 전체. */
export const ALL_SCREEN_IDS = [...NAV_ORDER, ...OFF_NAV_ORDER] as const

/** 사이드바 렌더링용 배열. */
export const NAV_SCREENS = NAV_ORDER.map((id) => ({ id, ...SCREEN_BY_ID[id] }))

/**
 * 기본 진입 경로 — 기능①(CII 예측) 화면.
 * `UIFLOW`는 메인보드 진입 후 이동을 기술하나, #133이 *"기능① 화면을 기본 진입
 * 경로로 설정"* 을 완료 기준으로 두고 있고 8/8 데모의 주 경로도 이 화면이다.
 */
export const DEFAULT_PATH = SCREEN_BY_ID.CII_FORECAST.path

/** 경로로 화면 메타를 찾는다. 라우트에 없는 경로면 `undefined`. */
export function findScreenByPath(path: string): ScreenMeta | undefined {
  for (const id of ALL_SCREEN_IDS) {
    if (SCREEN_BY_ID[id].path === path) return SCREEN_BY_ID[id]
  }
  return undefined
}
