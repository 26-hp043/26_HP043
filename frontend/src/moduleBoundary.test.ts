import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 모듈 경계 — 다른 파일이 쓰지 않는 `export` (#594).
 *
 * ## 왜 테스트인가
 *
 * `#594`가 **한 번 손으로** 세어 48종을 골라냈다. 사유를 주석으로만 적으면 **새로
 * 늘어도 아무도 모른다** — `oxlint`·`tsc`는 이 경우를 잡지 않는다(다른 모듈이 쓸
 * 수도 있다고 보므로).
 *
 * 그래서 측정을 여기로 옮기고 **사유가 붙은 목록**과 대조한다.
 *
 * ```
 * 새로 생겼다        → 실패. 분류하고 사유를 적는다
 * 참조가 생겼다      → 실패. 목록에서 뺀다 (낡은 목록은 거짓말이다)
 * ```
 *
 * ## 무엇이 「참조」인가
 *
 * **테스트 파일을 포함한 다른 모든 `.ts`/`.tsx`**에서 그 이름이 **코드로** 한 번이라도
 * 나오면 참조로 센다. `#594` 본문이 「테스트만 쓰는 것은 스크립트가 테스트를 제외해서
 * 잡혔다」고 적었는데 **사실이 아니다** — 재현 명령도 참조를 셀 때는 테스트를
 * 포함한다. 여기 남는 것들은 테스트도 쓰지 않는다.
 *
 * **주석과 문자열 안의 이름은 참조가 아니다** (`#1351` · :func:`withoutCommentsAndStrings`).
 * 설명 문장에 이름이 우연히 나온다는 이유로 죽은 코드가 빠져나가면, 이 검사는 **잡는
 * 것이 없는데 초록**인 상태가 된다.
 *
 * ## 이 그물에 걸리지 않는 참조가 있다
 *
 * **파이썬 테스트가 TS 소스를 문자열로 읽는다.** `tests/test_reports.py`가
 * `realtimeRules.ts`에서 `export const PROJECTION_REASONS` 문자열을 **그대로 잘라**
 * 파싱한다. 프론트엔드만 훑는 검사에는 절대 걸리지 않으므로 아래에서 따로 잠근다.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url))

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx?$/.test(entry) ? [full] : []
  })
}

const FILES = walk(HERE)

/**
 * **이 파일은 참조를 세는 대상에서 뺀다.** 아래 `KEPT` 목록이 이름들을 문자열로
 * 담고 있어, 포함하면 목록에 적는 순간 「참조가 생겼다」가 되어 검사가 스스로를
 * 무력화한다.
 */
const SELF = join(HERE, 'moduleBoundary.test.ts')
/** 원문 그대로. **문자열 내용을 봐야 하는 검사**가 이것을 쓴다 (`#1351`). */
const RAW = new Map(FILES.filter((f) => f !== SELF).map((f) => [f, readFileSync(f, 'utf-8')]))

/** 참조를 세는 사본 — 주석·문자열 내용이 지워져 있다 (`#1351`). */
const SOURCE = new Map([...RAW].map(([f, text]) => [f, withoutCommentsAndStrings(text)]))

const DECLARATION = /^export (?:const|function|class|interface|type) (\w+)/gm

/**
 * 주석과 문자열의 **내용**을 지운 사본. 참조는 이것으로 센다 (`#1351`).
 *
 * ## 무엇이 문제였나
 *
 * 종전에는 파일 본문을 그대로 훑어 **주석 속 이름도 참조로 셌다.** 렌더 소비처가
 * 0곳인 `ComingSoon`이 다른 파일의 **설명 문장**에 이름이 나온다는 이유로 미참조
 * 목록에 걸리지 않았다 — `KEPT`에 등재되어 봐준 것이 아니라 **탐지기가 못 본 것**이다.
 *
 * 위험한 것은 죽은 코드 하나가 아니다. **앞으로 진짜 죽은 코드가 생겨도 누군가의 설명
 * 주석에 같은 이름이 우연히 등장하면 이 검사가 조용히 놓친다** — 잡는 것이 없는데
 * 초록인 상태가 가장 나쁘다.
 *
 * ## 문자열도 지운다
 *
 * 이름이 문자열 안에 있는 것은 **코드가 그 export를 쓰는 것이 아니다.**
 * `screens.test.ts`의 `source.includes('ComingSoon')`이 그 예다 — 페이지 파일 **본문에
 * 그 낱말이 있는지**를 보는 것이지 컴포넌트를 부르는 것이 아니다.
 *
 * 문자열을 지워서 새로 드러나는 것은 **`ComingSoon` 하나뿐이다**(실측). 파이썬 검사가
 * TS 소스를 문자열로 읽는 건은 아래 `KEPT`가 이미 따로 잠그고 있다.
 *
 * 따옴표 자체는 남긴다 — 지우는 것은 **내용**이고, 단어 경계 검색만 하므로 줄 수·위치는
 * 맞출 필요가 없다.
 */
