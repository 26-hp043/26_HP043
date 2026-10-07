import type { ReactNode } from 'react'
import { ErrorState } from '../../components/ErrorState'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { ciiUnit } from '../voyage-cii/resultRules'
import type { CiiYear, VesselDetail } from '../vessel-detail/types'
import { voyageCountText } from '../vessel-detail/voyageCount'
import { YtdNotice } from '../vessel-detail/YtdNotice'
import { ANNUAL_COPY } from './copy'

/**
 * 연도별 실적 — 시뮬레이션 결과 **위**의 블록 (#2017 · `API_SPEC §2.7`).
 *
 * ## 나란히 두는 것은 시뮬레이션 결과가 아니라 확정 실적이다
 *
 * 지나간 해는 잔여 계획이 없어 Monte Carlo 분포가 점 하나로 무너진다(`PRD §12.4.1` —
 * 「확정 실적은 변하지 않는다」). 그 해를 시뮬레이션으로 돌려 나란히 두면 표는 채워지는데
 * 목표 달성 확률이 0%·100%뿐이라 읽을 것이 없다. 그래서 이 블록은 **선박 상세가 이미 쓰는
 * 연도별 이력**(`GET /vessels/{id}/cii-history`)을 그대로 받아 확정 등급·실적 CII·기준 CII를
 * 적고, **확률을 싣지 않는다.**
 *
 * ## 진행 중인 해의 등급은 확정이 아니다 — `PRD COR-2` · `§3.3.7` 각주
 *
 * 응답의 `IN_PROGRESS` 행(올해 누적)에도 `rating`이 오지만 그것은 **연중 누적 예측값**이다.
 * 확정 행과 같은 「등급」 칸에 고지 없이 두면 공식 등급으로 읽힌다. 그래서 그 행은 구분 칸을
 * 「진행 중」으로, 등급 칸에 **보이는 글자로** 「현재 누적 기준 예상」을 붙이고, 표 아래에
 * 선박 상세와 **같은 문장**의 고지(`YtdNotice`)를 둔다. 판정은 문자열이 아니라 `status`다.
 *
 * ## 카드가 아니라 바닥이다
 *
 * `DESIGN_SYSTEM §5` 카드 예산(4개)은 입력 · 결론 띠 · 확률 분포 · 민감도로 이미 차 있다.
 * 이 블록은 면을 띄우지 않는다. ⚠️ 두 블록의 배치·경계 표시·실적/예측 구분 방법·
 * `data_available=false` 해의 표시·창의 길이는 **개발 임시안**이며 디자인 확정 대상이다
 * (`#2017` 정정 코멘트 5 · `rlatnals4114`).
 *
 * ## 값은 선박 상세와 같게 읽힌다
 *
 * 같은 응답을 같은 자릿수(`DISPLAY_DIGITS.cii`)·같은 항차 수 표기(`voyageCountText`)로 적는다.
 * 같은 값이 화면마다 다르게 보이면 사용자는 둘 중 하나가 틀렸다고 읽는다(`#750` · `#866`).
 * 수치는 서버 문자열을 그대로 쓴다(`API_SPEC §1.7`).
 */

export type ActualsState =
  | { status: 'loading' }
  | { status: 'success'; detail: VesselDetail }
  /**
   * 이 블록만 실패한다 — 시뮬레이션 쪽은 그대로다(`PRD §16.2` 오류 격리).
   * `retryable`이 거짓이면(없는 선박 · 404) 「다시 시도」를 주지 않는다 — 다시 눌러도 같은
   * 실패다(선박 상세 · `#694`).
   */
  | { status: 'error'; message: string; retryable: boolean }

