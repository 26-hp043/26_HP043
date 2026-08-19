/**
 * 화면 메타 정의 — `UIFLOW.md` v2.0 §1·§2에서 옮겼다.
 *
 * **프론트엔드 화면 구조의 기준 문서는 `UIFLOW.md`다.** UIFLOW 헤더가 후속 문서로
 * `프론트엔드 구현 (#133 · #136)`을 지정하고 있고, 화면 흐름·진입 조건의 소유자가
 * 디자인 담당이기 때문이다. 시각 표현은 `DESIGN_SYSTEM.md`가 소유한다(UIFLOW 헤더).
 *
 * **UIFLOW v2.0(#344) — 선대·선박·항차 3계층.** `PRD v4.0`(#343)이 같은 구조를
 * 확정했으므로 종전의 PRD ↔ UIFLOW 병렬 정의 불일치는 해소됐다. 주요 변화:
 *
 * - 종전 `1-3 메인보드`와 `2-4 선대 모니터링`이 **하나의 대시보드 화면**으로
 *   통합됐다(`MAINBOARD`, uiflowRef `1-3 · 2-4`). `FLEET_MONITORING` 화면은 폐지.
 * - 신설 계층 화면 `2-8 선박 상세`(`VESSEL_DETAIL`) · `2-9 실시간 CII`(`REALTIME_CII`) —
 *   드릴다운 라우트며 사이드바 밖이다.
 * - `2-5 보고서`는 MVP로 승격됐다(#344). 화면 구현은 후속 이슈가 채운다.
 *
 * `UIFLOW §0`(인증) 화면(LOGIN · LOGIN_FAILURE)은 #278에서 추가됐다 — 사이드바
 * 밖(온보딩 흐름)이므로 OFF_NAV 로 둔다.
 *
 * `width`는 `DESIGN_SYSTEM.md` §7.1 폭 정책이다.
 *   - `wide`: 대시보드·차트·비교 화면 → full-bleed(max 1920), 좌우 패딩 32
 *   - `form`: 폼·설정·상세 조회 → max 1440, 좌우 패딩 24
 */

import { matchPath } from 'react-router'

export type ScreenWidth = 'wide' | 'form'

export interface ScreenMeta {
  /** 라우트 경로. 계층 드릴다운 화면은 `:vesselId` 같은 경로 파라미터를 포함한다. */
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
  /**
   * 이 화면을 채우는 구현이 지금 존재하는가.
   *
   * `false`면 사이드바에 **비활성 상태로 노출**한다 — 숨기지 않는다
   * (`DESIGN_SYSTEM §7.2`, 2026-08-04 디자인 회신).
   * 항목을 숨기면 사용자가 제품 범위를 좁게 인식하고, 나중에 항목이 늘어날 때
   * 네비게이션이 통째로 달라 보인다.
   *
   * **현행 기준** — 종전 8/8 데모 기준에서, 방향 전환(#343·#344) 뒤의
   * MVP 범위 + 구현 완료 여부로 판정한다. MVP 승격 화면이라도 라우트가
   * 준비 중 표시(ComingSoon)라면 `false`다.
   *
   * ## 「실 데이터로 도는가」를 뜻한다 (#442)
   *
   * 종전에는 사실상 **「화면 파일이 있는가」**로 판정하고 있었다. 그래서 기능③이
   * 고정값 목업(`#157`)인 상태로 `true`였고, 엔진(`#63`)·API(`#64`)가 들어온 뒤에도
   * **목록상 빠진 게 없어 보여** 연결이 안 된 사실이 드러나지 않았다.
   *
   * 기준을 고친다 — **`VITE_USE_API=true`에서 실 API로 도는 화면만 `true`다.**
   * demo provider만 있는 화면은 파일이 있어도 `false`다.
   */
  demoScope: boolean
}

