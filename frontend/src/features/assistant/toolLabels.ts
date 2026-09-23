/**
 * 서버 도구 이름 → 화면에 적는 한국어 (#1818).
 *
 * ## 왜 필요한가
 *
 * 응답의 `tool_calls`는 **그 답의 값을 무엇이 냈는지**를 말한다(`API_SPEC §15.1`).
 * 그 값을 답 아래 적으면 `§20 O-12`의 No-Compute가 화면에서도 읽힌다 — 챗봇이
 * 값을 지어내지 않고 **계산이 낸 값을 인용**한다는 것이 보이기 때문이다.
 *
 * ⚠️ **도구 이름을 그대로 적지 않는다.** `project_year_end`는 개발의 말이다.
 *
 * ## 문구가 왜 여기 있나
 *
 * `DESIGN_SYSTEM §16` 항목 18(어시스턴트 문구의 소유)이 **대기**다. 이 파일의 문구는
 * `AssistantOverlay.tsx`가 이미 들고 있는 여섯과 **같은 자리**이며, 항목 18이 정해지면
 * **함께** 옮긴다.
 */

/**
 * `services/chat_tools.py`의 `TOOL_*` 상수와 짝이다 —
 * `toolLabels.sync.test.ts`가 대조한다. 도구가 늘면 그 검사가 먼저 붉어진다.
 */
export const TOOL_LABELS: Readonly<Record<string, string>> = {
  search_vessel: '선박 찾기',
  calc_voyage_cii: '항차 CII 계산',
  compare_scenarios: '속도 시나리오 비교',
  project_year_end: '연말 예상 계산',
  explain_screen_result: '화면의 계산 결과',
  lookup_regulation: '규제 기준값 표',
}

/** 근거 줄 앞에 붙는 말. 칩 하나가 무엇인지 낭독에도 실린다. */
export const CITE_LABEL = '근거'

/**
 * 한 턴이 부른 도구들을 **중복 없이 순서대로** 한국어로 바꾼다.
 *
 * 모르는 이름은 **버린다** — 풀이집에 없는 도구가 생기면 위 동기화 검사가 잡는 것이
 * 맞고, 화면에 `project_year_end` 같은 날것이 나가는 쪽이 더 나쁘다.
 */
export function citeLabels(toolCalls: readonly string[] | undefined): readonly string[] {
  if (!toolCalls || toolCalls.length === 0) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const name of toolCalls) {
    const label = TOOL_LABELS[name]
    if (!label || seen.has(label)) continue
    seen.add(label)
    out.push(label)
  }
  return out
}