export function YearlyActuals({
  state,
  onRetry,
  simulatedYear,
  footer,
}: {
  /** 카드 맨 아래 — 재현 · 계산 근거 (10/7). */
  footer?: ReactNode
  state: ActualsState
  onRetry: () => void
  /**
   * 아래 결과가 계산한 규제연도 (#2017 리뷰). 그 해가 이 표에 **확정 행**으로 있으면 같은 해가
   * 두 번 보이므로, 두 값의 계산 경로가 다르다는 한 줄을 표 아래에 둔다.
   */
  simulatedYear?: number
}) {
  return (
    <section
      className="annual-sim__actuals"
      aria-labelledby="annual-sim-actuals-title"
      data-testid="annual-sim-actuals"
    >
      <h2 id="annual-sim-actuals-title" className="card__title annual-sim__section-title">
        {ANNUAL_COPY.actualsTitle}
      </h2>
      <p className="annual-sim__caption">
        {ANNUAL_COPY.actualsCaption}
        {state.status === 'success'
          ? ` ${ANNUAL_COPY.actualsUnit.replace('{unit}', ciiUnit(state.detail.capacityBasis))}`
          : null}
      </p>
      {state.status === 'loading' ? (
        <p className="annual-sim__hint" role="status">
          {ANNUAL_COPY.actualsLoading}
        </p>
      ) : null}
      {/*
        「받지 못함」 — 블록 안에서만 알리고 다시 시도한다. 화면 전체의 오류로 올리지 않는다:
        시뮬레이션은 이 조회와 무관하게 실행할 수 있다.
      */}
      {state.status === 'error' ? (
        <ErrorState
          level="region"
          subject={ANNUAL_COPY.actualsErrorSubject}
          message={state.message}
          onRetry={state.retryable ? onRetry : undefined}
        />
      ) : null}
      {state.status === 'success' ? (
        <ActualsTable
          years={state.detail.years}
          unit={ciiUnit(state.detail.capacityBasis)}
          simulatedYear={simulatedYear}
        />
      ) : null}
      {footer}
    </section>
  )
}

