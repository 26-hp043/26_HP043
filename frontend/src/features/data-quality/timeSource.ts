/**
 * 「이 값으로 채우기」로 넣은 시각의 출처 표식 (#2114 · `PRD §17.4.4` 「바꾼 값의 출처는 칸마다 남는다」).
 *
 * 서버는 시각 칸마다 출처를 싣는다 — 항차 `actual_departure_source`·`actual_arrival_source`
 * (`API_SPEC §3.6`), 정박 구간 `started_at_source`·`ended_at_source`(`API_SPEC §2.10`). 값은
 * `USER_INPUT`(사람이 넣음) · `PUBLIC_RECORD`(공적 기록에서 옮김) · `null`(「모른다」)이다.
 *
 * ## `PUBLIC_RECORD`일 때만 붙인다
 *
 * 계획 거리의 「좌표 기반 추정 거리」 표식(`ESTIMATED_DISTANCE_LIST_NOTE` · #1256)과 **같은 규칙**이다
 * — `null`(「모른다」)에는 아무것도 붙이지 않는다. 사람이 넣은 값에 「공적 기록」이 붙으면
 * 공적 기록과 어긋남이 다시 보였을 때 어느 쪽이 공적 기록인지 거꾸로 읽힌다.
 *
 * 표식의 자리·모양은 디자인 담당 확인 전 **개발 임시안**이다(`DESIGN_SYSTEM §2.3.1`).
 */

export type TimeSource = 'USER_INPUT' | 'PUBLIC_RECORD'

/** 서버 값 → 출처. 두 값 밖은 `null`(「모른다」)로 접는다 — 모르는 출처에 표식을 붙이지 않는다. */
export function timeSource(raw: unknown): TimeSource | null {
  return raw === 'USER_INPUT' || raw === 'PUBLIC_RECORD' ? raw : null
}

/** 표식의 앞머리 — 데이터 점검의 「이 값으로 채우기」가 남긴 값이라는 뜻이다. */
const PUBLIC_RECORD_FILLED_LABEL = '공적 기록에서 채움'

/**
 * 표식 한 줄. 시각은 부르는 쪽이 표시 문자열로 만들어 넘긴다(`formatTimestamp`). 읽을 수
 * 없으면 `null`을 넘기고, 그때는 시각 조각을 뺀다(「— 기준」을 적지 않는다 · #2124).
 */
export function publicRecordFilledNote(fieldLabel: string, time: string | null): string {
  const what = time === null ? fieldLabel : `${fieldLabel} ${time}`
  return `${PUBLIC_RECORD_FILLED_LABEL} — ${what} · 해양수산부 선박운항정보의 공적 기록에서 옮긴 값입니다.`
}
