/**
 * Layer 1 문자열의 표시 형식 변환 — `DESIGN_SYSTEM §4`(숫자 · 단위 포맷)의 구현.
 *
 * **이 모듈은 특정 feature에 속하지 않는다** (#392). `§4`가 화면 전체에 적용되는
 * 규약이므로 `src/display/`에 둔다. 종전에는 `features/voyage-cii/` 안에 있어
 * `annual-simulation`·`scenario-comparison`이 `../voyage-cii/format`으로 끌어 쓰는
 * 상태였다 — 참조할 이유가 없는 feature를 경로가 강제하고 있었고, 방향 전환으로
 * 신설되는 화면 4건(대시보드 #351 · 선박 상세 #356 · 실시간 CII #357 · 리포트 #362)이
 * 같은 경로를 물려받을 참이었다.
 *
 * 새 표시 규약이 생기면 이 디렉토리에 둔다 — `§4`가 소관인 것은 전부 여기다.
 *
 * **문자열을 받아 문자열을 반환한다.** `parseFloat()`·`Number()`를 쓰지 않는다 —
 * `API_SPEC §1.7` `[ORACLE-C-1]`이 Layer 1 값을 문자열로 직렬화하는 이유가
 * JSON float 파싱의 정밀도 손실을 막기 위해서인데, 화면에서 되돌리면 그 보호가 사라진다.
 *
 * 자릿수는 `DESIGN_SYSTEM §4.2`(물리량)와 `§4.1`(CII)을 따른다.
 * 반올림은 `ROUND_HALF_UP`이며 **표시 시점에만** 적용한다(`§4.2` 「반올림」).
 *
 * ⚠️ **포매터 함수는 단위 문자열을 붙이지 않는다.** 숫자 문자열만 반환한다.
 * CII 단위는 선종의 capacity 축에서 파생되므로(`PRD §3.3.3` · `DESIGN_SYSTEM §4.1`)
 * 포매터가 단위를 붙이려면 선종을 알아야 한다. **부착은 호출부 책임이다**(#164).
 *
 * 다만 **질량·거리 단위 문자열의 정의는 이 모듈이 소유한다**(`DISPLAY_UNITS`, #164).
 * 부착 위치가 호출부인 것과 값이 어디서 오는지는 별개다 — 값까지 호출부에 두면
 * 화면마다 리터럴이 박혀 바꿀 때 누락이 생긴다.
 */

/**
 * 화면 표시 자릿수.
 *
 * `DESIGN_SYSTEM §4.2` 소수 자릿수 표(🔒)와 `§4.1` CII 3자리를 옮긴 것이다.
 *
 * ⚠️ **`PRD §9.3`과 3건이 상충한다** — 연료 2→1 · CO₂ 2→1 · 거리 1→0.
 * `AGENTS §3.2.2`상 **화면 표시 자릿수는 `DESIGN_SYSTEM` 소관**이므로 이쪽을 따른다.
 * `PRD §9.3` 본문을 `§4` 참조로 전환하는 정합화는 `#185`가 추적한다.
 */
export const DISPLAY_DIGITS = {
  /** CII 값 — attained · required · 경계 · margin (`§4.1`) */
  cii: 3,
  /** 연료 사용량 (`§4.2`) */
  fuelTon: 1,
  /** CO₂ 배출량 (`§4.2`) */
  co2Ton: 1,
  /** 항해거리 (`§4.2`) */
  distanceNm: 0,
  /** 운항 시간 (`§4.2`). 기능② 필드라 기능① 결과 화면에는 나오지 않는다 */
  durationHours: 1,
  /** 비율·확률의 **백분율** 자릿수 (`§4.2`) */
  percent: 1,
} as const

/**
 * 천단위 구분자를 넣을 항목.
 *
 * `DESIGN_SYSTEM §4.2` 「천단위 구분자」(🔒) — 적용은 연료·거리·CO₂이며
 * **CII · 비율 · 확률에는 넣지 않는다.**
 *
 * CII는 통상 1000을 넘지 않아 구분자가 등장하지 않으며, 적용하면 `§4.1`이
 * 자릿수 고정으로 확보한 소수부 정렬을 방해한다. **명시적으로 제외하지 않으면
 * 구현에서 일괄 적용될 여지가 있어** 목록으로 못박는다.
 */
