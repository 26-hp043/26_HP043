/**
 * Layer 1 문자열의 표시 형식 변환.
 *
 * **문자열을 받아 문자열을 반환한다.** `parseFloat()`·`Number()`를 쓰지 않는다 —
 * `API_SPEC §1.7` `[ORACLE-C-1]`이 Layer 1 값을 문자열로 직렬화하는 이유가
 * JSON float 파싱의 정밀도 손실을 막기 위해서인데, 화면에서 되돌리면 그 보호가 사라진다.
 *
 * 자릿수는 `PRD §9.3` 표를 따른다 — CII 3자리 · 연료 2자리 · CO₂ 2자리 · 거리 1자리.
 * `DESIGN_SYSTEM §4.1`도 CII 소수점 3자리 고정으로 같은 값을 규정한다.
 * 반올림은 `TECH_SPEC`의 `ROUND_HALF_UP`을 따른다.
 */

/** `PRD §9.3` 화면 표시 자릿수. */
export const DISPLAY_DIGITS = {
  /** CII 값 — attained · required · 경계 · margin */
  cii: 3,
  /** 연료 사용량 (ton) */
  fuelTon: 2,
  /** CO₂ 배출량 (tCO₂) */
  co2Ton: 2,
  /** 항해거리 (nm) */
  distanceNm: 1,
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
