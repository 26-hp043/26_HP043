/**
 * 지도 자산의 자리와 있는지 여부 (`#763`).
 *
 * ## 키가 없고 런타임 외부 요청도 없다
 *
 * 타일은 **우리 오리진에서 서빙하는 PMTiles 파일 하나**다. `PRD §5.2`가 지도를
 * 제외하며 든 네 사유(타일 서비스 · API 키 · 비용 · 오프라인 시연) 중 어느 것도
 * 이 방식에는 해당하지 않는다 —
 *
 * - **키 없음**: `VITE_` 접두 값은 번들에 그대로 인라인되므로(`README`) 애초에
 *   프론트에 키를 둘 수 없다. 키가 필요 없는 방식만 쓸 수 있다.
 * - **외부 요청 없음**: 자기 오리진의 정적 파일이다. OSM 표준 타일 서버는
 *   **사전 다운로드를 정책이 금지**하고 예고 없이 차단할 수 있다.
 * - **오프라인 동작**: 심사장 인터넷이 보장되지 않는다(`#791`).
 *
 * ## 자산은 저장소에 없다
 *
 * 파일이 약 83 MB다(전 세계 z0–z6 + 항만 43곳 주변 z7–z10 · 2026-09-12 실측).
 * 이미지가 이미 699 MB라 여기에 더할 수 없다 — `scripts/fetch_basemap.sh`가
 * 배포 볼륨으로 내려받고, 없으면 **개략도로 떨어진다**(`PositionChart`).
 */

/** 자산 경로. 정적 서버가 HTTP Range를 지원해야 한다(nginx는 지원). */
export const BASEMAP_URL = '/basemap/bluelog.pmtiles'

/**
 * 글리프(글자 모양) 자산의 자리.
 *
 * **CDN을 가리키지 않는다.** 가리키면 오프라인에서 지도 배경은 뜨는데 **글자만
 * 사라진다** — 고장인지 아닌지 판단할 수 없는 상태가 가장 나쁘다. 타일과 같은
 * 스크립트가 같은 볼륨에 내려받는다.
 */
export const BASEMAP_FONTS_URL = '/basemap/fonts'

/** 자산이 없을 때 화면에 적는 말. 「지도가 없다」가 아니라 **왜 없는지**를 적는다. */
export const BASEMAP_MISSING_NOTICE =
  '지도 자산이 없어 개략도로 표시합니다. 위치 관계와 등급은 그대로 읽을 수 있습니다.'

/**
 * 확대 상한 (`#763` ⓐ 결정).
 *
 * 자산은 z10까지 담는다. 더 확대하면 마지막 층을 늘려 보여 주므로(overzoom) 화면이
 * 깨지지는 않지만, **위치 데이터가 그 정확도를 받치지 못한다** — 지금 좌표는 사람이
 * 찍은 한 점이라 z12까지 열면 한 달 전에 손으로 찍은 점이 부두 하나를 정확히
 * 가리키는 것처럼 보인다. AIS(`#764`)가 붙어 관측이 쌓이면 그때 올린다.
 */
export const MAX_ZOOM = 10

/** 처음 그릴 때의 줌. 선대가 흩어져 있으면 아래 `fitBounds`가 다시 잡는다. */
export const INITIAL_ZOOM = 2

/**
 * 자산이 실제로 있는지 묻는다.
 *
 * **`HEAD` 한 번**으로 끝낸다 — PMTiles는 Range 요청으로 읽으므로 본문을 받을
 * 필요가 없고, 83 MB를 확인용으로 당길 수는 더더욱 없다.
 *
 * 실패(404 · 네트워크 오류 · Range 미지원 서버)는 **전부 「없음」으로 접는다.**
 * 사용자에게는 어느 쪽이든 결과가 같고(개략도로 떨어진다), 원인을 화면에서 가르면
 * 문구만 늘어난다.
 *
 * ## 상태 코드만으로는 모자란다 (`#1144`)
 *
 * SPA fallback을 쓰는 정적 서버는 **없는 경로에 `index.html`을 200으로 돌려준다**
 * — 개발 Vite도, 운영 nginx의 `try_files $uri $uri/ /index.html`도 그랬다. 그래서
 * `response.ok`만 보면 자산이 없는데 **「있다」로 판정**하고, 개략도로 떨어지지
 * 않는다. 그 다음은 maplibre가 HTML을 PMTiles로 읽다 실패하는데, 이때 지도의
 * `load` 이벤트가 끝내 오지 않아 **마커와 항로까지 그려지지 않는다**(`FleetMap`).
 * 화면에는 회색 사각형만 남고 안내 문구도 없다 — 고장인지 아닌지 알 수 없는 상태다.
 *
 * 그래서 **HTML이면 자산이 아니다**로 본다. 정적 서버가 무엇이든(Vite · nginx ·
 * 미리보기) 같게 동작한다. 서버 쪽에서도 `/basemap/`을 fallback에서 빼 두었지만
 * (`frontend/nginx.conf`), 그 설정이 닿지 않는 자리가 있으므로 이 판정을 남긴다.
 */
export async function hasBasemap(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  url: string = BASEMAP_URL,
): Promise<boolean> {
  try {
    const response = await fetchImpl(url, { method: 'HEAD' })
    if (!response.ok) return false
    return !isHtml(response.headers.get('content-type'))
  } catch {
    return false
  }
}

/**
 * 응답이 HTML인가 — 즉 자산이 아니라 SPA fallback인가 (`#1144`).
 *
 * `content-type`이 없는 응답은 **HTML로 보지 않는다.** 헤더를 주지 않는 정적 서버가
 * 있고, 그 경우까지 「없음」으로 접으면 자산이 실제로 있는 환경에서 지도가 사라진다 —
 * 놓치는 쪽이 잘못 끄는 쪽보다 낫다.
 */
function isHtml(contentType: string | null): boolean {
  if (contentType === null) return false
  return contentType.split(';', 1)[0].trim().toLowerCase() === 'text/html'
}
