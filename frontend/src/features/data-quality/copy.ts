import type { PublicRecordField, Severity } from './types'

/**
 * 데이터 점검 화면 문구 (`UIFLOW 2-11` · `PRD §17.4` · #513).
 *
 * 모양·문구는 **2026-09-22에 현행대로 확정**됐다(`#1052` ⑹ · `UIFLOW 2-11`). 심각도 명칭·색은
 * `DESIGN_SYSTEM §2.3.1` 🔒 그대로다.
 */
export const DATA_QUALITY_COPY = {
  lead: '연간 CII 계산에 실측이 아닌 값이 어디에 들어갔는지 선대 단위로 봅니다.',
  yearLabel: '규제연도',
  loading: '데이터 점검 결과를 불러오는 중입니다…',
  loadSubject: '데이터 점검 결과',
  noVessels: '등록된 선박이 없습니다.',
  /*
   * #1923 — 이 화면에서 값이 바뀌는 길은 「이 값으로 채우기」 하나다(`UIFLOW 2-11`). 「읽기
   * 전용입니다」만 적으면 옆의 버튼과 말이 어긋난다.
   */
  readOnlyNote:
    '「공적 기록과 다름」의 「이 값으로 채우기」 말고는 값을 바꾸지 않습니다. 그 밖의 값은 선박 상세의 항차에서 실적을 입력하거나 보정합니다.',

  summaryTitle: '요약',
  completenessLabel: '데이터 완결성',
  /*
   * ⚠️ **무엇의 비율인지 말한다.** 「완결성 94%」만 적으면 항차 수의 비율로 읽힌다 —
   * 실제로는 CO₂ 비율이라 큰 항차 하나가 작은 항차 여럿보다 무겁다(`PRD §17.4.3`).
   */
  completenessHint: '누적 CO₂ 중 실측으로 계산된 비율',
  completenessNone: '계산할 배출 없음',
  /* 판정 못 한 항차는 0건과 섞지 않는다 (`PRD §17.4.1`). */
  unjudgedHint: (n: number) => `판정하지 못한 항차 ${n}건 — 선박 제원 또는 운항 시각이 없습니다`,

  listTitle: '점검 항목',
  countSuffix: '건',
  /*
   * ⚠️ **0건 심각도를 지우는 것이 아니다** (`#513` · `#1766`). 표를 하나로 합치면서 그룹이
   * 없어졌고, 「확인했고 0건이다」는 **요약 띠의 칸**이 계속 말한다. 여기 문구는 다섯 축이
   * 전부 0건일 때 — 표 자리에 아무것도 없으면 「불러오지 못했다」로 읽힌다.
   */
  noIssues: '이 연도에 점검할 항목이 없습니다.',
  legendTitle: '심각도가 뜻하는 것',
  colSeverity: '심각도',
  colVessel: '선박',
  colVoyage: '항차',
  colProblem: '문제',
  colImpact: 'CII 영향',
  colGo: '이동',
  vesselLevel: '선박 전체',
  goToVessel: '선박 상세',
  goToVoyage: '이 항차로',
  /*
   * ⚠️ **부호의 뜻을 적는다.** `+0.12`만 보면 좋아졌다는 뜻인지 나빠졌다는 뜻인지 알 수
   * 없다 — CII는 낮을수록 좋다.
   */
  impactCaption:
    'CII 영향은 이 항차를 빼고 계산한 누적 CII와의 차이입니다. +는 이 항차가 누적 CII를 높이고(나쁘게) 있다는 뜻입니다.',

  vesselsTitle: '선박별 데이터 완결성',
  colRating: '누적 등급',
  colVoyages: '실적 항차',
  colCompleteness: '완결성',
  noActualVoyages: '올해 실적 항차 없음',

  /*
   * 공적 기록 대조 한 줄 (#1197). 시각·항만청 이름은 부르는 쪽에서 이미 표시 문자열로
   * 만들어 넘긴다 — 이 파일은 `formatTimestamp` 같은 표시 포맷터를 갖지 않는다(다른 화면
   * 표시값도 `DataQuality.tsx`가 포맷하고 `copy.ts`는 틀만 쥔다).
   */
  publicRecordMismatch: (
    fieldLabel: string,
    entered: string,
    recorded: string,
    authorityName: string,
    hours: number,
    minutes: number,
  ) => `${fieldLabel} 입력 ${entered} · 공적 기록 ${recorded} (${authorityName}) · ${hours}시간 ${minutes}분 차이`,
  /** 출처 표기 — `DESIGN_SYSTEM` 확정 대기 중이라 개발 임시안이다(#1197). */
  publicRecordSourceNote: (sourceText: string, fetchedAt: string) => `출처: ${sourceText} · ${fetchedAt} 기준`,

  /*
   * 「이 값으로 채우기」 (#1923 · `PRD §17.4.4`). 버튼 모양·다이얼로그 표현은 `DESIGN_SYSTEM
   * §2.3.1` 🔒 절이라 **개발 임시안**이다 — 디자인 담당 확인 전까지.
   */
  fillAction: '이 값으로 채우기',
  fillBusy: '채우는 중…',
  /** 확정 항차 재확인 줄 — 무엇이 달라지는지 적고 실행 버튼은 동사로 끝난다(`VoyagePanel` 확인 줄과 같은 규칙) */
  fillConfirmedCaution:
    '실적이 확정된 항차입니다. 확정을 되돌리고 이 칸만 공적 기록 값으로 채웁니다. 항차는 완료 상태로 남고, 다시 확정은 선박 상세에서 합니다.',
  fillConfirmedAction: '확정을 되돌리고 채우기',
  fillKeep: '그만두기',
  fillFailed: '공적 기록으로 채우지 못했습니다.',
  fillDone: (fieldLabel: string, voyageNo: string) => `${voyageNo} 항차의 ${fieldLabel}을 공적 기록 값으로 채웠습니다.`,
  fillDoneReverted: (fieldLabel: string, voyageNo: string) =>
    `${voyageNo} 항차의 확정을 되돌리고 ${fieldLabel}을 공적 기록 값으로 채웠습니다. 다시 확정은 선박 상세에서 합니다.`,
} as const

