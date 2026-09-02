import type { ScenarioType } from './types'

/**
 * 시나리오 도식 — `#739`.
 *
 * ## 장식이 아니다
 *
 * 세 카드는 이름(`직항`·`우회`·`감속`)만으로 서로 구분되고, **무엇이 다른지**는
 * 표 여섯 줄을 읽어야 나왔다. 특히 「감속」이 **거리는 같고 속력만 다르다**는 것은
 * 라벨에서 읽히지 않는다. 그림이 그 차이를 형태로 옮긴다.
 *
 * `DESIGN_SYSTEM §14`(색만으로 의미 전달 금지)에 어긋나지 않는다 — 그림은 유일한
 * 채널이 아니라 **네 번째** 채널이다. 이름·타입·거리·속력이 모두 글로 남아 있고,
 * 그림을 못 보아도 잃는 정보가 없다.
 *
 * ## 형태에 뜻을 싣는다
 *
 * | | 형태 | 무엇을 말하는가 |
 * |---|---|---|
 * | 직항 | 실선 직선 | 기준이 되는 길 |
 * | 우회 | 점선 직선(원래 길) + 그 위로 부푼 실선 호 | **길이가 늘었다** |
 * | 감속 | 같은 직선을 성긴 파선으로 | **길은 같고 나아감이 느리다** |
 *
 * 우회에 원래 길을 점선으로 남기는 것이 핵심이다 — 호만 그리면 「길이 휘었다」로만
 * 읽히고 **얼마나 늘었는지**가 빠진다.
 *
 * ## 색을 쓰지 않는다
 *
 * 등급 램프(`--cii-*`)도 시맨틱(`--semantic-*`)도 끌어오지 않는다. 세 시나리오는
 * 좋고 나쁨의 순서가 아니라 **선택지**이고, 색을 주면 그 자체가 추천으로 읽힌다
 * (`PRD §11.2` 「추천 시나리오를 표시하지 않는다」 · `§6.3` 「자동 결정 금지」).
 */

const VIEW_W = 120
const VIEW_H = 28
const X1 = 8
const X2 = VIEW_W - 8
const MID = VIEW_H / 2

/** 도식이 말하는 것을 글로도 남긴다 — 스크린 리더는 선을 읽지 못한다. */
const GLYPH_LABEL: Readonly<Record<ScenarioType, string>> = {
  DIRECT: '두 지점을 잇는 직선 항로',
  DETOUR: '원래 항로보다 길게 우회하는 항로',
  SLOW_STEAMING: '같은 항로를 더 느리게 항해',
}

export function ScenarioRouteGlyph({ type }: { type: ScenarioType }) {
  return (
    <svg
      className="scenario-glyph"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      role="img"
      aria-label={GLYPH_LABEL[type]}
      preserveAspectRatio="none"
    >
      {/* 우회는 원래 길을 점선으로 남긴다 — 늘어난 양이 그 대비에서 읽힌다. */}
      {type === 'DETOUR' ? (
        <line
          className="scenario-glyph__baseline"
          x1={X1}
          y1={MID + 6}
          x2={X2}
          y2={MID + 6}
        />
      ) : null}

      {type === 'DETOUR' ? (
        <path
          className="scenario-glyph__path"
          d={`M ${X1} ${MID + 6} Q ${VIEW_W / 2} ${MID - 12} ${X2} ${MID + 6}`}
          fill="none"
        />
      ) : (
        <line
          className={`scenario-glyph__path${type === 'SLOW_STEAMING' ? ' scenario-glyph__path--slow' : ''}`}
          x1={X1}
          y1={MID}
          x2={X2}
          y2={MID}
        />
      )}

      <circle className="scenario-glyph__port" cx={X1} cy={type === 'DETOUR' ? MID + 6 : MID} r="3" />
      <circle className="scenario-glyph__port" cx={X2} cy={type === 'DETOUR' ? MID + 6 : MID} r="3" />
    </svg>
  )
}
