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
  ['MapLibre shared routeStyles chunk', 'routeStyles-', 1100 * 1024],
]
let failed = false
for (const [label, prefix, budget] of budgets) {
  const bytes = size(prefix)
  const over = bytes === 0 || bytes > budget
  if (over) failed = true
  console.log(`${over ? 'FAIL' : 'PASS'} ${label}: ${bytes} / ${budget} bytes`)
}
if (failed) process.exitCode = 1
