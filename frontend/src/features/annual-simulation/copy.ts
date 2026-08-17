/**
 * 기능③ 화면 문구 (#157).
 *
 * ## 왜 문구를 모듈로 빼는가
 *
 * **이 이슈의 가장 큰 위험이 「근거 없는 표현」이다.** 실제 누적 데이터도 Monte Carlo
 * 결과도 없는 상태에서 「연말 예상 등급」 같은 문구를 띄우면 **없는 근거를 있는 것처럼
 * 보이게 한다.** `#136`이 같은 이유로 그 표현들을 금지했다.
 *
 * 문구가 JSX에 흩어져 있으면 그 금지를 테스트로 확인할 수 없다. 여기 모아 두면
 * `copy.test.ts`가 전수 검사한다.
 */

/**
 * 화면에 쓰면 안 되는 표현.
 *
 * | 금지 | 이유 |
 * |---|---|
 * | `연말` | 연말 시점 예측을 하지 않는다. 기능③ 엔진(`#63`)이 `2026.10`이다 |
 * | `예상 등급` | 등급은 「참고 등급」이다(`#136`) |
 * | `누적 기준 예상` | 실제 누적 데이터가 없다 |
 * | `추천` | `PRD §6.3` 「자동 결정 금지」 |
 *
 * ## `P(D` 를 금지 목록에서 뺐다 (#442)
 *
 * v1은 「`P(D∪E)`의 계산 정의가 `PRD`에 없다(`#170` ⑶)」를 근거로 금지했다. **그 근거가
 * 해소됐다** — `#339`(2026-08-14)가 `PRD §12.5`에 정의를 넣었고(`P(D∪E) = P(D) + P(E)`,
 * 여사건 조건 포함) `#170`은 CLOSED다. 그리고 `DESIGN_SYSTEM §2.5 (a)`가 **`⚠ P(D/E) 28%`
 * 표기를 규정**하므로, 금지를 유지하면 정본이 시키는 표기를 쓸 수 없다.
 *
 * 실제 표기는 `annualRules.riskFlag`가 만든다(문구가 아니라 값에서 파생되는 표시).
 */
export const FORBIDDEN_PHRASES = [
  '연말',
  '예상 등급',
  '누적 기준 예상',
  '추천',
] as const

/** 화면 문구. 여기 있는 값만 화면에 쓴다. */
export const ANNUAL_COPY = {
  title: '연간 CII 시뮬레이션',
  titleEn: 'Annual CII Simulation',

  /** 실제 계산 결과가 아님을 화면에서 구분 가능하게 한다(`#157` 완료 기준). */
  sampleBadge: '예시 데이터',
  sampleNotice:
    '이 화면은 고정된 예시 데이터로 만든 목업입니다. 실제 계산 결과가 아닙니다.',

  /**
   * `DESIGN_SYSTEM §11` — 전면 추정 화면이므로 개별 표기 대신 화면 단위 고지로 갈음한다.
   */
  estimateNotice:
    '표시된 수치는 잔여 계획을 전제로 산출한 예측값입니다. 실측이 아닙니다.',

  /* ── 실행 입력 ─────────────────────────────────────────────────────── */
  runTitle: '실행 조건',
  targetRatingLabel: '목표 등급',
  /** `PRD §12.8` — E는 목록에 두지 않는다. 「달성」이 의미를 잃는다 */
  targetRatingHint: 'A~D 중에서 고릅니다.',
  runsLabel: '반복 횟수',
  runsHint: '1,000~10,000회. 많을수록 분포가 안정되고 오래 걸립니다.',
  seedLabel: 'seed (선택)',
  seedHint: '비워 두면 서버가 정합니다. 같은 seed는 같은 결과를 냅니다.',
  submit: '시뮬레이션 실행',
  submitting: '실행 중입니다…',

  /* ── 결정론 (PRD §12.3) ────────────────────────────────────────────── */
  deterministicTitle: '결정론 예측',
  deterministicCaption:
    '누적 실적과 잔여 계획을 그대로 더해 계산합니다. 같은 입력이면 항상 같은 값입니다.',
  projectedCiiLabel: '예측 누적 CII',
  projectedRatingLabel: '참고 등급',
  completedLabel: '집계된 실적 항차',
  remainingLabel: '남은 계획 항차',

  /* ── 확률 (PRD §12.4 · §12.5) ──────────────────────────────────────── */
  probabilityTitle: '등급 확률 분포',
  probabilityCaption: '잔여 계획의 변동을 반복 추출해 얻은 분포입니다.',
  targetSuccessLabel: '목표 달성 확률',
  targetSuccessHint: '목표 등급 이상을 받을 확률입니다.',
  riskLabel: '위험도',
  spreadTitle: '분포 요약',
  p10Label: '하위 10%',
  p50Label: '중앙값',
  p90Label: '상위 10%',
  meanLabel: '평균',

  /* ── 민감도 (PRD §12.6) ────────────────────────────────────────────── */
  sensitivityTitle: '민감도',
  columnVariable: '변수',
  columnProjectedCii: '예측 CII',
  columnRatingChange: '등급 변화',
  columnProbabilityChange: '달성 확률 변화',

  /* ── 재현성 (TECH_SPEC §5.2 · §11) ─────────────────────────────────── */
  reproTitle: '재현 정보',
  reproCaption: '같은 조건으로 다시 실행할 때 필요한 값입니다.',
  snapshotLabel: '데이터 스냅샷',
  snapshotHint: '실행 시점의 항차 데이터를 따로 보관합니다.',
  runIdLabel: '계산 이력',

  loading: '시뮬레이션을 실행하는 중입니다…',
  empty: '실행 조건을 고르고 실행해 주세요.',
  errorTitle: '시뮬레이션을 실행하지 못했습니다',
} as const
