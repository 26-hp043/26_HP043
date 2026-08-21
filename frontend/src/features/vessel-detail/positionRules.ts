/**
 * 선박 위치·운항 상태 입력 규칙 — `API_SPEC §2.6` (`#369` 엔드포인트).
 *
 * ## 왜 화면이 조합까지 판정하는가
 *
 * `§2.6`이 **함께 보내야 하는 쌍** 셋을 규정한다 — 상태 2축이 함께, 조합이 허용
 * 집합 안에, 위경도가 함께. 전부 **화면이 이미 값을 쥐고 있는** 조건이라 서버에
 * 보내 보고 422를 받을 이유가 없다. `voyage-management`의 전환 가드와 같은 규율이다
 * (`§3.5` 가드 중 화면이 판정할 수 있는 것만 미리 막는다).
 *
 * 조합 표는 서버(`services/vessel.py`)와 마이그레이션 026 CHECK의 **사본**이다.
 * 사본인 이상 갈라질 수 있으므로, 갈라지면 **서버가 맞다** — 여기서 통과시킨 값이
 * 422를 받으면 서버 문구를 그대로 보인다.
 *
 * ## 부분 전송이다
 *
 * `§2.6`의 네 필드는 전부 선택이다. 사용자가 위치만 고쳤으면 상태는 보내지 않는다 —
 * 보내면 서버가 「바꿨다」로 보고 `position_updated_at`을 갱신하는데, 실제로 상태는
 * 그대로다. **그 시각이 곧 「낡은 값인지」 판별의 근거**라 의미 없는 갱신을 만들지
 * 않는다.
 *
 * 그래서 **아무것도 바뀌지 않았으면 보내지 않는다.** 빈 본문은 200이지만
 * `position_updated_at`을 건드리지 않으므로 사용자는 「저장했는데 아무 일도 없다」를
 * 보게 된다.
 *
 * ## `position_updated_at`을 보내지 않는다
 *
 * `extra="forbid"`가 422로 거부한다. 클라이언트 시계를 신뢰하면 「언제 기준
 * 위치인가」가 단말마다 갈리므로 **서버가 확정한다**(`§2.6`).
 */

export type UnderwayState = 'UNDER_WAY' | 'NOT_UNDER_WAY'

/**
 * 운항 상태별 허용 세부 상태 — 마이그레이션 026 `chk_vessel_state_pair`의 사본.
 *
 * `NOT_UNDER_WAY` 6값은 `not_underway_period.period_type`(025)과 **같은 집합**이다.
 * 정박 구간의 성격이 곧 선박의 표시 상태가 되기 때문이다(`§2.6`).
 */
export const DETAIL_STATUS_BY_STATE: Readonly<Record<UnderwayState, readonly string[]>> = {
  UNDER_WAY: ['SAILING'],
  NOT_UNDER_WAY: ['IN_PORT', 'AT_ANCHOR', 'DRIFTING', 'STS', 'CANAL_TRANSIT', 'DRYDOCK'],
}

export interface PositionDraft {
  /** 빈 문자열 = 「바꾸지 않음」. `null`과 구분할 필요가 없어 폼 값 그대로 둔다. */
  underwayState: string
  detailStatus: string
  lat: string
  lon: string
}

export type PositionErrors = Partial<Record<keyof PositionDraft, string>>

export interface PositionPayload {
  underway_state?: string
  detail_status?: string
  current_lat?: number
  current_lon?: number
}

export function initialPositionDraft(vessel: {
  underwayState: string | null
  detailStatus: string | null
  lat: string | null
  lon: string | null
}): PositionDraft {
  return {
    underwayState: vessel.underwayState ?? '',
    detailStatus: vessel.detailStatus ?? '',
    lat: vessel.lat ?? '',
    lon: vessel.lon ?? '',
  }
}

/**
 * 운항 상태를 바꾸면 세부 상태를 다시 고른다.
 *
 * `UNDER_WAY`는 허용값이 `SAILING` 하나뿐이라 자동으로 채운다 — 고를 것이 없는
 * 선택지를 내밀지 않는다. 반대 방향(`NOT_UNDER_WAY`)은 6값 중 무엇인지 사용자만
 * 알므로 **비워서 고르게 한다.** 종전 값을 남겨 두면 `SAILING`이 그대로 남아
 * 저장 단계에서 422가 된다.
 */
