import type { CapacityBasis } from './types'

/**
 * demo provider용 **provisional 고정표**.
 *
 * ## 값의 성격이 두 가지다 — 섞어 읽지 말 것
 *
 * | 구분 | 대상 | 출처 | 성격 |
 * |---|---|---|---|
 * | **잠정값** | `requiredCii` · 등급 경계 4개 | 이슈 #132 계약 코멘트의 8/8 provisional fixture | ⚠️ canonical이 아니다. `#45`가 확정되면 교체·검증(#138) |
 * | **전사값** | 연료 CF 8종 · `aDecimal` · `c` · `dVector` · `zFactorPercent` · `requiredCii` · 경계 4개 | `PRD §3.4.1~§3.4.4` · `§13.1` | ⚠️ **2차 사본이다 — IMO 원문 대조는 하지 않았다.** 값을 재작성하지는 않았다 |
 *
 * 잠정값은 `#38`의 자릿수 결정을 대체하지 않는다.
 *
 * ⚠️ **전사값을 "1차 출처"로 인용하지 말 것.** CF·기준선·d-vector는 IMO 규제값이고
 * 1차 출처는 MEPC 결의서다. `PRD`는 그걸 옮겨 적은 사본이며, 이 파일은 그 사본의
 * 사본이므로 **검증 근거로 쓰려면 원문까지 거슬러 올라가야 한다.**
 *
 * 전사는 `AGENTS §3` 우선순위에 따라 **`PRD`에서 했다.** `DB_SCHEMA §3.2`에도 같은 CF
 * 표가 있으나 하위 문서다.
 *
 * ## ⚠️ 전체 자릿수로 보관하고, 자르는 것은 응답 직렬화 단계에서만
 *
 * `requiredCii`와 경계 4개를 표시 자릿수(6자리)로 잘라서 보관하면 **등급 판정이
 * 백엔드와 갈린다.** `#39`는 `PRD §13.1`의 전체 자릿수로 비교하므로,
 * 예를 들어 `5.347770 < attained ≤ 5.3477703124` 구간에서 프론트는 D, 백엔드는 C를 낸다.
 * 폭이 3e-7이라 시연에서 밟힐 일은 없지만 `#39`·`#40` 머지 후 대조에서 불일치로 보고된다.
 *
 * 따라서 **비교용 값은 전체 자릿수, 표시·응답용은 형식화 단계에서 자른다.**
 *
 * ## `aDecimal` · `c` · `dVector` · `zFactorPercent`는 계산에 쓰지 않는다
 *
 * `required_cii`와 경계 4개를 조회로 처리하므로 이 네 값은 **계산 입력이 아니다.**
 * 응답의 `calculation_basis`·`parameters_used`에 그대로 실어 계약을 재현하기 위한
 * 출처 기록일 뿐이다. **이 값으로 다른 선박·연도를 계산하지 말 것** — 그렇게 하면
 * 선박을 1척으로 좁힌 결정을 정확히 되돌리게 된다.
 *
 * **`required_cii`와 등급 경계 4개는 계산하지 않고 여기서 조회한다.** 두 값이
 * `#45`·`#38`의 확정에 걸려 있어, provider가 직접 계산하면 미확정 값을 프론트엔드가
 * 선점하게 된다(#134).
 *
 * ## 지원 범위 — 선박 1척 × 연도 1개
 *
 * `(vesselId, year)` 조합이 이 표에 있어야만 계산한다. 없으면 임의 계산하지 않고
 * 오류를 던진다(#134 완료 기준).
 *
 * 현재 등록된 조합은 **BULK_CARRIER 50,000 DWT × 2026** 하나뿐이다. 이유:
 *
 * - `#132` 계약이 **이 조합에만** UUID·`required_cii`·기대 응답 전문을 확정했다.
 * - `#34`의 나머지 샘플 선박 2척(LNG_CARRIER · CRUISE_PASSENGER)은 **UUID가 정해지지
 *   않았고** `required_cii`를 대조할 fixture도 없다.
 * - 그 2척을 지원하려면 선종별 capacity 축 분기(DWT ↔ GT)와 LNG 구간 분기를 프론트엔드에
 *   다시 구현해야 하는데, 그건 `#41`(PR #130, 미머지) 영역이다. **잠글 fixture가 없는
 *   중복 구현**이 된다.
 * - 연도 축도 같다 — `required_cii`는 Z계수에 걸려 연도마다 달라지고,
 *   `regulation_year` 설정 경로는 `#150`이 미해결이다.
 *
 * 표 구조는 `(vesselId, year)` 키라 **fixture가 확정되면 행 추가만으로 늘어난다.**
 * 코드를 고칠 필요가 없다.
 */

/** 데모 샘플 선박. `#132` 계약이 고정한 UUID를 쓴다 — `#135`도 같은 값을 써야 한다. */
export interface DemoVessel {
  id: string
  displayName: string
  shipType: string
  /** Layer 1 문자열로 그대로 응답에 실린다. */
  transportCapacity: string
  transportCapacityBasis: CapacityBasis
  referenceCapacity: string
  /** enum이 아니라 파라미터 테이블 값 그대로. */
  referenceCapacityRule: string
}

export const DEMO_VESSELS: readonly DemoVessel[] = [
  {
    id: '00000000-0000-4000-8000-000000000001',
    displayName: '샘플 벌크선 (50,000 DWT)',
    shipType: 'BULK_CARRIER',
    transportCapacity: '50000',
    transportCapacityBasis: 'DWT',
    referenceCapacity: '50000',
    referenceCapacityRule: 'DWT',
  },
]

