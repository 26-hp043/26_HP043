/**
 * 서버 오류의 `details[].field`가 이 화면에 입력창이 있는 이름인지 가린다 (#2126).
 *
 * 입력창이 있으면 그 이름을, 없거나 비었으면 `null`을 돌려준다. `null`은 「어느 칸에도
 * 붙이지 않는다」이므로 호출부는 폼 상단 일반 오류로 보낸다 — 모르는 이름을 엉뚱한 칸에
 * 붙이거나(그 칸의 오류가 아니다), 읽는 요소가 없는 키에 붙여 문구를 잃지 않게 한다
 * (`API_SPEC §1.3.2`). 등록·수정·위치 세 폼이 같은 판정을 쓴다.
 */
export function knownServerField(
  field: string | undefined,
  known: ReadonlySet<string>,
): string | null {
  return field !== undefined && known.has(field) ? field : null
}
