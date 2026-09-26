import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { createApiRealtimeCiiProvider } from '../realtime-cii/apiProvider'
import { underwayStateText, ytdCiiText } from './fleetRules'
import type { FleetVessel } from './types'
import './VesselPopover.css'

/**
 * 마커 팝오버 — 지도의 배를 누르면 뜨는 요약 (`DESIGN_SYSTEM §9.5` v2.28 · `#1831`).
 *
 * ## 무엇을 담는가
 *
 * 정본이 정한 넷이다 — 이름 · 운항 상태 · 올해 누적 · 연말 예상. **여기서 계산하지
 * 않는다**(`PRD §20 O-12` No-Compute): 누적은 선대 요약이 준 값을 그대로 적고, 연말
 * 예상은 서버에 묻는다.
 *
 * 「실시간 CII」로 바로 가는 링크는 **두지 않는다** — 그 화면의 경로는
 * `/vessels/:vesselId/voyages/:voyageId`(`screens.REALTIME_CII`)라 **항차 id가 필요**하고,
 * 선대 요약은 그것을 주지 않는다. 없는 id를 지어내는 대신 선박 상세로 보낸다 — 거기
 * 탭으로 들어갈 수 있다(`#1772`).
 *
 * ## 연말 예상은 열 때 한 번 묻는다
 *
 * 선대 요약(`API_SPEC §2.8`)에는 연말 예상이 없다. **요약에 필드를 더하지 않는다** — 그
 * 경로는 전 선박을 계산하는 자리이고, `#989`로 줄여 둔 쿼리 수를 다시 늘리게 된다. 배를
 * 누른 그 한 척만 `GET /vessels/{id}/cii/current`로 묻는다.
 *
 * ⚠️ **조회가 실패해도 화면이 흔들리지 않는다.** 실패를 이 카드 안에서 한 줄로 말하고
 * 바깥으로 던지지 않는다 — 던지면 대시보드가 통째로 오류 화면이 되고, 그것이 곧 격리
 * 실패다. 지도와 선박 목록은 이미 받은 값으로 멀쩡히 서 있어야 한다.
 *
 * ## 자리를 이 컴포넌트가 정하지 않는다
 *
 * 마커의 자리(`anchor`)와 무대의 크기는 **대시보드가 재서 넘긴다.** 마커 DOM은 선박
 * 목록이 바뀔 때마다 새로 만들어지므로(`FleetMap`의 `onSelectVessel` 주석) 요소를 오래
 * 쥐고 있을 수 있는 쪽이 없다 — 재는 쪽과 id로 다시 찾는 쪽을 한곳에 두었다.
 */
/** 연말 예상 — 등급과 값 한 쌍. 서버가 못 주면 각각 `null`이다. */
export type YearEnd = { readonly rating: string | null; readonly attainedCii: string | null } | null

export interface PopoverAnchor {
  /** 마커의 왼쪽 위 — **무대(`.fleet__stage`) 기준**이다. 화면 좌표가 아니다. */
  readonly left: number
  readonly top: number
  /** 마커의 폭. 카드를 마커 옆에 붙이려면 얼마를 비켜야 하는지가 이 값이다. */
  readonly size: number
}

/** 자리 계산에만 쓰는 값. 모양(여백·그림자·글자)은 CSS가 정한다 (`§0.2` 치수는 Figma 소유). */
const WIDTH = 240
const GAP = 10
const HEIGHT_GUESS = 190

const LOADING_TEXT = '연말 예상을 불러오는 중…'
const FAILED_TEXT = '연말 예상을 불러오지 못했습니다.'

