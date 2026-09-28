/**
 * 표의 **머리글이 자기 열과 같은 정렬 클래스를 받는가** (`#2015`).
 *
 * CSS 쪽은 `styles/textAlign.sync.test.ts`가 「규칙이 이기는가」를 봅니다. 그 규칙이
 * 이겨도 **머리글에 클래스가 없으면** 여전히 한 열 안에서 정렬이 갈립니다 — 실제로
 * 규제 기준값의 「연도」와 선박 상세의 여섯 열이 그 상태였습니다.
 *
 * jsdom은 캐스케이드를 계산하지 않으므로 **클래스가 붙었는가**로 봅니다. 열 번호는
 * `thead`의 `th` 순서로 세고, 몸통 행의 같은 번째 칸과 맞춥니다(`th scope="row"` 포함).
 */

/** 머리글과 값의 정렬 클래스가 어긋난 열의 머리글 문구. */
export function misalignedColumns(table: HTMLTableElement, numericClass: string): string[] {
  const headers = [...table.querySelectorAll('thead th')]
  const rows = [...table.querySelectorAll('tbody tr')]
  const out: string[] = []

  headers.forEach((header, index) => {
    const cells = rows.map((row) => row.children[index]).filter(Boolean) as Element[]
    if (cells.length === 0) return
    const headerIsNum = header.classList.contains(numericClass)
    const cellsAreNum = cells.map((cell) => cell.classList.contains(numericClass))
    // 한 열 안에서 값끼리 갈리는 것도 어긋남이다 — 자릿수가 줄마다 다른 쪽에 선다.
    const uniform = cellsAreNum.every((v) => v === cellsAreNum[0])
    if (!uniform || cellsAreNum[0] !== headerIsNum) {
      const name = (header.textContent ?? '').trim().replace(/\s+/g, ' ')
      out.push(
        `${name || `${index}번째 열`} — 머리글 ${headerIsNum ? numericClass : '없음'} · ` +
          `값 ${[...new Set(cellsAreNum)].map((v) => (v ? numericClass : '없음')).join('/')}`,
      )
    }
  })
  return out
}
