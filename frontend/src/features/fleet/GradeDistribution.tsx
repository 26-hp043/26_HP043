import { gradePatternUrl } from '../../components/gradePattern'
import {
  distributionAria,
  distributionSlots,
  gradeDistributionSegments,
  showsInlineLabel,
  usesPictogram,
  zeroRatings,
  type DistributionSegment,
} from './fleetRules'
import { VesselGlyph } from './VesselGlyph'
import type { Rating } from '../voyage-cii/types'

/**
 * 선대 등급 분포 — 대시보드 KPI 행.
 *
 * ## 왜 배지+숫자에서 바로 바꿨나
 *
 * 종전에는 `A 0 B 1 C 0 D 1 E 2`가 작은 배지와 숫자로 나란히 있었다. **0척과
 * 2척이 같은 무게로 보여** 「우리 선대가 어느 쪽으로 쏠려 있나」가 읽히지 않았다.
 * 대시보드에서 가장 먼저 읽혀야 할 값인데 화면에서 가장 약했다.
 *
 * 가로 스택 바는 비율을 형태로 보여 준다 — 「E가 절반」이 숫자를 세지 않아도 보인다.
 *
 * ## 척수가 적으면 배 그림으로 센다
 *
 * 스무 척 남짓까지는 **배 한 척 = 마크 하나**가 막대보다 낫다. 비율을 눈으로 환산할
 * 필요 없이 낱개가 그대로 보이고, 「배」라는 형태가 값이 무엇을 세는지 말한다.
 * 시연 피드백의 「등급 분포가 눈에 안 띈다」와 「그림이 없어 가독성이 떨어진다」가
 * 여기서 함께 닫힌다.
 *
 * **막대를 지우지 않았다.** 세는 것이 일이 되는 척수(`PICTOGRAM_MAX_VESSELS`)를
 * 넘으면 막대로 돌아간다 — 그때는 비율을 바로 보여 주는 쪽이 맞다.
 *
 * ## 막대의 형태는 `§10.2`를 따른다
 *
 * `§10.2`(등급 확률 스택 바)와 **뜻하는 값은 다르지만**(확률 vs 척수) 형태가 같다.
 * 구간 폭 8% 임계를 따로 정하면 같은 모양이 화면마다 다른 폭에서 글자를 감춘다.
 *
 * ## 패턴은 필수다
 *
 * `§2.4.4` — 등급 문자가 놓이지 않는 자리에서는 패턴이 필수다. 8% 미만 구간은
 * 글자가 빠지므로 그 구간이 정확히 그 경우가 된다. 3색 체계는 적록색맹에서
 * 초록·주황·빨강이 모두 황갈색으로 수렴해 5색보다 오히려 취약하다.
 *
 * 무늬는 셸이 한 번 그리는 `GradePatternDefs`를 참조한다 — 자산이 두 벌이 되면
 * 서로 다른 무늬를 그리게 된다(`§15.1`).
 *
 * ## 0척인 등급을 감추지 않는다
 *
 * 폭 0인 조각은 그릴 수 없지만, **「A등급이 한 척도 없다」는 것 자체가 정보다.**
 * 바 아래에 따로 적어 감추는 대신 형태를 바꾼다.
 */
