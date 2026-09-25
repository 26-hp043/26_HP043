import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const assets = join(process.cwd(), 'dist', 'assets')
const files = readdirSync(assets).filter((file) => file.endsWith('.js'))
const size = (prefix) => files.filter((file) => file.startsWith(prefix)).reduce((sum, file) => sum + statSync(join(assets, file)).size, 0)
const budgets = [
  ['초기 application JS', 'index-', 750 * 1024],
  ['Harbor lazy loader', 'harborRenderer-', 5 * 1024],
  ['Three shared lazy chunk', 'three.module-', 550 * 1024],
  ['Three Harbor scene', 'harborSceneRenderer-', 100 * 1024],
  ['Three vessel custom layer', 'vesselLayer-', 10 * 1024],
  ['MapLibre adapter', 'mapLibreRenderer-', 100 * 1024],
  // MapLibre 본체가 들어가는 공유 청크. **이름은 Vite가 모듈 그래프에서 고른다** —
  // `#1909`에서 워커 주소를 고정하는 모듈이 생기며 `routeStyles-`에서 이 이름으로 바뀌었다.
  // 크기 예산은 그대로다(바뀐 것은 이름뿐이다).
  ['MapLibre shared chunk', 'mapLibreWorker-', 1100 * 1024],
  // 타일 파싱 워커 (`#1909`). **0이면 빌드가 워커를 빠뜨린 것이고, 그때 지도는
  // 회색 사각형이 된다** — maplibre는 오류를 내지 않으므로 이 줄이 유일한 신호다.
  ['MapLibre 타일 워커', 'maplibre-gl-worker-', 600 * 1024],
]
let failed = false
for (const [label, prefix, budget] of budgets) {
  const bytes = size(prefix)
  const over = bytes === 0 || bytes > budget
  if (over) failed = true
  console.log(`${over ? 'FAIL' : 'PASS'} ${label}: ${bytes} / ${budget} bytes`)
}
if (failed) process.exitCode = 1
