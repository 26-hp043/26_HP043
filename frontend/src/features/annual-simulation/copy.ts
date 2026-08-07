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
 * | `P(D` | 확률 표기. `P(D∪E)`의 계산 정의가 `PRD`에 없다(`#170` ⑶) |
 */
export const FORBIDDEN_PHRASES = [
  '연말',
  '예상 등급',
  '누적 기준 예상',
  '추천',
  'P(D',
] as const

/** 화면 문구. 여기 있는 값만 화면에 쓴다. */
export const ANNUAL_COPY = {
  title: '연간 CII 시뮬레이션',
  titleEn: 'Annual CII Simulation',

  /** 실제 계산 결과가 아님을 화면에서 구분 가능하게 한다(`#157` 완료 기준). */
  sampleBadge: '예시 데이터',
  sampleNotice:
    '이 화면은 고정된 예시 데이터로 만든 목업입니다. 실제 계산 결과가 아니며 연간 시뮬레이션 엔진은 아직 연결되지 않았습니다.',

  /**
   * `DESIGN_SYSTEM §11` — 전면 추정 화면이므로 개별 표기 대신 화면 단위 고지로
   * 갈음한다. **외부 데이터 출처가 없으므로 출처명 필드를 강제하지 않는다**(PR #184).
   */
  estimateNotice:
    '표시된 수치는 모두 예시 값이며 실측이 아닙니다. 기준 시각은 화면을 연 시점입니다.',

  /** 집계 구간 전체의 CII. 「연말」·「예상 등급」을 쓰지 않는다. */
  attainedLabel: '연간 누적 CII',
  requiredLabel: '기준 CII',
  ratioLabel: '기준 대비 비율',
  ratingLabel: '참고 등급',
  riskLabel: '위험도',

  totalDistanceLabel: '누적 항해거리',
  totalFuelLabel: '누적 연료 사용량',
  totalCo2Label: '누적 CO₂ 배출량',

  monthsTitle: '월별 집계',
  monthsCaption: '집계 구간의 월별 요약입니다. 값은 전부 예시입니다.',

  columnMonth: '월',
  columnVoyages: '항차 수',
  columnDistance: '항해거리',
  columnFuel: '연료',
  columnCo2: 'CO₂',
  columnCii: 'CII',

  loading: '예시 데이터를 불러오는 중입니다…',
  empty: '표시할 집계 데이터가 없습니다.',
  errorTitle: '예시 데이터를 불러오지 못했습니다',
} as const