/** 등급 경계 4개. `PRD §3.3.6` `required_CII × d`. */
export interface RatingBoundaries {
  superior: string
  lower: string
  upper: string
  inferior: string
}

/** `(선박, 연도)` 조합의 고정 파라미터. */
export interface FixedParameters {
  vesselId: string
  year: number
  /**
   * 고정값 — 계산하지 않는다. `PRD §13.1`이 인쇄한 전체 자릿수 그대로.
   * 응답에는 6자리로 형식화해 싣는다(`#132` 계약의 `"5.045066"`).
   */
  requiredCii: string
  /**
   * 고정값 — 계산하지 않는다. **`PRD §13.1`이 인쇄한 값을 전사했다.**
   *   A/B superior = 5.0450663325 × 0.86 = 4.3387570460
   *   B/C lower    = 5.0450663325 × 0.94 = 4.7423623525
   *   C/D upper    = 5.0450663325 × 1.06 = 5.3477703124
   *   D/E inferior = 5.0450663325 × 1.18 = 5.9531782723
   *
   * `upper`는 `#132` 계약의 `next_worse_boundary_margin = 0.365370`과 교차 검증된다
   * (`5.3477703124 − 4.9824 = 0.3653703124` → 6자리 `0.365370`).
   *
   * ⚠️ **`TEST_PLAN §1.2`는 다른 값을 쓴다** — `superior "4.338757045"` ·
   * `upper "5.347770311"`. 자릿수 차이가 아니라 **`CII_ref` 단계에서 이미 갈렸고**
   * (PRD `5.6686138567` ↔ TEST_PLAN `"5.668613856"`, 약 1.5e-9) 그것이 네 경계에
   * 전파된 것이다. `AGENTS §3`상 PRD가 상위이므로 PRD를 따랐다.
   * 이 불일치는 `#38`이 다루는 범위다(`#38` 참조 문서에 `TEST_PLAN §1.2`가 있다).
   * 6자리로 형식화하면 양쪽이 같아지므로 응답 값은 어느 쪽으로 확정되든 영향받지 않는다.
   */
  boundaries: RatingBoundaries
  dVector: { d1: string; d2: string; d3: string; d4: string }
  aDecimal: string
  c: string
  zFactorPercent: string
  parameterSourceVersion: string
}

export const FIXED_PARAMETERS: readonly FixedParameters[] = [
  {
    vesselId: '00000000-0000-4000-8000-000000000001',
    year: 2026,
    requiredCii: '5.0450663325',
    boundaries: {
      superior: '4.3387570460',
      lower: '4.7423623525',
      upper: '5.3477703124',
      inferior: '5.9531782723',
    },
    dVector: { d1: '0.86', d2: '0.94', d3: '1.06', d4: '1.18' },
    aDecimal: '4745',
    c: '0.622',
    zFactorPercent: '11.0',
    parameterSourceVersion: 'imo-mepc-2024-q1',
  },
]

/**
 * 연료 CO₂ 계수(CF).
 *
 * **`PRD.md` §3.4.2의 8행을 그대로 전사했다** — 값은 `DB_SCHEMA §3.2`와 같으나
 * `AGENTS §3` 우선순위에 따라 상위 문서에서 옮겼다. 규제값의 원 출처 문서는
 * `MEPC.364(79)` §2.2.1이다(#87 확정).
 *
 * 8종을 전부 넣은 이유 — `#137` 데모 검증 항목에 *"연료 종류 변경 — 해당 CF에 따라
 * CO₂와 CII가 변하는지 확인"* 이 있고 `#135`가 연료 종류 선택을 요구한다. 값 자체는
 * 계산이 아니라 전사이므로, 선박·연도를 1조합으로 좁힌 것과 성격이 다르다.
 *
 * `Ethane`(2.927)과 `OTHER`는 넣지 않았다 — **8/8 시연 범위 밖이기 때문이다.**
 * `Ethane`이 `§3.2`에 없는 것 자체가 별건(seed 이슈)이므로 그 부재를 제외 근거로 삼지
 * 않는다. `OTHER`는 CF가 사용자 입력이라 고정표에 담을 값이 없다.
 *
 * 응답에 실리는 문자열은 계약 예시(`"3.114"`)를 따라 소수점 3자리로 적는다 —
 * §3.2 원본 표기(`3.114000`)와 자릿수만 다르고 값은 같다. 최종 자릿수 정책은 `#38` 소관.
 */
export const FUEL_CF: Readonly<Record<string, { displayName: string; cf: string }>> = {
  HFO: { displayName: 'Heavy Fuel Oil', cf: '3.114' },
  LFO: { displayName: 'Light Fuel Oil', cf: '3.151' },
  DIESEL_GAS_OIL: { displayName: 'Diesel/Gas Oil', cf: '3.206' },
  LPG_PROPANE: { displayName: 'LPG Propane', cf: '3.000' },
  LPG_BUTANE: { displayName: 'LPG Butane', cf: '3.030' },
  LNG: { displayName: 'Liquefied Natural Gas', cf: '2.750' },
  METHANOL: { displayName: 'Methanol', cf: '1.375' },
  ETHANOL: { displayName: 'Ethanol', cf: '1.913' },
}

export function findVessel(vesselId: string): DemoVessel | undefined {
  return DEMO_VESSELS.find((v) => v.id === vesselId)
}

export function findFixedParameters(
  vesselId: string,
  year: number,
): FixedParameters | undefined {
  return FIXED_PARAMETERS.find((p) => p.vesselId === vesselId && p.year === year)
}

/** 고정표가 지원하는 규제연도 목록. */
export function supportedYears(vesselId: string): number[] {
  return FIXED_PARAMETERS.filter((p) => p.vesselId === vesselId).map((p) => p.year)
}
