import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 접근성 배선의 회귀를 막는다 (#829 ⑸).
 *
 * ## 왜 소스로 보는가
 *
 * 이 성질들은 **화면이 깨지지 않는다.** `role`을 빼도 그림은 그대로이고, 달라지는
 * 것은 낭독뿐이라 눈으로도 기존 검사로도 드러나지 않는다. 그래서 소스에서 본다 —
 * `moduleBoundary.test.ts`·`deadCss.test.ts`와 같은 규율이다.
 */
const SRC = new URL('.', import.meta.url).pathname

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sources(path)
    if (!/\.tsx$/.test(name) || name.includes('.test.')) return []
    return [path]
  })
}

const FILES = sources(SRC).map((path) => ({ path: path.slice(SRC.length), text: readFileSync(path, 'utf8') }))

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
   * `#936` — **이관 진척을 세는 검사다.** 실패 목록이 곧 남은 작업이다.
   *
   * `§8.4`가 배선을 `Field`로 모으기 전, 폼 컨트롤 87곳 중 `aria-invalid`가 붙은 것은
   * **18곳**이었다. 나머지는 오류를 색으로만 말하고 있었고(`§14` 위반), 라벨·힌트가
   * 컨트롤에 프로그램적으로 닿지 않았다.
   *
   * **허용 목록으로 센다.** 「전부 `Field`를 써야 한다」로 잠그면 이관이 끝날 때까지
   * 빨간불이라 아무도 보지 않게 된다. 대신 **아직 옮기지 않은 파일을 적어 두고**,
   * 그 목록이 줄어드는 것으로 진척을 본다 — 목록에 없는 파일이 배선 없는 컨트롤을
   * 새로 들이면 그때 실패한다.
   *
   * 이관이 끝나면 목록이 비고, 이 검사는 **회귀 가드**로 남는다.
   */
  const NOT_YET_MIGRATED = [
    'features/scenario-comparison/ScenarioComparison.tsx',
    'features/not-underway/NotUnderwayPanel.tsx',
    'features/fleet-reduction/FleetReduction.tsx',
    'features/annual-simulation/AnnualSimulation.tsx',
    'features/voyage-management/ExportCsv.tsx',
    'features/voyage-management/VoyagePanel.tsx',
    'features/account/AccountPanel.tsx',
    'features/vessel-detail/PositionForm.tsx',
    'features/auth/AuthShell.tsx',
    'features/assistant/AssistantOverlay.tsx',
  ]

  it('이관한 파일은 폼 컨트롤 배선을 Field에 맡긴다 (#936)', () => {
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      if (NOT_YET_MIGRATED.includes(path)) continue
      // 직접 적은 `aria-invalid`는 `Field`가 줄 배선을 호출부가 다시 쓴 것이다.
      for (const match of text.matchAll(/\saria-invalid=/g)) {
        offenders.push(`${path} :: ${text.slice(match.index, (match.index ?? 0) + 40).trim()}`)
      }
    }
    expect(
      offenders,
      'Field가 배선을 주므로 호출부가 aria-invalid를 적을 필요가 없다. ' +
        '아직 이관 전이라면 NOT_YET_MIGRATED에 남겨 두세요.',
    ).toEqual([])
  })

  it('이관 목록이 실재하는 파일만 담는다', () => {
    /* 파일이 사라지거나 이름이 바뀌면 목록이 조용히 낡는다 — 그때 검사가 헐거워진다. */
    const known = new Set(FILES.map((f) => f.path))
    const stale = NOT_YET_MIGRATED.filter((path) => !known.has(path))
    expect(stale, `이관 목록에 없는 파일이 적혀 있다: ${stale.join(', ')}`).toEqual([])
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