/**
 * 화면 ID. 잘못된 문자열이 타입 단계에서 걸리도록 유니온으로 고정한다.
 * UIFLOW는 `SCR-00x` 같은 ID를 부여하지 않으므로 의미 기반 키를 쓰고
 * 출처는 `uiflowRef`로 남긴다.
 */
export type ScreenId =
  | 'LOGIN'
  | 'LOGIN_FAILURE'
  | 'SIGNUP'
  | 'PASSWORD_RESET'
  | 'VERIFY_EMAIL'
  | 'MAINBOARD'
  | 'VESSEL_REGISTRATION'
  | 'VESSEL_MANAGEMENT'
  | 'VESSEL_DETAIL'
  | 'REALTIME_CII'
  | 'CII_FORECAST'
  | 'ROUTE_COMPARISON'
  | 'ANNUAL_GRADE'
  | 'REPORTS'
  | 'SETTINGS'

export const SCREEN_BY_ID = {
  LOGIN: {
    path: '/login',
    label: '로그인',
    labelEn: 'Login',
    uiflowRef: '0',
    purpose: '구글 OIDC 로그인 진입 — 서비스 소개·면책 문구·단일 버튼',
    width: 'form',
    demoScope: false, // 인증 화면 — 데모 데이터와 무관, 사이드바 밖
  },
  LOGIN_FAILURE: {
    path: '/login/failure',
    label: '로그인 실패',
    labelEn: 'Login Failure',
    // v2.1에서 0-1 → 0-2로 되돌렸다 — 회원가입이 복원되며 번호가 제자리를 찾았다.
    uiflowRef: '0-2',
    purpose: '로그인 실패 사유 안내 및 재시도',
    width: 'form',
    demoScope: false,
  },
  SIGNUP: {
    path: '/signup',
    label: '회원가입',
    labelEn: 'Sign Up',
    uiflowRef: '0-1',
    purpose: '이메일·비밀번호로 계정 생성',
    width: 'form',
    demoScope: false, // 인증 화면 — 사이드바 밖
  },
  PASSWORD_RESET: {
    path: '/password-reset',
    label: '비밀번호 찾기',
    labelEn: 'Password Reset',
    uiflowRef: '0-3',
    purpose: '재설정 메일 요청 및 새 비밀번호 설정',
    width: 'form',
    demoScope: false,
  },
  VERIFY_EMAIL: {
    path: '/verify-email',
    label: '이메일 인증',
    labelEn: 'Verify Email',
    uiflowRef: '0-4',
    purpose: '가입 확인 메일 링크의 토큰 검증',
    width: 'form',
    demoScope: false,
  },
  MAINBOARD: {
    path: '/dashboard',
    label: '대시보드',
    labelEn: 'Dashboard',
    uiflowRef: '1-3 · 2-4',
    purpose: '보유 선박 전체 현황 조망 · 위험 선박 경고 — 선대 계층 중심 화면',
    width: 'wide',
    demoScope: true,   // 기본 진입 경로. 실제 데이터 그리드는 #351이 채운다
  },
  VESSEL_REGISTRATION: {
    path: '/vessel-registration',
    label: '선박 등록',
    labelEn: 'Vessel Registration',
    uiflowRef: '1-2',
    purpose: '사용자의 선박 기본 정보 입력 및 시스템 등록',
    width: 'form',
    // 온보딩 흐름 — 사이드바 밖(`OFF_NAV_ORDER`)이라 이 값이 표시에 영향을 주지 않는다.
    //
    // 값은 `false`로 둔다. 등록은 **쓰기**라 데모 모드에서 수행할 수 없고
    // (`providerSelection.ts` — 가짜 성공을 두지 않는다), 그 상태에서는
    // 「실 API로 돈다」고 말할 수 없기 때문이다. **`#527`과 같은 오해가 아니다** —
    // 선박 관리는 조회가 실 API로 돌지만 이 화면은 제출 자체가 막힌다.
    demoScope: false,
  },
  VESSEL_MANAGEMENT: {
    path: '/vessels',
    label: '선박 관리',
    labelEn: 'Vessel Management',
    // UIFLOW §2.2 매핑 표에 SCR-002 행이 없다. 근거는 상위 문서인 `PRD §6.1`
    // (「(계층 밖) 선박 등록」)·`§6.2 SCR-002`이며, UIFLOW 보강은 디자인 담당 소관이다.
    uiflowRef: '1-2',
    purpose: '보유 선박 목록 조회 · 제원 수정 · 삭제 — 등록은 1-2로 이어진다',
    width: 'wide',
    //
    // **실 API로 돈다** — `GET`·`PATCH`·`DELETE /vessels`를 실제로 부른다 (#510).
    //
    // 종전에 `false`였던 것은 **이 플래그의 뜻을 잘못 읽은 것**이다 (#527).
    // 「데모 모드에서 쓰기를 흉내 내지 않는다」는 판단 자체는 맞고 그것은
    // `vessel-management/providerSelection.ts`가 처리한다 — 그러나 `demoScope`가
    // 뜻하는 것은 **「실 API로 도는가」**다(위 필드 주석 · #442).
    //
    // 그 결과 사이드바가 이 화면을 **비활성으로 렌더해 클릭조차 되지 않았다** —
    // 기능은 전부 동작하는데 들어가는 문만 막혀 있었다.
    //
    demoScope: true,
  },
  VESSEL_DETAIL: {
    path: '/vessels/:vesselId',
    label: '선박 상세',
    labelEn: 'Vessel Detail',
    uiflowRef: '2-8',
    purpose: '연도별 CII 이력 · 올해 누적(YTD) 등급 · 현재 위치·운항 상태',
    width: 'wide',
    demoScope: true,  // #356 구현 완료. OFF_NAV라 사이드바 표시에는 영향 없다
  },
  REALTIME_CII: {
    path: '/vessels/:vesselId/voyages/:voyageId',
    label: '실시간 CII',
    labelEn: 'Realtime CII',
    uiflowRef: '2-9',
    purpose: '항해 중 누적값 · 연말 예상 등급 · 정박(정류) 반영',
    width: 'wide',
    demoScope: true,  // #357 구현 완료. OFF_NAV라 사이드바 표시에는 영향 없다
  },
  CII_FORECAST: {
    path: '/voyage-cii',
    label: 'CII 예측',
    labelEn: 'CII Forecast',
    uiflowRef: '2-1',
    purpose: '항해 전 항차 조건으로 CII 추정 — 실시간 산출(2-9)의 계획 단계',
    width: 'form',
    demoScope: true,   // #135 입력 폼 · #136 결과 화면
  },
  ROUTE_COMPARISON: {
    path: '/route-comparison',
    label: '항로 비교',
    labelEn: 'Route Comparison',
    uiflowRef: '2-2',
    purpose: '직항·우회·감속 시나리오의 중립 비교 — 사후 설명·보고 근거',
    width: 'wide',
    demoScope: true,   // #156 기능② 비교 UI
  },
  ANNUAL_GRADE: {
    path: '/annual-grade',
    label: '연간 등급 관리',
    labelEn: 'Annual Grade',
    uiflowRef: '2-3',
    purpose: '선박별 연간 누적 CII 등급 및 목표 달성 현황 모니터링',
    width: 'wide',
    // #442 실 API 연결 완료 — demo provider는 백엔드 없이 화면만 볼 때만 쓴다.
    demoScope: true,
  },
  REPORTS: {
    path: '/reports',
    label: '보고서',
    labelEn: 'Reports',
    uiflowRef: '2-5',
    purpose: '항차 완료 리포트 · 연간 실적 리포트 생성·내보내기 (PDF · CSV)',
    width: 'form',
    demoScope: true,  // #362 구현 완료 (API는 #361)
  },
  SETTINGS: {
    path: '/settings',
    label: '설정',
    labelEn: 'Settings',
    uiflowRef: '2-6',
    purpose: '사용자 및 시스템 환경 설정',
    width: 'form',
    demoScope: false,  // #359(어드민 범위 확정) 결정 대기 — UIFLOW v2.0 판정 보류
  },
} as const satisfies Record<ScreenId, ScreenMeta>

