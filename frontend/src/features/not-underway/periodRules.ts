import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatGrouped,
  formatTimestamp,
  kstInputToIso,
  toDecimalInput,
  toKstInput,
} from '../../display/format'
import { fuelTypeText } from '../parameters/fuelTypes'
import type { FuelUse, FuelUseDraft, Period, PeriodDraft } from './types'

/**
 * not under way 구간 화면 규칙 (`#370`).
 *
 * 컴포넌트에서 분리한 이유는 기능①의 `resultRules`와 같다 — **판정과 변환은 DOM 없이
 * 검증할 수 있어야 한다.** 이 저장소의 vitest에는 DOM 환경이 없다.
 */

/**
 * 한국어 라벨. **선택지 자체는 서버가 준다** — 여기 없는 코드가 와도 코드를 그대로
 * 보여 주면 되므로, 이 표가 뒤처져도 화면은 깨지지 않는다.
 *
 * 반대로 이 표를 선택지의 근거로 쓰면 서버가 새 값을 줄 때 그 항목이 사라진다.
 */
export const PERIOD_TYPE_LABELS: Readonly<Record<string, string>> = {
  IN_PORT: '접안',
  AT_ANCHOR: '묘박',
  DRIFTING: '표류',
  STS: 'STS 이송',
  CANAL_TRANSIT: '운하 통과',
  DRYDOCK: '드라이독',
}

export const CONSUMER_TYPE_LABELS: Readonly<Record<string, string>> = {
  MAIN_ENGINE: '주기관',
  AUX_ENGINE: '보조기관',
  OIL_FIRED_BOILER: '보일러',
  OTHER: '기타',
}

/**
 * 이동 거리가 **0이어야 하는** 구간 유형 (`#2130` · 전수검수 D-11).
 *
 * 접안·묘박은 배가 움직이지 않는데, 이 거리는 CII 분모 `Dt`에 더해진다(`types.ts`). 접안에
 * 50을 넣으면 등급이 좋아지는 쪽으로 조용히 바뀐다. 폼은 이 유형을 고르면 거리 칸을 잠그고
 * `0`을 보낸다.
 *
 * ⚠️ **서버가 같은 목록과 문구를 들고 있다** — `services/not_underway.py`의
 * `STATIONARY_PERIOD_TYPES` · `STATIONARY_DISTANCE_MESSAGE`. 서버는 생성·수정·CSV에서 422로
 * 막는다(`API_SPEC §2.10`). 두 곳이 갈리면 화면이 잠그지 않은 칸을 서버가 거부하거나 그
 * 반대가 되므로, `tests/test_not_underway_crud_db.py`가 이 소스 글자를 읽어 대조한다 —
 * **배열 리터럴과 작은따옴표 문자열 모양을 바꾸면 그 검사를 함께 고친다.**
 */
export const STATIONARY_PERIOD_TYPES: readonly string[] = ['IN_PORT', 'AT_ANCHOR']

/** 정본 문구 (`API_SPEC §2.10`) — 서버 422와 같은 문장이다. 바꾸려면 정본 개정이 먼저다. */
export const STATIONARY_DISTANCE_MESSAGE = '접안·묘박 구간의 이동 거리는 0이어야 합니다.'

/** 이 유형이면 거리 칸을 잠근다 — 값은 `0`으로 고정한다. */
export function distanceLocked(periodType: string): boolean {
  return STATIONARY_PERIOD_TYPES.includes(periodType)
}

/** 라벨이 없으면 코드를 그대로 보여 준다. 빈칸이면 항목이 없는 것으로 읽힌다. */
export function labelOf(code: string, table: Readonly<Record<string, string>>): string {
  return table[code] ?? code
}

/**
 * `<input type="datetime-local">` 값 → ISO 8601.
 *
 * **입력 칸은 KST이고 서버는 UTC로 받는다.** 문자열에 `Z`를 붙여 보내면 한국에서 넣은
 * 09:00이 UTC 09:00(= 한국 18:00)이 되어 **9시간이 밀린다.** 그 어긋남은 화면에 드러나지
 * 않고 CII 집계의 연도 귀속과 겹침 판정만 조용히 바꾼다.
 *
 * ⚠️ **브라우저 시간대로 읽지 않는다** (`DESIGN_SYSTEM §4.4` 🔒 · `#1686`). 종전에는
 * `new Date(로컬문자열)`로 읽어 기기 시간대를 따랐다 — 왕복은 맞았지만 KST가 아닌
 * 브라우저에서 **같은 값이 목록과 편집 칸에서 다르게** 보였다. 변환은 `format.ts`가
 * 소유한다(`§4.4`의 표시 형식과 같은 자리).
 */
