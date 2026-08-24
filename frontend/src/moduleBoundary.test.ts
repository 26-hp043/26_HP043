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
 * **테스트 파일을 포함한 다른 모든 `.ts`/`.tsx`**에서 그 이름이 한 번이라도 나오면
 * 참조로 센다. `#594` 본문이 「테스트만 쓰는 것은 스크립트가 테스트를 제외해서
 * 잡혔다」고 적었는데 **사실이 아니다** — 재현 명령도 참조를 셀 때는 테스트를
 * 포함한다. 여기 남는 것들은 테스트도 쓰지 않는다.
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
const SOURCE = new Map(
  FILES.filter((f) => f !== SELF).map((f) => [f, readFileSync(f, 'utf-8')]),
)

const DECLARATION = /^export (?:const|function|class|interface|type) (\w+)/gm

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
  // ── 크로스 언어 참조: 파이썬 가드가 이 파일을 문자열로 읽는다 ──────────────
  'features/realtime-cii/realtimeRules.ts::PROJECTION_REASONS':
    'tests/test_reports.py가 `export const PROJECTION_REASONS` 문자열을 잘라 파싱한다',
  'features/voyage-cii/resultRules.ts::RISK_LABEL':
    'tests/test_reports.py가 이 파일을 읽어 DESIGN_SYSTEM §2.5 (b) 🔒과 대조한다',

  // ── provider 오류 계약 ────────────────────────────────────────────────────
  'features/annual-simulation/apiProvider.ts::AnnualSimulationError':
    '오류 계약 4종(VoyageError·NotUnderwayError·ParametersError·FuelCatalogError) 중 하나. 하나만 감추면 이 provider만 다른 규칙으로 읽힌다',

  // ── provider·훅 경계 타입: 이름이 곧 경계 문서다 (#134) ────────────────────
  'features/parameters/apiProvider.ts::ParametersProvider': 'provider 경계 (#134)',
  'features/parameters/apiProvider.ts::FuelTypeOption': 'provider 응답 계약',
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
  'features/voyage-cii/types.ts::WeatherModel': 'API_SPEC §4.1 weather_model enum',
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
    const tables = [...SOURCE]
      .filter(([f]) => !f.includes('.test.'))
      .filter(([, t]) => /IN_PROGRESS: '[^']+'/.test(t) && /CONFIRMED: '[^']+'/.test(t))
      .map(([f]) => relative(HERE, f).replaceAll('\\', '/'))

    expect(tables).toEqual(['features/voyage-management/voyageRules.ts'])
  })
})