export function VesselPopover({
  vessel,
  anchor,
  stage,
  panelRight,
  onClose,
  provider,
}: {
  vessel: FleetVessel
  anchor: PopoverAnchor
  /** 무대의 크기 — 가장자리에서 뒤집을지 판단한다. */
  stage: { readonly width: number; readonly height: number }
  /** 좌측 패널의 오른쪽 끝(무대 기준). 겹치면 이 바깥으로 민다. */
  panelRight: number
  onClose: () => void
  /** 검사가 서버 없이 세 갈래(불러오는 중 · 값 · 실패)를 다 보기 위한 자리. */
  provider?: { yearEnd(vesselId: string): Promise<YearEnd> }
}) {
  const [yearEnd, setYearEnd] = useState<YearEnd>(null)
  const [state, setState] = useState<'loading' | 'ok' | 'failed'>('loading')
  const boxRef = useRef<HTMLDivElement | null>(null)

  const client = useMemo(() => provider ?? defaultProvider(), [provider])

  useEffect(() => {
    let cancelled = false
    /*
     * `setState('loading')`을 여기서 다시 부르지 않는다 — 초기값이 이미 그것이고, 배가
     * 바뀌면 호출부가 `key`로 카드를 다시 만든다(그러면 상태도 초기값부터다).
     */
    client.yearEnd(vessel.id).then(
      (value) => {
        if (cancelled) return
        setYearEnd(value)
        setState('ok')
      },
      () => {
        // 던지지 않는다 — 실패는 이 카드 안에서 끝난다.
        if (!cancelled) setState('failed')
      },
    )
    return () => {
      cancelled = true
    }
  }, [client, vessel.id])

  /*
   * **열리면 초점이 카드로 온다.**
   *
   * 마커에서 `Enter`로 열었는데 초점이 마커에 남으면 `Tab`이 카드가 아니라 **다음
   * 마커로** 가고, 화면 낭독으로는 카드가 열린 줄도 모른다. 돌려보내는 쪽(닫을 때 그
   * 배의 마커로 초점 복귀)은 무대가 맡는다 — 마커를 id로 다시 찾을 수 있는 쪽이 거기다.
   */
  useEffect(() => {
    boxRef.current?.focus()
  }, [vessel.id])

  useEffect(() => {
    /*
     * 바깥을 누르면 닫는다.
     *
     * ⚠️ **마커는 「바깥」이 아니다.** 마커에서 시작한 누름까지 닫아 버리면 다른 배를
     * 누를 때 닫혔다 열려 한 번 깜빡인다. 마커는 그냥 두면 그 배의 선택이 카드를 바꿔
     * 단다 — **한 번에 하나**는 그렇게 지켜진다.
     */
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target
      if (!(target instanceof Element)) return
      if (boxRef.current?.contains(target) === true) return
      if (target.closest('.fleetmap__marker') !== null) return
      onClose()
    }
    /* `Esc`는 문서에서 받는다 — 카드 안에서만 받으면 초점이 카드를 벗어난 뒤 안 닫힌다. */
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    /*
     * **지도를 확대하면 닫는다.** 카드는 마커 자리에 붙어 있고 확대는 그 자리를 옮긴다 —
     * 매 프레임 다시 재는 길도 있으나, 확대하는 동안 카드가 따라다니는 편이 읽기 더
     * 어렵다. 끌기는 위의 「바깥 누르기」가 이미 받는다(지도를 끄는 첫 동작이 누름이다).
     * **지도 위에서 굴렸을 때만** 닫는다 — 패널 목록을 굴리는 것은 지도와 무관하다.
     */
    const onWheel = (event: WheelEvent) => {
      const target = event.target
      if (target instanceof Element && target.closest('.fleetmap__canvas') !== null) onClose()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('wheel', onWheel, { passive: true })
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('wheel', onWheel)
    }
  }, [onClose])

  /*
   * 자리 (`§9.5` v2.28) — 배 **옆**이다. 오른쪽 가장자리에 닿으면 왼쪽으로 뒤집고,
   * 아래에 닿으면 위로 올린다. 좌측 패널과 겹치면 패널 바깥으로 민다 — 카드가 자기가
   * 가리키는 배를 가리거나 패널 밑으로 숨지 않게 한다.
   */
  const flipX = anchor.left + anchor.size + GAP + WIDTH > stage.width
  const left = Math.max(
    panelRight + GAP,
    flipX ? anchor.left - GAP - WIDTH : anchor.left + anchor.size + GAP,
  )
  const top = Math.max(GAP, Math.min(anchor.top, stage.height - HEIGHT_GUESS - GAP))

  return (
    <div
      className="vpop"
      role="dialog"
      aria-label={`${vessel.name} 요약`}
      ref={boxRef}
      tabIndex={-1}
      style={{ left: `${left}px`, top: `${top}px`, inlineSize: `${WIDTH}px` }}
    >
      <p className="vpop__name">{vessel.name}</p>
      <p className="vpop__state">{underwayStateText(vessel)}</p>

      <dl className="vpop__values">
        <dt>올해 누적</dt>
        {/* 자릿수는 `§4.1`(🔒)이 정한다 — 선박 목록과 **같은 원천**을 쓴다. */}
        {/* 한 식으로 쓴다 — 조각으로 나누면 화면에서는 한 줄이어도 문자열이 갈린다. */}
        <dd>{`${vessel.ytdRating ?? '—'} · ${ytdCiiText(vessel.ytdAttainedCii)}`}</dd>
        <dt>연말 예상</dt>
        <dd>
          {state === 'loading' ? (
            <span className="vpop__pending">{LOADING_TEXT}</span>
          ) : state === 'failed' ? (
            <span className="vpop__failed">{FAILED_TEXT}</span>
          ) : (
            `${yearEnd?.rating ?? '—'} · ${ytdCiiText(yearEnd?.attainedCii ?? null)}`
          )}
        </dd>
      </dl>

      <p className="vpop__go">
        <Link to={`/vessels/${vessel.id}`}>선박 상세</Link>
      </p>

      <button type="button" className="vpop__close" onClick={onClose}>
        닫기
      </button>
    </div>
  )
}

/**
 * 실시간 CII의 조회를 **다시 만들지 않는다** — 같은 경로를 두 곳이 정의하면 한쪽만
 * 고쳐졌을 때 두 화면이 다른 값을 말한다. 기능 사이를 잇는 자리이므로
 * `moduleBoundary.test.ts`의 `COMPOSITION`에 사유와 함께 올렸다.
 */
function defaultProvider() {
  const realtime = createApiRealtimeCiiProvider()
  return {
    async yearEnd(vesselId: string): Promise<YearEnd> {
      const snapshot = await realtime.load(vesselId)
      return { rating: snapshot.projection.rating, attainedCii: snapshot.projection.attainedCii }
    },
  }
}
