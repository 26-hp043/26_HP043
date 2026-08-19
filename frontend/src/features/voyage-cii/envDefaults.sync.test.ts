/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { isEnabled, shouldUseApi } from './providerSelection'

/**
 * 개발 서버가 **조용히 데모 모드로 떨어지는 것**을 막는다 (#528).
 *
 * ## 무엇이 문제였나
 *
 * `VITE_USE_API=true`가 `frontend/.env.local`에만 있었고 그 파일은 gitignore
 * 대상이다. 저장소를 새로 clone한 사람에게는 없으므로 값이 `undefined`가 되고,
 * `isEnabled()`가 `raw === 'true'`로 판정하므로 **데모 모드로 떴다.**
 *
 * 데모 모드는 선박 목록만 줄어드는 것이 아니다. demo provider가 있는 기능은
 * 셋뿐이라(`voyage-cii` · `scenario-comparison` · `annual-simulation`)
 * **대시보드·보고서·선박 상세·선박 관리는 아예 돌지 않는다.** 인증 가드까지
 * 꺼져서(`auth/session.ts`) 로그인 없이 화면이 열리므로 **데모 모드인 줄
 * 알아채기도 어렵다.**
 *
 * 실제로 디자인 담당이 이 상태로 작업하다 「선박이 하나만 뜬다」고 알려 왔다.
 * 그 하나가 고정표(`referenceTable.ts`)의 유일한 선박이었다.
 *
 * ## 어떻게 고쳤나
 *
 * 커밋되는 `frontend/.env`에 기본값을 둔다. Vite 우선순위상 `.env.local`이 더
 * 높으므로 **데모로 쓰려는 사람은 여전히 `.env.local`로 끌 수 있다.**
 *
 *     .env.[mode].local  >  .env.[mode]  >  .env.local  >  .env
 *
 * ## 이 파일이 잠그는 것
 *
 * 그 기본값 파일이 **사라지거나 값이 뒤집히는 것**을 막는다. 파일 하나가 없어지면
 * 증상은 「선박이 하나만 뜬다」처럼 엉뚱하게 나타나므로, 원인 자리에 신호를 둔다.
 */

const ENV_FILE = new URL('../../../.env', import.meta.url)

function readEnvDefaults(): Record<string, string> {
  const text = readFileSync(ENV_FILE, 'utf-8')
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (trimmed === '' || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq > 0) out[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim()
  }
  return out
}

describe('개발 서버 기본값 (#528)', () => {
  it('커밋되는 .env가 존재하고 실 API를 기본으로 둔다', () => {
    const env = readEnvDefaults()
    expect(
      env.VITE_USE_API,
      'frontend/.env의 VITE_USE_API가 사라졌거나 뒤집혔습니다. ' +
        '이 파일이 없으면 새로 clone한 사람이 데모 모드로 뜨고, ' +
        '증상은 「선박이 하나만 뜬다」처럼 엉뚱하게 나타납니다 (#528).',
    ).toBe('true')
  })

  it('그 값이 실제로 실 API 모드로 해석된다', () => {
    // 파일에 'true'가 적혀 있어도 판정 함수가 다르게 읽으면 소용이 없다.
    expect(isEnabled(readEnvDefaults().VITE_USE_API)).toBe(true)
  })

  it('데모로 끄는 길은 열려 있다 — 백엔드 없이 화면만 보는 작업이 있다', () => {
    // `.env.local`이 `.env`를 덮는다는 Vite 규칙에 기대는 부분이라,
    // 판정 함수가 'false'를 데모로 읽는지만 여기서 고정한다.
    expect(isEnabled('false')).toBe(false)
    expect(isEnabled(undefined)).toBe(false)
  })

  it('테스트 환경도 이 기본값을 물려받는다 — vitest가 .env를 읽는다', () => {
    /*
     * **처음에는 반대로 예상했다가 이 단언에서 틀린 것이 드러났다.**
     * Vitest는 Vite 설정을 그대로 쓰므로 `.env`가 `import.meta.env`에 실린다.
     *
     * 그래서 `frontend/.env`를 추가하는 것은 테스트 환경의 기본값도 바꾼다.
     * 지금은 provider 테스트들이 전부 env를 **명시적으로 주입**해 쓰므로 영향이
     * 없지만, 기본값에 기대는 테스트를 새로 쓰면 그 사실을 알고 써야 한다.
     */
    expect(shouldUseApi()).toBe(true)
  })
})