function withoutCommentsAndStrings(text: string): string {
  let out = ''
  let index = 0
  let quote: string | null = null

  while (index < text.length) {
    const char = text[index]

    if (quote) {
      if (char === '\\') {
        index += 2
        continue
      }
      if (char === quote) {
        out += char
        quote = null
      }
      index += 1
      continue
    }

    if (char === "'" || char === '"' || char === '`') {
      quote = char
      out += char
      index += 1
      continue
    }

    if (char === '/' && text[index + 1] === '/') {
      const end = text.indexOf('\n', index)
      index = end === -1 ? text.length : end
      continue
    }

    if (char === '/' && text[index + 1] === '*') {
      const end = text.indexOf('*/', index + 2)
      index = end === -1 ? text.length : end + 2
      continue
    }

    out += char
    index += 1
  }

  return out
}

/** `src` 기준 상대 경로 + 이름. 목록 키와 같은 모양이다. */
function key(file: string, name: string): string {
  return `${relative(HERE, file).replaceAll('\\', '/')}::${name}`
}

function unreferencedExports(): string[] {
  const found: string[] = []
  for (const [file, text] of SOURCE) {
    if (file.includes('.test.')) continue
    for (const [, name] of text.matchAll(DECLARATION)) {
      const pattern = new RegExp(`\\b${name}\\b`)
      const used = [...SOURCE].some(([other, body]) => other !== file && pattern.test(body))
      if (!used) found.push(key(file, name))
    }
  }
  return found.sort()
}

/**
 * 남아 있는 미참조 `export`와 **남긴 이유**.
 *
 * 이슈 완료 기준 그대로다 — 「남아 있다면 남긴 이유가 코드에 있다」.
 */
