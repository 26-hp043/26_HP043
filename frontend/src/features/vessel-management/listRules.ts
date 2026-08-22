import { formatCapacity } from '../../display/format'
import { capacityAxisOf } from '../vessel-registration/shipTypes'
import type { Vessel } from '../vessel-registration/types'

/**
 * 선박 목록의 표시 규칙 (#510).
 *
 * ## 무엇이 비어 있는지를 값으로 만든다
 *
 * `#449`가 세운 원칙을 따른다 — **계산할 수 없을 때 그럴듯한 값을 만들지 않고 그
 * 사실을 값으로 만든다.** 목록에서 제원이 빈 칸으로만 보이면 「입력하지 않았다」와
 * 「불러오지 못했다」가 구분되지 않고, 무엇보다 **그 배로 계산이 안 되는 이유**가
 * 화면 어디에도 드러나지 않는다.
 *
 * 이 규칙이 `#511`(항로 비교가 데모 선박에서 실패한다)의 원인을 목록에서 바로
 * 보이게 한다 — 데모 선박 4척 모두 `reference_daily_foc_ton`이 비어 있다.
 */

/** 표에서 「없음」을 나타내는 문자. `DESIGN_SYSTEM §2.4.3` 등급 없음과 같은 기호다. */
export const MISSING = '—'

/**
 * 숫자를 목록 셀 문자열로. 없으면 `—`.
 *
 * ⚠️ **용량(DWT·GT)에는 쓰지 않는다** — `capacityCell`이 `formatCapacity`를 쓴다
 * (`DESIGN_SYSTEM §4.2` · `#633`). `toLocaleString`은 자릿수를 고정하지 않아
 * `50,000`과 `6,405.77`이 섞이고, 선박 상세와도 값이 갈렸다.
 */
export function cellNumber(value: number | null): string {
  if (value === null) return MISSING
  return value.toLocaleString('ko-KR')
}

/** 용량 셀 — `§4.2` 규정을 거친다. 없으면 `—`. */
function capacityText(value: number | null): string {
  return formatCapacity(value) ?? MISSING
}

/*
 * 선종 코드 → 표시 문구.
 *
 * 구현을 `shipTypes.ts`(13종 표가 있는 곳)로 옮기고 여기서는 다시 내보내기만 한다.
 * 대시보드와 선박 상세도 같은 이름이 필요해졌는데, 그쪽이 `vessel-management`를
 * 거쳐 가져오는 것은 자리가 어색하다. 기존 import 경로는 그대로 둔다.
 */
export { shipTypeLabel } from '../vessel-registration/shipTypes'

/**
 * 이 선박의 capacity 축에 해당하는 값과 라벨.
 *
 * DWT 기반 선종에 GT만 있어도 CII는 계산되지 않는다(`PRD §3.3.3`). 그래서 목록은
 * **두 값을 나란히 보이지 않고 그 선종이 실제로 쓰는 축**을 보인다 — 두 칸을 다 보이면
 * 「하나만 있으면 된다」로 읽힌다.
 */
export function capacityCell(vessel: Vessel): { label: string; value: string } {
  const axis = capacityAxisOf(vessel.ship_type)
  if (axis === 'GT') return { label: 'GT', value: capacityText(vessel.gross_tonnage) }
  if (axis === 'DWT') return { label: 'DWT', value: capacityText(vessel.deadweight) }
  // 선종을 모르면 축도 모른다. 지어내지 않고 둘 다 보인다.
  return {
    label: 'GT / DWT',
    value: `${capacityText(vessel.gross_tonnage)} / ${capacityText(vessel.deadweight)}`,
  }
}

