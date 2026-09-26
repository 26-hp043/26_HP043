/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 타입 스케일 ↔ `DESIGN_SYSTEM §3` 드리프트 가드 (#1691).
 *
 * 종전에는 `tokens.css`의 display 28 · 굵기 700/600 · label 500이 §3(display 32 ·
 * 굵기 400/500만)과 달랐는데 어느 검사도 둘을 잇지 않았다. 여기서는 §3 표를 읽어
 * 크기 · 굵기 · 행간(px)을 코드 토큰과 대조하고, CSS 어디에도 600 · 700이 없음을 본다.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url))
const DOC = readFileSync(join(SRC, '..', '..', 'DESIGN_SYSTEM.md'), 'utf-8')
const TOKENS = readFileSync(join(SRC, 'styles', 'tokens.css'), 'utf-8')

/** §3 이름 → 코드 토큰 접미사. 정본과 코드의 이름이 다른 곳을 한 곳에 적는다. */
const CODE_NAME: Record<string, string> = {
  display: 'display',
  // `#1763` — §3 v2.26이 `page`(28) 행을 두어 「알려진 차이」를 닫았다. 이제 표와 대조한다.
  page: 'page',
  title: 'h2',
  heading: 'h3',
  body: 'body',
  label: 'label',
  caption: 'micro',
}

function section3(): string {
  const start = DOC.indexOf('## 3. 타이포그래피')
  const end = DOC.indexOf('## 4. ', start)
  expect(start, 'DESIGN_SYSTEM §3을 찾지 못했습니다').toBeGreaterThan(-1)
  return DOC.slice(start, end)
}

function specRows(): Map<string, { size: number; weight: number; lineHeight: number }> {
  const rows = new Map<string, { size: number; weight: number; lineHeight: number }>()
  const pattern = /^\|\s*`([a-z]+)`\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|/gm
  for (const m of section3().matchAll(pattern)) {
    rows.set(m[1], { size: Number(m[2]), weight: Number(m[3]), lineHeight: Number(m[4]) })
  }
  return rows
}

function token(name: string): number {
  const m = new RegExp(`--${name}:\\s*([0-9.]+)(px)?;`).exec(TOKENS)
  if (!m) throw new Error(`tokens.css에 --${name}이 없다`)
  return Number(m[1])
}

describe('타입 토큰이 DESIGN_SYSTEM §3과 같다 (#1691)', () => {
  const rows = specRows()

  it('§3 표에서 대조할 행을 모두 읽었다', () => {
    for (const name of Object.keys(CODE_NAME)) expect(rows.has(name), `§3 \`${name}\``).toBe(true)
  })

  for (const [spec, code] of Object.entries(CODE_NAME)) {
    it(`${spec} → --font-size-${code} · 행간`, () => {
      const row = rows.get(spec)!
      const size = token(`font-size-${code}`)
      expect(size).toBe(row.size)
      // 행간은 단위 없는 비로 둔다 — 크기와 곱해 §3의 px(±0.5)와 같아야 한다.
      expect(Math.abs(token(`line-height-${code}`) * size - row.lineHeight)).toBeLessThanOrEqual(0.5)
    })
  }

  it('굵기는 §3이 적은 값이다 — display · title · heading 500, body · label 400', () => {
    expect(token('font-weight-display')).toBe(rows.get('display')!.weight)
    expect(token('font-weight-h2')).toBe(rows.get('title')!.weight)
    expect(token('font-weight-h3')).toBe(rows.get('heading')!.weight)
    expect(token('font-weight-body')).toBe(rows.get('body')!.weight)
    expect(token('font-weight-label')).toBe(rows.get('label')!.weight)
  })

  it('페이지 제목은 KPI 숫자와 다른 크기다 (#1691 · #1763)', () => {
    /*
     * 크기 · 행간 대조는 위 `CODE_NAME` 반복이 맡는다(`#1763`이 `page` 행을 §3에 두면서
     * 「알려진 차이」가 닫혔다). 여기서는 **둘이 같은 값으로 되돌아가지 않는지**만 본다 —
     * 종전에는 h1이 `display`를 빌려 페이지 제목과 KPI 숫자가 한 값에 묶여 있었다.
     */
    expect(token('font-size-page')).not.toBe(token('font-size-display'))
  })
})

