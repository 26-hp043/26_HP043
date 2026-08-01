/**
 * 화면 메타 정의 — PRD.md §6.1(네비게이션) · §6.2(화면 목록)에서 그대로 옮겼다.
 *
 * 화면 ID·화면명·순서는 PRD가 정본이다. UIFLOW.md §2는 6개 화면을 다른 이름으로
 * 묶고 있으나, AGENTS.md §3 문서 우선순위에 따라 상위 문서인 PRD를 따른다.
 *
 * `width`는 DESIGN_SYSTEM.md §7.1 폭 정책이다.
 *   - `wide`: 대시보드·차트·시나리오 비교 → full-bleed(max 1920), 좌우 패딩 32
 *   - `form`: 폼·설정·상세 조회 → max 1440, 좌우 패딩 24
 */

export type ScreenWidth = 'wide' | 'form'

export interface ScreenMeta {
  /** PRD §6.2 Screen ID */
  id: string
  /** 라우트 경로 */
  path: string
  /** 한국어 라벨 (DESIGN_SYSTEM §14 — 한국어 라벨 + 영문 약어 병기) */
  label: string
  /** PRD §6.1 네비게이션의 영문 명칭 */
  labelEn: string
  /** PRD §6.2 목적 */
  purpose: string
  width: ScreenWidth
}

/** PRD §6.1 네비게이션 순서 그대로. */
export const SCREENS: readonly ScreenMeta[] = [
  {
    id: 'SCR-001',
    path: '/dashboard',
    label: '대시보드',
    labelEn: 'Dashboard',
    purpose: '선택 선박의 핵심 상태 요약',
    width: 'wide',
  },
  {
    id: 'SCR-002',
    path: '/vessels',
    label: '선박 관리',
    labelEn: 'Vessels',
    purpose: '선박 등록·수정·샘플 선택',
    width: 'form',
  },
  {
    id: 'SCR-003',
    path: '/voyage-cii',
    label: '항차 CII 추정',
    labelEn: 'Voyage CII Estimator',
    purpose: '운항 전 항차 CII 추정',
    width: 'form',
  },
  {
    id: 'SCR-004',
    path: '/scenarios',
    label: '시나리오 비교',
    labelEn: 'Scenario Comparison',
    purpose: '직항·우회·감속 비교',
    width: 'wide',
  },
  {
    id: 'SCR-005',
    path: '/annual-simulation',
    label: '연간 시뮬레이션',
    labelEn: 'Annual CII Simulator',
    purpose: '연말 등급 예측·목표 달성 확률 확인',
    width: 'wide',
  },
  {
    id: 'SCR-006',
    path: '/parameters',
    label: '파라미터 관리',
    labelEn: 'Parameter Management',
    purpose: '규정·연료·모델 파라미터 조회·수정',
    width: 'form',
  },
  {
    id: 'SCR-007',
    path: '/data-io',
    label: '데이터 입출력',
    labelEn: 'Data Import/Export',
    purpose: '샘플/CSV 데이터 입력·출력',
    width: 'form',
  },
]

/**
 * 기본 진입 경로. 기능①(항차 CII 추정) 화면이다.
 * 8/8 데모의 주 경로이므로 `/`는 이 경로로 보낸다(#133).
 */
export const DEFAULT_PATH = '/voyage-cii'

export function findScreen(path: string): ScreenMeta | undefined {
  return SCREENS.find((screen) => screen.path === path)
}