export function toIso(localValue: string): string {
  const iso = kstInputToIso(localValue)
  // 꼴이 어긋난 값은 종전처럼 던진다 — 호출부가 유효성을 먼저 본다.
  if (iso === null) return new Date(localValue).toISOString()
  return iso
}

/** ISO → `datetime-local` 표시값(KST). 초 이하는 버린다(입력 칸의 정밀도가 분이다). */
export function toLocalInput(iso: string): string {
  return toKstInput(iso)
}

export function formatRange(period: Pick<Period, 'startedAt' | 'endedAt'>): string {
  // 형식은 `formatTimestamp`가 갖는다 (#1420).
  // 읽을 수 없는 시각은 값 없음으로 적는다 (#2124) — 구간은 두 끝이 다 있어야 구간으로 읽힌다.
  const start = formatTimestamp(period.startedAt) ?? NO_VALUE_TEXT
  // 「진행 중」과 「모름」은 다르다. 빈칸이나 「—」로 두면 종료 시각을 잊은 것으로 읽힌다.
  if (period.endedAt === null) return `${start} ~ 진행 중`
  return `${start} ~ ${formatTimestamp(period.endedAt) ?? NO_VALUE_TEXT}`
}

/**
 * 겹침(409) 문구 — 상대 구간의 시각을 **목록과 같은 형식**으로 적는다 (#2122).
 *
 * 서버는 시각을 값으로 준다(`API_SPEC §2.10` `details[0].overlap_started_at` ·
 * `overlap_ended_at`). 종전에는 서버 문구의 UTC ISO 원문(`2026-08-10T14:00:00+00:00`)을
 * 그대로 보여, 바로 위 목록의 KST 시각과 9시간 어긋났다 — 사용자는 그 시각의 구간을
 * 목록에서 찾지 못한다. `formatRange`를 지나면 목록의 그 행과 **글자까지 같다.**
 */
export function overlapText(clash: Pick<Period, 'startedAt' | 'endedAt'>): string {
  return `같은 선박에 이미 겹치는 구간이 있습니다 (${formatRange(clash)}). 기존 구간의 종료 시각을 먼저 확정해 주세요.`
}

/** 구간의 연료 합계 (표시용). 소수 둘째 자리는 `fuel_ton`의 DB 정밀도다. */
export function totalFuelTon(period: Period): number {
  // `toFixed(2)`로 미리 자르지 않는다 (#572). 표시 자릿수는 `§4.2`가 1자리로 정하는데,
  // 2자리로 한 번 반올림한 뒤 다시 1자리로 반올림하면 **두 번 반올림**이 된다
  // (`16.449` → `16.45` → `16.5`, 한 번만 하면 `16.4`). 반올림은 표시 시점에 한 번만 한다.
  return period.fuelUses.reduce((sum, fu) => sum + fu.fuelTon, 0)
}

/**
 * 삭제 전에 한 번 더 묻는 줄의 문구 (`#2130` · 전수검수 D-11).
 *
 * 항차 카드의 확인 줄(`voyage-management/voyageRules.ts`의 `transitionCaution` · `#1598`)과
 * 같은 모양이다 — 설명은 **무엇이 달라지는지**만 말하고, 실행 버튼은 동사로 끝난다.
 * 「정말로?」만 물으면 누른 사람이 판단할 근거가 없으므로 **그 구간·그 줄의 값**을 적는다.
 *
 * * 구간 삭제는 서버에서 소프트 삭제지만(`API_SPEC §2.12`) **되살리는 경로가 없다** —
 *   사용자에게는 되돌릴 수 없는 동작이다.
 * * 연료 한 줄 삭제는 **물리 삭제다**(`API_SPEC §2.13` · `types.ts`).
 *
 * 둘 다 누적 CII의 분자(연료)·분모(거리)를 바꾼다. 연료가 없는 구간은 「0 t이 빠집니다」가
 * 아니라 **없다는 사실**을 말한다 — 안 넣은 것과 0을 같게 적지 않는다(목록의 「미입력」과 같다).
 */
