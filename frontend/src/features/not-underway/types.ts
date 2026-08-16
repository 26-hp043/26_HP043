/**
 * not under way 구간 화면 타입 (`API_SPEC §2.9~§2.13` · `#370`).
 *
 * ## 열거값을 여기에 박지 않는다
 *
 * `periodType`·`consumerType`을 유니온으로 고정하면 DB CHECK 제약이 바뀔 때 화면이
 * 조용히 갈라진다 — 서버가 새 값을 주는데 화면은 그 항목을 표시하지 못하고, 사용자는
 * 저장 단계에서야 거부를 만난다. 선택지는 **목록 응답의 `meta`가 준다**(§2.9).
 *
 * 한국어 라벨만 화면이 갖는다(`PERIOD_TYPE_LABELS`). 라벨이 없는 값이 와도 코드를
 * 그대로 보여 주면 되므로, 이쪽은 갈라져도 화면이 깨지지 않는다.
 */

/** 연료 기록 1건. `cfUsed`는 서버가 뜬 snapshot이며 화면은 표시만 한다. */
export interface FuelUse {
  id: string
  consumerType: string
  fuelType: string
  fuelTon: number
  /** 계산 시점 배출계수. 과거 계산과 값이 다를 때 원인을 찾을 유일한 단서다. */
  cfUsed: number
}

export interface Period {
  id: string
  vesselId: string
  regulationYear: number
  periodType: string
  startedAt: string
  /** `null`이면 **진행 중**이다. 「모름」이 아니다 — 화면이 이 둘을 같게 그리면 안 된다. */
  endedAt: string | null
  portName: string | null
  /** CII 분모 `Dt`에 더해진다. 접안·묘박은 0이 정상값이다. */
  distanceNm: number
  fuelUses: FuelUse[]
}

/** 목록 응답 — 선택지를 함께 받는다(§2.9 `meta`). */
export interface PeriodList {
  periods: Period[]
  periodTypes: string[]
  consumerTypes: string[]
  /**
   * 활성 연료 코드. `API_SPEC §7.2`의 연료 조회 API가 **아직 구현되지 않아** 구간
   * 목록이 함께 준다 — 화면이 코드를 박아 두면 seed와 갈라진다(실제로 `MDO`는
   * 그럴듯해 보이지만 시드에 없는 코드다).
   */
  fuelTypes: string[]
}

/** 생성 요청. `cfUsed`가 없는 것이 계약이다 — 배출계수는 서버가 정한다. */
export interface FuelUseDraft {
  consumerType: string
  fuelType: string
  fuelTon: string
}

export interface PeriodDraft {
  periodType: string
  startedAt: string
  endedAt: string | null
  portName: string | null
  distanceNm: string
  fuelUses: FuelUseDraft[]
}

export interface NotUnderwayProvider {
  list(vesselId: string): Promise<PeriodList>
  create(vesselId: string, draft: PeriodDraft): Promise<Period>
  /** 진행 중 구간의 종료 확정. `#370`이 지목한 주 용도다. */
  close(periodId: string, endedAt: string): Promise<Period>
  remove(periodId: string): Promise<void>
}