const KEPT: Readonly<Record<string, string>> = {
  // ── 의도된 보관: 지금 쓰이지 않지만 지우지 않는다 ─────────────────────────
  'components/ComingSoon.tsx::ComingSoon':
    '#594 판정 — 렌더 소비처가 0곳이지만 미구현 화면의 표준 스텁이라 남긴다. ' +
    '#1351 전까지는 다른 파일의 주석·문자열에 이름이 나온다는 이유로 탐지기가 이것을 ' +
    '「참조 있음」으로 오인해, 봐준 것이 아니라 못 본 것이었다',

  // ── 크로스 언어 참조: 파이썬 가드가 이 파일을 문자열로 읽는다 ──────────────
  'features/realtime-cii/realtimeRules.ts::PROJECTION_REASONS':
    'tests/test_reports.py가 `export const PROJECTION_REASONS` 문자열을 잘라 파싱한다',
  'features/voyage-cii/resultRules.ts::RISK_LABEL':
    'tests/test_reports.py가 이 파일을 읽어 DESIGN_SYSTEM §2.5 (b) 🔒과 대조한다',

  // ── provider 오류 계약 ────────────────────────────────────────────────────
  'features/annual-simulation/apiProvider.ts::AnnualSimulationError':
    '오류 계약 4종(VoyageError·NotUnderwayError·ParametersError·FuelCatalogError) 중 하나. 하나만 감추면 이 provider만 다른 규칙으로 읽힌다',

  // ── provider·훅 경계 타입: 이름이 곧 경계 문서다 (#134) ────────────────────
  'api/parameters.ts::ParametersProvider': 'provider 경계 (#134)',
  'api/parameters.ts::FuelTypeOption': 'provider 응답 계약',
  'features/parameters/fuelCatalog.ts::FuelCatalogProvider': 'provider 경계 (#134)',
  'features/parameters/fuelCatalog.ts::FuelOptionsState': '훅 반환 계약',
  'features/parameters/yearCatalog.ts::YearOptionsState': '훅 반환 계약',
  'features/voyage-cii/vesselCatalog.ts::VesselCatalogProvider': 'provider 경계 (#134)',
  'layout/voyageCatalog.ts::VoyageCatalogProvider': 'provider 경계 (#134)',

  // ── API 응답 계약: 추론으로만 쓰여도 계약이다 ─────────────────────────────
  // `auth/session.ts::CurrentUser`는 여기 있었다. `#717`에서 `AccountMenu`가 prop
  // 타입으로 명시하면서 참조가 생겨 뺐다 — 남겨 두면 목록이 거짓말이 된다.
  'features/annual-simulation/types.ts::DeterministicBlock': 'API_SPEC §6.1 응답 계약',
  'features/annual-simulation/types.ts::RngMetadata': 'API_SPEC §6.1 응답 계약',
  'features/annual-simulation/types.ts::SnapshotBlock': 'API_SPEC §6.1 응답 계약',
  'features/realtime-cii/types.ts::ProjectionAssumptions': 'API_SPEC §2.11 응답 계약',
  'features/voyage-cii/types.ts::VoyageCiiData': 'API_SPEC §4.1 응답 계약',
  'features/voyage-cii/types.ts::CalculationBasis': 'API_SPEC §4.1 응답 계약',
  'features/voyage-cii/types.ts::FuelCfDetail': 'API_SPEC §4.1 응답 계약',
  'features/voyage-cii/types.ts::FuelUseInput': 'API_SPEC §4.1 요청 계약',
  'features/voyage-cii/types.ts::ModelVersion': 'API_SPEC §1.8 재현성 계약',
  'features/voyage-cii/types.ts::ParametersUsed': 'API_SPEC §4.1 재현성 계약',
  'features/voyage-cii/types.ts::ResponseMeta': 'API_SPEC §1.1 공통 meta 계약',
  'features/fleet/types.ts::FleetAction': 'API_SPEC §2.8 응답 계약',
  'features/fleet/types.ts::FleetCounts': 'API_SPEC §2.8 응답 계약',
  'features/vessel-detail/types.ts::YearStatus': '선박 상세 연도별 상태 계약',

  // ── 내보낸 함수의 인자·반환 형태: 소비자가 이름으로 받을 수 있어야 한다 ──
  'components/applicability.ts::ApplicabilityState': 'applicabilityState()의 반환 형태',
  'components/gradeScale.ts::GradeScale': 'gradeScale()의 반환 형태',
  'components/gradeScale.ts::ScaleBand': 'GradeScale의 구성 요소',
  'features/annual-simulation/annualRules.ts::RiskFlagTone': 'riskFlag()의 반환 형태',
  'features/realtime-cii/realtimeRules.ts::RatingTransition': 'ratingTransition()의 반환 형태',
  'features/realtime-cii/realtimeRules.ts::TransitionDirection': 'RatingTransition의 구성 요소',
  'features/scenario-comparison/comparisonRules.ts::LowestSummary': 'lowestSummary()의 반환 형태',
  'features/scenario-comparison/comparisonRules.ts::ComparableMetric': '비교 지표 enum',
  'features/voyage-cii/resultRules.ts::MarginDisplay': 'marginDisplay()의 반환 형태',
  'features/vessel-registration/shipTypes.ts::ShipTypeOption': 'SHIP_TYPES 항목 형태',
  'features/vessel-registration/shipTypes.ts::CapacityAxis': 'capacityAxisOf()의 반환 형태',
  'screens.ts::ScreenWidth': 'SCREEN_BY_ID의 width 필드 형태 (DESIGN_SYSTEM §7.1)',
  'theme/theme.ts::ThemeMatchMedia': '테마 훅이 주입받는 matchMedia 형태 (테스트 대역용)',
}