export const GROUPED_FIELDS = ['fuelTon', 'co2Ton', 'distanceNm'] as const

/**
 * 화면에 붙이는 단위 문자열 (`DESIGN_SYSTEM §4.2`).
 *
 * **화면에 리터럴로 박지 않고 여기를 참조한다** (#164). 단위 표기는
 * `AGENTS §3.2.2`상 디자인 소관이라 회신에 따라 바뀔 수 있는데, 리터럴이
 * 화면마다 흩어져 있으면 바꿀 때 일부가 남는다. 그 누락은 **화면이 깨지지
 * 않고 내용만 틀리므로 발견이 늦다** — `§4.1`이 CII 단위에 대해 고정 문자열을
 * 금지한 것과 같은 이유다. 여기 모아 두면 교체가 한 곳이다.
 *
 * ⚠️ **CII 단위는 여기 없다.** 선종의 capacity 축에서 파생되어
 * `gCO₂/(DWT·nm)`·`gCO₂/(GT·nm)`로 갈리므로 상수가 아니다(`§4.1` 🔒).
 *
 * 현재 값의 근거:
 * - `fuel: 't'` — `t`는 tonne(1,000 kg)의 SI 기호다. `ton`은 short ton(907 kg)·
 *   long ton(1,016 kg)과 표기가 겹쳐 국제 규제 맥락에서 모호하다.
 * - `co2: 'tCO₂'` — 같은 화면에 연료 질량과 CO₂ 질량이 나란히 놓인다. 둘 다 `t`면
 *   무엇의 질량인지 구분되지 않는다. 저장소 안에서도 `PRD §3.4.2`(연료 CF 표
 *   헤더 `CF, tCO₂/tFuel`)·`§9.4`(단위표)가 이미 `tCO₂`를 쓴다.
 */
export const DISPLAY_UNITS = {
  /** 연료 사용량 */
  fuel: 't',
  /** CO₂ 배출량 */
  co2: 'tCO₂',
  /** 항해거리 — 나노미터와 기호가 겹치나 해운 실무 표기다 (`§4.1`) */
  distance: 'nm',
  /** 운항 시간 */
  duration: 'h',
  /** 평균 속력 (노트) */
  speed: 'kn',
} as const

/**
 * 십진 문자열을 지정한 소수 자릿수로 표시한다.
 *
 * - 자릿수가 모자라면 `0`으로 채운다.
 * - 넘치면 `ROUND_HALF_UP`으로 반올림한다.
 * - 부동소수점을 거치지 않으므로 원본 정밀도가 손상되지 않는다.
 *
 * @example
 * formatDecimalString('4.982400', 3)  // '4.982'
 * formatDecimalString('4.9825', 3)    // '4.983'  (half-up)
 * formatDecimalString('80', 2)        // '80.00'
 */
export function formatDecimalString(value: string, digits: number): string {
  if (!Number.isInteger(digits) || digits < 0) {
    throw new RangeError(`digits는 0 이상의 정수여야 합니다: ${digits}`)
  }

  const trimmed = value.trim()
  if (!/^[+-]?\d+(\.\d+)?$/.test(trimmed)) {
    throw new TypeError(`십진 문자열이 아닙니다: ${JSON.stringify(value)}`)
  }

  const negative = trimmed.startsWith('-')
  const unsigned = trimmed.replace(/^[+-]/, '')
  const [intPart, fracPart = ''] = unsigned.split('.')

  let resultInt = intPart
  let resultFrac: string

  if (fracPart.length <= digits) {
    resultFrac = fracPart.padEnd(digits, '0')
  } else {
    const keep = fracPart.slice(0, digits)
    const roundUp = fracPart.charCodeAt(digits) >= '5'.charCodeAt(0)
    if (roundUp) {
      const carried = addOne(resultInt + keep)
      // 자리올림으로 정수부 길이가 늘어날 수 있다 (9.99 → 10.0)
      const cut = carried.length - digits
      resultInt = digits === 0 ? carried : carried.slice(0, cut)
      resultFrac = digits === 0 ? '' : carried.slice(cut)
    } else {
      resultFrac = keep
    }
  }

  resultInt = stripLeadingZeros(resultInt)
  const body = digits === 0 ? resultInt : `${resultInt}.${resultFrac}`
  // -0.000 같은 표기를 만들지 않는다
  const isZero = /^0(\.0*)?$/.test(body)
  return negative && !isZero ? `-${body}` : body
}

