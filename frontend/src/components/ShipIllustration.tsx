import type { ReactNode } from 'react'
import './ShipIllustration.css'

/**
 * 선종별 선박 일러스트 (10/7 디자인 결정).
 *
 * 실제 배 사진을 쓰지 않는다 — 실존 선박 사진은 저작권이 있고, 사진이 없는 배가
 * 실서비스의 기본 상태라 빈 칸이 생긴다. 선종마다 측면 실루엣을 직접 그려 모든 배에
 * 자동으로 붙인다. 사용자 사진 올리기가 생기면 사진이 있는 배만 이 자리를 바꾼다.
 *
 * - 그림은 장식이다(`aria-hidden`). 선종은 옆 글자가 말한다(§14)
 * - 색은 `--ship-*` 토큰(그림 전용)만 쓴다 — 등급 · 상태 색을 쓰지 않는다
 * - 좌표계 96 × 40, 수선 y = 32, 선수는 오른쪽
 */
type ShipFamily = 'bulk' | 'tanker' | 'gas' | 'container' | 'general' | 'roro' | 'passenger'

const FAMILY_BY_TYPE: Record<string, ShipFamily> = {
  BULK_CARRIER: 'bulk',
  COMBINATION_CARRIER: 'bulk',
  TANKER: 'tanker',
  GAS_CARRIER: 'gas',
  LNG_CARRIER: 'gas',
  CONTAINER_SHIP: 'container',
  GENERAL_CARGO_SHIP: 'general',
  REFRIGERATED_CARGO_CARRIER: 'general',
  RO_RO_CARGO_VEHICLE: 'roro',
  RO_RO_CARGO: 'roro',
  RO_RO_PASSENGER: 'passenger',
  RO_RO_PASSENGER_HSC: 'passenger',
  CRUISE_PASSENGER: 'passenger',
}

function shipFamilyOf(shipType: string | null | undefined): ShipFamily {
  return (shipType != null && FAMILY_BY_TYPE[shipType]) || 'bulk'
}

const HULL = 'M4 21 H92 L88.2 30.6 Q87.6 32 86 32 H10.5 Q8.6 32 8 30.4 Z'
const BOOT = 'M7.4 28.6 H89.6 L88.2 30.6 Q87.6 32 86 32 H10.5 Q8.6 32 8 30.4 Z'

function Hull() {
  return (
    <>
      <path className="ship-ill__hull" d={HULL} />
      <path className="ship-ill__boot" d={BOOT} />
    </>
  )
}

/** 선미 거주구 + 연돌 — 화물선 공통 */
function AftHouse() {
  return (
    <>
      <path className="ship-ill__funnel" d="M13 3.5 H18.4 L17.8 9 H13.6 Z" />
      <path className="ship-ill__hull" d="M13.1 3.5 H18.4 L18.25 4.9 H13.25 Z" />
      <rect className="ship-ill__house" x="8" y="8.2" width="15" height="1.8" rx="0.4" />
      <rect className="ship-ill__house" x="9" y="10" width="13" height="11" />
      <rect className="ship-ill__window" x="10.4" y="10.8" width="10.2" height="1.4" rx="0.3" />
      <rect className="ship-ill__window ship-ill__window--soft" x="10.4" y="14.2" width="10.2" height="0.9" />
      <rect className="ship-ill__window ship-ill__window--soft" x="10.4" y="17" width="10.2" height="0.9" />
    </>
  )
}

function Forecastle() {
  return <path className="ship-ill__hull" d="M84.6 21 V18.6 H90.4 L92 21 Z" />
}

const CARGO = ['ship-ill__cargo-1', 'ship-ill__cargo-2', 'ship-ill__cargo-3', 'ship-ill__deck'] as const

