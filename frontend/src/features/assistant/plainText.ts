/**
 * 모델 답에 섞여 들어온 마크다운 기호를 **화면에서만** 걷는다 (`#2064`).
 *
 * ## 왜 걷는가 — 그리지 않고
 *
 * 말풍선은 평문이다(`AssistantOverlay.css`의 `white-space: pre-wrap`). 마크다운을
 * **그리는** 쪽으로 가면 모델이 낸 문자열을 HTML로 바꾸는 경로가 생기고, 그 경로는
 * 외부 LLM이 낸 문자열을 신뢰하는 경로다. 이 제품에서 그 신뢰는 비싸다.
 *
 * 그래서 방향은 이슈의 ⒞다 — **프롬프트로 줄이고, 새어 나온 기호는 화면이 걷는다.**
 * 프롬프트만으로는 모자란다(모델은 가끔 샌다). 화면만으로도 모자란다(걷어 낸 자리에
 * 의도했던 강조가 사라진다). 둘이 같이 있어야 한다.
 *
 * ## 원문은 건드리지 않는다
 *
 * 저장된 대화는 감사 기록이다 — 모델이 낸 그대로 둔다. 이 함수는 **그리기 직전**에만
 * 불린다. `apiProvider`(받아서 상태에 넣는 쪽)는 이 모듈을 알지 못하며,
 * `plainText.test.ts`가 그 경계를 잠근다.
 *
 * ## 밑줄(`_`)은 걷지 않는다
 *
 * 프롬프트가 모델에게 `source_ref` · `condition_expr` · `reduction_factor.by_year`를
 * **답에 적으라고** 시킨다(`#1703` · `#1973`). `_강조_`를 걷으려고 밑줄 쌍을 지우면
 * 그 칸 이름들이 망가진다. 별표는 그런 짝이 없으므로 걷는다.
 */

/** ```로 시작하는 코드 울타리 줄. 안의 내용은 남기고 울타리만 걷는다. */
const FENCE = /^\s*```.*$/
/** 제목 — `#` 한 개에서 여섯 개까지. */
const HEADING = /^(\s*)#{1,6}\s+/
/** 목록 머리 — `-` · `*` · `+`. */
const BULLET = /^(\s*)[-*+][ \t]+/
/** 인용 — `>`. */
const QUOTE = /^(\s*)>[ \t]?/

/** `[글자](주소)` → `글자`. */
const LINK = /\[([^\]\n]+)\]\([^)\s]*\)/g
/** 홑백틱 코드. */
const CODE = /`([^`\n]+)`/g
/** 별표 둘로 묶은 강조. */
const STRONG = /\*\*(\S(?:[^*\n]*\S)?)\*\*/g
/** 별표 하나로 묶은 강조 — 둘을 먼저 걷고 남은 것만 본다. */
const EMPHASIS = /\*(\S(?:[^*\n]*\S)?)\*/g

/**
 * 목록 머리는 **지우지 않고 가운뎃점으로 바꾼다.**
 *
 * 통째로 지우면 평문에서 줄들이 한 덩어리로 보여 목록이었다는 것이 사라진다.
 * `·`는 이 제품이 이미 쓰는 구분자다(사이드바 · 브랜드 판 · 인용 줄).
 */
const BULLET_MARK = '· '

export function stripMarkdown(text: string): string {
  return text
    .split('\n')
    .filter((line) => !FENCE.test(line))
    .map((line) =>
      line
        .replace(HEADING, '$1')
        .replace(QUOTE, '$1')
        .replace(BULLET, `$1${BULLET_MARK}`)
        .replace(LINK, '$1')
        .replace(CODE, '$1')
        .replace(STRONG, '$1')
        .replace(EMPHASIS, '$1'),
    )
    .join('\n')
}
