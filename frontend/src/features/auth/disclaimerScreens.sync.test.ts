/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * `UIFLOW §0` 화면 표의 「면책 문구」 ↔ 인증 화면의 `disclaimer` 드리프트 가드 (`#1455`).
 *
 * ## 왜 필요한가
 *
 * `0-1 회원가입`은 v2.1(`#413`)에서 되살아나며 구성 요소에 「면책 문구」를 적었는데,
 * 화면(`#415`)은 로그인에만 깃발을 켰다. `AuthShell` 주석이 「로그인 화면만」이라고
 * 적고 있어 **코드와 주석은 서로 맞았고, 정본과만 달랐다** — 그래서 아무 검사에도
 * 걸리지 않았다.
 *
 * ## 무엇을 보는가
 *
 * 표의 행마다 「구성 요소」 칸에 `면책 문구`가 **있는지**와, 그 화면 파일이
 * `disclaimer` 깃발을 **켜는지**가 같아야 한다. 양방향이다 — 정본이 적지 않은
 * 화면(비밀번호 찾기 · 이메일 인증)에 켜는 것도 어긋남이다.
 *
 * `0-2 로그인 실패`는 `LoginPage` 안의 분기라 파일로 가를 수 없어 표에서 뺐다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = join(HERE, '..', '..', '..', '..')
const PAGES = join(HERE, '..', '..', 'pages')

const SCREENS = [
  { id: '0', file: 'LoginPage.tsx' },
  { id: '0-1', file: 'SignupPage.tsx' },
  { id: '0-3', file: 'PasswordResetPage.tsx' },
  { id: '0-4', file: 'VerifyEmailPage.tsx' },
] as const

/** `| **0-1** | **회원가입** | 구성 요소 | 이동 |`에서 구성 요소 칸을 뽑는다. */
function componentsCell(id: string): string {
  const text = readFileSync(join(ROOT, 'UIFLOW.md'), 'utf-8')
  const row = new RegExp(`^\\|\\s*\\*\\*${id.replace('-', '\\-')}\\*\\*\\s*\\|[^|]*\\|([^|]*)\\|`, 'm')
  const match = row.exec(text)
  if (!match) throw new Error(`UIFLOW §0 표에서 ${id} 행을 찾지 못했다`)
  return match[1]
}

/** 주석을 걷고, JSX 속성으로 `disclaimer`(또는 `disclaimer={true}`)가 켜져 있는지. */
function turnsOnDisclaimer(file: string): boolean {
  const src = readFileSync(join(PAGES, file), 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
  return /^\s*disclaimer(\s*=\s*\{\s*true\s*\})?\s*$/m.test(src)
}

describe('UIFLOW §0 면책 문구 ↔ 인증 화면 (#1455)', () => {
  it.each(SCREENS)('$id — 정본이 면책을 적는 것과 화면이 켜는 것이 같다', ({ id, file }) => {
    expect(turnsOnDisclaimer(file)).toBe(componentsCell(id).includes('면책 문구'))
  })

  it('표가 적어도 한 화면에는 면책을 요구한다 — 파서가 헛돌지 않는다', () => {
    expect(SCREENS.filter(({ id }) => componentsCell(id).includes('면책 문구')).length).toBeGreaterThan(0)
  })
})
