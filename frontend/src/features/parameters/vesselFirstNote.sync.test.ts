/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { SELECT_VESSEL_FIRST, YEAR_STATE_COPY } from './yearCatalog'

/**
 * 연도 칸의 상태 문구는 **한 곳에서 나온다** (#2048 · `#2155`).
 *
 * ## 왜 검사인가
 *
 * 이 문장은 `PRD §6.4`가 등재한 패턴(`{선행 대상}을/를 먼저 선택해 주세요`)이고,
 * 같은 상태를 그리는 화면이 넷이다(보고서 · 연간 등급 관리 · 항로 비교 · 항차 CII).
 * 화면마다 적으면 갈린다 — 실제로 이 저장소에서 **두 벌이 따로 있었고**, 같은
 * 자리의 빈 상태 문구는 지금도 「등재된…」과 「등록된…」으로 갈려 있다.
 *
 * `#829`·`#1171` ⑶이 고친 것이 바로 이 갈림이고, 갈리면 다시 「값이 없다」와
 * 「아직 물어보지 않았다」가 섞인다. 한 곳에서 나오는지를 **소스로** 본다.
 *
 * ## 빈 목록 문구도 같은 자리다 (`#2155`)
 *
 * 위 주석이 *「같은 자리의 빈 상태 문구는 지금도 「등재된…」과 「등록된…」으로 갈려
 * 있다」*고 적어 둔 그 갈림이다. 낱말은 `#2183`이 맞췄지만 **문장은 세 곳에 따로 적혀
 * 있었다** — 한쪽이 바뀌면 나머지가 낡는 상태는 그대로였다. 두 문구를 같은 방식으로 본다.
 */
const SRC = join(process.cwd(), 'src')
const HOME = 'features/parameters/yearCatalog.ts'

/**
 * 주석을 걷는다 — **주석 속 언급이 근거가 되지 않게** 한다.
 *
 * 이 검사를 처음 돌렸을 때 다섯 파일이 걸렸는데 넷은 「왜 이 문장인가」를 적은
 * 주석이었다. `#2061`에서 같은 형태로 두 번 밟았다(주석의 토큰 이름이 선언으로
 * 잡혔고, 규칙 이름을 주석에 적어 둔 탓에 그 규칙을 지워도 초록이었다).
 * `deadCss.test.ts`·`launcherReserve.sync.test.ts`가 같은 이유로 같은 일을 한다.
 */
function code(path: string): string {
  return readFileSync(path, 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return entry === 'node_modules' ? [] : sourceFiles(full)
    if (!/\.tsx?$/.test(entry)) return []
    // 검사 파일은 단언하느라 문장을 그대로 적는다 — 그쪽은 대상이 아니다.
    return /\.test\.tsx?$/.test(entry) ? [] : [full]
  })
}

/**
 * ⚠️ **마침표가 붙은 것은 다른 문자열이다.**
 *
 * `annual-simulation/copy.ts`의 「상단에서 선박을 먼저 선택해 주세요.」와
 * `reports/reportRules.ts`의 「선박을 먼저 선택해 주세요.」는 마침표가 있어
 * `§6.4`의 이 패턴(관례 ② — 마침표 없음)과 **같은 문자열이 아니다.** 둘은 이 이슈
 * 이전부터 있었고 어느 상태로 쓰는지가 화면마다 갈려 있다 — 문구 소관은 디자인이므로
 * (`AGENTS §4.6`) 여기서 고치지 않고 후속으로 둔다. 이 검사는 **마침표 없는 쪽**만 본다.
 */
/**
 * 한 곳에서만 나와야 하는 문구와 **그 집**.
 *
 * ⚠️ 종전에는 「마침표가 붙은 것은 다른 문자열이다」로 두 자리를 **후속으로 비켜** 두었다
 * (`reports/reportRules.ts` · `annual-simulation/copy.ts`). `#2155`가 그 둘을 닫았다 —
 * 마침표는 **자리가 정한다**(컨트롤 한 줄은 찍지 않고 안내 문단은 찍는다). 문구 자체는
 * 어느 자리든 이 상수에서 나오므로, 이제 **마침표를 가리지 않고** 본다.
 */
const ONE_SOURCE: readonly { readonly text: string; readonly name: string }[] = [
  { text: SELECT_VESSEL_FIRST, name: 'SELECT_VESSEL_FIRST' },
  { text: YEAR_STATE_COPY.empty, name: 'YEAR_STATE_COPY.empty' },
]

