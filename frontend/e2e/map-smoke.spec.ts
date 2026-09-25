import { expect, test, type Page } from '@playwright/test'

async function fixtures(page: Page, routeFailure = false) {
  await page.route('**/api/v1/ports/samples', (route) => route.fulfill({ json: { data: [] } }))
  await page.route('**/api/v1/ports/sea-route**', (route) => routeFailure
    ? route.fulfill({ status: 503, json: { detail: 'smoke failure' } })
    : route.fulfill({ json: { data: { coordinates: [[129.0333, 35.1], [120, 20], [103.85, 1.2833]], length_nm: 2500, legs: 1, source: 'searoute/marnet' } } }))
}

test.beforeEach(async ({ page }) => { await fixtures(page) })

test('Fleet·Comparison·Annual과 Harbor 왕복 visual smoke', async ({ page }, testInfo) => {
  const pageErrors: Error[] = []
  const consoleErrors: string[] = []
  const failedRequests: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error))
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('requestfailed', (request) => {
    // StrictMode cleanup과 history 전환이 취소한 fetch는 의도된 resource 정리다.
    if (!request.failure()?.errorText.includes('ERR_ABORTED')) failedRequests.push(request.url())
  })
  await page.goto('/map-smoke.html')
  await expect(page.locator('[data-smoke="fleet"] [role="img"]')).toBeVisible()
  await expect(page.locator('[data-smoke="comparison"] [role="img"]')).toBeVisible()
  await expect(page.getByRole('region', { name: '항로 재생 제어' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('maps.png'), fullPage: true })
  const port = page.getByRole('button', { name: /싱가포르.*도착항/ }).first()
  await port.click()
  await expect(page.getByRole('button', { name: '전체 항로로 돌아가기' })).toBeFocused()
  const harbor = page.getByRole('region', { name: '싱가포르 항만 상세 장면' })
  await expect(harbor.getByRole('status')).toContainText(/항만 장면이 준비|표시하지 못했습니다/)
  await page.goBack()
  await expect(port).toBeFocused()
  await port.click()
  await expect(page.getByRole('button', { name: '전체 항로로 돌아가기' })).toBeFocused()
  await page.goBack()
  await expect(port).toBeFocused()
  expect(pageErrors.filter((error) => !error.message.includes('ResizeObserver loop'))).toEqual([])
  expect(consoleErrors.filter((message) => !message.includes('지도 오류'))).toEqual([])
  expect(failedRequests).toEqual([])
})

test('reduced-motion과 low quality는 정적 fallback 의미를 유지한다', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/map-smoke.html')
  await page.getByRole('button', { name: /싱가포르.*도착항/ }).first().click()
  const harbor = page.getByRole('region', { name: '싱가포르 항만 상세 장면' })
  await expect(harbor.getByRole('status')).toContainText(/기기 성능 또는 움직임 설정|3D 항만/)
  await expect(page.getByRole('button', { name: '전체 항로로 돌아가기' })).toBeVisible()
})

test('명시적 autoplay fixture만 Annual playback을 시작하고 reduced-motion은 억제한다', async ({ page }) => {
  await page.goto('/map-smoke.html?autoplay=1#annual-playback-scene')
  await expect(page.getByRole('status').filter({ hasText: /재생 중/ })).toBeVisible()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.reload()
  await expect(page.getByRole('status').filter({ hasText: /일시정지/ })).toBeVisible()
})

test('low quality capability에서는 항만 3D 대신 설명 가능한 fallback을 쓴다', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'deviceMemory', { configurable: true, value: 2 })
  })
  await page.goto('/map-smoke.html')
  await page.getByRole('button', { name: /싱가포르.*도착항/ }).first().click()
  await expect(page.getByRole('region', { name: '싱가포르 항만 상세 장면' }).getByRole('status'))
    .toContainText('기기 성능 또는 움직임 설정')
})

test('route 실패는 계산 화면을 중단하지 않고 대체 문구를 보인다', async ({ page }) => {
  await page.unrouteAll({ behavior: 'wait' })
  await fixtures(page, true)
  await page.goto('/map-smoke.html')
  await expect(page.getByText(/항로선을 불러오지 못했습니다/).first()).toBeVisible()
  await expect(page.getByRole('region', { name: '항로 재생 제어' })).toBeVisible()
})

test('PMTiles 실패는 구조화 대체 정보로 격리된다', async ({ page }) => {
  await page.route('**/basemap/bluelog.pmtiles**', (route) => route.abort('failed'))
  await page.goto('/map-smoke.html')
  await expect(page.getByRole('img', { name: /현재 위치 개략도/ })).toBeVisible()
  await expect(page.getByText(/지도 타일을 불러오지 못했습니다/).first()).toBeVisible()
  await expect(page.getByRole('region', { name: '항로 재생 제어' })).toBeVisible()
})

test('WebGL unavailable에서도 화면과 텍스트 경로를 유지한다', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return null
      return Reflect.apply(original, this, [type, ...args])
    } as typeof HTMLCanvasElement.prototype.getContext
  })
  await page.goto('/map-smoke.html')
  await expect(page.getByRole('img', { name: /현재 위치 개략도/ })).toBeVisible()
  await expect(page.getByRole('region', { name: '항로 비교 지도 대체 정보' })).toBeVisible()
  await expect(page.getByRole('region', { name: '항로 재생 제어' })).toBeVisible()
})

test('Harbor 자산 실패 뒤에도 history back과 focus return이 동작한다', async ({ page }) => {
  await page.route('**/harbor/*.json', (route) => route.fulfill({ status: 503, body: 'fixture failure' }))
  await page.goto('/map-smoke.html')
  const port = page.getByRole('button', { name: /싱가포르.*도착항/ }).first()
  await port.click()
  const harbor = page.getByRole('region', { name: '싱가포르 항만 상세 장면' })
  await expect(harbor.getByRole('status')).toContainText('항만 장면을 표시하지 못했습니다')
  await page.goBack()
  await expect(port).toBeFocused()
})