/**
 * 사이드바 노출 순서 — UIFLOW v2.0 §2의 3계층 구조도(선대 → 선박 → 항차 →
 * 산출물 → 계층 밖)를 따른다. 드릴다운 화면(선박 상세·실시간 CII)은 사이드바가
 * 아니라 상위 계층 화면에서 진입하므로 OFF_NAV_ORDER에 둔다.
 *
 * **순서를 객체 선언 순서에서 파생하지 않는다.** 순서는 UIFLOW가 정한 의미 있는
 * 정보이므로 명시적으로 적는다.
 */
export const NAV_ORDER = [
  'MAINBOARD',       // [선대] 2-4 대시보드
  'ANNUAL_GRADE',    // [선박] 2-3 연간 등급 관리
  'CII_FORECAST',    // [항차] 2-1 CII 예측
  'ROUTE_COMPARISON',// [항차] 2-2 항로 비교
  'REPORTS',         // [산출물] 2-5 보고서
  'VESSEL_MANAGEMENT',// [계층 밖] SCR-002 선박 관리 (PRD §6.1)
  'SETTINGS',        // [계층 밖] 2-6 설정
] as const satisfies readonly ScreenId[]

/**
 * 사이드바에 노출되지 않는 화면.
 * - `UIFLOW §1-2` 선박 등록 — 온보딩 흐름(`1-1 → 1-2 → 1-3`)이며 기능 메뉴가 아니다.
 * - `UIFLOW §2-8` 선박 상세 · `§2-9` 실시간 CII — 상위 계층에서 드릴다운으로만
 *   진입한다(대시보드 카드 선택 → 선박 상세 → 진행 중 항차 선택).
 */