function ActualsTable({
  years,
  unit,
  simulatedYear,
}: {
  years: CiiYear[]
  unit: string
  simulatedYear?: number
}) {
  // 「값 없음」 — 서버가 연도를 하나도 주지 않았다. 받지 못한 것(위 오류)과 다르다.
  if (years.length === 0) {
    return <p className="annual-sim__caption">{ANNUAL_COPY.actualsEmpty}</p>
  }
  const unavailable = years.filter((year) => !year.dataAvailable)
  const hasInProgress = years.some((year) => year.status === 'IN_PROGRESS')
  // 아래 결과의 해가 표의 **확정** 행이면 같은 해가 두 경로로 보인다 — 진행 중인 해는 해당 없다.
  const sameYear = years.find(
    (year) => year.status === 'CONFIRMED' && year.regulationYear === simulatedYear,
  )

  return (
    <>
      <div className="annual-sim__tablewrap">
        {/*
          같은 화면의 민감도 표와 같은 모양이다 — 표가 서로 다르면 다른 종류의 정보로 읽힌다.
          숫자 칸만 오른쪽 정렬이고 머리글과 값이 같은 규칙을 받는다(`#2015`) — 민감도 표의
          공용 규칙은 건드리지 않고 이 표의 클래스에만 건다.
        */}
        <table className="annual-sim__table annual-sim__actuals-table">
          {/* 표 제목과 단위를 표에 잇는다 — 선박 상세 `CiiHistoryChart`와 같은 방식. 시각으로는 위 제목·캡션이 있어 숨긴다. */}
          <caption className="sr-only">
            {ANNUAL_COPY.actualsTitle} · {ANNUAL_COPY.actualsUnit.replace('{unit}', unit)}
          </caption>
          <thead>
            <tr>
              <th scope="col">{ANNUAL_COPY.actualsColumnYear}</th>
              <th scope="col">{ANNUAL_COPY.actualsColumnKind}</th>
              <th scope="col" className="num">
                {ANNUAL_COPY.actualsColumnAttained}
              </th>
              <th scope="col" className="num">
                {ANNUAL_COPY.actualsColumnRequired}
              </th>
              <th scope="col">{ANNUAL_COPY.actualsColumnRating}</th>
              <th scope="col" className="num">
                {ANNUAL_COPY.actualsColumnVoyages}
              </th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const inProgress = year.status === 'IN_PROGRESS'
              return (
                <tr key={year.regulationYear}>
                  <th scope="row">{year.regulationYear}</th>
                  <td>{inProgress ? ANNUAL_COPY.actualsInProgress : ANNUAL_COPY.actualsConfirmed}</td>
                  {/* `DESIGN_SYSTEM §4.1` 🔒 — CII·required 모두 소수 3자리. 선박 상세 표와 같은 함수다. */}
                  <td className="num">
                    {year.attainedCii === null
                      ? '—'
                      : formatDecimalString(year.attainedCii, DISPLAY_DIGITS.cii)}
                  </td>
                  <td className="num">
                    {year.requiredCii === null
                      ? '—'
                      : formatDecimalString(year.requiredCii, DISPLAY_DIGITS.cii)}
                  </td>
                  {/*
                    등급은 문자로 적는다 — 색만으로 구분하지 않는다(`§14`). 진행 중인 해의 등급은
                    **보이는 글자로** 예상임을 드러낸다(`PRD COR-2` 「현재 누적 기준 예상 등급」).
                  */}
                  <td>
                    {year.rating ?? '—'}
                    {inProgress && year.rating ? (
                      <>
                        {' '}
                        <span className="annual-sim__hint">({ANNUAL_COPY.actualsYtdRatingHint})</span>
                      </>
                    ) : null}
                  </td>
                  <td className="num">{voyageCountText(year)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {/*
        진행 중인 해의 고지 — 선박 상세와 같은 문장(`YtdNotice`). 근거 `PRD §3.3.7` 각주 · `COR-2`.
        진행 중 행이 없으면(모두 확정) 고지할 대상이 없어 두지 않는다.
      */}
      {hasInProgress ? <YtdNotice className="annual-sim__caption" /> : null}
      {/*
        「계산 못 함」 — 칸은 「—」로 두고 이유는 표 아래 한 번(`UIFLOW 2-11` · #1581의 규칙을 이
        표에도 적용). 사유마다 사용자가 할 일이 다르므로 한 문장으로 뭉치지 않는다.
      */}
      {unavailable.map((year) => (
        <p className="annual-sim__caption" key={year.regulationYear}>
          {unavailableText(year)}
        </p>
      ))}
      {/*
        아래 결과가 계산한 해가 이 표의 확정 행이면 같은 해가 두 번 보인다 (#2017 리뷰). 두 값은
        계산 경로가 다르다 — 표는 등록된 항차의 확정 집계, 결과는 실행 시점 스냅샷의 재계산.
        말하지 않으면 둘 중 하나가 틀린 것으로 읽힌다. ⚠️ 문구는 개발 임시안.
      */}
      {sameYear ? (
        <p className="annual-sim__caption" data-testid="annual-sim-actuals-same-year">
          {ANNUAL_COPY.actualsSameYearNote.replace('{year}', String(sameYear.regulationYear))}
        </p>
      ) : null}
    </>
  )
}

/** `data_available=false`의 사유 문장 — 선박 상세의 `noDataText`와 같은 구분이다. */
function unavailableText(year: CiiYear): string {
  const y = String(year.regulationYear)
  if (year.reason === 'NO_REGULATION_PARAMS') {
    return ANNUAL_COPY.actualsReasonNoParams.replace('{year}', y)
  }
  if (year.reason === 'NO_DATA' || year.reason === null) {
    return ANNUAL_COPY.actualsReasonNoData.replace('{year}', y)
  }
  return ANNUAL_COPY.actualsReasonOther.replace('{year}', y).replace('{reason}', year.reason)
}