function Body({ family }: { family: ShipFamily }): ReactNode {
  switch (family) {
    case 'bulk':
      return (
        <>
          <Hull />
          <AftHouse />
          {[26, 38, 50, 62, 74].map((x) => (
            <rect key={x} className="ship-ill__deck" x={x} y="18.2" width="9.2" height="2.8" rx="0.7" />
          ))}
          <Forecastle />
        </>
      )
    case 'tanker':
      return (
        <>
          <Hull />
          <AftHouse />
          <rect className="ship-ill__line" x="24" y="19.4" width="60" height="0.9" />
          <rect className="ship-ill__deck" x="51" y="16.6" width="5" height="2.8" rx="0.4" />
          {[30, 40, 62, 72].map((x) => (
            <rect key={x} className="ship-ill__line" x={x} y="17.6" width="0.7" height="3.4" />
          ))}
          <Forecastle />
        </>
      )
    case 'gas':
      return (
        <>
          <Hull />
          <AftHouse />
          {[34, 49, 64, 79].map((cx) => (
            <path key={cx} className="ship-ill__dome" d={`M${cx - 6.6} 21 A6.6 6.6 0 0 1 ${cx + 6.6} 21 Z`} />
          ))}
        </>
      )
    case 'container': {
      const tiers = [3, 4, 4, 4, 3, 2]
      return (
        <>
          <Hull />
          <AftHouse />
          {tiers.map((count, bay) =>
            Array.from({ length: count }, (_, tier) => (
              <rect
                key={`${bay}-${tier}`}
                className={`ship-ill__box ${CARGO[(bay * 2 + tier) % CARGO.length]}`}
                x={25 + bay * 10}
                y={21 - (tier + 1) * 2.9}
                width="9.4"
                height="2.9"
              />
            )),
          )}
          <Forecastle />
        </>
      )
    }
    case 'general':
      return (
        <>
          <Hull />
          <AftHouse />
          {[27, 47, 67].map((x) => (
            <rect key={x} className="ship-ill__deck" x={x} y="18.2" width="15" height="2.8" rx="0.7" />
          ))}
          {[44.6, 64.6].map((x) => (
            <g key={x}>
              <rect className="ship-ill__hull" x={x - 0.7} y="8" width="1.4" height="13" />
              <path className="ship-ill__boom" d={`M${x} 10 L${x + 10} 15.5`} />
            </g>
          ))}
          <Forecastle />
        </>
      )
    case 'roro':
      return (
        <>
          <Hull />
          <path className="ship-ill__house" d="M8 21 V9.6 Q8 8 9.6 8 H81 Q88 8 91 14 L92 21 Z" />
          <rect className="ship-ill__cargo-2" x="8.3" y="17" width="83" height="1.5" />
          <rect className="ship-ill__house" x="74" y="5" width="11" height="3.2" rx="0.4" />
          <rect className="ship-ill__window" x="75.2" y="5.9" width="8.6" height="1.2" rx="0.3" />
          <path className="ship-ill__funnel" d="M14 3.8 H19.4 L18.9 8 H14.4 Z" />
        </>
      )
    case 'passenger':
      return (
        <>
          <Hull />
          <path className="ship-ill__house" d="M9 21 V12 H80 Q87 12 91 17 L92 21 Z" />
          <path className="ship-ill__house" d="M17 12 V8 H71 Q76 8 79 12 Z" />
          {Array.from({ length: 24 }, (_, i) => (
            <rect key={`a${i}`} className="ship-ill__window" x={12 + i * 3} y="15.2" width="1.8" height="1.3" rx="0.3" />
          ))}
          {[22, 30, 38, 46, 54, 62].map((x) => (
            <rect key={x} className="ship-ill__cargo-1" x={x} y="12.6" width="4.6" height="1.6" rx="0.8" />
          ))}
          {Array.from({ length: 17 }, (_, i) => (
            <rect key={`b${i}`} className="ship-ill__window" x={20 + i * 3} y="9.6" width="1.8" height="1.2" rx="0.3" />
          ))}
          <path className="ship-ill__funnel" d="M40 3 H47.5 L46.6 8 H41 Z" />
          <path className="ship-ill__boot" d="M40.05 3 H47.5 L47.3 4.2 H40.25 Z" />
        </>
      )
  }
}

export function ShipIllustration({
  shipType,
  framed = false,
  className,
}: {
  shipType: string | null | undefined
  /** 바다 배경과 함께 — 상세 머리처럼 크게 쓸 때 */
  framed?: boolean
  className?: string
}) {
  const family = shipFamilyOf(shipType)
  return (
    <svg
      className={`ship-ill ship-ill--${family}${framed ? ' ship-ill--framed' : ''}${className ? ` ${className}` : ''}`}
      viewBox={framed ? '0 -2 96 42' : '2 2 92 31'}
      aria-hidden="true"
      focusable="false"
    >
      {framed ? (
        <>
          <rect className="ship-ill__sea" x="0" y="31" width="96" height="9" />
          <path className="ship-ill__wave" d="M0 34.5 Q4 33.5 8 34.5 T16 34.5 T24 34.5 T32 34.5 T40 34.5 T48 34.5 T56 34.5 T64 34.5 T72 34.5 T80 34.5 T88 34.5 T96 34.5" />
        </>
      ) : null}
      <Body family={family} />
    </svg>
  )
}