export interface DeleteCaution {
  /** 확인 줄의 설명 */
  message: string
  /** 확인 버튼 */
  confirm: string
}

export function periodDeleteCaution(period: Period): DeleteCaution {
  const parts: string[] = []
  if (period.fuelUses.length === 0) {
    parts.push('이 구간에는 연료 기록이 없습니다.')
  } else {
    const ton = quantityText(totalFuelTon(period), DISPLAY_DIGITS.fuelTon)
    parts.push(`이 구간의 연료 ${ton} ${DISPLAY_UNITS.fuel}이 누적에서 빠집니다.`)
  }
  if (period.distanceNm > 0) {
    const nm = quantityText(period.distanceNm, DISPLAY_DIGITS.distanceNm)
    parts.push(`이동 거리 ${nm} ${DISPLAY_UNITS.distance}도 빠집니다.`)
  }
  parts.push('지운 구간은 되돌릴 수 없습니다.')
  return { message: parts.join(' '), confirm: '삭제하기' }
}

export function fuelUseDeleteCaution(fuelUse: FuelUse): DeleteCaution {
  const consumer = labelOf(fuelUse.consumerType, CONSUMER_TYPE_LABELS)
  const ton = quantityText(fuelUse.fuelTon, DISPLAY_DIGITS.fuelTon)
  return {
    message: `${consumer} ${fuelTypeText(fuelUse.fuelType)} ${ton} ${DISPLAY_UNITS.fuel}이 누적에서 빠집니다. 지운 연료 기록은 되돌릴 수 없습니다.`,
    confirm: '삭제하기',
  }
}

export interface DraftErrors {
  startedAt?: string
  endedAt?: string
  distanceNm?: string
  fuelUses?: string
}

/**
 * 저장 전에 화면이 볼 수 있는 것만 본다.
 *
 * **겹침·연료 코드 유효성은 여기서 보지 않는다** — 다른 구간과 연료 seed를 알아야
 * 하고, 그건 서버가 안다. 화면이 흉내 내면 두 판정이 갈리고, 갈린 쪽이 맞다고 믿을
 * 근거가 없다.
 */
export function validateDraft(draft: PeriodDraft): DraftErrors {
  const errors: DraftErrors = {}

  if (!draft.startedAt) {
    errors.startedAt = '시작 시각을 입력해 주세요.'
  }
  if (draft.endedAt && draft.startedAt && draft.endedAt <= draft.startedAt) {
    errors.endedAt = '종료 시각은 시작 시각보다 뒤여야 합니다.'
  }

  const distance = Number(draft.distanceNm)
  if (draft.distanceNm === '' || Number.isNaN(distance) || distance < 0) {
    // 0은 정상값이다 — 접안·묘박은 움직이지 않는다(마이그레이션 028).
    errors.distanceNm = '0 이상의 숫자를 입력해 주세요.'
  } else if (distanceLocked(draft.periodType) && distance !== 0) {
    // 폼은 칸을 잠가 이 갈래에 닿지 않게 한다. 그래도 두는 것은 **판정이 서버와 같은
    // 함수 모양**이어야 하기 때문이다 — 잠금이 풀리는 날 서버 422를 받기 전에 여기서 말한다.
    errors.distanceNm = STATIONARY_DISTANCE_MESSAGE
  }

  for (const fu of draft.fuelUses) {
    const ton = Number(fu.fuelTon)
    if (fu.fuelTon === '' || Number.isNaN(ton) || ton <= 0) {
      // 0톤 기록은 「안 썼다」가 아니라 오타다 — 안 썼으면 줄을 지우면 된다.
      errors.fuelUses = '연료량은 0보다 커야 합니다. 사용하지 않았다면 줄을 지워 주세요.'
      break
    }
  }

  const seen = new Set<string>()
  for (const fu of draft.fuelUses) {
    // 구분자로 `\u0000`을 쓴다 — 두 코드 어디에도 나올 수 없어 `A|B`·`AB|` 같은
    // 조합이 같은 키가 되는 일이 없다. **이스케이프로 적는다**: 소스에 NUL 문자를
    // 그대로 넣으면 git이 파일 전체를 바이너리로 보아 **PR에서 diff가 보이지 않는다**
    // (#572에서 발견). 런타임 동작은 같다.
    const key = `${fu.consumerType}\u0000${fu.fuelType}`
    if (seen.has(key)) {
      errors.fuelUses = '같은 소비원·유종이 두 번 있습니다. 한 줄로 합쳐 주세요.'
      break
    }
    seen.add(key)
  }

  return errors
}

