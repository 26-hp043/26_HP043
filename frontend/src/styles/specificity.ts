/**
 * CSS **특이도**를 셈한다 — `#2015`가 표에서 쓰던 것을 꺼내 한 곳에 둔다 (`#2047`).
 *
 * ## 왜 공용으로 두나
 *
 * 「규칙은 코드에 있는데 화면에서 진다」가 이 저장소에서 되풀이되는 실패다
 * (`#1770` · `#2015` · `#2047`). 그것을 보려면 특이도를 계산해야 하는데, 검사마다
 * 제 사본을 두면 **사본이 갈린다** — `#2046`이 컨트롤 블록 일곱 줄의 사본 넷에서
 * 같은 줄이 빠진 것을 찾은 것과 같은 유형이다.
 */

/** `[ids, classes, elements]` — 앞자리부터 견준다. */
export type Specificity = readonly [number, number, number]

/**
 * `#id` · `.class`/`[attr]`/`:pseudo` · 요소를 센다.
 *
 * `::before`는 요소 쪽이고, `:not(...)`은 괄호 안을 그대로 센다(명세대로다).
 */
export function specificity(selector: string): Specificity {
  const cleaned = selector.replace(/::[a-z-]+/g, ' el ').replace(/:not\(([^)]*)\)/g, ' $1 ')
  const ids = (cleaned.match(/#[\w-]+/g) ?? []).length
  const classes = (cleaned.match(/\.[\w-]+|\[[^\]]+\]|:[a-z-]+(\([^)]*\))?/g) ?? []).length
  const elements = (cleaned.match(/(^|[\s>+~])(el|[a-z][\w-]*)(?![\w-]*[({])/g) ?? []).length
  return [ids, classes, elements]
}

/** `a`가 `b`를 **이기는가**. 같으면 거짓 — 그때는 소스 순서가 판정한다. */
export function stronger(a: Specificity, b: Specificity): boolean {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] > b[i]
  }
  return false
}

/** 선택자를 조합자로 끊는다 — `.a .b > c` → `['.a', '.b', 'c']`. */
export function compounds(selector: string): string[] {
  return selector.trim().split(/[\s>+~]+/).filter(Boolean)
}
