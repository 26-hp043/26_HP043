import { DISPLAY_DIGITS } from '../../display/format'
import type { Rating } from './types'

/**
 * 「이 등급이 되려면 연료를 얼마나 줄여야 하나」 — 화면 파생 참고값 (`#727`).
 *
 * ## 왜 `resultRules.ts`에 두지 않는가
 *
 * 그 모듈은 **「Layer 1 값에 `parseFloat`·`Number`를 쓰지 않는다」**(`API_SPEC §1.7`
 * `[ORACLE-C-1]` · `#136` 완료 기준)를 헤더에 못박고, 「0보다 큰가」 같은 판단까지
 * 문자열로 한다. 여기서 하는 일은 그 계약과 정면으로 다르므로 **파일을 나눈다** —
 * 한 모듈 안에 「숫자로 만지지 않는다」와 「숫자로 만진다」가 같이 있으면, 나중에
 * 읽는 사람이 어느 쪽이 이 파일의 규칙인지 알 수 없다.
 *
 * ## 여기서 숫자 연산이 허용되는 이유
 *
 * 이 모듈이 만드는 값은 **서버가 보낸 규제값이 아니라 화면이 새로 만든 안내값**이다.
 * `ORACLE-C-1`이 막는 것은 Layer 1이 `Decimal` 30자리로 지킨 값을 화면이 되돌려
 * **같은 자리에 다시 내보내는 것**이다. 반면 여기 결과는 원본으로 되돌아가지 않고,
 * 표시 자릿수(연료 1자리)까지만 뜻을 갖는다. 800 t 규모에서 1자리는 상대오차
 * 1e-4이고 float64는 1e-16이라 자릿수가 흔들릴 여지가 없다.
 *
 * **그래도 안전한 방향으로 내림한다.** 「이 값 이하면 C 등급」이라고 적는 자리라
 * 반올림으로 0.05 t 올라가면 경계를 넘은 값을 허용치로 적게 된다. 넘치는 쪽이
 * 틀리고 모자란 쪽은 틀리지 않으므로 내림이 유일하게 맞는 방향이다.
 *
 * ## 유종 구성을 몰라도 된다
 *
 * `attained_CII = M / W`이고 `M = Σ(연료ᵢ × CFᵢ)`, `W`는 연료와 무관하다. 모든
 * 연료를 같은 배율 `k`로 줄이면 `M`도 정확히 `k`배이므로 `attained`도 `k`배다.
 * 따라서 **목표 CII / 현재 CII** 가 그대로 연료 배율이 된다 — CF도, 유종별 배분도
 * 필요 없다. 이것이 「모든 유종을 같은 비율로 줄인다」를 가정으로 명시하는 이유다.
 * 특정 유종만 줄이는 계획은 배분이 하나로 정해지지 않아 화면이 답할 수 없다.
 */

/** 목표 등급 한 줄. **전부 표시용 문자열이며 규제값이 아니다.** */
interface GradeTarget {
  /** 목표 등급 */
  rating: Rating
  /** 그 등급의 상한 CII (`required_cii × d`) */
  boundaryCii: string
  /** 그 CII 이하가 되는 총 연료 상한. 내림. */
  allowedFuelTon: string
  /** 현재 연료 − 상한. 화면에서 두 값을 빼 볼 것이므로 상한에서 되계산한다. */
  reduceFuelTon: string
  /** 감축률(%) */
  reducePercent: string
}

/** 계산에 필요한 것만 받는다 — 응답 전체를 받으면 이 모듈이 응답 형태를 소유하게 된다. */
interface TargetInputs {
  estimated_rating: Rating
  required_cii: string
  attained_cii: string
  fuel_consumption_ton: string
}

/** `d1`~`d4`는 각각 A·B·C·D 등급의 **상한** 배율이다. E는 상한이 없다. */
interface RatingBoundary {
  d1: string
  d2: string
  d3: string
  d4: string
}

/*
 * `resultRules.nextWorseRating`도 같은 배열을 갖는다. 공유 상수로 빼지 않은 것은
 * 그 모듈을 여기서 import 하면 「문자열로만 판단한다」는 파일과 「숫자로 만진다」는
 * 파일이 다시 엮이기 때문이다. 다섯 글자짜리 배열의 중복이 그 결합보다 싸다.
 */
const RATING_ORDER: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

/**
 * 현재보다 나은 등급마다 「연료 상한 / 감축량 / 감축률」을 낸다.
 *
 * 등급 A면 오를 곳이 없어 빈 배열이다. 값이 하나라도 읽히지 않거나 앞뒤가 맞지
 * 않으면 **통째로 빈 배열**이다 — 일부만 그리면 나머지 등급은 「방법이 없다」로
 * 읽히고, 그것은 사실이 아니다.
 */
export function gradeTargets(data: TargetInputs, boundary: RatingBoundary): GradeTarget[] {
  const required = Number(data.required_cii)
  const attained = Number(data.attained_cii)
  const fuel = Number(data.fuel_consumption_ton)
  if (!(required > 0) || !(attained > 0) || !(fuel > 0)) return []

  const currentIndex = RATING_ORDER.indexOf(data.estimated_rating)
  if (currentIndex <= 0) return []

  const ratios = [boundary.d1, boundary.d2, boundary.d3, boundary.d4]
  const targets: GradeTarget[] = []

  for (let i = 0; i < currentIndex; i += 1) {
    const d = Number(ratios[i])
    if (!Number.isFinite(d) || d <= 0) return []

    const boundaryCii = required * d
    const allowed = floorTo(fuel * (boundaryCii / attained), DISPLAY_DIGITS.fuelTon)

    /*
     * 현재보다 나은 등급이므로 상한은 반드시 현재 연료보다 적다. 그렇지 않다면
     * 등급과 수치가 어긋난 응답이고, 그때 안내를 지어내면 안 된다.
     */
    if (!(allowed >= 0) || allowed >= fuel) return []

    const reduce = roundTo(fuel - allowed, DISPLAY_DIGITS.fuelTon)

    targets.push({
      rating: RATING_ORDER[i],
      boundaryCii: boundaryCii.toFixed(DISPLAY_DIGITS.cii),
      allowedFuelTon: allowed.toFixed(DISPLAY_DIGITS.fuelTon),
      reduceFuelTon: reduce.toFixed(DISPLAY_DIGITS.fuelTon),
      reducePercent: ((reduce / fuel) * 100).toFixed(DISPLAY_DIGITS.percent),
    })
  }

  return targets
}

function floorTo(value: number, digits: number): number {
  const scale = 10 ** digits
  return Math.floor(value * scale) / scale
}

function roundTo(value: number, digits: number): number {
  const scale = 10 ** digits
  return Math.round(value * scale) / scale
}
