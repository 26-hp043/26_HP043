/**
 * 한국어 사전 — i18n 키의 정본 (#1215).
 *
 * 키는 `kebab` 점 표기(영역.항목)로 평면하게 둔다. 중첩 객체는 키 접근이
 * 타입 추론과 함께 흐트러지고, 평면 키는 `Object.keys` 대조만으로 완전성을 본다.
 *
 * **정본 문구는 여기에 두지 않는다** (`AGENTS §4.6`). 면책(`PRD §6.3`) · 경고
 * 배너 · 규제 용어 · 경고 메시지(`API_SPEC §1.6` 체인) · 상태 문구(`PRD §6.4` —
 * `errorCopy.ts`)는 어느 언어에서도 한국어 원문 그대로 렌더된다. 번역하려면
 * 정본 개정이 먼저다.
 */
export const ko = {
  /** 상단바 — 전역 선박·항차 컨텍스트 (#512) */
  'shell.vessel': '선박',
  'shell.voyage': '항차',
  'shell.vessel.loading': '선박 목록을 불러오는 중…',
  'shell.vessel.failed': '선박 목록을 불러오지 못했습니다',
  'shell.vessel.none': '선박 없음',
  'shell.vessel.unselected': '선박 선택 안 함',
  'shell.voyage.selectVesselFirst': '선박 먼저 선택',
  'shell.voyage.loading': '불러오는 중…',
  'shell.voyage.failed': '항차를 불러오지 못했습니다',
  'shell.voyage.none': '항차 없음',
  'shell.voyage.unselected': '항차 선택 안 함',

  /** 상단바 — 알림 자리(체계 미정의 · `DESIGN_SYSTEM §16` 항목 10) */
  'shell.notification.aria': '알림 (준비 중)',
  'shell.notification.title': '알림 — 준비 중',

  /** 사이드바 — 미구현·사무직 전용 항목에 붙는 꼬리표 */
  'shell.navTag': '준비 중',
  'shell.navTagOffice': '사무직 전용',

  /** 상단바 — 로그아웃 (#278) */
  'shell.logout': '로그아웃',

  /** 계정 메뉴 (#717) */
  'account.noDisplayName': '표시 이름 없음',
  'account.verified': '이메일 인증 완료',
  'account.unverified': '이메일 인증 대기',
  'account.theme': '화면 테마',
  'account.language': '언어',
  'account.settings': '설정',
  'account.settingsSub': '계정 정보 · 비밀번호',

  /** 언어 선택 칸(#1215) — 안내는 현재 언어로 읽힌다 */
  'i18n.groupLabel': '언어',
  'i18n.korean': '한국어',
  'i18n.english': '영어',
} as const

/** 사전 키 — `en.ts`가 이 집합을 전부 갖는지 타입이 강제한다. */
export type MessageKey = keyof typeof ko
