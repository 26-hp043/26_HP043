/**
 * 한국어 조사 (#598).
 *
 * ## 왜 함수인가
 *
 * 화면이 상태 이름을 문장에 끼워 넣는다 — 「**실적 확정**으로 전환」. 그런데 이름마다
 * 받침이 갈려서 **한 문자열로는 맞출 수 없다.**
 *
 * ```
 * 실적 확정 + 으로   ← 받침 ㅇ
 * 항해 완료 + 로     ← 받침 없음
 * ```
 *
 * 종전에는 `(으)로`로 적어 두 경우를 함께 냈는데, 화면에 **괄호가 그대로 보였다**
 * (`VoyagePanel.tsx`). 안내문에 괄호가 섞이면 읽는 사람이 「무엇을 고르라는 건가」로
 * 멈춘다.
 *
 * 그 자리에서 삼항 연산으로 때우지 않는 이유는 **다음 자리에서 다시 짜게 되기**
 * 때문이다. 받침 판정은 한 곳에 둔다.
 *
 * ## 받침 판정
 *
 * 한글 음절은 유니코드에서 `0xAC00`부터 **초성 × 중성 × 종성(28)** 순서로 배열돼
 * 있다. 그래서 `(코드 - 0xAC00) % 28`이 곧 종성 번호이며, 0이면 받침이 없다.
 * 표를 두지 않고 계산으로 얻는 이유는 그 표가 11,172행이기 때문이다.
 */

const HANGUL_BASE = 0xac00
const HANGUL_LAST = 0xd7a3
const FINAL_COUNT = 28

/**
 * 끝의 괄호 설명 — 「총톤수(GT)」의 「(GT)」. 조사는 **그 앞 낱말**을 따른다 (`#1369`).
 *
 * 서버가 같은 규칙을 쓴다(`api/validation_messages.py`의 `_TRAILING_PAREN`). 이것이
 * 없으면 라벨 여섯(`총톤수(GT)` · `재화중량톤수(DWT)` · `방형계수(CB)` ·
 * `시작 시각(부터)` · `시작 시각(까지)` · `난수 시드(seed)`)에서 **화면과 서버가 다른
 * 조사를 낸다** — 「시작 시각(부터)은」 vs 「시작 시각(부터)는」.
 */
const TRAILING_PAREN = /\s*\([^()]*\)\s*$/

/** 종성 번호 중 `ㄹ`. `로`·`으로`가 갈리는 유일한 예외다. */
const FINAL_RIEUL = 8

/**
 * 마지막 글자의 종성 번호. 한글 음절이 아니면 `null`.
 *
 * **모르면 `null`이다.** 영문·숫자로 끝나는 이름(`LNG운반선`은 한글로 끝나지만
 * `HFO`는 아니다)에 받침을 단정하면 틀린 조사가 붙는다. 호출부가 그때 무엇을 할지
 * 정한다 — 여기서 「받침 있음」으로 기울이면 그 판단이 숨는다.
 */
export function finalConsonant(word: string): number | null {
  const last = word.replace(TRAILING_PAREN, '').trim().slice(-1)
  if (last === '') return null

  const code = last.charCodeAt(0)
  if (code < HANGUL_BASE || code > HANGUL_LAST) return null
  return (code - HANGUL_BASE) % FINAL_COUNT
}

/**
 * 방향을 나타내는 조사 — 「로」 또는 「으로」.
 *
 * 받침이 없거나 `ㄹ` 받침이면 「로」다(「서울**로**」). 그 외에는 「으로」.
 *
 * 한글로 끝나지 않으면 **「로」를 쓴다.** 영문 약어는 읽는 방식이 사람마다 달라
 * 받침을 단정할 수 없고(`HFO`를 「에이치에프오」로 읽으면 받침이 없다), 둘 중
 * 하나를 골라야 한다면 괄호 없이 자연스러운 쪽이 낫다.
 */
export function ro(word: string): string {
  const final = finalConsonant(word)
  if (final === null) return '로'
  return final === 0 || final === FINAL_RIEUL ? '로' : '으로'
}

/** 「{말}로」 · 「{말}으로」를 한 문자열로. */
export function withRo(word: string): string {
  return `${word}${ro(word)}`
}

/**
 * 목적격 조사 — 「을」 또는 「를」 (2026-09-11 디자인 확정 B).
 *
 * 받침이 있으면 「을」(「선박 목록**을**」), 없으면 「를」(「연료**를**」).
 *
 * 한글로 끝나지 않으면 **「를」을 쓴다** — `ro`와 같은 판단이다. `CSV`·`HFO`는 영문
 * 이름으로 읽으면 받침이 없다.
 */
export function eulReul(word: string): string {
  const final = finalConsonant(word)
  return final === null || final === 0 ? '를' : '을'
}

/** 「{말}을」 · 「{말}를」을 한 문자열로. */
export function withEulReul(word: string): string {
  return `${word}${eulReul(word)}`
}

/**
 * 주격 조사 — 「은」 또는 「는」 (`#1369`).
 *
 * 받침이 있으면 「은」(「선명**은**」), 없으면 「는」(「총톤수(GT)**는**」).
 *
 * ## 왜 함수인가 — 종전에는 화면이 「은(는)」을 **박아** 썼다
 *
 * 검증 문구 여덟 자리가 `${label}은(는) …`을 그대로 적었다. 같은 오류를 서버가 낼
 * 때는 받침을 계산해 **하나만** 쓰므로(`api/validation_messages.py`), 사용자가 같은
 * 실수에 **두 가지 문구**를 보게 된다 — 화면에서 막히면 「총톤수(GT)은(는) 0보다 커야
 * 합니다」, 서버까지 가면 「총톤수(GT)는 0보다 커야 합니다」.
 *
 * 한글로 끝나지 않으면 **「는」을 쓴다** — `eulReul`과 같은 판단이다(2026-09-11 디자인
 * 확정 B: 괄호를 화면에 내보내지 않는다). ⚠️ 서버는 그 경우 「은(는)」을 적으므로 이
 * 한 갈래는 아직 갈린다. 다만 현재 서버 라벨 118개 중 **한글로 끝나지 않는 것은 0개**라
 * 실제로 닿지 않는다(실측).
 */
export function eunNeun(word: string): string {
  const final = finalConsonant(word)
  return final === null || final === 0 ? '는' : '은'
}

/** 「{말}은」 · 「{말}는」을 한 문자열로. */
export function withEunNeun(word: string): string {
  return `${word}${eunNeun(word)}`
}