/**
 * 이 선박에 대해 지금 할 수 없는 것.
 *
 * 서버가 판정하는 `is_cii_applicable_hint`는 **GT 기준 규제 적용 여부**이고, 여기서
 * 보는 것은 **계산에 필요한 입력이 있는가**다. 둘은 다르다 — 규제 대상이면서 제원이
 * 없어 계산이 안 되는 배가 있다(데모 벌크선이 정확히 그 상태다).
 *
 * `PRD §11.4` 연료 예측 모델 우선순위가 근거다.
 *
 * > ⑴ 사용자 입력 → ⑵ `base_daily_foc_ton` + `reference_speed_kn` → ⑶ 샘플 선박 기본값
 *
 * ⑵는 **둘 다** 있어야 성립한다(`calc/annual_simulation.py`의 `_has_speed_model`이
 * 같은 판단을 한다) — 하나만 있으면 「기준속도는 있으니 되겠지」로 읽히므로
 * **무엇이 빠졌는지 이름을 적는다.**
 *
 * ## 문구가 사실과 달랐다 (#630)
 *
 * 종전에는 「항로 비교·연간 시뮬레이션이 **실패합니다**」로 적었다. 실측하면
 * **연간 시뮬레이션은 실패하지 않는다** — 200으로 돌고 감속 민감도만 조용히 0이 된다
 * (`_shift_speed`가 제원 없는 항차를 건너뛴다). 멀쩡한 기능을 고장났다고 예고하면서
 * 진짜 문제는 말하지 않고 있었다.
 */
export function blockedReasons(vessel: Vessel): string[] {
  const reasons: string[] = []

  const axis = capacityAxisOf(vessel.ship_type)
  if (axis === 'DWT' && vessel.deadweight === null) {
    reasons.push('재화중량톤수(DWT) 없음 — CII 등급을 산출할 수 없습니다')
  }
  if (axis === 'GT' && vessel.gross_tonnage === null) {
    reasons.push('총톤수(GT) 없음 — CII 등급을 산출할 수 없습니다')
  }

  const missingFuelModel: string[] = []
  if (vessel.reference_speed_kn === null) missingFuelModel.push('기준속도')
  if (vessel.reference_daily_foc_ton === null) missingFuelModel.push('기준 일일 연료소모량')
  if (missingFuelModel.length > 0) {
    reasons.push(
      `${missingFuelModel.join(' · ')} 없음 — 항로 비교가 실패하고, 연간 시뮬레이션의 감속 민감도가 산출되지 않습니다`,
    )
  }

  return reasons
}

/**
 * 목록 전체가 비었을 때의 안내.
 *
 * `UIFLOW 1-1`이 규정한 상태다 — *「등록된 선박 데이터가 없는 최초 진입 상태 (…)
 * `1-2. 선박 등록`으로 자동 이동」*. 자동 이동은 대시보드(`1-3`)의 몫이고, 관리
 * 화면에서는 **이동시키지 않는다** — 사용자가 스스로 이 화면에 온 것이므로 목록이
 * 비었다는 사실 자체가 답이다.
 */
export const EMPTY_MESSAGE =
  '등록된 선박이 없습니다. 선박을 등록하면 대시보드·CII 예측에서 선택할 수 있습니다.'

/**
 * 삭제 확인 문구.
 *
 * **soft delete임을 밝힌다.** `services/vessel.py:293`가 *「실제 DELETE가 아니라
 * `is_deleted = true`로 표시만 한다」*고 규정하며, 완료 기준(`#52`)에 **같은 IMO
 * 재등록 가능**이 들어 있다. 「영구 삭제」로 안내하면 사용자가 되돌릴 방법을 묻지
 * 않게 되고, 반대로 실제보다 가볍게 적으면 항차·계산 이력이 목록에서 사라지는 것을
 * 예상하지 못한다.
 */
export function deleteConfirmMessage(vessel: Vessel): string {
  return (
    `${vessel.name}(IMO ${vessel.imo_number})을(를) 목록에서 제거합니다. ` +
    '항차·계산 이력은 보존되며 같은 IMO로 다시 등록할 수 있습니다.'
  )
}