describe('미참조 export 목록 (#594)', () => {
  it('파일과 export를 실제로 읽었다', () => {
    // 못 읽으면 아래 대조가 「빈 것끼리 같다」로 통과한다.
    expect(FILES.length).toBeGreaterThan(100)
    const total = [...SOURCE].reduce(
      (n, [f, t]) => n + (f.includes('.test.') ? 0 : [...t.matchAll(DECLARATION)].length),
      0,
    )
    expect(total).toBeGreaterThan(400)
  })

  it('목록에 없는 미참조 export가 없다', () => {
    const surprises = unreferencedExports().filter((k) => KEPT[k] === undefined)
    expect(surprises).toEqual([])
  })

  it('목록이 낡지 않았다 — 참조가 생긴 것은 뺀다', () => {
    const measured = new Set(unreferencedExports())
    const stale = Object.keys(KEPT).filter((k) => !measured.has(k))
    expect(stale).toEqual([])
  })

  it('남긴 것에는 사유가 있다', () => {
    for (const [name, reason] of Object.entries(KEPT)) {
      expect(reason.length, name).toBeGreaterThan(5)
    }
  })
})

describe('크로스 언어 참조 — 파이썬 가드가 읽는 자리 (#594)', () => {
  /*
   * 프론트엔드만 훑는 검사에는 걸리지 않는다. `export`를 떼면 파이썬 쪽이 깨지는데
   * 그 실패는 **다른 언어의 다른 파일**에서 나와 원인을 잇기 어렵다.
   */
  it('realtimeRules.ts가 `export const PROJECTION_REASONS`를 유지한다', () => {
    const source = readFileSync(join(HERE, 'features/realtime-cii/realtimeRules.ts'), 'utf-8')
    expect(source).toContain('export const PROJECTION_REASONS')
  })

  it('resultRules.ts가 `export const RISK_LABEL`을 유지한다', () => {
    const source = readFileSync(join(HERE, 'features/voyage-cii/resultRules.ts'), 'utf-8')
    expect(source).toContain('export const RISK_LABEL')
  })

  it('voyageRules.ts가 서버와 대조되는 두 표를 유지한다', () => {
    // `reports/labels.py`의 VOYAGE_STATUS_LABELS·INCLUSION_POLICY_LABELS가 이 둘을
    // 원본으로 삼는다. `#594`가 보고서 화면의 중복 표를 여기로 합쳤다.
    const source = readFileSync(join(HERE, 'features/voyage-management/voyageRules.ts'), 'utf-8')
    expect(source).toContain('export const STATUS_LABELS')
    expect(source).toContain('export const POLICY_LABELS')
  })
})

describe('항차 상태 이름표는 하나다 (#594)', () => {
  it('화면 전체에 상태 이름표가 하나뿐이다', () => {
    // 종전에는 보고서 화면이 자기 표를 갖고 같은 상태를 다른 이름으로 불렀다
    // (`계획 확정` ↔ `계획`), 그리고 `ARCHIVED`가 빠져 코드가 그대로 나왔다.
    // 이 검사는 **문자열 안의 이름표**를 보므로 원문을 쓴다 (`#1351`).
    const tables = [...RAW]
      .filter(([f]) => !f.includes('.test.'))
      .filter(([, t]) => /IN_PROGRESS: '[^']+'/.test(t) && /CONFIRMED: '[^']+'/.test(t))
      .map(([f]) => relative(HERE, f).replaceAll('\\', '/'))

    expect(tables).toEqual(['features/voyage-management/voyageRules.ts'])
  })
})

/**
 * 기능 사이 `apiProvider` import — **한 기능이 다른 기능의 요청 계층에 기대지 않는다** (`#1249`).
 *
 * ## 무엇이 문제였나
 *
 * `DEFAULT_API_BASE_URL`은 **어느 기능의 것도 아닌데** `voyage-cii/apiProvider.ts`에
 * 살았고(그리고 `annual-simulation`에 **한 벌 더** 있었다), 다른 기능 열여섯이 그것을
 * 가리켰다. `readPageMeta`도 `vessel-management`에서 둘이 가져다 썼다.
 *
 * 화면에는 드러나지 않는다. 드러나는 것은 **한 기능을 들어내려 할 때**다 — 선대·정박·
 * 챗봇·보고서가 `voyage-cii`의 파일 하나에 매달려 있었다. 같은 값이 두 곳에 있었다는
 * 것은 이미 **한쪽만 바뀌는 날**을 예약해 둔 상태이기도 했다.
 *
 * ## 왜 이 범위인가
 *
 * 기능 사이 import를 **전부** 막지 않는다. `voyage-cii/types`·`voyage-management/voyageRules`
 * 처럼 **도메인 규칙과 타입**을 나눠 쓰는 자리가 백여 곳이고, 그것을 한 번에 끊는 것은
 * 이 이슈의 결정(`#1249` 「나」)이 하지 않기로 한 일이다. 여기서 잠그는 것은 **요청
 * 계층**(`apiProvider` · `*Provider.ts`)이다 — 공용으로 옮길 자리가 이미 생겼으므로
 * (`api/base.ts`) 새로 기대는 것은 실수다.
 */