/** 십진 숫자 문자열에 1을 더한다. 부동소수점을 쓰지 않는다. */
function addOne(digitsOnly: string): string {
  const chars = digitsOnly.split('')
  let i = chars.length - 1
  while (i >= 0) {
    if (chars[i] === '9') {
      chars[i] = '0'
      i -= 1
    } else {
      chars[i] = String(Number(chars[i]) + 1)
      return chars.join('')
    }
  }
  return `1${chars.join('')}`
}

function stripLeadingZeros(intPart: string): string {
  const stripped = intPart.replace(/^0+/, '')
  return stripped === '' ? '0' : stripped
}

/**
 * 정수부에 천단위 구분자를 넣는다.
 *
 * `DESIGN_SYSTEM §4.2` 「천단위 구분자」 — **연료 · 거리 · CO₂ 전용**이다.
 * CII · 비율 · 확률에는 쓰지 않는다(`GROUPED_FIELDS` 참조).
 *
 * **`toLocaleString()`을 쓰지 않는다.** 그것은 `number`를 받으므로 안전 정수 범위를
 * 넘는 값에서 정밀도가 깨지고, 로케일에 따라 구분자가 `.`이 되기도 한다.
 * 정수부 문자열을 뒤에서 세 자리씩 끊는다.
 *
 * @example
 * formatGrouped('12480', 0)      // '12,480'
 * formatGrouped('1000.04', 1)    // '1,000.0'
 * formatGrouped('80', 1)         // '80.0'      천 단위 미만은 그대로
 */
export function formatGrouped(value: string, digits: number): string {
  const formatted = formatDecimalString(value, digits)
  const negative = formatted.startsWith('-')
  const unsigned = negative ? formatted.slice(1) : formatted
  const [intPart, fracPart] = unsigned.split('.')

  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const body = fracPart === undefined ? grouped : `${grouped}.${fracPart}`
  return negative ? `-${body}` : body
}

/**
 * 소수 비율을 백분율 문자열로 바꾼다.
 *
 * `DESIGN_SYSTEM §4.2` 「비율」 — **API는 소수 문자열(`"0.98758"`)로 내려오고
 * 백분율 환산과 반올림은 표시 시점에만** 적용한다. `§4.1`의 3자리 규칙을 그대로
 * 적용하면 `0.988`이 되어 의미가 전달되지 않는다.
 *
 * **`% 기호는 붙이지 않는다.** 단위 부착은 호출부 책임이다(모듈 주석 참조).
 *
 * 곱셈을 쓰지 않고 **소수점 위치를 두 칸 옮긴다** — `Number('0.98758') * 100`은
 * `98.75800000000001`이 된다.
 *
 * @example
 * formatPercent('0.98758')   // '98.8'
 * formatPercent('0.072')     // '7.2'
 * formatPercent('1')         // '100.0'
 */
export function formatPercent(value: string, digits: number = DISPLAY_DIGITS.percent): string {
  const trimmed = value.trim()
  if (!/^[+-]?\d+(\.\d+)?$/.test(trimmed)) {
    throw new TypeError(`십진 문자열이 아닙니다: ${JSON.stringify(value)}`)
  }

  const negative = trimmed.startsWith('-')
  const unsigned = trimmed.replace(/^[+-]/, '')
  const [intPart, fracPart = ''] = unsigned.split('.')

  // 소수점을 오른쪽으로 두 칸. 모자라면 0으로 채운다.
  const padded = fracPart.padEnd(2, '0')
  const shiftedInt = `${intPart}${padded.slice(0, 2)}`
  const shiftedFrac = padded.slice(2)
  const shifted = shiftedFrac === '' ? shiftedInt : `${shiftedInt}.${shiftedFrac}`

  return formatDecimalString(negative ? `-${shifted}` : shifted, digits)
}
