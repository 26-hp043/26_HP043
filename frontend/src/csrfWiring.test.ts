import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 상태를 바꾸는 요청의 CSRF 배선 (`#2127`).
 *
 * `API_SPEC §1.2`는 상태 변경 요청(POST·PUT·PATCH·DELETE)에 `X-CSRF-Token` 헤더를
 * 요구하고, **세션을 요구하는 라우트에 예외를 두지 않는다**(`#634`). 헤더를 빠뜨리면
 * 서버가 403을 내는데, 그 세션으로는 토큰을 다시 받을 길이 없어 같은 요청을 다시 보내도
 * 결과가 같다 — 화면에서는 「저장이 안 된다」로만 보인다.
 *
 * ## 무엇을 잠그는가
 *
 * 화면 소스 전체에서 **메서드를 적은 자리**를 세어 아래 표와 대조한다.
 *
 * ```
 * 새 파일에 상태 변경 요청이 생겼다   → 실패. 헤더를 싣는지 보고 표에 적는다
 * 한 파일의 요청 수가 달라졌다         → 실패. 늘어난 요청이 헤더를 지나는지 본다
 * 그 파일이 csrfHeaders()를 부르지 않는다 → 실패
 * ```
 *
 * 이 검사는 **파일 단위**다 — 요청마다 헤더가 실리는지는 각 기능의 검사가 실제 호출로
 * 본다(`auth/session.test.ts`가 인증 요청 일곱을 그렇게 본다). 여기는 목록에서 빠진
 * 요청이 조용히 생기지 않게 하는 그물이다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
  })
}

const MUTATING = /method:\s*['"](POST|PUT|PATCH|DELETE)['"]/g

/**
 * 파일별 상태 변경 요청 수.
 *
 * `auth/session.ts`의 8곳 가운데 하나(`postJsonWithStatus`)는 **공개 인증 요청 일곱**
 * (로그인·둘러보기·가입·메일 인증 2종·비밀번호 재설정 2종)이 함께 쓰는 자리다. 그 일곱은
 * 세션 없이 부르므로 검증할 세션이 없다 — `API_SPEC §1.2`가 「예외가 아니라 적용 대상이
 * 아닌 것」으로 적은 경로다. 나머지 7곳이 세션을 요구하고 전부 헤더를 싣는다.
 */
const EXPECTED: Record<string, number> = {
  'auth/session.ts': 8,
  'features/annual-simulation/apiProvider.ts': 1,
  'features/assistant/apiProvider.ts': 1,
  'features/data-quality/apiProvider.ts': 1,
  'features/fleet-reduction/apiProvider.ts': 2,
  'features/not-underway/apiProvider.ts': 5,
  'features/parameters/revisionProvider.ts': 1,
  'features/scenario-comparison/apiProvider.ts': 2,
  'features/vessel-detail/apiProvider.ts': 1,
  'features/vessel-management/apiProvider.ts': 2,
  'features/vessel-registration/apiProvider.ts': 1,
  'features/voyage-cii/apiProvider.ts': 1,
  'features/voyage-management/apiProvider.ts': 4,
}

const FOUND = new Map<string, { count: number; source: string }>()
for (const file of walk(HERE)) {
  const source = readFileSync(file, 'utf-8')
  const count = [...source.matchAll(MUTATING)].length
  if (count > 0) FOUND.set(relative(HERE, file).replaceAll('\\', '/'), { count, source })
}

describe('상태를 바꾸는 요청의 CSRF 배선 (#2127)', () => {
  it('상태 변경 요청이 있는 파일과 그 수가 목록과 같다', () => {
    const actual = Object.fromEntries([...FOUND].map(([file, { count }]) => [file, count]))
    expect(actual).toEqual(EXPECTED)
  })

  it('그 파일들은 전부 csrfHeaders()를 부른다', () => {
    const missing = [...FOUND]
      .filter(([, { source }]) => !/csrfHeaders\(\)/.test(source))
      .map(([file]) => file)
    expect(missing).toEqual([])
  })
})