describe('기능 사이 요청 계층 import (#1249)', () => {
  const FEATURE = /features\/([a-z-]+)\//

  /**
   * **원문(`RAW`)으로 센다.** `SOURCE`는 문자열 **내용**을 지운 사본이라
   * (`#1351`) `from '../x/apiProvider'`의 경로가 통째로 사라진다 — 그것으로 세면
   * 위반이 하나도 없는 것처럼 보인다. 대신 `import` 줄만 본다(주석 속 경로가
   * 위반으로 잡히지 않게).
   */
  function crossFeatureProviderImports(): string[] {
    const found: string[] = []
    for (const [file, text] of RAW) {
      const from = FEATURE.exec(relative(HERE, file).replaceAll('\\', '/'))
      if (from === null) continue
      for (const match of text.matchAll(/^import[^\n]*from '\.\.\/([a-z-]+)\/([A-Za-z]*[Pp]rovider)'/gm)) {
        if (match[1] !== from[1]) {
          found.push(`${relative(HERE, file).replaceAll('\\', '/')} → ${match[1]}/${match[2]}`)
        }
      }
    }
    return found.sort()
  }

  /**
   * 남겨 둔 다섯 — **화면이 다른 기능의 조회를 합쳐 보이는 자리**와 **여러 기능의
   * 경로를 한자리에서 대조하는 검사**다. 요청 계층이 서로에게 기대는 것이 아니라
   * 바깥에서 둘을 **조립**하는 것이므로 이 규칙이 막으려던 결합과 다르다.
   *
   * 목록으로 두는 이유는 `#594`의 `KEPT`와 같다 — **새로 늘면 여기서 걸리고**,
   * 사유를 적지 않은 채로는 늘릴 수 없다.
   */
  const COMPOSITION = [
    // 선대 대시보드가 데이터 점검의 「실적 확정 전」 목록을 함께 보인다.
    'features/fleet/UnconfirmedVoyages.tsx → data-quality/apiProvider',
    // 한 화면이 항차 하나를 읽어 폼을 채운다 — 항차 관리의 조회를 다시 만들지 않는다.
    'features/voyage-cii/VoyageCiiForm.tsx → voyage-management/apiProvider',
    // 아래 셋은 검사다. 여러 기능의 요청 경로·타입을 한자리에서 대조한다.
    'features/voyage-cii/VoyageCiiActions.test.tsx → voyage-management/apiProvider',
    'features/voyage-cii/apiPath.test.ts → annual-simulation/apiProvider',
    'features/voyage-cii/apiPath.test.ts → scenario-comparison/apiProvider',
  ].sort()

  it('요청 계층 결합은 사유가 적힌 다섯뿐이다', () => {
    expect(crossFeatureProviderImports()).toEqual(COMPOSITION)
  })

  it('목록이 낡지 않았다 — 사라진 자리는 뺀다', () => {
    const actual = new Set(crossFeatureProviderImports())
    expect(COMPOSITION.filter((entry) => !actual.has(entry))).toEqual([])
  })

  it('공용 자리가 실제로 있다 — 규칙만 있고 갈 곳이 없으면 규칙이 무시된다', () => {
    const shared = readFileSync(join(HERE, 'api/base.ts'), 'utf-8')
    expect(shared).toContain('export const DEFAULT_API_BASE_URL')
    expect(shared).toContain('export function readPageMeta')
  })

  it('같은 상수를 두 곳이 정의하지 않는다', () => {
    const definers = [...RAW]
      .filter(([, text]) => /^export const DEFAULT_API_BASE_URL/m.test(text))
      .map(([f]) => relative(HERE, f).replaceAll('\\', '/'))

    expect(definers).toEqual(['api/base.ts'])
  })
})