export const SEVERITY_TITLE: Record<Severity, string> = {
  SUBSTITUTED: '대체 계산',
  UNAVAILABLE: '계산 불가',
  ANOMALY: '이상치',
  UNCONFIRMED: '실적 미입력',
  PUBLIC_RECORD: '공적 기록과 다름',
}

/** 그룹 헤더 아래 한 줄 — `DESIGN_SYSTEM §2.3.1` 「의미」 열. */
export const SEVERITY_MEANING: Record<Severity, string> = {
  SUBSTITUTED: '실적 대신 계획값으로 계산됐습니다.',
  UNAVAILABLE: '대체할 계획값조차 없어 계산에 들어가지 못했습니다.',
  ANOMALY: '계산됐으나 값을 믿기 어렵습니다. 계산에서 빼지는 않습니다.',
  UNCONFIRMED: '완료됐지만 실적이 확정되지 않았습니다.',
  PUBLIC_RECORD:
    '넣은 출항·도착·정박 시각이 해양수산부 선박운항정보의 공적 기록과 6시간 넘게 다릅니다. 값은 바꾸지 않았습니다.',
}

/** `public_record.mismatches[].field` → 화면 문구 (#1197). */
export const PUBLIC_RECORD_FIELD_LABEL: Record<PublicRecordField, string> = {
  DEPARTURE: '출항 시각',
  ARRIVAL: '도착 시각',
  BERTH_START: '정박 시작',
  BERTH_END: '정박 끝',
}

/** `public_record.source` → 화면 문구. **모르는 출처는 원문 그대로**(`reasonText`와 같은 방침). */
const PUBLIC_RECORD_SOURCE_TEXT: Record<string, string> = {
  MOF_VESSEL_OPS: '해양수산부 선박운항정보(공공데이터포털)',
}

export function publicRecordSourceText(source: string): string {
  return PUBLIC_RECORD_SOURCE_TEXT[source] ?? source
}