export function GradeDistribution({
  distribution,
}: {
  distribution: Readonly<Record<Rating, number>>
}) {
  const segments = gradeDistributionSegments(distribution)
  const zeros = zeroRatings(distribution)

  if (segments.length === 0) {
    // 빈 바를 그리지 않는다 — 회색 막대는 「로딩 중」으로 읽힌다.
    return <p className="dist__none">집계된 등급이 없습니다.</p>
  }

  if (usesPictogram(segments)) {
    /*
     * 0척인 등급도 **같은 줄에 같은 형식으로** 세운다 — 배 마크만 없다.
     *
     * 종전에는 「A · C등급 0척」을 아래 줄에 문장으로 붙였다. 두 가지가 아쉬웠다.
     * ⑴ 그 칸만 한 줄 더 길어져 KPI 세 칸의 줄이 어긋나 보였고,
     * ⑵ 남은 「B · D · E」만 서 있어 **등급 축이 끊겼다** — A와 C가 어디쯤인지
     *   세어 봐야 알 수 있었다.
     *
     * 다섯이 A→E로 나란히 서면 순서가 그대로 보이고, 빈 자리는 마크가 없다는
     * 것으로 드러난다. `#701` ②가 정한 **「0척인 등급을 감추지 않는다」**는
     * 그대로다 — 감추지 않는 방법만 바뀐다.
     */
    return (
      <div className="dist">
        <div className="dist__fleet" role="group" aria-label={`등급 분포 — ${distributionAria(segments)}`}>
          {distributionSlots(distribution).map((slot) => {
            /*
             * `as`로 찍어 내리지 않는다. `segments`가 0척을 빼고 오므로 **못 찾은
             * 것이 곧 0척**이고, 그 사실을 캐스트로 감추면 나중에 `segments`의
             * 계약이 바뀌어도 여기가 조용히 통과한다.
             */
            const segment = segments.find((seg) => seg.rating === slot.rating)
            return segment ? (
              <GradeGroup key={slot.rating} segment={segment} />
            ) : (
              <ZeroGroup key={slot.rating} rating={slot.rating} />
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="dist">
      {/*
       * `role`을 `img`가 아니라 `group`으로 둔다. `img`는 하위 트리를 통째로
       * presentational로 만들어 **구간마다 붙인 이름이 보조기술에 닿지 않는다.**
       */}
      <div className="dist__bar" role="group" aria-label={`등급 분포 — ${distributionAria(segments)}`}>
        {segments.map((seg) => {
          const pattern = gradePatternUrl(seg.rating)
          const inline = showsInlineLabel(seg.percent)
          const text = `${seg.rating} ${seg.count}`

          return (
            <span
              key={seg.rating}
              className={`dist__seg dist__seg--${seg.rating.toLowerCase()}`}
              style={{ width: `${seg.percent}%` }}
              role="img"
              aria-label={`${seg.rating}등급 ${seg.count}척`}
              /*
               * 8% 미만은 구간 안에 글자가 들어가지 않으므로 툴팁으로 낸다(`§10.2`).
               * `title`은 포인터 전용이라 그것만으로는 키보드 사용자가 못 읽는다 —
               * `tabIndex`로 초점을 받게 해 위 `aria-label`이 읽히는 경로를 연다.
               */
              {...(inline ? {} : { title: `${seg.rating}등급 ${seg.count}척`, tabIndex: 0 })}
            >
              {/*
               * 뷰박스를 두지 않는다 — 사용자 단위가 곧 CSS 픽셀이라 4px 타일이
               * 4px로 그려진다. 뷰박스를 주고 폭에 맞춰 늘이면 무늬가 찌그러진다.
               */}
              {pattern ? (
                <svg className="dist__seg-pattern" aria-hidden="true">
                  <rect width="100%" height="100%" fill={pattern} />
                </svg>
              ) : null}
              {inline ? (
                <span className="dist__seg-label" aria-hidden="true">
                  {text}
                </span>
              ) : null}
            </span>
          )
        })}
      </div>

      <ZeroNote zeros={zeros} />
    </div>
  )
}

/**
 * 한 등급의 배들과 그 이름표.
 *
 * 이름은 **묶음에 한 번만** 붙인다 — 낱개마다 붙이면 스무 개가 각각 읽혀 목록보다
 * 나빠진다. 이름표에 등급 문자가 있으므로 `§14`의 「색 외 보조 채널」이 여기서도
 * 충족된다(무늬는 그와 별개로 `§2.4.4`가 요구한다).
 */
function GradeGroup({ segment }: { segment: DistributionSegment }) {
  return (
    <div className="dist__group" role="img" aria-label={`${segment.rating}등급 ${segment.count}척`}>
      <div className="dist__ships">
        {Array.from({ length: segment.count }, (_, i) => (
          <VesselGlyph key={i} rating={segment.rating} />
        ))}
      </div>
      <p className={`dist__group-label dist__group-label--${segment.rating.toLowerCase()}`}>
        <b>{segment.rating}</b> {segment.count}척
      </p>
    </div>
  )
}

/**
 * 배가 없는 등급 — 픽토그램용.
 *
 * **등급색을 쓰지 않는다.** 다른 묶음과 같은 색이면 「여기에도 뭔가 있다」로
 * 잠깐 읽힌다. 없다는 사실이 색이 아니라 **빈 자리**로 드러나야 한다.
 *
 * 마크 자리를 채우지 않아도 라벨은 다른 묶음과 밑선이 맞는다 —
 * `.dist__fleet`이 `align-items: flex-end`다.
 */
function ZeroGroup({ rating }: { rating: Rating }) {
  return (
    <div className="dist__group" role="img" aria-label={`${rating}등급 0척`}>
      <p className="dist__group-label">
        <b>{rating}</b> 0척
      </p>
    </div>
  )
}

/** 0척인 등급 — 막대용. 막대는 폭 0인 조각을 그릴 수 없어 글로 남긴다. */
function ZeroNote({ zeros }: { zeros: readonly string[] }) {
  if (zeros.length === 0) return null
  return <p className="dist__zero">{zeros.join(' · ')}등급 0척</p>
}
