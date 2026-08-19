/// <reference types="node" />
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEMO_VESSELS } from './referenceTable'

/**
 * 고정표 ↔ 시드 ↔ 화면 상수 드리프트 가드 (#526).
 *
 * ## 무엇이 조용했나
 *
 * 프론트 고정표(`DEMO_VESSELS`)와 실제 시드(`db/demo_seed.py`)가 어긋나 있는데
 * **아무것도 그것을 잡지 않았다.** 시드는 선박 4척을 넣고 고정표에는 1척뿐이다.
 *
 * `#511`이 그 사례다. 화면이 `vessel_id: '…0003'`을 상수로 박아 두었는데 그 UUID가
 * 고정표에 없어, **데모 모드에서 항로 비교가 아무 입력 없이 언제나 실패**했다.
 * 서버에 요청이 나가지도 않았고 **테스트도 lint도 빌드도 전부 통과**했다.
 * 사람이 화면을 열어 보고서야 발견됐다.
 *
 * ## 두 방향을 함께 본다
 *
 * | 규칙 | 방향 | 막는 것 |
 * |---|---|---|
 * | **A** | 고정표 → 시드 | 고정표에만 있는 **유령 선박** |
 * | **B** | 화면 → 고정표 | 화면이 박아 둔 `vessel_id`가 고정표에 없는 것 — **`#511`이 여기서 터졌다** |
 *
 * **「두 목록이 같아야 한다」로 두지 않는다.** 고정표는 계산 가능한 조합만 담는다는
 * `#135` 설계 요구가 있어(대조할 fixture가 없는 선박은 넣지 않는다), 시드 전체를
 * 복제하는 것이 목적이 아니다. A는 **부분집합**만 요구한다.
 *
 * ## 선례
 *
 * `shipTypes.sync.test.ts`(`#441`)가 TypeScript 테스트에서 Python 원본을 직접 읽는다.
 * `tokens.sync.test.ts`(`#409`)도 같은 취지다. 여기서도 같은 방식을 쓴다.
 *
 * ## 데모 모드가 사라지면
 *
 * `#542`가 데모 모드 존치 여부를 다룬다. 폐기로 정해지면 고정표와 함께 이 가드도
 * 사라진다 — 그때까지는 **임시라는 사실이 CI에 남아 있는 편**이 낫다.
 */

const demoSeedPy = readFileSync(
  new URL('../../../../src/cii_platform/db/demo_seed.py', import.meta.url),
  'utf8',
)

/** UUID v4 리터럴. 이 저장소의 데모 값은 전부 `00000000-0000-4000-8000-…` 대역이다. */
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/

/**
 * `demo_seed.py`가 정의한 선박 UUID.
 *
 * `VESSEL_ID_BULK = "00000000-…"` 형태의 상수만 본다. 항차·정박 구간 UUID는
 * 다른 접두(`VOYAGE_ID_` 등)를 쓰므로 섞이지 않는다.
 */
function seedVesselIds(): string[] {
  const found = Array.from(
    demoSeedPy.matchAll(new RegExp(`VESSEL_ID_[A-Z_]+\\s*=\\s*"(${UUID.source})"`, 'g')),
    (m) => m[1],
  )
  // 정규식이 아무것도 못 잡으면 **가드가 조용히 통과**한다(빈 집합의 부분집합은 언제나 참).
  // 그래서 개수를 함께 단언한다 — 파싱 실패와 「정말 비었다」를 구분한다.
  expect(
    found.length,
    'demo_seed.py에서 VESSEL_ID_* 상수를 찾지 못했다 — 정의 형태가 바뀌었다',
  ).toBeGreaterThan(0)
  return found
}

/** `frontend/src/features` 아래의 소스 파일. 테스트는 뺀다. */
function featureSourceFiles(): string[] {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const out: string[] = []

  function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules') continue
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) {
        walk(full)
        continue
      }
      if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue
      // 고정표 자신은 대상이 아니다 — 여기가 정의하는 곳이다.
      if (entry === 'referenceTable.ts') continue
      out.push(full)
    }
  }
  walk(root)
  return out
}

/**
 * 화면 코드가 상수로 박아 둔 `vessel_id`.
 *
 * **모든 UUID를 훑지 않는다.** `calculation_run_id`·`simulation_id`·`request_id`처럼
 * 선박과 무관한 UUID가 데모 응답에 여럿 있고, 그것까지 고정표에 있으라고 요구하면
 * 가드가 틀린 것을 잡는다. 이름이 `vessel`을 포함하는 자리만 본다.
 */
function hardcodedVesselIds(): Array<{ file: string; id: string }> {
  const pattern = new RegExp(`[Vv][Ee][Ss][Ss][Ee][Ll]_?[Ii][Dd]\\s*[:=]\\s*'(${UUID.source})'`, 'g')
  const found: Array<{ file: string; id: string }> = []

  for (const file of featureSourceFiles()) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(pattern)) {
      found.push({ file: file.replace(/.*[/\\]features[/\\]/, 'features/'), id: match[1] })
    }
  }
  return found
}

describe('규칙 A — 고정표의 선박은 시드에 있어야 한다', () => {
  it('고정표가 비어 있지 않다', () => {
    // 비면 아래 검사가 공허하게 참이 된다.
    expect(DEMO_VESSELS.length).toBeGreaterThan(0)
  })

  it('고정표의 모든 id가 demo_seed에 있다 — 유령 선박을 막는다', () => {
    const seeded = new Set(seedVesselIds())
    const ghosts = DEMO_VESSELS.filter((vessel) => !seeded.has(vessel.id))

    expect(
      ghosts.map((v) => `${v.displayName} (${v.id})`),
      '고정표에는 있으나 demo_seed.py에 없는 선박이다. ' +
        '데모 모드에서만 존재하는 배가 되어, 실 API로 바꾸는 순간 사라진다.',
    ).toEqual([])
  })

  it('시드가 고정표보다 많은 것은 허용한다 — #135 설계 요구', () => {
    // 고정표는 **계산 가능한 조합만** 담는다. 대조할 fixture가 없는 선박은
    // 넣지 않는 것이 옳고, 그래서 「완전 일치」가 아니라 부분집합이다.
    expect(seedVesselIds().length).toBeGreaterThanOrEqual(DEMO_VESSELS.length)
  })
})

describe('규칙 B — 화면이 박아 둔 vessel_id는 고정표에 있어야 한다', () => {
  it('스캐너가 실제로 파일을 읽는다', () => {
    // 파일 목록이 비면 아래 검사가 조용히 통과한다.
    expect(featureSourceFiles().length).toBeGreaterThan(10)
  })

  it('상수로 박힌 vessel_id가 전부 고정표에 있다 — #511이 여기서 터졌다', () => {
    const known = new Set(DEMO_VESSELS.map((vessel) => vessel.id))
    const orphans = hardcodedVesselIds().filter((entry) => !known.has(entry.id))

    expect(
      orphans.map((entry) => `${entry.file}: ${entry.id}`),
      '화면 코드가 고정표에 없는 vessel_id를 상수로 쓰고 있다. ' +
        '데모 모드에서 그 화면은 아무 입력 없이 언제나 실패한다 (#511). ' +
        '고정표에 행을 추가하거나, 선박을 목록에서 고르도록 바꾸세요.',
    ).toEqual([])
  })
})