describe('페이지 제목은 KPI 숫자 크기(display)를 빌리지 않는다 (#1691)', () => {
  it('h1과 화면 제목 클래스(`…__title`)는 `--font-size-display`를 쓰지 않는다', () => {
    const offenders: string[] = []
    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((n) => {
        const p = join(dir, n)
        return statSync(p).isDirectory() ? walk(p) : n.endsWith('.css') ? [p] : []
      })
    for (const file of walk(SRC)) {
      const css = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
        const selector = m[1].trim()
        if (!/(^|[\s,])h1\b|__title\b/.test(selector)) continue
        if (/--font-size-display/.test(m[2])) offenders.push(`${file.slice(SRC.length)}: ${selector}`)
      }
    }
    expect(offenders).toEqual([])
  })
})

describe('CSS 어디에도 400 · 500 밖의 굵기가 없다 (#1691)', () => {
  function cssFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) return cssFiles(path)
      return name.endsWith('.css') ? [path] : []
    })
  }

  it('번들 글꼴이 400 · 500뿐이다 — 600 · 700 · bold는 합성 굵기로 그려진다', () => {
    const offenders: string[] = []
    for (const file of cssFiles(SRC)) {
      const css = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      for (const m of css.matchAll(/(?:font-weight|--font-weight-[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
        const value = m[1].trim()
        if (/^(var\(|400$|500$|normal$|inherit$)/.test(value)) continue
        offenders.push(`${file.slice(SRC.length)}: ${m[0]}`)
      }
    }
    expect(offenders).toEqual([])
  })
})

/**
 * 타입 스케일 값을 CSS에 **리터럴로 적지 않는다** (#1781).
 *
 * ## 왜 필요한가
 *
 * 위 검사들은 `§3` 표와 `tokens.css`만 잇고 **사용처는 보지 않는다.** 그래서 대시보드
 * KPI 수치가 `34px` 리터럴인 것을 `#1691`(PR `#1697`)이 토큰을 정본에 맞추는 동안에도
 * 아무도 잡지 못했다 — 토큰은 32인데 화면은 34를 그리고 있었고, 두 값을 잇는 검사가
 * 한 곳도 없었다. 「정본 = 토큰」만 잠그면 화면이 토큰을 안 쓰는 길로 빠져나간다.
 *
 * ## 무엇을 잡는가
 *
 * `§3` 표의 크기 중 **코드 토큰이 있는 것**(`CODE_NAME`이 잇는 행)을 CSS가 리터럴
 * `font-size`로 적으면 실패한다. 토큰이 없는 크기(`§3` `micro` 11)는 바꿀 수단이
 * 없으므로 대상이 아니다 — 대응 토큰을 만드는 것은 `§15` 네이밍과 Figma가 함께 걸리는
 * 자리다(`§0.2` 치수는 Figma 소유).
 *
 * 표 **밖**의 크기(`FleetMap`의 9px 마커 이름표 · `AnnualSimulation`의 0.5rem 입자)도
 * 대상이 아니다. 이 검사는 「스케일 값을 토큰 없이 쓰는 것」을 막지, 「스케일 밖 크기를
 * 쓰는 것」을 판정하지 않는다 — 후자는 `§3`이 아직 말하지 않은 자리다.
 *
 * 사용자 지정 속성 선언(`--font-size-display: 32px`)은 값의 **출처**이므로 지나친다.
 */
describe('타입 스케일 값을 리터럴로 적지 않는다 (#1781)', () => {
  function cssFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) return cssFiles(path)
      return name.endsWith('.css') ? [path] : []
    })
  }

  it('§3 표의 크기는 토큰으로만 쓴다', () => {
    const rows = specRows()
    /* 크기 → 써야 할 토큰. `CODE_NAME`이 잇는 행만 — 토큰이 없는 크기는 뺀다. */
    const tokenFor = new Map<number, string>()
    for (const [spec, code] of Object.entries(CODE_NAME)) {
      const row = rows.get(spec)
      if (row) tokenFor.set(row.size, `--font-size-${code}`)
    }
    expect(tokenFor.size, '§3에서 읽은 행이 없다').toBeGreaterThan(0)

    const offenders: string[] = []
    for (const file of cssFiles(SRC)) {
      const css = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      /* 선행 문자를 함께 잡아 `--font-size-…:` 선언을 거른다. */
      for (const m of css.matchAll(/(^|[;{\s])font-size:\s*([0-9.]+)px/g)) {
        const size = Number(m[2])
        const token = tokenFor.get(size)
        if (token !== undefined) {
          offenders.push(`${file.slice(SRC.length)}: font-size: ${size}px → var(${token})`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
