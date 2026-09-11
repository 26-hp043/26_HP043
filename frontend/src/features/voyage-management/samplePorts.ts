/**
 * 샘플 항만 — 항차 추가의 출발·도착항 입력 규칙 (#760 · `PRD §15.1` · `§15.2`).
 *
 * `PRD §15.1`이 MUST로 둔 「샘플 항만 테이블」이다. 목록은 서버가 준다(`API_SPEC §3.8`) —
 * 값의 출처(NGA World Port Index)를 한 곳에 두어야 원본과 대조할 수 있다.
 *
 * ## 고르면 좌표가 따라온다 · 자유 입력은 좌표가 없다
 *
 * 항만명 칸은 **자유 입력**이다(`PRD §20 O-11`). 입력이 목록의 항과 **정확히** 같을 때만
 * 그 좌표를 쓴다 — 비슷한 이름을 추측해 좌표를 붙이면, 사용자가 다른 항을 뜻했을 때
 * 틀린 좌표가 조용히 저장된다.
 */

/** `GET /ports/samples` 한 행. */
export interface SamplePort {
  locode: string
  /** 항차에 저장되는 이름(대문자 영문). */
  name: string
  /** 목록에 보이는 이름. */
  name_ko: string
  country_code: string
  lat: number
  lon: number
}

export interface PortCoord {
  lat: number
  lon: number
}

/**
 * 입력이 목록의 항과 같으면 그 항을 돌려준다. 영문 이름(대소문자 무시)이나 한국어 이름이
 * **정확히** 같아야 한다 — 위 모듈 설명 참조.
 */
export function matchSamplePort(ports: readonly SamplePort[], text: string): SamplePort | null {
  const wanted = text.trim()
  if (wanted === '') return null
  const upper = wanted.toUpperCase()
  return ports.find((p) => p.name === upper || p.name_ko === wanted) ?? null
}

/** 목록에 보이는 한 줄 — 「부산 · KR」. */
export function portOptionLabel(port: SamplePort): string {
  return `${port.name_ko} · ${port.country_code}`
}

/**
 * 추정 거리 칸의 표시 — **원문은 `PRD §15.2`다**(「화면에 `좌표 기반 추정 거리`라고 표시한다」).
 *
 * 대권거리는 운하·해협을 돌아가는 실제 항로보다 짧다. 사용자가 그 값을 실제 거리로 믿고
 * 두지 않도록 **왜 짧은지와 무엇을 하면 되는지**를 함께 적는다.
 */
export const ESTIMATED_DISTANCE_HINT =
  '좌표 기반 추정 거리 — 운하·해협을 돌아가는 실제 항로보다 짧을 수 있습니다. 실제 항로거리를 알면 고쳐 주세요.'

/** 추정 거리를 계획 거리 칸에 넣을 문자열로 — 소수 2자리(`planned_distance_nm` NUMERIC(12,2)). */
export function distanceInput(distanceNm: number): string {
  return distanceNm.toFixed(2)
}
