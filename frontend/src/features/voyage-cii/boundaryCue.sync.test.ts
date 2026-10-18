import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { marginDisplay } from './resultRules'

/**
 * 경계 근처의 값을 무엇이 가리키는가 — `DESIGN_SYSTEM §4.1` 〔확정 2026-10-18 · `#2427`〕.
 *
 * ## 무엇을 막는가
 *
 * `§4.1`은 CII를 **3자리 고정**으로 적는다. 그래서 경계 양쪽의 두 입력이 **같은 숫자**로
 * 나오면서 등급만 갈릴 수 있다(`#2352` — `8.571`이 B와 C). 확정은 그 자리에 경계값을
 * 적지 않기로 했는데, **그것은 금지가 아니라 「지금의 채널로 충분하다」는 판정**이다.
 *
 * 그 판정이 근거로 든 것은 둘이다 — **여유율 문구**(`§2.5 (b)`의 「0.1% 미만」)와 **등급
 * 스케일 바**. 둘 중 하나가 화면에서 조용히 빠지면 **조항은 남고 근거만 사라진다.**
 * 그러면 경계 근처의 값은 아무 신호 없이 등급만 갈리는 상태로 돌아간다. 여기서 보는 것은
 * 조항의 **근거가 제자리에 있는지**다(`#2156`과 같은 꼴 — 예외의 사유도 함께 잠근다).
 */
const ROOT = join(process.cwd(), '..')
const DOC = readFileSync(join(ROOT, 'DESIGN_SYSTEM.md'), 'utf-8')

/** `§4.1`의 이 조항만 잘라 둔다 — 다른 절의 문장이 근거가 되지 않게. */
const CLAUSE = (() => {
  const from = DOC.indexOf('- **경계값을 값 옆에 적지 않는다')
  expect(from, '`§4.1`의 「경계값을 값 옆에 적지 않는다」를 찾지 못했습니다').toBeGreaterThan(-1)
  const rest = DOC.slice(from)
  const to = rest.indexOf('\n- **단위 표기')
  return to === -1 ? rest : rest.slice(0, to)
})()

/** 조항 안에서 **채널을 열거한 그 줄** 하나. */
const CHANNELS = (() => {
  const line = CLAUSE.split('\n').find((l) => l.includes('경계와의 거리'))
  expect(line, '채널을 열거한 줄을 찾지 못했습니다').toBeTruthy()
  return line as string
})()

function source(rel: string): string {
  return readFileSync(join(process.cwd(), rel), 'utf-8')
}

const RESULT = 'src/features/voyage-cii/VoyageCiiResult.tsx'
const REALTIME = 'src/features/realtime-cii/RealtimeCiiView.tsx'

describe('§4.1 경계값 조항이 근거로 든 것을 적었다 (#2427)', () => {
  it('조항을 실제로 읽었다 — 파서가 조용히 빈 손을 내지 않게', () => {
    expect(CLAUSE.length).toBeGreaterThan(400)
    expect(CLAUSE).toContain('#2427')
  })

  it('두 채널을 이름으로 가리킨다 — 여유율 문구와 등급 스케일 바', () => {
    /*
     * ⚠️ **조항 안에 그 말이 있는지로 보면 안 된다** — 처음 쓴 검사가 그랬는데, 채널
     * 줄에서 「등급 스케일 바」를 지워 보아도 **마지막 줄(가드 약속)이 같은 말을 들고 있어**
     * 초록이 났다. 근거를 세는 것은 **채널을 적은 그 줄**이다.
     */
    expect(CHANNELS).toContain('0.1% 미만')
    expect(CHANNELS).toContain('여유율 문구')
    expect(CHANNELS).toContain('등급 스케일 바')
  })

  it('가드 자신을 가리킨다 — 근거가 빠지면 붉어진다는 약속이 조항에 적혀 있다', () => {
    expect(CLAUSE).toContain('boundaryCue.sync.test.ts')
  })
})

describe('§4.1이 근거로 든 채널이 제자리에 있다 (#2427)', () => {
  it('⑴ 여유율 문구 — 0보다 크고 0.1% 미만은 `0.0%`가 아니라 「0.1% 미만」이다', () => {
    /*
     * 문자열 대조가 아니라 **함수를 불러** 본다. `§2.5 (b)`의 그 선이 「가깝다」의
     * 기준이므로, 분기가 사라지면(반올림값을 그대로 쓰면) 여기서 갈린다.
     */
    expect(marginDisplay('B', '0.0004')).toEqual({
      kind: 'below-threshold',
      text: 'C 등급까지 0.1% 미만',
    })
    expect(marginDisplay('B', '0.0004').text).not.toContain('0.0%')
  })

  it('⑵ CII 예측이 그 문구를 결론 띠에 쓴다', () => {
    const code = source(RESULT)
    expect(code).toMatch(/marginDisplay\s*\(/)
    expect(code).toContain('다음 경계까지')
  })

  it('⑶ 등급 스케일 바 — 경계를 받는 두 화면이 모두 그린다', () => {
    for (const rel of [RESULT, REALTIME]) {
      const code = source(rel)
      expect(code, `${rel}이 GradeScaleBar를 그려야 한다`).toMatch(/<GradeScaleBar/)
    }
  })

  it('⑷ 스케일 바는 경계값을 필수로 받는다 — 균등 분할로 떨어지지 않는다', () => {
    const bar = source('src/components/GradeScaleBar.tsx')
    /*
     * ⚠️ **선택 prop(`boundaries?`)으로 바뀌는 것**이 이 조항에 치명적이다 — 바가 남은 채
     * 균등 분할이 되면 「경계까지 얼마나 남았나」를 더 이상 말하지 않는데 화면은 멀쩡하다.
     */
    expect(bar).toMatch(/\n\s*boundaries:\s*DVector\b/)
    expect(bar).not.toMatch(/\n\s*boundaries\?:/)
  })
})

describe('§4.1이 대상에서 뺀 자리가 그대로다 (#2427)', () => {
  it('선박 상세는 경계를 불러오지 않는다 — `§8.6` 「다른 경로를 더 불러 채우지 않는다」', () => {
    const dir = 'src/features/vessel-detail'
    const hits: string[] = []
    for (const name of readdirSync(join(process.cwd(), dir))) {
      if (!/\.tsx?$/.test(name) || name.includes('.test.')) continue
      const code = source(`${dir}/${name}`)
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '')
      if (/boundar/i.test(code)) hits.push(name)
    }
    expect(hits, '선박 상세가 경계를 받기 시작했다면 `§8.6`·`§4.1`을 먼저 고친다').toEqual([])
  })

  it('조항이 그 제외를 적어 두었다', () => {
    expect(CLAUSE).toContain('선박 상세는 대상이 아니다')
  })
})
