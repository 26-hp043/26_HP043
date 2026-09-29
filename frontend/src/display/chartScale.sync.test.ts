import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { dirOf, srcKey } from '../test/srcPaths'

/**
 * **새로 만든 차트가 배율을 타면 붉어진다** (`DESIGN_SYSTEM §9.1` · `#2038`).
 *
 * ## 왜 목록으로 두는가
 *
 * `chartBox.test.tsx`는 훅이 **제 일을 하는지**를 본다 — 잰 폭과 뷰박스 폭이 같은지.
 * 그러나 그것만으로는 **훅을 안 쓰는 새 차트**를 잡지 못한다. `YtdSeriesChart`가
 * 정확히 그 자리에 있었다 — `non-scaling-stroke`를 쓰는 자리가 저장소에 넷이나
 * 있었는데 **그 하나만 빠져** 있었고, 아무 검사도 실패하지 않았다.
 *
 * 그래서 `viewBox`를 가진 파일을 **전부** 세고, 훅을 쓰지 않는 파일은 **여기에 이유를
 * 적어야** 통과한다. 새 파일이 생기면 둘 중 하나를 해야 한다 — 훅을 쓰거나, 왜 안
 * 쓰는지 적거나.
 *
 * ## 글리프는 배율을 타는 것이 맞다
 *
 * `§9`가 다루는 것은 **축 · 계열 · 경계선을 가진 그림**이다. 아이콘·글리프는 `§12`
 * 소관이고, CSS가 정한 크기에 맞춰 **통째로 늘어나는 것이 의도**다. 그래서 예외는
 * 목록을 채우는 요식이 아니라 **갈래**다.
 */
const SRC = dirOf(import.meta.url, '..')

/**
 * 훅을 쓰지 않아도 되는 파일과 **그 이유**.
 *
 * ⚠️ 「목록에 있으니 괜찮다」가 아니다 — `position-chart`는 **같은 증상이 남아 있고**
 * 이 이슈의 범위 밖이라 적어 둔 것이다. 이유를 함께 적어야 다음 사람이 가를 수 있다.
 */
const EXEMPT: Readonly<Record<string, string>> = {
  'features/fleet/PositionChart.tsx':
    '개략도 — 축·계열이 없어 §9 대상이 아니다. ⚠️ 다만 SVG `<text>` 둘이 배율을 탄다(#2038 범위 밖 · 후속)',
  'features/fleet/FleetMap.tsx': '지도 — 타일이 배율을 갖는다(maplibre 소관)',
  'features/fleet/FleetDashboard.tsx': '글리프 — 카드 장식',
  'features/fleet/VesselGlyph.tsx': '글리프 — 선박 실루엣',
  'features/fleet/UnderwayChip.tsx': '글리프 — 상태 칩 안의 표식',
  'features/vessel-management/VesselManagement.tsx': '글리프 — 목록 행의 선박 실루엣',
  'features/scenario-comparison/ScenarioRouteGlyph.tsx': '글리프 — 표 머리의 항로 모양',
  'layout/NavIcons.tsx': '아이콘 — §12 소관',
  'theme/ThemeToggle.tsx': '아이콘 — §12 소관',
}

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : tsxFiles(path)
    if (!/\.tsx$/.test(name) || /\.test\.tsx$/.test(name)) return []
    return [path]
  })
}

/** `viewBox`를 그리는 파일 — 검사 파일은 뺀다. */
function withViewBox(): string[] {
  return tsxFiles(SRC)
    .filter((path) => readFileSync(path, 'utf8').includes('viewBox'))
    .map((path) => srcKey(SRC, path))
    .sort()
}

/**
 * 훅을 **부르는지** 본다.
 *
 * ⚠️ 종전에는 `includes('useChartWidth')`였다. 돌연변이로 이름을 `useChartWidthX`로
 * 바꿔 봤더니 **초록이었다** — 부분 문자열이라 이름만 비슷해도 통과한다. 호출 모양
 * (`useChartWidth(`)으로 본다.
 */
function usesHook(key: string): boolean {
  return /\buseChartWidth\s*\(/.test(readFileSync(join(SRC, key), 'utf8'))
}

describe('차트는 배율을 타지 않는다 — 목록 (#2038)', () => {
  it('viewBox를 그리는 파일은 훅을 쓰거나 예외 목록에 이유가 있다', () => {
    const missing = withViewBox().filter((key) => !usesHook(key) && EXEMPT[key] === undefined)
    expect(missing).toEqual([])
  })

  it('예외 목록에 죽은 항목이 없다 — 파일이 사라지거나 훅을 쓰기 시작하면 지운다', () => {
    const live = new Set(withViewBox().filter((key) => !usesHook(key)))
    const dead = Object.keys(EXEMPT).filter((key) => !live.has(key))
    expect(dead).toEqual([])
  })

  it('두 차트는 훅을 쓴다', () => {
    expect(usesHook('features/realtime-cii/YtdSeriesChart.tsx')).toBe(true)
    expect(usesHook('features/vessel-detail/CiiHistoryChart.tsx')).toBe(true)
  })
})

/**
 * `§9`가 정한 px가 **CSS에 그대로 적혀 있는지** 본다.
 *
 * 배율이 `1.0×`로 고정된 뒤에야 이 값들이 화면의 px가 된다 — 그전에는 같은 선언이
 * 창 폭에 따라 `1.53`~`4.37px`로 그려졌다. 두 가드가 짝이다.
 */
describe('§9 치수가 CSS와 같다 (#2038)', () => {
  const YTDS = readFileSync(join(SRC, 'features/realtime-cii/YtdSeriesChart.css'), 'utf8')

  /**
   * `.클래스 { … }` 한 덩어리를 꺼낸다 — **주석은 지운다.**
   *
   * 주석에 규칙 이름이 적혀 있으면(여기서는 「`inline-size: 100%`를 두면…」) 검사가
   * 설명문을 선언으로 읽는다. 값이 아니라 **말**을 보고 판정하는 셈이다.
   */
  function rule(selector: string): string {
    const found = YTDS.match(new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`))
    return found === null ? '' : found[1].replace(/\/\*[\s\S]*?\*\//g, '')
  }

  it('§9.2 실적·예측 선은 1.5px이다 — v2.34', () => {
    expect(rule('.ytds__actual')).toMatch(/stroke-width:\s*1\.5\s*;/)
    expect(rule('.ytds__plan')).toMatch(/stroke-width:\s*1\.5\s*;/)
  })

  it('§9.2 예측은 점선 `6 4`다', () => {
    expect(rule('.ytds__plan')).toMatch(/stroke-dasharray:\s*6 4\s*;/)
  })

  it('§9.4 등급 경계선은 1px dashed `3 3`이고 등급색을 쓰지 않는다', () => {
    const boundary = rule('.ytds__boundary')
    expect(boundary).toMatch(/stroke-width:\s*1\s*;/)
    expect(boundary).toMatch(/stroke-dasharray:\s*3 3\s*;/)
    expect(boundary).not.toMatch(/--cii-/)
  })

  it('§9.1 축 라벨은 caption(12px)이다', () => {
    expect(rule('.ytds__band-label,\n.ytds__edge-label,\n.ytds__today-label')).toMatch(
      /font-size:\s*var\(--font-size-caption\)/,
    )
  })

  it('캔버스를 늘이지 않는다 — 뷰박스가 실제 픽셀이다', () => {
    expect(rule('.ytds__canvas')).not.toMatch(/inline-size:\s*100%/)
  })
})
