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
 * ## 자산은 저장소에 있다 (`#985` · 2026-09-18)
 *
 * 전 세계 z0–z5 타일 15 MB + 글리프 12 MB = **26 MB**다. 종전에는 넣지 않았고
 * 근거는 「83 MB」였는데, 그 값은 항만 43곳의 z7–z10을 더한 것이었다 — 배포처가
 * **파일 하나 25 MiB**로 막으므로 어차피 올라가지 않는다. 범위를 좁혀 넣는다.
 *
 * 넣지 않으면 배포본에서는 **영원히 개략도만** 뜬다. Cloudflare Pages는 저장소를
 * 받아 빌드하므로, 빌드 단계에서 받아오게 하면 `pmtiles` CLI와 외부 네트워크가
 * **배포의 선행 조건**이 된다.
 *
 * 그래도 없을 수 있다(얕은 clone · 자산을 지운 로컬). 그때는 아래 `hasBasemap`이
 * 「없음」으로 접고 **개략도로 떨어진다**(`PositionChart`).
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
 * 근거는 둘이고 **좁은 쪽을 따른다.**
 *
 * ⑴ **위치 데이터가 정확도를 받치지 못한다.** 지금 좌표는 사람이 찍은 한 점이라
 *    z12까지 열면 한 달 전에 손으로 찍은 점이 부두 하나를 정확히 가리키는 것처럼
 *    보인다. AIS(`#764`)가 붙어 관측이 쌓이면 그때 올린다.
 * ⑵ **자산이 z5까지다** (`#985` · 2026-09-18). 배포처 제한(파일당 25 MiB) 안에
 *    들어가도록 전 세계 z0–z5만 담는다 — 15 MB다. 더 확대하면 마지막 층을 늘려
 *    보여 주므로(overzoom) 깨지지는 않지만, 다섯 단계를 늘리면 해안선이 뭉툭해진다.
 *    한 단계 정도가 한계라 `6`으로 둔다.
 *
 * 종전 값은 `10`이었다 — 자산이 항만 z7–z10까지 담는다는 전제였고, 그 전제가 바뀌었다.
 */
export const MAX_ZOOM = 6

/** 처음 그릴 때의 줌. 선대가 흩어져 있으면 아래 `fitBounds`가 다시 잡는다. */
export const INITIAL_ZOOM = 2

/** PMTiles 아카이브의 첫 7바이트 — `PMTiles` (spec v3). */
const PMTILES_MAGIC = [0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73]

/**
 * 자산이 실제로 있는지 묻는다.
 *
 * **첫 7바이트만 받아 매직 넘버를 본다.** 80 MB를 확인용으로 당길 수는 없고,
 * 있는지 없는지는 그 7바이트로 끝난다.
 *
 * 실패(404 · Range 미지원 · 네트워크 오류 · 매직 불일치)는 **전부 「없음」으로
 * 접는다.** 사용자에게는 어느 쪽이든 결과가 같고(개략도로 떨어진다), 원인을
 * 화면에서 가르면 문구만 늘어난다.
 *
 * ## 왜 `HEAD`가 아닌가 (`#1144`)
 *
 * 종전에는 `HEAD` 한 번으로 상태 코드만 봤다. 두 가지가 깨졌다.
 *
 * ⑴ **상태 코드는 거짓말을 한다.** SPA fallback을 쓰는 정적 서버는 없는 경로에
 *    `index.html`을 **200**으로 돌려준다 — 개발 Vite도, nginx의
 *    `try_files $uri $uri/ /index.html`도 그랬다. 그래서 자산이 없는데 「있다」로
 *    판정했고, 개략도로 떨어지지 않은 채 maplibre가 HTML을 PMTiles로 읽다
 *    실패했다. 그때 지도의 `load`가 오지 않아 **마커와 항로까지 그려지지 않았고**,
 *    화면에는 회색 사각형만 남았다.
 *
 * ⑵ **대용량 파일의 `HEAD`에 응답하지 않는 서버가 있다.** Vite 개발 서버가 이
 *    80 MB 파일의 `HEAD`에서 35초 동안 한 바이트도 돌려주지 않았다(같은 서버가
 *    `favicon.svg`·글리프 `.pbf`의 `HEAD`는 정상 응답했다). 그러면 자산이
 *    **있는데도** 판정이 끝나지 않아 지도가 영영 뜨지 않는다.
 *
 * 매직 넘버를 보면 둘 다 사라진다. HTML은 매직이 다르고, 잘린 파일도 걸러지며,
 * 받는 양은 7바이트다.
 *
 * ## `206`이 아니면 없는 것으로 본다
 *
 * PMTiles는 **Range 요청으로 파일 일부만 읽는다** — Range를 지원하지 않는 서버에서는
 * 어차피 지도가 뜨지 않는다. 그래서 `206`이 아니면 자산이 있든 없든 「없음」이다.
 * 본문을 읽지 않고 끊으므로 80 MB를 받아 버리는 일도 없다.
 */
export async function hasBasemap(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  url: string = BASEMAP_URL,
): Promise<boolean> {
  try {
    const response = await fetchImpl(url, {
      headers: { Range: `bytes=0-${PMTILES_MAGIC.length - 1}` },
    })
    if (response.status !== 206) {
      // 본문을 끌어오지 않고 끊는다 — 200이면 80 MB가 딸려 온다.
      await response.body?.cancel()
      return false
    }
    const head = new Uint8Array(await response.arrayBuffer())
    return isPmtiles(head)
  } catch {
    return false
  }
}

/** 받은 앞머리가 PMTiles 아카이브인가 (`#1144`). */
function isPmtiles(head: Uint8Array): boolean {
  if (head.length < PMTILES_MAGIC.length) return false
  return PMTILES_MAGIC.every((byte, index) => head[index] === byte)
}