const REASON_TEXT: Record<string, string> = {
  DISTANCE: '실적 거리 없음 — 계획 거리로 계산',
  FUEL: '실적 연료 없음 — 계획 연료로 계산',
  FUEL_UNFILLED: '연료 실적·계획 모두 없음',
  FUEL_NO_RECORD: '연료 기록이 없음 — 행 자체가 없다',
  FUEL_VS_MODEL: '연료가 속력 모델 기대값의 0.6~1.4배 밖',
  SPEED_ABOVE_REFERENCE: '운항 시각으로 낸 속력이 기준 속력의 1.5배 초과',
  SPEED_MISMATCH: '기록 속력과 운항 시각으로 낸 속력이 30% 이상 차이',
  COMPLETED: '완료 상태 — 실적 확정 전',
  NO_DATA: '실적 항차의 거리·연료 합이 0',
  MISSING_SPEC: '선박 제원으로 계산할 수 없음',
  NO_PARAMETERS: '이 선종의 규정 기준값 없음',
  CALCULATION_ERROR: '계산 중 오류',
  /*
   * 공적 기록 어긋남 (#1197) — `PUBLIC_RECORD:ARRIVAL`처럼 **전체 코드**로 키를 둔다.
   * 다른 항목은 `head:detail`에서 `detail`(유종·항만청 등)을 원문 그대로 괄호로 붙이지만,
   * 여기 `detail`은 필드 코드(`ARRIVAL` 등)라 원문 그대로면 한국어 화면에 영문이 남는다.
   */
  [`PUBLIC_RECORD:DEPARTURE`]: `${PUBLIC_RECORD_FIELD_LABEL.DEPARTURE}이 공적 기록과 다름`,
  [`PUBLIC_RECORD:ARRIVAL`]: `${PUBLIC_RECORD_FIELD_LABEL.ARRIVAL}이 공적 기록과 다름`,
  [`PUBLIC_RECORD:BERTH_START`]: `${PUBLIC_RECORD_FIELD_LABEL.BERTH_START}이 공적 기록과 다름`,
  [`PUBLIC_RECORD:BERTH_END`]: `${PUBLIC_RECORD_FIELD_LABEL.BERTH_END}이 공적 기록과 다름`,
}

/**
 * 사유 코드 → 문구. `FUEL:HFO`처럼 유종이 붙으면 뒤에 괄호로 적는다.
 *
 * **전체 코드가 그대로 키에 있으면 그것을 먼저 쓴다** — `PUBLIC_RECORD:ARRIVAL`처럼 뒤쪽이
 * 필드 코드라 원문 그대로 괄호로 붙이면 한국어 화면에 영문이 남는다(위 `REASON_TEXT` 주석).
 *
 * **모르는 코드는 코드 그대로** 보인다 — 빈칸으로 두면 문제가 없는 것처럼 보인다.
 */
export function reasonText(code: string): string {
  if (code in REASON_TEXT) return REASON_TEXT[code]
  const [head, detail] = code.split(':', 2)
  const text = REASON_TEXT[head] ?? code
  return detail ? `${text} (${detail})` : text
}

/**
 * CII 영향을 낼 수 없는 사유 (`API_SPEC §2.16` `cii_impact_reason`).
 *
 * ## 칸은 짧게, 이유는 표 아래 한 번 (#1580)
 *
 * 종전에는 칸마다 긴 문장을 적어, 사유가 같은 행이 여럿이면 **같은 문장이 표 안에서 줄마다
 * 되풀이**됐다(실측 5행). 칸에는 짧은 말과 표시(`*`)만 두고, 그 표가 담은 사유만 표 아래에
 * 한 번씩 적는다. 표시는 **사유마다 고정**이라 표가 달라도 같은 사유는 같은 표시다.
 */
export const IMPACT_REASON: Record<string, { cell: string; mark: string; note: string }> = {
  ONLY_VOYAGE: {
    cell: '비교 불가',
    mark: '*',
    note: '선박의 유일한 항차라 빼고 비교할 누적 CII가 없습니다.',
  },
  BASE_UNAVAILABLE: {
    cell: '계산 불가',
    mark: '**',
    note: '선박 누적 CII를 계산할 수 없어 차이를 낼 수 없습니다.',
  },
}

/** 표시 순서 — 표 아래 각주는 이 순서로 적는다(행 순서에 따라 흔들리지 않게). */
export const IMPACT_REASON_ORDER = ['ONLY_VOYAGE', 'BASE_UNAVAILABLE'] as const
