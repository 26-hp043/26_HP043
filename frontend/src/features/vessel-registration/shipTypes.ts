/**
 * 선종 선택지 (#441).
 *
 * ## 화면이 선종을 새로 나열하지 않는다
 *
 * 정본은 `PRD §3.4.3`이고 구현 기준은 `src/cii_platform/calc/capacity.py`의
 * `DWT_BASED_SHIP_TYPES`(8종)·`GT_BASED_SHIP_TYPES`(5종)다. 이 파일은 그 13종을
 * **화면용으로 옮겨 적은 것**이며, 옮겨 적은 것이 어긋나면 `shipTypes.sync.test.ts`가
 * 실패한다 — 파이썬 원본을 읽어 코드 집합과 축을 대조한다.
 *
 * 가드 없이 두면 선종이 늘 때 **화면에만 없는 선종**이 생기고, 그 상태는 화면을
 * 봐서는 드러나지 않는다(사용자는 없는 선택지를 그리워할 수 없다). 저장소가 겪은
 * 사고가 같은 형태였다 — 규칙은 적혀 있었고 확인하는 것이 없었다.
 *
 * ## 축(`axis`)을 왜 화면이 갖는가
 *
 * `VesselDetail`은 표시 단위의 축을 **서버가 준 `transport_capacity_basis`**로 쓴다
 * (`DESIGN_SYSTEM §4.1` 🔒). 등록 화면에는 그 응답이 **아직 없다** — 사용자가 선종을
 * 고르는 시점에 「이 선종은 DWT가 있어야 CII를 계산한다」를 알려야 하기 때문이다.
 *
 * 그래서 축을 갖되 **유추하지 않는다.** `capacity.py`의 두 집합 중 어디에 있는지가
 * 곧 축이고, 그 대응을 위 가드가 잠근다. 계산에는 쓰지 않는다 — 등록 후의 모든
 * 표시는 서버 값을 쓴다.
 *
 * ## 한국어 이름은 표시 문구다
 *
 * `AGENTS §4.6` 기준 **표시 문구**다(정본이 원문을 확정한 문구가 아니다). 디자인
 * 담당이 문서 개정 없이 바꿀 수 있다. 반대로 `code`는 계약값이므로 바꾸면 안 된다 —
 * 그래서 셀렉트에 코드를 함께 보인다(`#135` 연료 셀렉트와 같은 규칙).
 */

/** capacity 축. `capacity.py`의 두 집합 중 어디에 속하는지와 같다. */
export type CapacityAxis = 'DWT' | 'GT'

export interface ShipTypeOption {
  /** 계약값. `POST /vessels`의 `ship_type`에 그대로 실린다. */
  code: string
  /** 표시 문구 (`AGENTS §4.6`). */
  label: string
  axis: CapacityAxis
}

/**
 * 13종. 순서는 `PRD §3.4.3` 표 순서(DWT 8종 → GT 5종)를 따른다.
 *
 * 알파벳 정렬로 두지 않는다 — 표와 눈으로 대조할 때 순서가 다르면 대조가 느려진다
 * (`services/vessel.py to_dict()`가 키 순서를 §2.1 예시와 맞춘 것과 같은 이유).
 */
export const SHIP_TYPES: readonly ShipTypeOption[] = [
  { code: 'BULK_CARRIER', label: '벌크선', axis: 'DWT' },
  { code: 'GAS_CARRIER', label: '가스운반선', axis: 'DWT' },
  { code: 'TANKER', label: '탱커', axis: 'DWT' },
  { code: 'CONTAINER_SHIP', label: '컨테이너선', axis: 'DWT' },
  { code: 'GENERAL_CARGO_SHIP', label: '일반화물선', axis: 'DWT' },
  { code: 'REFRIGERATED_CARGO_CARRIER', label: '냉동화물선', axis: 'DWT' },
  { code: 'COMBINATION_CARRIER', label: '겸용선', axis: 'DWT' },
  { code: 'LNG_CARRIER', label: 'LNG운반선', axis: 'DWT' },
  { code: 'RO_RO_CARGO_VEHICLE', label: '차량운반선', axis: 'GT' },
  { code: 'RO_RO_CARGO', label: '로로화물선', axis: 'GT' },
  { code: 'RO_RO_PASSENGER', label: '로로여객선', axis: 'GT' },
  { code: 'RO_RO_PASSENGER_HSC', label: '로로여객선(고속선)', axis: 'GT' },
  { code: 'CRUISE_PASSENGER', label: '크루즈여객선', axis: 'GT' },
]

/** 코드 → 선택지. 없는 코드는 `undefined`. */
export function findShipType(code: string): ShipTypeOption | undefined {
  return SHIP_TYPES.find((type) => type.code === code)
}

/**
 * 화면에 내보낼 선종 이름 — `BULK_CARRIER` → `벌크선`.
 *
 * 표 옆에 두는 것은 **13종 목록이 여기 있기 때문**이다. 선종이 늘면 표와 이 함수가
 * 같은 커밋에서 바뀐다.
 *
 * 모르는 코드는 **코드를 그대로 돌려준다.** 서버가 새 선종을 먼저 추가할 수 있는데,
 * 그때 빈칸이나 「알 수 없음」을 내면 화면이 무엇을 보고 있는지 알 수 없게 된다.
 * 낯선 코드라도 보이는 편이 낫다.
 */
export function shipTypeLabel(code: string): string {
  return findShipType(code)?.label ?? code
}

/**
 * 그 선종의 capacity 축. 모르는 코드는 `null`.
 *
 * `null`을 던지지 않고 돌려주는 이유: 오래된 폼 상태나 서버가 새로 추가한 선종이
 * 들어올 수 있고, 그때 화면이 죽는 것보다 **안내를 생략하는 쪽**이 낫다.
 */
export function capacityAxisOf(code: string): CapacityAxis | null {
  return findShipType(code)?.axis ?? null
}
