/**
 * 어느 항만에 **장면이 있는가** (`#1933`).
 *
 * 저장소가 담은 항만 스냅샷은 둘뿐이다 — 부산 북항(`KRPUS`)·싱가포르(`SGSIN`).
 * 그 밖의 항은 핀만 서고 **들어갈 곳이 없다.**
 *
 * ## 왜 따로 두는가
 *
 * 이 대응을 `HarborTransitionShell`이 자기 안에 갖고 있었다. 그러면 **핀을 만드는 쪽**
 * (`adapters.ts`)이 「이 핀을 눌러도 되는가」를 알 수 없어, 대시보드 핀은 아예 누를 수
 * 없는 그림으로 남았다 — 항만이 있는데 들어갈 길이 없었다(`#1933`).
 *
 * 무거운 것을 끌고 오지 않는 **작은 모듈**로 꺼내 둔다. `harborRenderer.ts`(three 장면)는
 * lazy 경계 뒤에 그대로 있고, 여기서는 이름만 다룬다.
 */

/**
 * 장면이 있는 항만. 키는 UN/LOCODE다.
 *
 * ⚠️ **싱가포르는 두 코드로 온다.** 샘플 항만표(NGA World Port Index · `API_SPEC §3.8`)가
 * 쓰는 값은 `SGKEP`(Keppel)이고, 종전 판정은 `SGSIN`만 봤다 — 그래서 싱가포르 항차의
 * 도착 핀이 **장면이 있는데도 그림으로 남았다**(`#1933` 실측). 둘 다 같은 장면을 연다.
 */
const SCENES = { KRPUS: 'busan', SGSIN: 'singapore', SGKEP: 'singapore' } as const

/** 장면 이름. 모듈 밖에서는 `harborSceneFor()`의 반환값으로만 쓴다. */
type HarborSceneId = (typeof SCENES)[keyof typeof SCENES]

/**
 * 이 문자열이 장면 있는 항만을 가리키는가.
 *
 * 항구 핀의 id(`fleet:KRPUS:35.1,129.0`)와 선택 이벤트 id(`port:…`) 양쪽이 들어온다 —
 * **LOCODE가 들어 있으면** 그 장면이다. 대소문자는 가리지 않는다.
 */
export function harborSceneFor(value: string | null | undefined): HarborSceneId | null {
  if (!value) return null
  const upper = value.toUpperCase()
  for (const [locode, scene] of Object.entries(SCENES)) {
    if (upper.includes(locode)) return scene
  }
  return null
}
