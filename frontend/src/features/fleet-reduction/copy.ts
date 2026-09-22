import type { Target } from './types'

/**
 * 함대 감축 계획 화면 문구 (`UIFLOW 2-10` · `PRD §12.3.2` · #513).
 *
 * 모양·문구는 **2026-09-22에 현행대로 확정**됐다(`#1052` ⑺ · `UIFLOW 2-10`). 슬라이더 색·키보드
 * 단위·등급 전이 표기는 `DESIGN_SYSTEM §8`·`§8.3` 🔒 확정 그대로다.
 */
export const FLEET_REDUCTION_COPY = {
  lead: '선박별 감속을 정해 목표 등급 달성 여부와 비용을 함께 봅니다.',
  /*
   * `PRD §6.3` 「함대 감축 계획 — 결정론 안내」 원문. **연간 등급 관리와 값이 다를 수 있다는
   * 사실**을 적지 않으면 사용자는 두 화면 중 하나가 틀렸다고 읽는다(`UIFLOW 2-10`).
   */
  deterministicNotice:
    '이 화면의 연말 등급은 확률 분포 없이 계획대로 간다고 본 단일값입니다. 연간 등급 관리의 확률 결과와 다르게 보일 수 있습니다.',
  yearLabel: '규제연도',
  targetLabel: '목표',
  loading: '계산하는 중입니다…',
  loadSubject: '함대 감축 계획',
  /* 실패 문구 대체값 — 진행 문구(「계산하는 중」)를 쓰면 실패가 진행 중으로 읽힌다 (#1069). */
  evaluateFailed: '계산 결과를 받지 못했습니다.',
  staleResult: '아래 표는 마지막으로 계산에 성공한 조건의 결과입니다.',
  priceInvalid: '0 이상의 숫자를 입력하세요.',
  saveBlockedByPrice: '연료 단가에 잘못된 값이 있습니다. 위에서 고친 뒤 저장할 수 있습니다.',

  vesselsTitle: '선박별 감속',
  colVessel: '선박',
  colGrade: '연말 등급',
  colReduction: '감속률',
  colExtraDays: '추가 항해일',
  colFuelSaved: '연료 절감',
  colCharter: '일일 용선료 (USD)',
  meets: '목표 달성',
  misses: '목표 미달',
  cutHint: (ton: string) => `목표까지 연료 ${ton}t 더`,
  unreachable: '감속만으로 닿지 않음',
  skippedHint: (n: number) => `제원이 없어 감속을 적용하지 못한 항차 ${n}건`,

  statusIdle: '감속률을 움직이면 목표 달성 여부와 비용이 계산됩니다.',
  statusMet: '목표를 달성합니다.',
  statusMissed: '목표에 모자란 선박이 있습니다.',
  statusNoVessel: '계산할 수 있는 선박이 없습니다.',

  costsTitle: '비용 요약',
  extraDays: '추가 항해일',
  charterLoss: '용선료 손실',
  fuelSaving: '연료비 절감',
  net: '순손익',
  /* ⚠️ 단가가 비면 0이 아니라 이 문장이다 — 0이면 「손익 영향 없음」으로 읽힌다(`PRD §12.3.2`). */
  needsPrice: '단가 입력 필요',
  /** 계산 전 — 어느 연료가 필요한지 서버가 아직 말하지 않았다 (`#1273`). */
  fuelPricesBeforeRun: '계산이 끝나면 이 계획에 필요한 연료의 단가 칸이 열립니다.',
  /** 계산은 됐는데 필요한 단가가 없다. */
  fuelPricesNone: '이 계획에는 연료 단가가 필요하지 않습니다.',
  fuelPricesTitle: '연료 단가 (USD/t)',
  pricesNote: '단가는 이 계획의 가정값이며 계획과 함께 저장됩니다.',

  distributionTitle: '연말 등급 분포',
  before: '조정 전',
  after: '조정 후',

  saveTitle: '계획 저장',
  planNameLabel: '계획 이름',
  saveButton: '저장',
  saving: '저장하는 중…',
  saved: (name: string) => `「${name}」을 저장했습니다.`,
  saveFailed: '계획을 저장하지 못했습니다.',
  plansFailed: '저장한 계획 목록을 불러오지 못했습니다.',
  loadLabel: '저장한 계획 불러오기',
  loadPlaceholder: '저장한 계획 선택',
  noPlans: '저장한 계획이 없습니다.',
} as const

export const TARGET_TEXT: Record<Target, string> = {
  NO_AT_RISK: '위험 선박 0척',
  ALL_C_OR_BETTER: '전 선박 C 이상',
}

export const UNAVAILABLE_TEXT: Record<string, string> = {
  NO_DATA: '올해 계산할 항차 없음',
  MISSING_SPEC: '선박 제원으로 계산할 수 없음',
  NO_PARAMETERS: '이 선종의 규정 기준값 없음',
  CALCULATION_ERROR: '계산 중 오류',
}
