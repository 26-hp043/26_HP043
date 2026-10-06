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
 * 위 셋은 **파일 단위**다. 파일이 `csrfHeaders()`를 한 번이라도 부르면 통과하므로, 요청이
 * 다섯인 파일에서 넷만 헤더를 실어도 초록이었다 — 수가 그대로인 채 한 요청의 헤더만 빠지는
 * 변경은 어느 줄에도 걸리지 않았다 (`#2145`).
 *
 * ## 요청 단위로도 본다 (`#2145`)
 *
 * 메서드를 적은 자리마다 **그 요청이 헤더를 싣는 길**을 소스에서 따라간다. 길은 둘이다.
 *
 * - **직접** — 메서드를 적은 객체 안에 `csrfHeaders()`가 있다.
 * - **공용 함수를 거쳐** — 객체를 넘겨받는 같은 파일의 함수(`call` · `request` …)가
 *   `csrfHeaders()`를 싣는다. 그 함수가 `if (init.write)`처럼 **조건을 걸어** 실으면,
 *   넘기는 쪽이 그 깃발(`write: true`)을 켰는지도 본다.
 *
 * 어느 길도 아니면 실패한다. 실제 호출로 보는 것(`auth/session.test.ts`의 인증 요청 일곱)을
 * 대신하지는 않는다 — 소스를 읽는 검사라 함수가 둘 이상의 파일에 걸치면 따라가지 못하고,
 * 그때는 「길을 찾지 못했다」로 **실패한다**(조용히 통과하지 않는다).
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

/** 주석을 걷어낸다 — 설명 문장 속 `csrfHeaders()`가 「실었다」로 읽히지 않게. 줄 수는 그대로 둔다. */
function withoutComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

/** `index`를 감싸는 가장 안쪽 `open … close` 쌍의 자리. 없으면 `null`. */
function enclosing(text: string, index: number, open: string, close: string): [number, number] | null {
  let depth = 0
  let start = -1
  for (let i = index; i >= 0; i -= 1) {
    if (text[i] === close) depth += 1
    else if (text[i] === open) {
      if (depth === 0) {
        start = i
        break
      }
      depth -= 1
    }
  }
  if (start === -1) return null
  depth = 0
  for (let i = start; i < text.length; i += 1) {
    if (text[i] === open) depth += 1
    else if (text[i] === close) {
      depth -= 1
      if (depth === 0) return [start, i]
    }
  }
  return null
}

/** 이름이 `name`인 함수의 정의 구간 — 정의 줄부터, 같은 들여쓰기의 닫는 중괄호 줄까지. */
function definitionOf(text: string, name: string): string | null {
  // 함수 꼴만 — `const doFetch = options.fetchImpl ?? fetch` 같은 **값**을 정의로 읽으면
  // 그 뒤에 오는 남의 `csrfHeaders()`까지 이 이름의 것으로 센다.
  const head = new RegExp(
    `^([ \\t]*)(?:export )?(?:async )?(?:function ${name}\\b|const ${name} = (?:async )?(?:<[^>]*>)?\\()`,
    'm',
  ).exec(text)
  if (head === null) return null
  const rest = text.slice(head.index)
  const end = new RegExp(`^${head[1]}\\}`, 'm').exec(rest)
  return end === null ? rest : rest.slice(0, end.index)
}

/**
 * 객체가 헤더를 **변수로** 넘기고(`headers,` · `headers: h`), 그 변수가 선언된 블록 안에서
 * 요청보다 **앞서, 조건 없이** `csrfHeaders()`를 받았는가.
 *
 * 받는 꼴은 둘이다 — `Object.assign(변수, csrfHeaders())`, 또는 선언의 객체 리터럴 안.
 * `if (…) Object.assign(…)`처럼 조건이 걸린 줄은 세지 않는다(그 길은 공용 함수 쪽에서 본다).
 */
function headersVariableCarriesCsrf(text: string, objectStart: number, init: string): boolean {
  const name = /\bheaders(?::\s*([A-Za-z_$][\w$]*))?\s*[,}\n]/.exec(init)
  if (name === null) return false
  const variable = name[1] ?? 'headers'
  const declared = new RegExp(`\\b(?:const|let)\\s+${variable}\\b`)
  let cursor = objectStart - 1
  for (;;) {
    const block = enclosing(text, cursor, '{', '}')
    if (block === null) return false
    const before = text.slice(block[0], objectStart)
    const at = before.search(declared)
    if (at !== -1) {
      const since = before.slice(at)
      const assigned = new RegExp(`^[ \\t]*Object\\.assign\\(\\s*${variable}\\s*,\\s*csrfHeaders\\(\\)`, 'm')
      const literal = new RegExp(`^${variable}\\b[^=]*=\\s*\\{[^}]*csrfHeaders\\(\\)`)
      return assigned.test(since) || literal.test(since.replace(/^(?:const|let)\s+/, ''))
    }
    cursor = block[0] - 1
    if (cursor < 0) return false
  }
}