/*
 * 훑기는 **한 번만** 한다 (`#2250`). 아래 검사는 문구마다 한 번씩 도는데, 종전에는 돌
 * 때마다 `src/`의 모든 소스를 다시 읽고 주석을 다시 걷었다 — 문구가 달라도 읽는 대상은
 * 같다. 검사 파일은 실행마다 새로 불려 오므로 이 기억이 다음 실행으로 넘어가지 않는다.
 */
let scanned: readonly { readonly file: string; readonly code: string }[] | undefined

function scannedSources(): readonly { readonly file: string; readonly code: string }[] {
  scanned ??= sourceFiles(SRC).map((file) => ({ file, code: code(file) }))
  return scanned
}

/*
 * 기본 5초를 쓰지 않는다 (`#2250`). `src/` 전체를 읽는 값은 디스크가 정한다 — CI에서는
 * 0.1초 안쪽이지만, 저장소가 느린 파일 시스템 위에 있고 다른 작업이 함께 돌면 한 번
 * 읽는 데 3~4초가 걸려 5초에 닿았다. 20초는 `deadCss.test.ts`가 같은 훑기에 준 값이다.
 */
const SCAN_TIMEOUT_MS = 20_000

describe('선행 선택 안내 문구는 한 곳에서 나온다 (#2048 · `PRD §6.4`)', () => {
  it.each(ONE_SOURCE)('$name — 문장이 화면 소스에 직접 적혀 있지 않다', { timeout: SCAN_TIMEOUT_MS }, ({ text, name }) => {
    const found = scannedSources()
      .filter((source) => source.code.includes(text))
      .map((source) => relative(SRC, source.file))
    expect(found, `문장을 직접 적은 파일이 있습니다 — \`${name}\`을 쓰세요`).toEqual([HOME])
  })

  it('⚠️ `PRD §6.4`의 패턴과 마침표 규칙을 지킨다', () => {
    /*
     * 패턴은 `{선행 대상}을/를 먼저 선택해 주세요`이고, 마침표는 찍지 않는다
     * (현행 관례 ② — 폼 컨트롤 안의 한 줄은 값 자리다). 마침표가 붙으면 검증 오류
     * 「선박을 선택해 주세요.」와 같은 모양이 되어 그 각주가 가른 두 상태가 다시 섞인다.
     */
    expect(SELECT_VESSEL_FIRST).toMatch(/먼저 선택해 주세요$/)
    expect(SELECT_VESSEL_FIRST.endsWith('.'), '마침표를 찍지 않는다 (관례 ②)').toBe(false)
    expect(YEAR_STATE_COPY.empty).toMatch(/^등록된/)
    expect(YEAR_STATE_COPY.empty.endsWith('.'), '마침표를 찍지 않는다 (관례 ②)').toBe(false)
  })

  /**
   * **마침표는 자리가 정한다** (`#2155`).
   *
   * 안내 문단 자리는 마침표를 찍는다 — 결과 영역의 `<p>` 한 문단이고 옆 줄들이 모두
   * 찍는다. 그 자리도 **문구는 공용 상수에서** 나와야 한다. 문장을 다시 적고 마침표만
   * 붙이면 그것이 곧 두 벌이다 — 종전 「상단에서 선박을 먼저 선택해 주세요.」가 그랬다.
   */
  it('문단 자리는 상수에 마침표만 붙여 쓴다', () => {
    const copy = code(join(SRC, 'features/annual-simulation/copy.ts'))
    expect(copy, '문구를 다시 적었다 — 상수를 보간해 쓴다').toContain(
      '`${SELECT_VESSEL_FIRST}.`',
    )
    expect(copy).not.toContain('상단에서 선박을')
  })

  it('정본이 이 상태를 실제로 등재하고 있다', () => {
    /*
     * 문구의 근거가 정본에서 사라지면 이 상수는 출처 없는 문장이 된다.
     * `reasonCodes.sync.test.ts`가 정본을 읽는 것과 같은 방향이다.
     */
    const prd = readFileSync(join(process.cwd(), '..', 'PRD.md'), 'utf-8')
    const row = prd.split('\n').find((line) => line.includes('선행 선택 필요'))
    expect(row, '`PRD §6.4`에 「선행 선택 필요」 행이 없습니다').toBeTruthy()
    expect(row!).toContain('먼저 선택해 주세요')
    expect(row!, '해당 칸이 연도 목록을 가리키지 않습니다').toContain('연도')
  })
})
