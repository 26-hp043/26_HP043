import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fallbackMessage } from './api/base'
import { dirOf, srcKey } from './test/srcPaths'

/*
 * 화면의 오류 문구가 HTTP 상태 코드를 싣지 않는다 (`#2221` · `#2112` 후속).
 *
 * 서버 문구가 없을 때의 폴백이 `… (HTTP ${response.status}).` 꼴로 서른세 곳에 흩어져
 * 있었다. 숫자는 사용자가 할 수 있는 일을 바꾸지 않는다 — 콘솔에만 남긴다
 * (`api/base.ts`의 `fallbackMessage`).
 *
 * **소스로 본다.** 폴백은 서버가 봉투 없이 실패할 때만 나오는 문구라, 화면마다 렌더로
 * 확인하려면 호출 경로 서른세 개를 전부 실패시켜야 한다. 새 호출부가 생기면 그 검사는
 * 따라오지 않는다.
 */
const SRC = dirOf(import.meta.url)

/** 상태 코드를 문자열에 끼워도 되는 단 한 자리 — 콘솔로 보내는 공용 함수다. */
const CONSOLE_ONLY = 'api/base.ts'

/**
 * 문자열에 상태 코드를 끼우는 꼴 셋.
 *
 * ⑴ `HTTP ${…}` — 종전 폴백의 꼴 ⑵ `${response.status}` · `${status}`처럼 상태 값을
 * **그대로** 끼운 것(「HTTP」를 지우고 숫자만 남기는 변형을 막는다) ⑶ `HTTP 500`처럼
 * 숫자를 직접 적은 것.
 *
 * ⑵는 항차 상태(`voyage.status`)를 라벨로 옮겨 끼우는 자리를 잡지 않는다 — 그쪽은
 * `STATUS_LABELS[…]`·`statusLabel(…)`을 거치므로 중괄호 안이 식별자 하나로 끝나지 않는다.
 */
const STATUS_IN_TEXT = [/HTTP\s*\$\{/, /\$\{\s*(?:\w+\??\.)*status(?:Code)?\s*\}/, /HTTP\s*\d{3}/]

/** 주석을 걷어낸다 — **줄 수는 그대로 둔다**(위반 자리를 줄 번호로 말하려고). */
function withoutComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

function offendingLines(text: string): number[] {
  return withoutComments(text)
    .split('\n')
    .flatMap((line, index) => (STATUS_IN_TEXT.some((pattern) => pattern.test(line)) ? [index + 1] : []))
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sources(path)
    return /\.tsx?$/.test(name) && !name.includes('.test.') ? [path] : []
  })
}

describe('오류 문구가 HTTP 상태 코드를 싣지 않는다 (#2221)', () => {
  // 수집 단계에서 한 번 읽는다 — 검사 안에서 읽으면 느린 디스크에서 시한(5초)에 걸린다.
  const texts = new Map(sources(SRC).map((file) => [srcKey(SRC, file), readFileSync(file, 'utf8')]))

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('검사가 종전 꼴을 실제로 잡는다 — 느슨해서 언제나 참인 검사가 아니다', () => {
    // 고치기 전 소스에 있던 꼴 그대로다.
    const before = [
      'throw new ParametersError(`연료 목록을 불러오지 못했습니다 (HTTP ${response.status}).`)',
      'body?.error?.message ?? `요청을 처리하지 못했습니다 (HTTP ${response.status}).`,',
      'return new AnnualSimulationError(`${MALFORMED_ERROR_MESSAGE} (HTTP ${status})`)',
      'if (!response.ok) throw new Error(`HTTP ${response.status}`)',
      // 「HTTP」만 지운 변형과 숫자를 직접 적은 변형.
      'throw new Error(`불러오지 못했습니다 (${response.status}).`)',
      "throw new Error('불러오지 못했습니다 (HTTP 500).')",
    ]
    for (const line of before) expect(offendingLines(line), line).toEqual([1])

    // 잡지 않아야 하는 것 — 항차 상태 라벨, 상태 코드 분기, 주석 속 설명.
    const allowed = [
      'return `${STATUS_LABELS[voyage.status]}에서는 갈 수 없는 상태입니다.`',
      '<span className={`vy__badge vy__badge--${voyage.status.toLowerCase()}`}>',
      'if (response.status === 404) throw new VesselDetailError(VESSEL_NOT_FOUND_MESSAGE)',
      '// 종전에는 `HTTP ${status}`만 내보냈다',
      '/* (HTTP ${response.status}) 폴백을 걷어냈다 */',
    ]
    for (const line of allowed) expect(offendingLines(line), line).toEqual([])

    // 여러 줄 주석을 걷어내도 줄 번호가 밀리지 않는다.
    expect(offendingLines('/*\n * HTTP ${status}\n */\nconst a = `HTTP ${status}`')).toEqual([4])
  })

  it('소스 어디에도 상태 코드를 끼운 문자열이 없다 — 콘솔로 보내는 한 자리만 빼고', () => {
    // 훑은 것이 비어 있으면 아래 단언은 언제나 참이다.
    expect(texts.size).toBeGreaterThan(100)

    const offenders = [...texts].flatMap(([key, text]) =>
      key === CONSOLE_ONLY ? [] : offendingLines(text).map((line) => `${key}:${line}`),
    )
    expect(offenders).toEqual([])
  })

  it('남은 한 자리는 콘솔로 가는 줄이다', () => {
    const text = texts.get(CONSOLE_ONLY) ?? ''
    const lines = withoutComments(text).split('\n')
    const hits = offendingLines(text).map((line) => lines[line - 1].trim())
    expect(hits).toHaveLength(1)
    expect(hits[0].startsWith('console.warn(')).toBe(true)
  })

  it('폴백 문구는 받은 그대로 나가고 상태 코드는 콘솔에만 남는다', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const text = fallbackMessage('요청을 처리하지 못했습니다.', 502)

    expect(text).toBe('요청을 처리하지 못했습니다.')
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('502')
  })
})