/**
 * 상태 변경 요청마다 헤더를 싣는 길을 판정한다.
 *
 * 돌려주는 것은 **길을 찾지 못한 자리**다 — `줄 번호: 사유`.
 */
function requestsWithoutCsrf(source: string): string[] {
  const text = withoutComments(source)
  const missing: string[] = []
  for (const match of text.matchAll(MUTATING)) {
    const line = text.slice(0, match.index).split('\n').length
    const object = enclosing(text, match.index, '{', '}')
    if (object === null) {
      missing.push(`${line}: 메서드를 적은 객체를 찾지 못했다`)
      continue
    }
    const init = text.slice(object[0], object[1] + 1)
    if (init.includes('csrfHeaders()')) continue
    if (headersVariableCarriesCsrf(text, object[0], init)) continue

    const call = enclosing(text, object[0], '(', ')')
    const callee = call === null ? null : /([\w$]+)\s*$/.exec(text.slice(0, call[0]))?.[1] ?? null
    if (callee === null) {
      missing.push(`${line}: 객체를 넘겨받는 함수를 찾지 못했다`)
      continue
    }
    if (/^fetch(Impl)?$/.test(callee)) {
      missing.push(`${line}: ${callee}를 직접 부르는데 헤더가 없다`)
      continue
    }
    const body = definitionOf(text, callee)
    if (body === null || !body.includes('csrfHeaders()')) {
      missing.push(`${line}: ${callee}()가 헤더를 싣지 않는다`)
      continue
    }
    // 조건을 걸어 싣는 함수 — 넘기는 쪽이 그 깃발을 켰어야 한다.
    const guarded = /if \(\w+\.(\w+)\)[^\n]*csrfHeaders\(\)/.exec(body)
    if (guarded !== null && !new RegExp(`\\b${guarded[1]}: true\\b`).test(init)) {
      missing.push(`${line}: ${callee}()는 ${guarded[1]}일 때만 헤더를 싣는데 켜지 않았다`)
    }
  }
  return missing
}

/**
 * 헤더 없이 보내는 것이 **맞는** 자리 — 사유와 함께.
 *
 * `API_SPEC §1.2`: 세션 없이 부르는 공개 인증 요청은 검증할 세션이 없어 적용 대상이 아니다.
 */
const WITHOUT_HEADER: Record<string, { within: string; reason: string }> = {
  'auth/session.ts': {
    within: 'postJsonWithStatus',
    reason: '공개 인증 요청 일곱(로그인·둘러보기·가입·메일 인증 2종·비밀번호 재설정 2종)이 함께 쓴다',
  },
}

