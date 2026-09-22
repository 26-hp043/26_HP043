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

  it('페이지 제목은 알려진 차이다 — 28, display와 떼어 둔다', () => {
    // §3 개정(3단계) 전까지 남기는 차이. 개정되면 이 검사를 §3 행 대조로 바꾼다.
    expect(token('font-size-page')).toBe(28)
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
