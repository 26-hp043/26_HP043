import { formatDecimalString } from './format'

/**
 * 표시 자릿수에서의 십진 사칙 (`#739` · `#820`).
 *
 * ⚠️ **Layer 1·Layer 2 값에 `parseFloat`·`Number`를 쓰지 않는다**
 * (`API_SPEC §1.7` `[ORACLE-C-1]`). `BigInt`는 정밀도를 잃지 않으므로 그 금지에
 * 걸리지 않는다 — 막는 것은 `Decimal` 30자리를 float 53비트로 눌러 담는 일이지
 * 정수 연산이 아니다.
 *
 * ## 왜 기능 폴더 밖에 있나
 *
 * 원래 `features/scenario-comparison/comparisonRules.ts` 안에 있었다(`#739`).
 * `#820`에서 연간 시뮬레이션 화면이 같은 계산을 필요로 했는데, **복사하면 한쪽만
 * 고쳐질 수 있다** — `#820`이 고치는 결함이 정확히 그 모양이다(`toPercent`는
 * 반올림을 고쳤는데 형제인 `riskFlag`는 옛 경로에 남았다). 그래서 옮겨 공유한다.
 *
 * ## **표시값**으로 계산한다
 *
 * 원본이 아니라 `formatDecimalString`이 낸 고정 자릿수 문자열을 정수로 올려 다룬다.
 * 사용자는 화면의 두 값을 눈으로 더하고 빼 보고 결과와 맞는지 확인한다. 원본으로
 * 계산하면 `106.2` · `111.5` 옆에 `+5.4`가 붙는 일이 생긴다 — 숨은 자리 때문에 맞는
 * 값인데, **화면만 보는 사람에게는 셋 중 하나가 틀린 것으로 보인다.**
 */

/** 고정 자릿수 십진 문자열을 그 자릿수만큼 올린 정수로. `'106.2'`·1 → `1062n` */
function displayScaled(value: string, digits: number): bigint {
  const fixed = formatDecimalString(value, digits)
  const negative = fixed.startsWith('-')
  const magnitude = BigInt(fixed.replace(/[^0-9]/g, ''))
  return negative ? -magnitude : magnitude
}

/** 올린 정수를 다시 십진 문자열로. `53n`·1 → `'5.3'` */
function unscale(scaled: bigint, digits: number): string {
  const negative = scaled < 0n
  const absolute = (negative ? -scaled : scaled).toString().padStart(digits + 1, '0')
  const cut = absolute.length - digits
  const body = digits === 0 ? absolute : `${absolute.slice(0, cut)}.${absolute.slice(cut)}`
  return negative ? `-${body}` : body
}

/** 표시 자릿수에서의 `a - b`. 부호를 포함한 십진 문자열이다. */
export function subtractFixed(a: string, b: string, digits: number): string {
  return unscale(displayScaled(a, digits) - displayScaled(b, digits), digits)
}

/** 표시 자릿수에서의 `a + b`. 부호를 포함한 십진 문자열이다. */
export function addFixed(a: string, b: string, digits: number): string {
  return unscale(displayScaled(a, digits) + displayScaled(b, digits), digits)
}

/**
 * 표시 자릿수에서의 비교. `a < b`면 음수, 같으면 0, 크면 양수.
 *
 * **임계 판정에 쓴다.** `Number(a) >= 0.4` 같은 비교는 `0.3500 + 0.0500`이
 * `0.39999999999999997`이 되는 순간 **표시된 숫자와 다른 답**을 낸다 (`#820`).
 */
export function compareFixed(a: string, b: string, digits: number): number {
  const left = displayScaled(a, digits)
  const right = displayScaled(b, digits)
  if (left === right) return 0
  return left < right ? -1 : 1
}