/**
 * 구간에 나중에 더하는 연료 한 줄을 검증한다 (`#638`).
 *
 * **`validateDraft`의 연료 규칙과 같은 문구를 쓴다** — 같은 값을 두 자리에서 넣는데
 * 거부 문구가 다르면 사용자가 다른 규칙으로 읽는다. 여기서 새로 적지 않고
 * 그쪽과 같은 문장을 돌려준다.
 *
 * **중복(같은 소비원·유종)은 보지 않는다.** 이미 저장된 구간의 연료와 대조해야 하는데,
 * 그 판정은 서버가 `409 CONFLICT`로 한다(`API_SPEC §2.13`). 화면이 흉내 내면 두 판정이
 * 갈리고, 갈린 쪽이 맞다고 믿을 근거가 없다 — `validateDraft` 머리주석과 같은 규율이다.
 */
export function validateFuelDraft(draft: FuelUseDraft): string | null {
  if (!draft.consumerType || !draft.fuelType) {
    return '소비원과 유종을 선택해 주세요.'
  }
  const ton = Number(draft.fuelTon)
  if (draft.fuelTon === '' || Number.isNaN(ton) || ton <= 0) {
    // 0톤 기록은 「안 썼다」가 아니라 오타다 — 안 썼으면 줄을 넣지 않으면 된다.
    return '연료량은 0보다 커야 합니다. 사용하지 않았다면 줄을 지워 주세요.'
  }
  return null
}

export function hasErrors(errors: DraftErrors): boolean {
  return Object.keys(errors).length > 0
}

/**
 * 수량을 `DESIGN_SYSTEM §4.2` 자릿수 문자열로 만든다 (#572).
 *
 * ## 왜 이 화면에만 다리가 필요한가
 *
 * `format.ts`의 포매터는 **십진 문자열**을 받는다. 계산 결과(`attained_cii` 등)가
 * `API_SPEC §1.7`상 문자열로 오기 때문이다. 그런데 이 화면의 값은 **JSON number**다 —
 * 서버 `not_underway._number()`가 *「Layer 1 계산 결과가 아니므로 JSON number다」* 로
 * 정한 것이며 계약대로다. 그래서 숫자를 문자열로 옮기는 한 단계가 필요하다.
 *
 * ## 반올림은 한 번만 한다
 *
 * 숫자를 문자열로 옮기는 다리는 `display/format`의 `toDecimalInput`이 소유한다
 * (`#872`). **자리를 맞추는 것이 아니라 지수 표기를 피하려는 것**이며(`String(1e-7)`은
 * `"1e-7"`이 되어 포매터가 던진다), 실제 반올림은 `formatGrouped`가 한 번 한다.
 * 종전에는 이 파일이 그 다리를 자체 구현하고 있었는데, 같은 규율이 다섯 화면에 더
 * 필요해져 공용으로 올렸다 — **복사하면 한쪽만 고쳐진다**(`display/decimal.ts`가
 * `#820`에서 옮겨진 것과 같은 이유).
 *
 * ## 없는 값은 포매터에 넣지 않는다
 *
 * 포매터는 십진 문자열이 아니면 **던진다.** 널 가드를 호출부마다 흩으면 검증할 수 없고,
 * 한 곳만 빠뜨려도 그 필드가 비어 오는 응답에서만 터진다 — `#566`이 같은 이유로
 * `formatOrNull`을 한 곳에 모았다.
 */
/** 값이 없을 때 쓰는 표시. 「0」과 구분된다 — 안 넣은 것과 0은 다르다. */
export const NO_VALUE_TEXT = '—'

export function quantityText(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE_TEXT
  return formatGrouped(toDecimalInput(value), digits)
}
