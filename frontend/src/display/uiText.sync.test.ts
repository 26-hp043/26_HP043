/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 화면에 보이는 문구에 **내부 문서 참조가 새어 나오는 것**을 막는다 (#529).
 *
 * ## 무엇이 문제였나
 *
 * 항로 비교 화면의 안내 문구가 이렇게 나가고 있었다.
 *
 * ```
 * 선박에 기준 일일 연료소모량이 등록돼 있지 않아도 이 값으로 계산합니다 (PRD §11.4 ⑴).
 * ```
 *
 * **사용자는 `PRD`가 무엇인지 모른다.** 이 화면을 쓰는 사람은 중소선사의 운항관리자이고
 * `PRD`는 팀 내부의 제품 요구사항 정의서다. 절 번호를 보여 줘도 확인할 방법이 없다.
 *
 * 디자인 담당이 스크린샷을 보내며 발견했고, 전수 확인 결과 **네 곳**이 있었다 —
 * 항로 비교 1곳, 선박 관리 3곳(`#510`에서 들어감).
 *
 * ## 근거를 버리라는 뜻이 아니다
 *
 * `AGENTS §4.6`이 **「정본 문구」와 「표시 문구」**를 구분한다(`#468`). 정본이 원문을
 * 확정한 문구는 화면이 임의로 못 바꾸지만, 그 밖의 안내는 **사용자가 읽을 말**로
 * 써야 한다. 근거는 **코드 주석**이 그 자리다 — 실제로 고칠 때 주석으로 옮겼다.
 *
 * ## 어떻게 잡나
 *
 * 주석을 걷어낸 뒤 남은 코드에서 `§`를 찾는다. 주석에 절 번호를 적는 것은 권장되는
 * 일이므로 **주석은 검사 대상이 아니다.**
 */

const SRC = fileURLToPath(new URL('..', import.meta.url))

/** 검사 대상 확장자. `.md`·설정 파일은 화면에 나가지 않는다. */
const EXTENSIONS = ['.ts', '.tsx']

/** 테스트 파일 자신은 제외한다 — 위 설명에 §가 들어 있다. */
function isTestFile(path: string): boolean {
  return path.includes('.test.') || path.includes('.sync.')
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      walk(full, out)
      continue
    }
    if (EXTENSIONS.some((ext) => full.endsWith(ext)) && !isTestFile(full)) out.push(full)
  }
  return out
}

/**
 * 주석을 지운다.
 *
 * 세 형태를 모두 지운다 — 블록 주석 `/* … *\/`, 줄 주석 `//`, 그리고 JSX 주석
 * `{/* … *\/}`(블록 주석 제거로 함께 처리된다).
 *
 * **문자열 안의 `//`는 남는다**(예: `'http://…'`). 그 경우 뒤가 잘리지만 이 검사가
 * 보는 것은 `§`뿐이라 영향이 없다.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

describe('화면 문구에 내부 문서 참조가 없다 (#529)', () => {
  const files = walk(SRC)

  it('검사 대상 파일이 실제로 잡힌다', () => {
    // 경로가 어긋나 0개를 훑고 조용히 통과하는 상태를 먼저 막는다.
    expect(files.length).toBeGreaterThan(50)
  })

  it('주석 밖에 정본 절 참조(§)가 없다', () => {
    const offenders: string[] = []
    for (const file of files) {
      const code = stripComments(readFileSync(file, 'utf-8'))
      code.split('\n').forEach((line, i) => {
        if (line.includes('§')) {
          offenders.push(`${file.slice(SRC.length)}:${i + 1}  ${line.trim()}`)
        }
      })
    }
    expect(
      offenders,
      '화면에 나가는 문자열에 문서 절 번호가 들어 있습니다. ' +
        '사용자는 PRD·API_SPEC이 무엇인지 모릅니다 — 근거는 주석에 적으십시오 (#529).\n' +
        offenders.join('\n'),
    ).toEqual([])
  })
})
