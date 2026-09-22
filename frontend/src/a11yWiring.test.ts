import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { dirOf, srcKey } from './test/srcPaths'

/**
 * 접근성 배선의 회귀를 막는다 (#829 ⑸).
 *
 * ## 왜 소스로 보는가
 *
 * 이 성질들은 **화면이 깨지지 않는다.** `role`을 빼도 그림은 그대로이고, 달라지는
 * 것은 낭독뿐이라 눈으로도 기존 검사로도 드러나지 않는다. 그래서 소스에서 본다 —
 * `moduleBoundary.test.ts`·`deadCss.test.ts`와 같은 규율이다.
 */
const SRC = dirOf(import.meta.url)

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sources(path)
    if (!/\.tsx$/.test(name) || name.includes('.test.')) return []
    return [path]
  })
}

const FILES = sources(SRC).map((path) => ({ path: srcKey(SRC, path), text: readFileSync(path, 'utf8') }))

describe('접근성 배선 (#829 ⑸)', () => {
  it('검증 오류 문구에 role="alert"가 있다', () => {
    /*
     * 없으면 **검증 실패가 아무것도 안 읽힌다.** 화면에는 빨간 글씨가 떠 있는데
     * 스크린 리더 쪽에서는 제출이 조용히 실패한 것으로 보인다. 26곳이 그 상태였다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(span|em|p)\s+className="[a-z-]+__field-error"([^>]*)>/g)) {
        if (!match[2].includes('role="alert"')) offenders.push(`${path} :: ${match[0].trim()}`)
      }
    }
    expect(offenders).toEqual([])
  })

  /*
   * `#936` — **이관이 끝났다. 이제부터는 회귀 가드다.**
   *
   * `§8.4`가 배선을 `Field`로 모으기 전, 폼 컨트롤 87곳 중 `aria-invalid`가 붙은 것은
   * **18곳**이었다. 나머지는 오류를 색으로만 말하고 있었고(`§14` 위반), 라벨·힌트가
   * 컨트롤에 프로그램적으로 닿지 않았다.
   *
   * 그동안은 **허용 목록(`NOT_YET_MIGRATED`)으로 셌다** — 「전부 `Field`를 써야 한다」로
   * 처음부터 잠그면 이관이 끝날 때까지 빨간불이라 아무도 보지 않게 되기 때문이다.
   * 목록은 `#1180`·`#1181`·`#1182`를 거쳐 비었고(13 → 10 → 5 → 0), 이 PR에서 **지운다.**
   *
   * 지금부터 호출부가 직접 적은 `aria-invalid`는 곧 배선을 다시 쓴 것이므로 실패한다.
   */

  /*
   * **`Field`를 씌울 수 없는 컨트롤이 실제로 있다.**
   *
   * 표 안의 입력칸이 그렇다 — 보이는 `<label>`이 없고 이름은 열 제목과 `aria-label`이
   * 준다. `Field`를 씌우면 셀마다 라벨 줄이 하나씩 생겨 표가 무너진다.
   *
   * 예외를 파일 단위로 두면 **같은 파일의 나머지 칸이 가드 밖으로 빠진다.** 그래서
   * **줄 단위**로 두고, 이유를 함께 적게 한다. 표식이 없으면 그대로 실패한다.
   */
  const FIELD_EXEMPTION = 'Field 예외(#936)'

  it('폼 컨트롤 배선을 Field에 맡긴다 (#936)', () => {
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      // 직접 적은 `aria-invalid`는 `Field`가 줄 배선을 호출부가 다시 쓴 것이다.
      for (const match of text.matchAll(/\saria-invalid=/g)) {
        // 바로 앞 다섯 줄 안에 이유를 적은 표식이 있으면 넘긴다.
        const before = text.slice(0, match.index).split('\n').slice(-6).join('\n')
        if (before.includes(FIELD_EXEMPTION)) continue
        offenders.push(`${path} :: ${text.slice(match.index, (match.index ?? 0) + 40).trim()}`)
      }
    }
    expect(
      offenders,
      'Field가 배선을 주므로 호출부가 aria-invalid를 적을 필요가 없다. ' +
        `씌울 수 없는 칸이라면 «${FIELD_EXEMPTION}» 주석에 이유를 적어 두세요.`,
    ).toEqual([])
  })

  it('예외 표식이 실제로 무언가를 넘기고 있다', () => {
    /* 표식이 아무 데도 안 걸리면 위 검사가 조용히 헐거워진 것이다 — 오타든 삭제든. */
    const marked = FILES.filter((f) => f.text.includes(FIELD_EXEMPTION))
    expect(marked.length, '예외 표식이 한 곳도 쓰이지 않는다').toBeGreaterThan(0)
  })

  it('role 없는 요소에 aria-label을 걸지 않는다', () => {
    /*
     * `role`이 없는 `<span>`·`<div>`의 `aria-label`은 **무시된다.** 라벨을 적어 둔
     * 사람은 읽힌다고 믿는데 실제로는 아무 이름도 없다.
     *
     * 조건부 라벨(`aria-label={x ? … : undefined}`)은 `role`도 같은 조건이면 되므로,
     * 여기서는 **`role=`이라는 낱말이 같은 태그 안에 있는지**만 본다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(span|div|p|li|ul)\s([^>]*)>/g)) {
        /*
         * **속성 자리의 주석을 걷어낸다.** 「`role="img"`가 있어야 읽힌다」고 적어 둔
         * 주석이 그 자체로 `role=`을 담아, 정작 속성이 빠졌을 때 잡히지 않았다 —
         * `deadCss.test.ts`에서 겪은 것과 같은 함정이다.
         */
        const attrs = match[2].replace(/\/\*[\s\S]*?\*\//g, '')
        if (attrs.includes('aria-label') && !attrs.includes('role=')) {
          offenders.push(`${path} :: <${match[1]}>`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  /*
   * `#936` — **JSX 문자열 속성 안에 평가되지 않은 `{표현식}`이 없다.**
   *
   * 이관 중 실제로 났다. `<span>기준 일일 연료소모량 ({DISPLAY_UNIT_DAILY_FUEL})</span>`을
   * `label="..."`로 옮기면서 중괄호가 **문자 그대로 굳어** 화면에 `{DISPLAY_UNIT_DAILY_FUEL}`이
   * 찍히는 상태가 됐다. `tsc`는 그 상수가 안 쓰인다고만 알렸고(다른 참조가 있었으면 그마저
   * 없다) **테스트 90개가 전부 통과했다** — 라벨 문구를 단언하는 검사가 없었기 때문이다.
   *
   * 눈으로도 잘 안 보인다. 단위가 붙는 자리라 「(t/일)」이 「({DISPLAY_UNIT_DAILY_FUEL})」로
   * 바뀐 것을 스쳐 지나가기 쉽다.
   */
  it('문자열 속성에 평가되지 않은 중괄호가 없다 (#936)', () => {
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      text.split('\n').forEach((line, index) => {
        for (const match of line.matchAll(/\s([a-zA-Z-]+)="([^"]*\{[^"]*\}[^"]*)"/g)) {
          offenders.push(`${path}:${index + 1} :: ${match[1]}="${match[2]}"`)
        }
      })
    }
    expect(
      offenders,
      '중괄호를 쓰려면 `attr={`…${expr}…`}` 형태여야 합니다 — 따옴표 안에서는 문자로 굳습니다.',
    ).toEqual([])
  })

  it('본문 바로가기 링크가 있고 main이 초점을 받는다', () => {
    // 없으면 매 화면 진입마다 사이드바 항목을 전부 Tab으로 지나야 한다 (WCAG 2.4.1).
    const shell = FILES.find((f) => f.path.endsWith('layout/AppShell.tsx'))
    expect(shell, 'AppShell.tsx를 찾지 못했습니다').toBeDefined()
    expect(shell!.text).toContain('className="skip-link"')
    expect(shell!.text).toMatch(/<main[^>]*tabIndex=\{-1\}/)
  })

  /**
   * 프로그램적 초점 대상에는 링을 그리지 않는다 — `DESIGN_SYSTEM §14` (`#1283`).
   *
   * 화면 전환마다 `<main>`이 초점을 받는데(`2.4.3` · `#829` ⑸c) 전역
   * `:focus-visible`에 제외가 없어 **본문 전체가 테두리에 감싸였다.**
   *
   * 되돌아가는 길이 둘이라 둘 다 막는다 — 제외 규칙을 지우는 것과, `tabIndex`를
   * 떼어 「고치는」 것이다. 후자는 본문 바로가기를 같이 부순다.
   */
  it('`tabindex="-1"` 초점 대상은 링 제외 규칙을 갖는다 (#1283)', () => {
    const css = readFileSync(join(SRC, 'styles/global.css'), 'utf8')
    const rule = /\[tabindex=['"]-1['"]\]:focus-visible\s*\{[^}]*outline:\s*none/
    expect(
      rule.test(css),
      '`[tabindex="-1"]:focus-visible { outline: none }`이 없습니다 — DESIGN_SYSTEM §14.',
    ).toBe(true)

    // 한 요소를 지목하는 형태로 좁히지 않는다 (`§14` · `#1052` ⓥ와 같은 이유).
    expect(css).not.toMatch(/\.app-shell__main:focus-visible\s*\{[^}]*outline:\s*none/)
  })

  it('라우트가 바뀌면 문서 제목을 갱신한다', () => {
    // SPA는 문서를 다시 읽지 않는다. 갱신하지 않으면 화면이 바뀐 것을 알 수단이 없다.
    const shell = FILES.find((f) => f.path.endsWith('layout/AppShell.tsx'))!
    expect(shell.text).toContain('document.title =')
  })

  it('로딩 문구가 라이브 리전 안에 있다', () => {
    /*
     * `aria-busy` **단독은 아무것도 알리지 않는다.** 「불러오는 중입니다…」가 화면에
     * 떠도 낭독되지 않으면, 사용자는 눌렀는데 아무 일도 없는 것으로 읽는다.
     */
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<(p|em|span)\s+([^>]*aria-busy="true"[^>]*)>/g)) {
        if (!match[2].includes('role="status"')) offenders.push(`${path} :: <${match[1]}>`)
      }
    }
    expect(offenders).toEqual([])
  })
})

/**
 * **비활성의 사유** — `DESIGN_SYSTEM §14` 「비활성 컨트롤은 「왜」를 함께 낸다」
 * (2026-09-18 확정 · `#1170` ⑵).
 *
 * ## 무엇이 안 보였나
 *
 * `disabled`는 요소를 **초점 순서에서 뺀다.** 그래서 잠긴 버튼은 「왜 잠겼는지」가
 * 아니라 **있다는 사실 자체**가 낭독에서 사라진다. 화면은 멀쩡하다 — 이 저장소가
 * 반복해 맞는 꼴이다.
 *
 * 확정은 속성을 바꾸지 않는다. `aria-disabled`로 옮기면 초점은 얻지만 저장소의
 * `:disabled` CSS 규칙 **51개**가 그대로 빠져(`[aria-disabled]`는 **0개**) 비활성임이
 * 보이지 않게 된다. 대신 **사유를 화면과 낭독 양쪽에** 둔다. 초점에 남길지는
 * `§16` 항목 20이 따로 받는다.
 *
 * ## 이 가드가 보는 것
 *
 * **등재**다. 비활성 조건이 `busy`·`saving` 같은 **일시적 진행 중**이면 버튼 글자가
 * 스스로 바뀌므로 대상이 아니고, **선행 조건 미충족**이면 여기 적혀 있어야 한다.
 * 새 버튼이 사유 없이 들어오면 실패한다 — 「선언과 사용이 함께 간다」와 같은 규율이다.
 *
 * 적힌 `describedBy`는 **문자열 두 개가 같은 파일에 함께 있는지**로 확인한다
 * (`id`와 `aria-describedby`). 렌더까지 보지 않는 이유는 이 성질이 조건부 분기라
 * 화면 검사로는 **사유가 뜨는 경우만** 덮이기 때문이다 — 빠진 배선은 소스에서 본다.
 */
describe('비활성의 사유 — §14 (#1170 ⑵)', () => {
  /**
   * 일시적 진행 중 — 대상이 아니다. 버튼 글자가 「저장 중…」으로 바뀌고 몇 초 뒤 돌아온다.
   */
  const TRANSIENT = new Set([
    'busy',
    'busy !== null',
    'busyId !== null',
    'saving',
    'submitting',
    'loading',
    'loadingMore',
    'sortLoading',
    'estimating',
    'isDeleting',
    'exporting',
    'pending',
    'stopped',
    "lookup.current.status === 'loading'",
    "lookup.destination.status === 'loading'",
    "reproduce.status === 'running'",
    "state.status === 'running'",
    "state.status === 'loading'",
    "adopt.status === 'running'",
    'fuelsLoading',
  ])

  /** `사유가 닿는 방법`. 문자열이면 잇는 `id`, `null`이면 곁의 칸이 스스로 말한다. */
  const REGISTERED: Readonly<Record<string, string | null>> = {
    "features/annual-simulation/AnnualSimulation.tsx :: state.status === 'running' || !office":
      'annual-sim-office-only',
    // 빈 질문칸이 바로 위에 있다 — 「무엇을 쓰지 않았는지」를 따로 적지 않는다.
    'features/assistant/AssistantOverlay.tsx :: pending || stopped || draft.trim().length === 0':
      null,
    "features/fleet-reduction/FleetReduction.tsx :: saving || planName.trim() === '' || pricesInvalid":
      'fr-save-blocked',
    // #1325 — 현장직 잠금(`!office`)이 더해졌다. 낭독은 더 근본적인 사유(사무직 전용)를 앞세우고,
    // 사무직이면 종전대로 `scenario-adopt-stale`로 잇는다.
    "features/scenario-comparison/ScenarioAdoptPanel.tsx :: !ready || adopt.status === 'running' || !office":
      'scenario-adopt-office-only',
    "features/scenario-comparison/ScenarioComparison.tsx :: state.status === 'loading' || noVessel || yearUnavailable":
      'sc-no-vessel',
    // #1750 — 두 항의 좌표가 있어야 대권거리를 낼 수 있다. `estimating`은 일시적 진행 중이다.
    'features/scenario-comparison/ScenarioComparison.tsx :: !canEstimate || estimating':
      'sc-estimate-blocked',
    'features/vessel-detail/PositionForm.tsx :: busy || nothingToSave': 'vd-pos-nothing',
    'features/voyage-cii/VoyageCiiActions.tsx :: stale': 'voyage-cii-actions-stale',
    'features/voyage-cii/VoyageCiiActions.tsx :: stale || exporting': 'voyage-cii-actions-stale',
    // 파일 선택칸이 같은 줄에 있다 — 고르지 않았다는 것이 그 칸으로 보인다.
    'features/parameters/ParameterRevision.tsx :: file === null || busy !== null': null,
    // #1517 — 검증을 통과하고 오류가 0건일 때만 연다(전부 아니면 전무). 잠긴 이유를 곁에 적는다.
    'features/parameters/ParameterRevision.tsx :: !ready || busy !== null': 'param-revision-commit-note',
    // 파일 선택칸이 같은 줄에 있다 — 고르지 않았다는 것이 그 칸으로 보인다.
    'features/voyage-management/ImportCsv.tsx :: file === null || busy !== null': null,
    'features/voyage-management/ImportCsv.tsx :: !canCommit(result) || busy !== null':
      'vy-import-commit-note',
    // 행마다 다른 사유라 `id`가 행별로 만들어진다.
    'features/voyage-management/VoyagePanel.tsx :: busy || blocker !== null': 'vy-blocker-',
  }

  /** `disabled=` 앞으로 거슬러 올라가 가장 가까운 여는 태그를 찾는다. */
  function enclosingTag(lines: string[], at: number): string | null {
    for (let i = at; i >= 0 && i > at - 25; i -= 1) {
      const found = /<(button|select|input|textarea|a)\b/.exec(lines[i])
      if (found !== null) return found[1]
    }
    return null
  }

  function preconditionButtons(): string[] {
    const keys: string[] = []
    for (const { path, text } of FILES) {
      const lines = text.split('\n')
      lines.forEach((line, index) => {
        const found = /disabled=\{(.+?)\}\s*>?\s*$/.exec(line)
        if (found === null) return
        const expression = found[1].trim()
        if (expression.split('||').every((term) => TRANSIENT.has(term.trim()))) return
        if (enclosingTag(lines, index) !== 'button') return
        keys.push(`${path} :: ${expression}`)
      })
    }
    return [...new Set(keys)].sort()
  }

  it('선행 조건으로 잠기는 버튼은 전부 등재돼 있다', () => {
    const unregistered = preconditionButtons().filter((key) => !(key in REGISTERED))
    expect(
      unregistered,
      '사유 없이 잠기는 버튼이다 — §14대로 사유를 적고 여기 등재하십시오',
    ).toEqual([])
  })

  it('등재부에 사라진 버튼이 남아 있지 않다', () => {
    /*
     * 목록은 **지워질 수 있어야** 한다. 버튼이 없어졌는데 줄이 남으면 다음 사람이
     * 그 자리를 찾다가 시간을 쓴다 — `RETIRED` 목록이 밟은 함정이다.
     */
    const present = new Set(preconditionButtons())
    expect(Object.keys(REGISTERED).filter((key) => !present.has(key))).toEqual([])
  })

  it('사유를 잇는다고 적은 버튼은 실제로 그 id가 배선돼 있다', () => {
    const offenders: string[] = []
    for (const [key, describedBy] of Object.entries(REGISTERED)) {
      if (describedBy === null) continue
      const path = key.split(' :: ')[0]
      const file = FILES.find((f) => f.path === path)
      expect(file, `${path}을 찾지 못했습니다`).toBeDefined()
      const text = (file as { text: string }).text
      if (!text.includes(`aria-describedby=`)) offenders.push(`${key} — aria-describedby 없음`)
      if (!text.includes(describedBy)) offenders.push(`${key} — id ${describedBy} 없음`)
    }
    expect(offenders).toEqual([])
  })
})