export function detailStatusFor(state: string, current: string): string {
  if (state === 'UNDER_WAY') return 'SAILING'
  if (state === 'NOT_UNDER_WAY') {
    return DETAIL_STATUS_BY_STATE.NOT_UNDER_WAY.includes(current) ? current : ''
  }
  return ''
}

function parseCoordinate(raw: string): number | null {
  const text = raw.trim()
  if (text === '') return null
  if (!/^[+-]?\d+(\.\d+)?$/.test(text)) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/** `§2.6` 요청 본문 검증. 통과해도 서버가 최종 판정한다. */
export function validatePosition(draft: PositionDraft): PositionErrors {
  const errors: PositionErrors = {}

  // ── 상태 2축은 함께 지정한다 ──────────────────────────────────
  const state = draft.underwayState.trim()
  const detail = draft.detailStatus.trim()
  if (state !== '' && detail === '') {
    errors.detailStatus = '세부 상태를 함께 골라 주세요.'
  } else if (state === '' && detail !== '') {
    errors.underwayState = '운항 상태를 함께 골라 주세요.'
  } else if (state !== '') {
    const allowed = DETAIL_STATUS_BY_STATE[state as UnderwayState]
    if (allowed === undefined) {
      errors.underwayState = '알 수 없는 운항 상태입니다.'
    } else if (!allowed.includes(detail)) {
      errors.detailStatus = '이 운항 상태에서는 사용할 수 없는 세부 상태입니다.'
    }
  }

  // ── 위경도는 함께 지정한다 ────────────────────────────────────
  const latText = draft.lat.trim()
  const lonText = draft.lon.trim()
  if (latText !== '' && lonText === '') {
    errors.lon = '경도를 함께 입력해 주세요.'
  } else if (latText === '' && lonText !== '') {
    errors.lat = '위도를 함께 입력해 주세요.'
  }

  if (latText !== '') {
    const lat = parseCoordinate(latText)
    if (lat === null) errors.lat = '숫자로 입력해 주세요.'
    else if (lat < -90 || lat > 90) errors.lat = '위도는 −90 ~ 90 사이여야 합니다.'
  }
  if (lonText !== '') {
    const lon = parseCoordinate(lonText)
    if (lon === null) errors.lon = '숫자로 입력해 주세요.'
    else if (lon < -180 || lon > 180) errors.lon = '경도는 −180 ~ 180 사이여야 합니다.'
  }

  return errors
}

export function hasPositionErrors(errors: PositionErrors): boolean {
  return Object.keys(errors).length > 0
}

/**
 * 바뀐 항목만 담은 요청 본문.
 *
 * **바뀌지 않은 필드를 싣지 않는다** — 서버는 값이 오면 「바꿨다」로 보고
 * `position_updated_at`을 갱신한다. 위치만 고쳤는데 상태까지 실으면 상태의
 * 갱신 시각이 사실과 달라진다.
 */
export function positionPayload(draft: PositionDraft, base: PositionDraft): PositionPayload {
  const payload: PositionPayload = {}

  const state = draft.underwayState.trim()
  const detail = draft.detailStatus.trim()
  if (state !== '' && (state !== base.underwayState || detail !== base.detailStatus)) {
    // 2축은 CHECK로 묶여 있어 **함께** 보낸다. 한쪽만 보내면 서버가 기존 값과
    // 섞어 조합을 다시 검증하는데, 그 조합은 화면에 보이지 않던 것이다.
    payload.underway_state = state
    payload.detail_status = detail
  }

  const latText = draft.lat.trim()
  const lonText = draft.lon.trim()
  if (latText !== '' && (latText !== base.lat || lonText !== base.lon)) {
    payload.current_lat = Number(latText)
    payload.current_lon = Number(lonText)
  }

  return payload
}

/** 보낼 것이 없으면 저장하지 않는다 — 빈 본문은 200이지만 아무 일도 일어나지 않는다. */
export function isEmptyPayload(payload: PositionPayload): boolean {
  return Object.keys(payload).length === 0
}
