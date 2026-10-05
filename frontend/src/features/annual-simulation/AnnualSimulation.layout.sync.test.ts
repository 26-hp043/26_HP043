/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 연간 등급 관리의 배치 규칙을 CSS에서 잠근다 (#1700).
 *
 * jsdom은 스타일시트를 계산하지 않으므로, 화면 검사(`AnnualSimulation.test.tsx`)는
 * **어느 클래스가 어디에 있는가**까지만 본다. 그 클래스가 정본의 값을 쓰는지는
 * 여기서 규칙 본문을 읽어 확인한다.
 */

const CSS = readFileSync(
  join(fileURLToPath(new URL('.', import.meta.url)), 'AnnualSimulation.css'),
  'utf8',
).replace(/\/\*[\s\S]*?\*\//g, '')

/** 미디어 쿼리 밖, 선택자가 정확히 일치하는 첫 규칙의 본문. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(CSS)
  if (!match) throw new Error(`규칙이 없다: ${selector}`)
  return match[2]
}

// 입력-결과 2단은 화면들을 한 표로 대조한다 — `styles/inputColumn.sync.test.ts` (#1711).
// 결론 띠의 크기 · pill 규칙은 공용 부품이 잠근다 — `components/VerdictStrip.sync.test.ts` (#1711).

describe('카드 예산 — `DESIGN_SYSTEM §5`', () => {
  it('「라벨 · 값」 줄은 면을 띄우지 않는다 — 배경 · 그림자 없이 구분선만', () => {
    const body = rule('.annual-sim__row')
    expect(body).not.toMatch(/background|box-shadow|border-radius/)
    expect(body).toMatch(/border-bottom:/)
  })
})

describe('연도별 실적 블록 — 카드 예산 밖 (#2017 · `DESIGN_SYSTEM §5`)', () => {
  it('면을 띄우지 않는다 — 배경 · 테두리 · 그림자 없이 바닥에 놓인다', () => {
    /*
     * 카드 예산 4개는 입력 · 결론 띠 · 확률 분포 · 민감도로 차 있다. 이 블록이 카드가 되면
     * 예산을 넘고, 기록된 값이 추정 카드와 같은 모양이 되어 `PRD §3.2`의 구분이 흐려진다.
     */
    const body = rule('.annual-sim__actuals')
    expect(body).not.toMatch(/background|box-shadow|border/)
  })
})

describe('스택 바 구간 안 문자 — `DESIGN_SYSTEM §10.2` 🔒 · `§14`', () => {
  it('글자 뒤에 표면색 바탕을 깐다 — 후광만으로는 사선 무늬 틈이 비친다', () => {
    const body = rule('.annual-sim__seg-label')
    expect(body).toMatch(/background:\s*var\(--color-surface\)/)
    expect(body).toMatch(/color:\s*var\(--color-text\)/)
    expect(body).not.toMatch(/text-stroke/)
  })
})

describe('분포 범위 막대 높이 — `DESIGN_SYSTEM §10.1` 〔확정〕 2026-09-27 (#1940 ②)', () => {
  it('리터럴 픽셀이 아니라 간격 토큰을 쓴다 — 같은 파일의 24 자리와 한 값', () => {
    const body = rule('.annual-sim__range-rail')
    expect(body).toMatch(/height:\s*var\(--space-24\)/)
    expect(body).not.toMatch(/height:\s*\d+px/)
  })
})

describe('연도별 실적 표의 정렬 — 숫자만 오른쪽 (#2017 · `DESIGN_SYSTEM §8`)', () => {
  it('공용 표 규칙이 모든 칸을 오른쪽에 붙이므로, 이 표의 문자 칸은 왼쪽으로 되돌린다', () => {
    // 공용 규칙이 오른쪽이라는 전제가 바뀌면 이 검사도 다시 본다.
    expect(CSS).toMatch(/\.annual-sim__table th,\s*\.annual-sim__table td\s*\{[^}]*text-align:\s*right/)
    expect(rule('.annual-sim__actuals-table :is(th, td):not(.num)')).toMatch(/text-align:\s*left/)
  })
})

describe('남은 해 기준 한 줄의 가정 문구 — 줄 바로 아래, 하단 배너 밖 (#2056 C④ 디자인 확정)', () => {
  /*
   * `DESIGN_SYSTEM §13`의 「하단 고지는 배너 한 칸」은 화면 바닥 고지의 규칙이고, 이 문장은
   * 바로 위 한 줄(「이대로면 …」)을 한정하는 문맥이다. 한정하는 대상에서 떨어지면 무엇에 대한
   * 가정인지 사라진다. 화면 검사는 렌더된 자리를 보고, 여기서는 **배너 쪽 소스가 이 문구를
   * 모른다**는 것을 잠근다 — 배너에 합치는 변경은 페이지나 배너 파일을 거쳐야 한다.
   */
  const here = fileURLToPath(new URL('.', import.meta.url))
  const read = (relative: string): string => readFileSync(join(here, relative), 'utf8')

  it('가정 문구를 그리는 곳은 `FutureYearsLine` 하나다', () => {
    const source = read('AnnualSimulation.tsx')
    const start = source.indexOf('function FutureYearsLine(')
    const end = source.indexOf('\nfunction Result(', start)
    expect(start).toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    const inside = source.slice(start, end)
    expect(inside).toContain('ANNUAL_COPY.futureYearsAssumption')
    // 함수 밖(주석 제외)에는 없다 — `onDisclaimer`로 배너에 넘기는 자리가 생기면 여기서 붉어진다.
    const outside = (source.slice(0, start) + source.slice(end)).replace(/\/\*[\s\S]*?\*\//g, '')
    expect(outside).not.toContain('futureYearsAssumption')
  })

  it('페이지의 하단 배너와 배너 부품은 이 문구를 모른다', () => {
    expect(read('../../pages/AnnualGradePage.tsx')).not.toContain('futureYearsAssumption')
    expect(read('../../components/DisclaimerBanner.tsx')).not.toContain('futureYearsAssumption')
  })
})
