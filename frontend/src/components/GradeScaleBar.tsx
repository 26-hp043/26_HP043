import './GradeScaleBar.css'
import { gradePatternUrl } from './gradePattern'
import { buildGradeScale, type DVector } from './gradeScale'
import type { Rating } from '../features/voyage-cii/types'

/**
 * 등급 스케일 바 — `DESIGN_SYSTEM §8` 「A–E 구간 + 현재 위치 마커」.
 *
 * §8이 **등급 배지와 분리된 별도 컴포넌트**로 규정한다. 배지는 「무슨 등급인가」에,
 * 이 바는 **「구간 안 어디에 있고 경계까지 얼마나 남았나」** 에 답한다.
 *
 * ## 구간 폭은 균등이 아니다 (`§9.4` 🔒)
 *
 * *"밴드 높이는 균등 분할이 아니라 `d1`~`d4` 실제 경계값에 비례해야 한다."* 계산은
 * `buildGradeScale()`이 하고 여기서는 그 비율을 그대로 `flex-grow`에 넘긴다.
 *
 * 경계값(`boundaries`)은 **필수 prop이다.** 없을 때 균등 분할로 떨어지게 두지 않았다 —
 * 균등 바는 멀쩡해 보이면서 「C에서 D까지가 B에서 C까지와 같다」는 틀린 감각을 준다.
 * 값을 못 주는 호출부는 이 컴포넌트를 쓰지 않는 편이 낫다.
 *
 * ## 색 + 패턴 (`§2.4.4` 🔒)
 *
 * 구간에는 등급 문자가 들어가지 않으므로 **패턴이 필수다.** 3색 체계라 초록·주황·빨강
 * 세 색상군이 적록색맹에서 모두 황갈색으로 수렴한다. `showPattern` 기본값이 `true`이고
 * *"끄는 쪽이 예외"* 인 것도 §2.4.4의 문구 그대로다.
 *
 * 패턴은 `GradePatternDefs`(공통 셸에 1회)를 참조한다. 여기서 다시 정의하면 같은 무늬가
 * 두 벌이 되어 한쪽만 고쳐지는 드리프트가 생긴다.
 *
 * ## 축에 등급 문자를 병기한다
 *
 * `§9.4`가 *"구간을 칠하는 경우 좌측 축에 등급 문자를 반드시 병기한다"* 고 요구한다
 * (`§0.2` 제약 2·3). 가로 바이므로 각 구간 **아래**에 둔다. 색·패턴·문자 세 채널이
 * 되어 `§14`의 이중화 요구를 넘어선다.
 *
 * ## 마커에 등급색을 쓰지 않는다
 *
 * 마커가 등급색이면 깔린 구간색과 섞여 위치가 흐려지고, `§9.4`의 *"등급색 사용 금지"*
 * 취지에도 어긋난다. `--text-primary` 단색으로 어느 구간 위에서도 같은 대비를 낸다.
 */

interface GradeScaleBarProps {
  /** `ratio_to_required` — 마커 위치의 근거. 문자열 그대로 받는다. */
  ratioToRequired: string
  /** `parameters_used.rating_boundary`. **필수** — 위 docstring 참조. */
  boundaries: DVector
  /** 현재 등급. 마커 설명에 쓴다. */
  rating: Rating
  /** 마커에 띄울 표시값. 자릿수는 호출부가 `format.ts`로 이미 맞춘 문자열이다. */
  valueLabel: string
  /** 스크린 리더가 읽을 이름. 화면마다 무엇의 등급인지 다르다. */
  label: string
  /** `§2.4.4` — 끄는 쪽이 예외다. */
  showPattern?: boolean
}

export function GradeScaleBar({
  ratioToRequired,
  boundaries,
  rating,
  valueLabel,
  label,
  showPattern = true,
}: GradeScaleBarProps) {
  const scale = buildGradeScale(ratioToRequired, boundaries)

  /*
   * 못 그리는 경우를 조용히 감추지 않는다 — 빈자리는 「아직 로딩 중」으로 읽힌다.
   * 위치가 틀린 바를 그리는 것보다는 못 그린다고 적는 편이 낫다.
   */
  if (!scale) {
    return (
      <p className="grade-scale-bar__unavailable">
        등급 경계값을 읽을 수 없어 스케일을 표시하지 않습니다.
      </p>
    )
  }

  return (
    <figure className="grade-scale-bar">
      <div
        className="grade-scale-bar__track"
        role="img"
        aria-label={`${label}. 현재 등급 ${rating}, 기준 대비 ${valueLabel}.`}
      >
        {/*
          구간만 따로 감싼다. 둥근 모서리를 내려면 잘라 내야 하는데, 트랙째 자르면
          트랙 위로 올라앉는 마커 값 라벨까지 함께 잘린다.
        */}
        <div className="grade-scale-bar__bands">
          {scale.bands.map((band) => {
            const lower = band.rating.toLowerCase()
            const pattern = showPattern ? gradePatternUrl(band.rating) : undefined

            return (
              <div
                key={band.rating}
                className="grade-scale-bar__band"
                style={{
                  flexGrow: band.fraction,
                  background: `var(--cii-${lower}-fill)`,
                }}
              >
                {/*
                  뷰박스를 두지 않는다. 사용자 단위가 곧 CSS 픽셀이라 4px 타일이
                  4px로 그려진다 — 뷰박스를 주고 폭에 맞춰 늘이면 무늬가 가로로
                  찌그러진다.
                */}
                {pattern ? (
                  <svg className="grade-scale-bar__pattern" aria-hidden="true">
                    <rect width="100%" height="100%" fill={pattern} />
                  </svg>
                ) : null}
              </div>
            )
          })}
        </div>

        <div
          className="grade-scale-bar__marker"
          style={{ left: `${scale.markerFraction * 100}%` }}
        >
          <span className="grade-scale-bar__marker-value">{valueLabel}</span>
        </div>
      </div>

      {/* §9.4 — 구간을 칠했으므로 등급 문자를 병기한다. */}
      <figcaption className="grade-scale-bar__axis" aria-hidden="true">
        {scale.bands.map((band) => (
          <span
            key={band.rating}
            className="grade-scale-bar__axis-label"
            style={{ flexGrow: band.fraction }}
          >
            {band.rating}
          </span>
        ))}
      </figcaption>
    </figure>
  )
}
