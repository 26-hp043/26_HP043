import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatCapacity,
  formatDecimalString,
  formatGrouped,
} from '../../display/format'
import { capacityAxisOf, shipTypeLabel } from '../vessel-registration/shipTypes'
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
export { shipTypeLabel }

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
 * 계산이 돌기까지 채워야 할 항목 (#719).
 *
 * ## 왜 목록이고 문장이 아닌가
 *
 * 아래 `blockedReasons`가 「무엇이 막혔나」를 **문장**으로 적는다. 그 문장은 정확하지만
 * **읽어야 안다** — 목록에서 스무 척을 훑을 때 필요한 것은 「이 배는 3개 중 1개」라는
 * 한 눈이다. 두 표현이 같은 판정에서 나와야 하므로 판정을 여기 한 번만 둔다.
 *
 * 종전에는 `blockedReasons` 안에 판정이 묻혀 있었다. 완성도를 따로 세면 **같은 규칙이
 * 두 벌**이 되고, 갈렸을 때 화면은 멀쩡해 보인다.
 *
 * ## 세 항목인 이유
 *
 * `PRD §11.4` 연료 예측 모델 우선순위가 근거다.
 *
 * - **용량** — 그 선종이 쓰는 축(`PRD §3.3.3`). 없으면 CII 등급 자체가 안 나온다
 * - **기준속도 · 기준 일일 연료소모량** — ⑵가 성립하는 조건. **둘 다** 있어야 한다
 *
 * `default_fuel_type`은 넣지 않는다. **어떤 계산도 막지 않는다** — 항차마다 연료를
 * 고르므로 비어 있어도 전부 돈다. 완성도에 넣으면 「채워야 하는 것」으로 읽힌다.
 */
/*
 * 내보내지 않는다. 쓰는 쪽은 `specChecklist()`의 반환에서 추론하면 되고, 이름을
 * 내보내면 **아무도 부르지 않는 export**가 되어 `moduleBoundary` 가드에 걸린다.
 */
interface SpecItem {
  key: 'capacity' | 'referenceSpeed' | 'referenceFoc'
  /** 사용자가 채울 칸의 이름. 수정 폼의 라벨과 같은 말을 쓴다. */
  label: string
  filled: boolean
  /**
   * 선종을 모르면 **어느 축이 필요한지도 모른다.** 이때는 미비로 세지 않는다 —
   * 없는 판정을 만들지 않는다(`#449`).
   */
  unknownAxis?: boolean
}

export function specChecklist(vessel: Vessel): SpecItem[] {
  const axis = capacityAxisOf(vessel.ship_type)

  const capacity: SpecItem =
    axis === 'GT'
      ? { key: 'capacity', label: '총톤수(GT)', filled: vessel.gross_tonnage !== null }
      : axis === 'DWT'
        ? { key: 'capacity', label: '재화중량톤수(DWT)', filled: vessel.deadweight !== null }
        : {
            key: 'capacity',
            label: '용량(GT · DWT)',
            filled: vessel.gross_tonnage !== null || vessel.deadweight !== null,
            unknownAxis: true,
          }

  return [
    capacity,
    {
      key: 'referenceSpeed',
      label: '기준속도',
      filled: vessel.reference_speed_kn !== null,
    },
    {
      key: 'referenceFoc',
      label: '기준 일일 연료소모량',
      filled: vessel.reference_daily_foc_ton !== null,
    },
  ]
}

/** 완성도 — 「3개 중 2개」. 축을 모르는 항목은 분모에서도 뺀다. */
export function specProgress(vessel: Vessel): { filled: number; total: number } {
  const counted = specChecklist(vessel).filter((item) => item.unknownAxis !== true)
  return { filled: counted.filter((item) => item.filled).length, total: counted.length }
}

/**
 * 이 선박에 대해 지금 할 수 없는 것.
 *
 * 서버가 판정하는 `is_cii_applicable_hint`는 **GT 기준 규제 적용 여부**이고, 여기서
 * 보는 것은 **계산에 필요한 입력이 있는가**다. 둘은 다르다 — 규제 대상이면서 제원이
 * 없어 계산이 안 되는 배가 있다(데모 벌크선이 정확히 그 상태다).
 *
 * **판정은 위 `specChecklist`가 한다.** 여기서는 그 결과를 문장으로 옮기기만 한다.
 *
 * ## 문구가 사실과 달랐다 (#630)
 *
 * 종전에는 「항로 비교·연간 시뮬레이션이 **실패합니다**」로 적었다. 실측하면
 * **연간 시뮬레이션은 실패하지 않는다** — 200으로 돌고 감속 민감도만 조용히 0이 된다
 * (`_shift_speed`가 제원 없는 항차를 건너뛴다). 멀쩡한 기능을 고장났다고 예고하면서
 * 진짜 문제는 말하지 않고 있었다.
 */
export function blockedReasons(vessel: Vessel): string[] {
  const items = specChecklist(vessel)
  const reasons: string[] = []

  const capacity = items[0]
  if (capacity.unknownAxis !== true && !capacity.filled) {
    reasons.push(`${capacity.label} 없음 — CII 등급을 산출할 수 없습니다`)
  }

  /*
   * `PRD §11.4` ⑵는 두 값이 **함께** 있어야 성립한다(`calc/annual_simulation.py`의
   * `_has_speed_model`이 같은 판단을 한다) — 하나만 있으면 「기준속도는 있으니
   * 되겠지」로 읽히므로 **무엇이 빠졌는지 이름을 적는다.**
   */
  const missingFuelModel = items
    .filter((item) => item.key !== 'capacity' && !item.filled)
    .map((item) => item.label)
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

/*
 * ── 제원 값 셀 (#719) ───────────────────────────────────────────────────
 *
 * 목록이 완성도를 **막대와 「2/3」**으로만 보이던 것을 값으로 바꾼다. 막대는 추상이라
 * *무엇이* 빠졌는지는 아래 경고 문장을 읽어야 알 수 있었다. 값을 열에 두면 `—`가 그
 * 자리에 바로 서고, **사용자가 채울 칸과 화면의 칸이 1:1로 대응**한다.
 *
 * 자릿수·단위는 `§4.2`와 `display/format`이 소유한다 — 여기서 리터럴로 적지 않는다
 * (`#164`). 연료는 `GROUPED_FIELDS`라 천 단위 구분을 넣고, 속도는 넣지 않는다.
 *
 * 없으면 `null`을 낸다. 화면이 `—`를 그릴지 다른 표기를 쓸지는 표시의 몫이다.
 */
export function referenceSpeedCell(vessel: Vessel): string | null {
  if (vessel.reference_speed_kn === null) return null
  const value = formatDecimalString(String(vessel.reference_speed_kn), DISPLAY_DIGITS.speedKn)
  return `${value} ${DISPLAY_UNITS.speed}`
}

export function dailyFuelCell(vessel: Vessel): string | null {
  if (vessel.reference_daily_foc_ton === null) return null
  const value = formatGrouped(String(vessel.reference_daily_foc_ton), DISPLAY_DIGITS.fuelTon)
  return `${value} ${DISPLAY_UNITS.fuel}`
}

/*
 * ── 정렬 (#719) ─────────────────────────────────────────────────────────
 *
 * ## 기본이 이름순이 아닌 이유
 *
 * 이 화면의 용건은 **제원을 채우는 것**이다(`PRD §6.1 SCR-002` — 「제원이 없으면
 * 뒤가 전부 안 돈다」). 이름순이 기본이면 할 일이 목록 아무 데나 흩어진다.
 * 대시보드가 「위험도순」을 기본으로 두는 것과 같은 판단이다.
 *
 * ## 서버 정렬이 아니다
 *
 * `GET /vessels`는 커서 페이지네이션이라 **불러온 만큼만** 정렬된다. 「더 보기」로
 * 뒤 페이지를 받으면 그때 다시 정렬된다 — 전체를 정렬한 것처럼 보이지 않도록
 * 화면이 「불러온 n척 기준」임을 밝힌다.
 */
export const SORT_KEYS = ['gaps', 'name', 'type', 'capacity'] as const

export type VesselSortKey = (typeof SORT_KEYS)[number]

export const SORT_LABEL: Readonly<Record<VesselSortKey, string>> = {
  gaps: '제원 미비 먼저',
  name: '이름순',
  type: '선종순',
  capacity: '용량 큰 순',
}

/** 그 선박의 축에 해당하는 수치. 축을 모르거나 값이 없으면 `null`. */
function capacityValue(vessel: Vessel): number | null {
  const axis = capacityAxisOf(vessel.ship_type)
  if (axis === 'GT') return vessel.gross_tonnage
  if (axis === 'DWT') return vessel.deadweight
  return null
}

/**
 * 정렬. **원본을 바꾸지 않는다** — 목록 상태를 그대로 두고 파생만 만든다.
 *
 * 모든 키가 마지막에 이름으로 떨어진다. 동점을 남기면 같은 목록이 **다시 그릴 때마다
 * 순서가 달라 보이고**, 그 흔들림은 「내가 방금 뭘 눌렀나」로 읽힌다.
 */
export function sortVessels(vessels: readonly Vessel[], key: VesselSortKey): Vessel[] {
  const byName = (a: Vessel, b: Vessel) => a.name.localeCompare(b.name, 'ko-KR')

  return [...vessels].sort((a, b) => {
    if (key === 'name') return byName(a, b)

    if (key === 'type') {
      const compared = shipTypeLabel(a.ship_type).localeCompare(
        shipTypeLabel(b.ship_type),
        'ko-KR',
      )
      return compared !== 0 ? compared : byName(a, b)
    }

    if (key === 'capacity') {
      const left = capacityValue(a)
      const right = capacityValue(b)
      // 값이 없는 배는 끝으로. 0으로 치면 「가장 작은 배」로 섞인다.
      if (left === null && right === null) return byName(a, b)
      if (left === null) return 1
      if (right === null) return -1
      return right - left !== 0 ? right - left : byName(a, b)
    }

    // gaps — 덜 채워진 것이 위로.
    const left = specProgress(a)
    const right = specProgress(b)
    const leftGaps = left.total - left.filled
    const rightGaps = right.total - right.filled
    return rightGaps - leftGaps !== 0 ? rightGaps - leftGaps : byName(a, b)
  })
}
