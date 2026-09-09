/**
 * 파일 내려받기의 공용 조각 (`#890`).
 *
 * ## 왜 기능 폴더 밖인가
 *
 * 종전에는 두 조각이 전부 `features/reports/`에 있었다 — 서버가 파일을 내려보내는
 * 화면이 리포트뿐이었기 때문이다. `#890`이 **운항 기록 CSV 내보내기**를 항차 패널에
 * 붙이면서 두 번째 소비처가 생겼다.
 *
 * **복사하면 한쪽만 고쳐진다.** `display/decimal.ts`(`#820`)·`display/format.ts`의
 * `toDecimalInput`(`#872`)이 각각 같은 이유로 기능 폴더 밖으로 나온 선례다. 특히
 * `saveBlob`은 **`revokeObjectURL`을 빠뜨리면 조용히 메모리가 샌다** — 그 규율이
 * 한 곳에만 남는 상태를 만들지 않는다.
 */

/**
 * `Content-Disposition` 헤더에서 파일명을 꺼낸다.
 *
 * 서버는 ASCII `filename`과 UTF-8 `filename*`을 **둘 다** 보낸다(RFC 6266 §4.3).
 * `filename*`을 우선한다 — 그쪽이 사람이 읽는 한글 이름이다.
 *
 * 헤더가 없으면 `null`이다. 호출부가 대체 이름을 만든다 — 여기서 지어 내면
 * 「서버가 준 이름」과 「우리가 만든 이름」이 섞여 어느 쪽인지 알 수 없다.
 */
export function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null

  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // 잘못 인코딩된 헤더로 다운로드 전체를 실패시키지 않는다 — ASCII로 내려간다.
    }
  }

  const ascii = /filename="([^"]+)"/i.exec(disposition)
  return ascii ? ascii[1] : null
}

/**
 * blob을 파일로 저장한다.
 *
 * `revokeObjectURL`을 반드시 부른다 — 부르지 않으면 blob이 탭이 닫힐 때까지
 * 메모리에 남고, 파일을 여러 번 받는 화면에서 그대로 누적된다.
 *
 * provider가 이 함수를 **주입 가능한 인자로** 받는 이유는 이 저장소의 provider
 * 검사가 node 환경이라 `document`가 없기 때문이다.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
