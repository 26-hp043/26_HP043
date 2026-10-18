import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { portDisplayName, type SamplePort } from './samplePorts'

/**
 * 기록의 항구를 화면에 적는 규칙 — `DESIGN_SYSTEM §4.5` 〔`#2434`〕.
 *
 * ## 무엇을 막는가
 *
 * 이 규칙은 **정본에 없었고 코드 주석에만** 있었다. 그래서 항차 탭은 `portDisplayName`을
 * 거치고 **정박 탭은 거치지 않아**, 폼 선택지가 「부산 · KR」인데 기록은 「BUSAN」으로
 * 나왔다 — 같은 항구가 한 제품에서 두 이름을 가졌다. 자리마다 조심하기로 두면 **다음에
 * 생기는 표시 자리**에서 되풀이되므로(`§8.4`), 여기서 두 가지를 함께 본다.
 *
 * ⑴ `§4.5` 표의 규칙과 `portDisplayName`의 **실제 동작**이 같은가 — 문자열 대조가 아니라
 *    함수를 불러서 본다. 표만 고치거나 함수만 고치면 붉어진다.
 * ⑵ `§4.5`가 적은 **표시 자리 목록**과 그 함수를 실제로 부르는 파일이 같은가 — 새 표시
 *    자리가 함수를 거르면(정박 탭이 그랬다) 목록에 없는 파일이 되거나 목록에 적힌 파일이
 *    함수를 잃어 **어느 쪽이든** 붉어진다.
 */
const ROOT = join(process.cwd(), '..')
const DOC = readFileSync(join(ROOT, 'DESIGN_SYSTEM.md'), 'utf-8')

/** `### 4.5` 절만 잘라 둔다 — 다른 절의 문장이 근거가 되지 않게. */
const SECTION = (() => {
  const from = DOC.indexOf('### 4.5 항구 이름')
  expect(from, '`§4.5`를 찾지 못했습니다').toBeGreaterThan(-1)
  const rest = DOC.slice(from + 1)
  const to = rest.search(/\n#{2,3} /)
  return to === -1 ? rest : rest.slice(0, to)
})()

/** 표의 「항목 | 규칙」 행들. 줄 안에서만 센다 — `[^|\n]`이 아니면 다음 행까지 삼킨다. */
const ROWS = [...SECTION.matchAll(/^\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$/gm)]
  .filter(([, item]) => item !== '항목' && !/^-+$/.test(item))

/**
 * `§4.5`가 적은 표시 자리 ↔ 그 자리의 파일.
 *
 * ⚠️ 값 사본이 아니라 **대조표**다 — 목록과 구현 어느 쪽이 움직여도 아래 두 검사가
 * 이 표에서 갈린다.
 */
const SITES: Readonly<Record<string, string>> = {
  '항차 관리': 'src/features/voyage-management/VoyagePanel.tsx',
  정박: 'src/features/not-underway/NotUnderwayPanel.tsx',
  '항차 선택 목록': 'src/layout/voyageCatalog.ts',
  '리포트 구간': 'src/features/reports/reportRules.ts',
  '항로 비교 지도': 'src/features/scenario-comparison/ScenarioComparison.tsx',
  '실시간 CII': 'src/features/realtime-cii/RealtimeCiiView.tsx',
}

const PORTS: readonly SamplePort[] = [
  { locode: 'KRPUS', name: 'BUSAN', name_ko: '부산', country_code: 'KR', lat: 35.1, lon: 129.0333 },
]

describe('§4.5 항구 이름 — 표의 규칙과 함수의 동작이 같다 (#2434)', () => {
  it('절을 실제로 읽었다 — 파서가 조용히 빈 손을 내지 않게', () => {
    expect(SECTION).toContain('portDisplayName')
    expect(ROWS.length).toBe(6)
  })

  it('표시 — 샘플 항만과 맞으면 보이는 이름이다', () => {
    expect(portDisplayName(PORTS, 'BUSAN')).toBe('부산')
    const row = ROWS.find(([, , rule]) => rule.includes('name_ko'))
    expect(row, '「표시」 행이 `name_ko`를 가리켜야 한다').toBeTruthy()
  })

  it('목록 밖 — 맞는 항만이 없으면 저장값 그대로다', () => {
    expect(portDisplayName(PORTS, 'ROTTERDAM')).toBe('ROTTERDAM')
    expect(portDisplayName(PORTS, '제3부두')).toBe('제3부두')
  })

  it('목록을 받지 못했을 때 — 저장값 그대로다 (조회 실패는 조용하다)', () => {
    expect(portDisplayName([], 'BUSAN')).toBe('BUSAN')
  })

  it('저장값을 덮어쓰지 않는다 — 보이는 이름을 넣어도 같은 항구로 읽는다', () => {
    expect(portDisplayName(PORTS, '부산')).toBe('부산')
  })
})

/**
 * `§4.5`가 **표시 자리를 나열한 그 줄**만 떼어 쪼갠다.
 *
 * ⚠️ 「절 안에 그 이름이 있는지」로 보면 안 된다 — 처음 쓴 검사가 그랬는데, 목록에서
 * 「정박」을 빼 보아도 같은 절의 사유 문단이 *「정박 탭은 거치지 않아」*로 그 글자를
 * 들고 있어 **초록이 났다.** 자리를 정하는 것은 이 줄이다.
 */
const LISTED = (() => {
  const line = SECTION.split('\n').find((l) => l.includes('기록을 보이는 자리는 전부 그 함수를 거친다'))
  expect(line, '표시 자리를 나열한 줄을 찾지 못했습니다').toBeTruthy()
  return (line as string)
    .slice((line as string).lastIndexOf('—') + 1)
    .split('·')
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
})()

describe('§4.5 표시 자리 목록과 구현이 같다 (#2434)', () => {
  /** 비검사 원본에서 `portDisplayName(`을 **부르는** 파일 — 선언·주석은 세지 않는다. */
  const callers = (() => {
    const found = new Set<string>()
    const walk = (dir: string): void => {
      for (const entry of readdirSync(join(process.cwd(), dir), { withFileTypes: true })) {
        const rel = `${dir}/${entry.name}`
        if (entry.isDirectory()) walk(rel)
        else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
          if (rel === 'src/features/ports/samplePorts.ts') continue
          const code = readFileSync(join(process.cwd(), rel), 'utf-8')
            .replace(/\/\*[\s\S]*?\*\//g, '')
            .replace(/^\s*\/\/.*$/gm, '')
          if (/portDisplayName\s*\(/.test(code)) found.add(rel)
        }
      }
    }
    walk('src')
    return found
  })()

  it('파일을 실제로 훑었다', () => {
    expect(callers.size).toBeGreaterThan(0)
  })

  it('나열한 줄을 실제로 쪼갰다', () => {
    expect(LISTED.length).toBe(Object.keys(SITES).length)
  })

  it('목록에 적힌 자리가 전부 함수를 거친다', () => {
    expect(LISTED.slice().sort()).toEqual(Object.keys(SITES).sort())
    for (const [name, file] of Object.entries(SITES)) {
      expect([...callers], `「${name}」(${file})이 portDisplayName을 불러야 한다`).toContain(file)
    }
  })

  it('목록 밖의 표시 자리가 없다 — 새 자리는 정본에 적는다', () => {
    expect([...callers].sort()).toEqual(Object.values(SITES).sort())
  })
})
