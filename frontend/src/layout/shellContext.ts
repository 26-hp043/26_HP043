import { useOutletContext } from 'react-router'
import type { VesselOption } from '../features/voyage-cii/vesselCatalog'

/**
 * 셸이 하위 화면에 내려주는 전역 컨텍스트 (#484 · #535).
 *
 * ## 왜 필요한가
 *
 * `#512`가 상단바에 선박·항차 선택기를 붙였지만, **그 선택을 읽을 수단이 화면 쪽에
 * 없었다.** 선택 상태는 `AppShell`의 지역 state였고 `<Outlet />`은 아무것도 넘기지
 * 않았다. 그래서 CII 예측·항로 비교는 각자 선박 셀렉트를 따로 들었고, 상단에서
 * 배를 바꿔도 폼은 그대로였다 — `#535`가 보고한 상태다.
 *
 * ## 화면은 선박 상태를 소유하지 않는다
 *
 * `globalContext.ts`가 세운 규칙(*"별도 상태를 소유하면 두 곳이 갈린다"*)을 화면까지
 * 확장한다. 화면은 `vesselId`를 **읽고**, 바꿀 때는 `selectVesselId()`를 부른다.
 * 그러면 주소가 갱신되고 그 주소가 다시 이 값으로 돌아온다. 양방향처럼 보이지만
 * **상태를 가진 곳은 URL 하나**다.
 *
 * ## 선박 목록도 함께 내린다
 *
 * 셸이 이미 `GET /vessels`를 부르고 있다(상단바 선택기가 쓴다). 화면이 같은 목록을
 * 다시 부르면 한 화면에 같은 요청이 두 번 나가고, 두 목록이 다른 시점의 것이 되어
 * **셀렉트에 있는 배가 상단바에는 없는** 상태가 만들어질 수 있다.
 */
export interface ShellContext {
  /** 지금 선택된 선박. 선택하지 않았으면 `null`. */
  vesselId: string | null
  /** 지금 선택된 항차. 선박이 없으면 항상 `null`. */
  voyageId: string | null
  /** 셸이 조회한 선박 목록. 아직 안 왔거나 실패했으면 빈 배열. */
  vessels: readonly VesselOption[]
  /**
   * 목록 조회가 어느 단계인가.
   *
   * **빈 배열의 이유를 구분하기 위해 있다.** `ready`인데 비었으면 등록된 배가
   * 없는 것이고, `failed`면 서버를 못 읽은 것이다. 화면이 그 둘에 같은 문구를
   * 쓰면 사용자는 배를 등록해야 하는지 서버를 봐야 하는지 알 수 없다.
   */
  vesselsState: 'loading' | 'ready' | 'failed'
  /** 선박 선택을 바꾼다. `null`이면 선택 해제. 항차 선택은 함께 버려진다. */
  selectVesselId: (vesselId: string | null) => void
}

/**
 * 하위 화면에서 셸 컨텍스트를 읽는다.
 *
 * `AppShell`의 라우트 자식에서만 쓸 수 있다. 그 밖에서 부르면 `useOutletContext`가
 * `null`을 주므로, **빈 컨텍스트로 낮춰 돌려준다** — 화면이 터지는 것보다
 * 「선택 없음」으로 도는 편이 낫다.
 */
export function useShellContext(): ShellContext {
  const context = useOutletContext<ShellContext | null>()
  return context ?? EMPTY_SHELL_CONTEXT
}

/** 셸 밖에서 렌더될 때의 기본값. 아무것도 선택되지 않은 상태다. */
export const EMPTY_SHELL_CONTEXT: ShellContext = {
  vesselId: null,
  voyageId: null,
  vessels: [],
  vesselsState: 'loading',
  selectVesselId: () => {},
}