/** 함수 `name`의 정의가 차지하는 줄 범위(1부터). 사유를 적은 자리가 **그 함수 안**인지 볼 때 쓴다. */
function linesOf(source: string, name: string): [number, number] {
  const text = withoutComments(source)
  const body = definitionOf(text, name)
  if (body === null) return [0, 0]
  const first = text.slice(0, text.indexOf(body)).split('\n').length
  return [first, first + body.split('\n').length - 1]
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

describe('상태를 바꾸는 요청 하나하나가 헤더를 싣는다 (#2145)', () => {
  it('길을 찾는 눈이 맞다 — 잡을 꼴과 잡지 않을 꼴', () => {
    const direct = "await fetchImpl(url, {\n  method: 'POST',\n  headers: { Accept: 'x', ...csrfHeaders() },\n})"
    const wrapper = [
      'async function call(path: string, init: RequestInit) {',
      '  return fetchImpl(path, { ...init, headers: { ...csrfHeaders() } })',
      '}',
    ].join('\n')
    const conditional = [
      'async function request(path: string, init: RequestInit & { write?: boolean }) {',
      '  const headers = {}',
      '  if (init.write) Object.assign(headers, csrfHeaders())',
      '  return fetchImpl(path, { ...init, headers })',
      '}',
    ].join('\n')
    const bare = 'async function send(path: string, init: RequestInit) {\n  return fetchImpl(path, init)\n}'

    // 싣는 꼴 — 직접, 공용 함수를 거쳐, 깃발을 켜고.
    expect(requestsWithoutCsrf(direct)).toEqual([])
    expect(requestsWithoutCsrf(`${wrapper}\nawait call('/x', { method: 'DELETE' })`)).toEqual([])
    expect(requestsWithoutCsrf(`${wrapper}\nawait call('/x', {\n  method: 'PATCH',\n  body: JSON.stringify({ a: { b: 1 } }),\n})`)).toEqual([])
    expect(requestsWithoutCsrf(`${conditional}\nawait request('/x', { method: 'PUT', write: true })`)).toEqual([])
    // 헤더를 변수로 모아 넘기는 꼴 — 같은 함수 안에서 요청보다 먼저 받는다.
    const viaVariable = (line: string) =>
      [
        'async function post(path: string) {',
        "  const headers: Record<string, string> = { 'Content-Type': 'application/json' }",
        line,
        '  try {',
        "    return await doFetch(path, { method: 'POST', headers })",
        '  } catch {',
        '    return null',
        '  }',
        '}',
      ].join('\n')
    expect(requestsWithoutCsrf(viaVariable('  Object.assign(headers, csrfHeaders())'))).toEqual([])
    expect(
      requestsWithoutCsrf(
        "async function put() {\n  const h = { Accept: 'x', ...csrfHeaders() }\n  return fetchImpl(url, { method: 'PUT', headers: h })\n}",
      ),
    ).toEqual([])
    // 변수에 아무도 넣지 않았거나, 조건을 걸어 넣었으면 실은 것이 아니다.
    expect(requestsWithoutCsrf(viaVariable(''))).toEqual(['5: doFetch()가 헤더를 싣지 않는다'])
    expect(requestsWithoutCsrf(viaVariable('  if (write) Object.assign(headers, csrfHeaders())'))).toEqual([
      '5: doFetch()가 헤더를 싣지 않는다',
    ])
    // 다른 함수의 `headers`가 받은 것은 이 요청의 것이 아니다.
    expect(
      requestsWithoutCsrf(
        `${viaVariable('  Object.assign(headers, csrfHeaders())')}\nasync function del() {\n  const headers = {}\n  return doFetch(url, { method: 'DELETE', headers })\n}`,
      ),
    ).toEqual(['12: doFetch()가 헤더를 싣지 않는다'])
    // 조회는 대상이 아니다.
    expect(requestsWithoutCsrf("await fetchImpl(url, { method: 'GET' })")).toEqual([])

    // 싣지 않는 꼴.
    expect(requestsWithoutCsrf("await fetchImpl(url, {\n  method: 'POST',\n  headers: { Accept: 'x' },\n})")).toEqual([
      '2: fetchImpl를 직접 부르는데 헤더가 없다',
    ])
    expect(requestsWithoutCsrf("await fetch(url, { method: 'DELETE' })")).toEqual([
      '1: fetch를 직접 부르는데 헤더가 없다',
    ])
    expect(requestsWithoutCsrf(`${bare}\nawait send('/x', { method: 'POST' })`)).toEqual([
      '4: send()가 헤더를 싣지 않는다',
    ])
    expect(requestsWithoutCsrf(`${conditional}\nawait request('/x', { method: 'DELETE' })`)).toEqual([
      '6: request()는 write일 때만 헤더를 싣는데 켜지 않았다',
    ])
    // 주석 속 `csrfHeaders()`는 「실었다」가 아니다.
    expect(
      requestsWithoutCsrf("await fetchImpl(url, {\n  method: 'POST', // csrfHeaders()는 아래에서\n})"),
    ).toEqual(['2: fetchImpl를 직접 부르는데 헤더가 없다'])
    // 같은 파일에 싣는 요청이 있어도 **다른 요청**의 빈자리를 가리지 않는다 — 파일 단위 검사의 구멍.
    expect(requestsWithoutCsrf(`${direct}\nawait fetchImpl(url, { method: 'DELETE' })`)).toEqual([
      '5: fetchImpl를 직접 부르는데 헤더가 없다',
    ])
  })

  it('헤더 없는 요청은 사유를 적은 자리뿐이다', () => {
    const actual = Object.fromEntries(
      [...FOUND]
        .map(([file, { source }]) => [file, requestsWithoutCsrf(source)] as const)
        .filter(([, missing]) => missing.length > 0),
    )
    // 사유는 **함수 하나**에 붙는다 — 같은 파일의 다른 요청이 헤더를 잃으면 그 줄은 범위 밖이다.
    const unexplained = Object.entries(actual).flatMap(([file, missing]) => {
      const allowed = WITHOUT_HEADER[file]
      const [first, last] = allowed === undefined ? [0, 0] : linesOf(FOUND.get(file)!.source, allowed.within)
      return missing
        .filter((entry) => {
          const line = Number(entry.split(':')[0])
          return line < first || line > last
        })
        .map((entry) => `${file}:${entry}`)
    })
    expect(unexplained).toEqual([])
    expect(actual['auth/session.ts']).toHaveLength(1)
    // 사유 목록이 낡지 않았다 — 그 자리가 사라졌으면 뺀다.
    expect(Object.keys(WITHOUT_HEADER).filter((file) => actual[file] === undefined)).toEqual([])
    for (const { reason } of Object.values(WITHOUT_HEADER)) expect(reason.length).toBeGreaterThan(5)
  })
})
