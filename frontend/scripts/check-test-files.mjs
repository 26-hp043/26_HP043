/**
 * 디스크의 검사 파일이 **전부 실행됐는가** (`#828` ⑸).
 *
 * ## 왜 필요한가
 *
 * `#828`이 전수 검토 중 관측한 상태다.
 *
 * ```
 * Vitest caught 1 unhandled error during the test run.
 *   Failed to start forks worker for test files .../VesselMark.test.tsx
 *  Test Files  65 passed (65)
 * [exited with code 0]
 * ```
 *
 * **한 파일이 통째로 돌지 않았는데 CI가 초록이다.** 그 파일이 지키던 것은 그 순간부터
 * 아무도 지키지 않는데, 실패가 아니라 **「그 파일이 없는 것처럼」** 지나간다.
 *
 * ## 왜 원인을 고치지 않고 결과를 보는가
 *
 * 관측된 원인은 **워커 기동 실패**(자원 부족)라 명령으로 재현되지 않는다. 그리고 원인은
 * 그것 하나가 아니다 — 파일이 잘못된 곳으로 옮겨져 glob에서 빠지거나, 설정의
 * `include`가 좁혀져도 **같은 결과**(조용히 덜 도는 것)가 된다.
 *
 * 그래서 **결과를 본다**: 디스크에 있는 검사 파일과 실제로 실행된 파일을 대조한다.
 * 원인이 무엇이든 걸린다.
 *
 * ## 왜 vitest 안의 검사로 두지 않는가
 *
 * 검사 파일은 **자기가 몇 개 돌았는지 알 수 없다.** 그 정보는 실행이 끝난 뒤 리포터에만
 * 있다. 그래서 이 스크립트가 `npm run test`의 마지막 걸음으로 붙는다.
 */

import { readFileSync, readdirSync, statSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = join(HERE, '..')
const SRC = join(ROOT, 'src')
const REPORT = join(ROOT, '.vitest-report.json')

/** `src` 아래의 모든 검사 파일. vitest의 기본 `include`와 같은 모양이다. */
function testFilesOnDisk(dir = SRC) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return testFilesOnDisk(full)
    return /\.test\.tsx?$/.test(entry) ? [relative(ROOT, full)] : []
  })
}

function ranAccordingToReport() {
  let raw
  try {
    raw = readFileSync(REPORT, 'utf-8')
  } catch {
    console.error(
      '::error::vitest 리포트를 찾지 못했습니다. `npm run test`가 --outputFile을 쓰는지 확인하십시오 (#828).',
    )
    process.exit(1)
  }
  const report = JSON.parse(raw)
  const results = report.testResults ?? []
  return new Set(results.map((r) => relative(ROOT, r.name)))
}

const onDisk = testFilesOnDisk().sort()
const ran = ranAccordingToReport()
const missing = onDisk.filter((path) => !ran.has(path))

// 리포트는 산출물이다 — 저장소에 남기지 않는다.
try {
  rmSync(REPORT)
} catch {
  /* 이미 없으면 그만이다. */
}

if (missing.length > 0) {
  console.error(
    `::error::검사 파일 ${missing.length}개가 실행되지 않았습니다 (#828):\n  ` +
      missing.join('\n  ') +
      '\n→ 워커 기동 실패·include 축소·파일 이동 중 하나입니다. ' +
      '돌지 않은 파일이 지키던 것은 그 순간부터 아무도 지키지 않습니다.',
  )
  process.exit(1)
}

console.log(`검사 파일 ${onDisk.length}개가 모두 실행됐습니다.`)