export const OFF_NAV_ORDER = [
  'LOGIN',
  'LOGIN_FAILURE',
  'SIGNUP',
  'PASSWORD_RESET',
  'VERIFY_EMAIL',
  'VESSEL_REGISTRATION',
  'VESSEL_DETAIL',
  'REALTIME_CII',
] as const satisfies readonly ScreenId[]

/** 라우팅 대상 전체. */
export const ALL_SCREEN_IDS = [...NAV_ORDER, ...OFF_NAV_ORDER] as const

/** 사이드바 렌더링용 배열. */
export const NAV_SCREENS = NAV_ORDER.map((id) => ({ id, ...SCREEN_BY_ID[id] }))

/**
 * 기본 진입 경로 — 대시보드(선대 계층).
 * UIFLOW v2.0 §2가 *"1-3 대시보드가 기본 진입 경로"* 로 확정했다. 종전의
 * 기능① 기본 진입(#133)은 폐지 — 계층 구조에서 항차 계층 화면이 먼저 열리면
 * 조망 흐름(선대 → 선박 → 항차)이 거꾸로 시작된다.
 */
export const DEFAULT_PATH = SCREEN_BY_ID.MAINBOARD.path

/**
 * 경로로 화면 메타를 찾는다. 라우트에 없는 경로면 `undefined`.
 *
 * 계층 드릴다운 화면은 경로 파라미터(`/vessels/:vesselId`)를 쓰므로 완전 일치에
 * 더해 react-router의 패턴 매칭(`matchPath`)으로 비교한다.
 */
export function findScreenByPath(path: string): ScreenMeta | undefined {
  for (const id of ALL_SCREEN_IDS) {
    const meta = SCREEN_BY_ID[id]
    if (meta.path === path || matchPath(meta.path, path) !== null) return meta
  }
  return undefined
}
