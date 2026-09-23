import { SHIP_TYPES } from '../vessel-registration/shipTypes'
import type { VesselListOptions } from './provider'

/**
 * 목록 조회 조건 — 검색 · 선종 (#1783).
 *
 * ## 서버가 거른다
 *
 * `API_SPEC §2.1`이 `search`(선박명 또는 IMO)와 `ship_type`을 **처음부터** 정의하고
 * 있고 서버도 둘 다 구현했다. 화면이 쓰지 않았을 뿐이다.
 *
 * 화면에서 거르면 **받은 페이지 안에서만** 맞다 — 지금 정렬과 제원 미비 칩이 그렇고,
 * 화면이 그 사실을 적고 있다(`LOADED_PARTIAL_HINT` · `#1102` ⑶). 검색을 같은 방식으로
 * 하면 찾는 배가 다음 페이지에 있을 때 **「없다」와 「이 페이지에 없다」가 같은 모양**이
 * 된다. `#1741`이 선박 상세 항차 목록에서 화면 정렬을 거절한 이유와 같다.
 *
 * ## DOM 없이 검증한다
 *
 * 조건을 조회 옵션으로 옮기는 규칙 · 빈 결과의 문구 · 걸린 조건의 표시는 전부 순수
 * 함수다. 컴포넌트에서 분리해 둔다(이 기능의 `listRules`·`editRules`와 같은 꼴).
 */

export interface VesselQuery {
  /** 선박명 또는 IMO 번호. 서버로 보낼 때 앞뒤 공백을 지운다. */
  search: string
  /** 선종 코드. 빈 문자열이 「전체」다. */
  shipType: string
}

export const EMPTY_QUERY: VesselQuery = { search: '', shipType: '' }

/** 선종 선택지 — 13종은 `shipTypes.ts`가 소유하고 `shipTypes.sync.test.ts`가 대조한다. */
export const SHIP_TYPE_OPTIONS = SHIP_TYPES

/**
 * 조회 옵션으로 옮긴다.
 *
 * **빈 값은 싣지 않는다** — `?search=`를 보내면 서버가 빈 문자열로 거르게 되고,
 * 그 동작은 「조건 없음」과 다를 수 있다. 조건이 없으면 파라미터도 없다.
 */
export function toListOptions(query: VesselQuery, cursor?: string): VesselListOptions {
  const options: VesselListOptions = {}
  if (cursor) options.cursor = cursor
  const search = query.search.trim()
  if (search) options.search = search
  if (query.shipType) options.shipType = query.shipType
  return options
}

/** 조건이 하나라도 걸려 있는가. 제원 미비 칩은 **화면 몫**이라 따로 받는다. */
export function isFiltered(query: VesselQuery, specGapOnly: boolean): boolean {
  return query.search.trim() !== '' || query.shipType !== '' || specGapOnly
}

/** 걸린 조건 하나 — 무엇이며 어떻게 지우는가. */
export interface ActiveFilter {
  key: 'search' | 'shipType' | 'specGap'
  label: string
}

/**
 * 지금 걸린 조건들.
 *
 * **걸어 놓고 잊는 것이 필터의 주된 사고다.** 목록이 짧아진 이유가 화면 어딘가의
 * 눌린 컨트롤뿐이면, 사용자는 「선박이 사라졌다」로 읽는다.
 */
export function activeFilters(query: VesselQuery, specGapOnly: boolean): ActiveFilter[] {
  const filters: ActiveFilter[] = []
  const search = query.search.trim()
  if (search) filters.push({ key: 'search', label: `검색 「${search}」` })
  if (query.shipType) {
    const option = SHIP_TYPE_OPTIONS.find((item) => item.code === query.shipType)
    filters.push({ key: 'shipType', label: `선종 ${option?.label ?? query.shipType}` })
  }
  if (specGapOnly) filters.push({ key: 'specGap', label: '제원 미비만' })
  return filters
}

/**
 * 조건을 걸었는데 아무것도 없을 때의 문구.
 *
 * **「등록된 선박이 없습니다」로 말하지 않는다.** `PRD §6.4`가 「값이 없다」와 「아직
 * 물어보지 않았다」를 가른 자리이고, 여기서는 **「없다」와 「걸러서 안 보인다」**를 가른다 —
 * 두 상태에서 사용자가 할 일이 정반대다(배를 등록한다 ↔ 조건을 지운다).
 */
export const FILTERED_EMPTY_MESSAGE =
  '조건에 맞는 선박이 없습니다. 위 조건을 지우면 전체 목록으로 돌아갑니다.'

/**
 * 검색어를 입력이 멈춘 뒤에 보낸다 (#1783).
 *
 * 글자마다 보내면 「샘플」을 치는 동안 조회가 세 번 나가고, 그중 둘은 사용자가 원한
 * 적 없는 조건이다. 값은 **사람이 한 낱말을 치는 사이**를 기준으로 잡았다 — 더 길면
 * 다 치고 기다리는 것이 느껴지고, 더 짧으면 낱말 중간에 나간다.
 */
export const SEARCH_DEBOUNCE_MS = 300
