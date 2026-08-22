import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApplicabilityBadge } from '../../components/ApplicabilityBadge'
import { GradeBadge } from '../../components/GradeBadge'
import { DisclaimerBanner } from '../../components/DisclaimerBanner'
import { NotUnderwayPanel } from '../not-underway/NotUnderwayPanel'
import { VoyagePanel } from '../voyage-management/VoyagePanel'
import { ciiUnit } from '../voyage-cii/resultRules'
import { shipTypeLabel } from '../vessel-registration/shipTypes'
import { detailStatusText } from '../fleet/fleetRules'
import { DISPLAY_DIGITS, formatDecimalString } from '../../display/format'
import { CiiHistoryChart } from './CiiHistoryChart'
import { createApiVesselDetailProvider, VesselDetailError } from './apiProvider'
import { PositionForm } from './PositionForm'
import type { CiiYear, VesselDetail as Detail, VesselSpec } from './types'
import './VesselDetail.css'

/**
 * 선박 상세 — `UIFLOW v2.0` 2-8 · `#356`.
 *
 * 3계층(선대 → 선박 → 항차)의 **허리**다. 대시보드에서 내려오고 실시간 CII로 내려간다.
 *
 * ## 올해 값을 이력에서 가져온다
 *
 * `GET /vessels/{id}/cii-history`가 올해 행을 `status: "IN_PROGRESS"`로 함께 준다.
 * `#354`의 3종 값 엔드포인트를 따로 부르지 않는 이유는, **같은 값을 두 곳에서 받으면
 * 어긋났을 때 어느 쪽이 맞는지 판단해야 하기 때문**이다.
 *
 * ## 단위를 화면이 만들지 않는다
 *
 * `gCO₂/(DWT·nm)`과 `gCO₂/(GT·nm)`은 선종에 따라 갈린다(`DESIGN_SYSTEM §4.1` 🔒).
 * 축은 **서버가 준 `transport_capacity_basis`**를 쓴다. 화면이 선종에서 유추하면
 * 선종이 늘 때 서버와 갈라지고, **크루즈선에 `DWT`가 표시돼도 화면은 깨지지 않는다.**
 */
export function VesselDetail() {
  const { vesselId } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  /*
   * provider를 매 렌더마다 새로 만들지 않는다. 로딩과 위치 저장이 같은
   * `fetch`·`baseUrl`을 써야 테스트가 하나만 갈아 끼워도 둘 다 대체된다 —
   * `voyage-management`가 연료 provider에 같은 것을 넘기는 이유와 같다.
   */
  const [provider] = useState(() => createApiVesselDetailProvider())
  const [failure, setFailure] = useState<{ message: string; notFound: boolean } | null>(
    null,
  )

  useEffect(() => {
    if (!vesselId) return
    let alive = true
    setDetail(null)
    setFailure(null)

    provider
      .load(vesselId)
      .then((data) => {
        if (alive) setDetail(data)
      })
      .catch((error: unknown) => {
        if (!alive) return
        setFailure({
          message:
            error instanceof Error ? error.message : '선박 정보를 불러오지 못했습니다.',
          notFound: error instanceof VesselDetailError && error.notFound,
        })
      })

    return () => {
      alive = false
    }
  }, [vesselId, provider])

  if (failure) {
    return (
      <div className="vd">
        <BackLink />
        <section className="empty empty--error" role="alert">
          <p className="empty__msg">{failure.message}</p>
          {failure.notFound ? (
            <Link className="empty__cta" to="/dashboard">
              대시보드로 돌아가기
            </Link>
          ) : null}
        </section>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="vd" aria-busy="true">
        <BackLink />
        <p className="fleet__loading">선박 정보를 불러오는 중입니다…</p>
      </div>
    )
  }

  const { vessel, years, capacityBasis } = detail
  const unit = ciiUnit(capacityBasis)
  // 올해 = 목록의 마지막 행(서버가 from~to 오름차순으로 준다).
  const current = years.length > 0 ? years[years.length - 1] : null

  return (
    <div className="vd">
      <BackLink />

      <header className="vd__head">
        <div>
          <h1 className="vd__title">
            {vessel.name}
            {/*
              선박 상세는 이 배의 제원을 확인하러 오는 자리다 (`#653`).
              적용 대상 여부가 여기 없으면, 아래 YTD·등급을 규제 결과로 읽게 된다.
            */}
            <ApplicabilityBadge
              isCiiApplicableHint={vessel.isCiiApplicableHint}
              grossTonnage={vessel.grossTonnage}
              vesselName={vessel.name}
            />
          </h1>
          <p className="vd__sub">
            IMO {vessel.imoNumber} · {shipTypeLabel(vessel.shipType)}
          </p>
        </div>
        {detail.asOf ? (
          <p className="vd__asof">
            기준 {new Date(detail.asOf).toLocaleString('ko-KR', { hour12: false })}
          </p>
        ) : null}
      </header>

      {/* ── 올해 누적(YTD) — 주 표시 ─────────────────────────────── */}
      <section className="card vd__ytd" aria-label="올해 누적 CII">
        <div className="card__head">
          <h2 className="card__title">올해 누적 (YTD)</h2>
          <span className="card__meta">
            {current ? `${current.regulationYear}년 · 진행 중` : '—'}
          </span>
        </div>

        {current?.dataAvailable && current.rating ? (
          <div className="ytd">
            <GradeBadge
              rating={current.rating}
              label={`올해 누적 등급 ${current.rating}`}
            />
            <dl className="ytd__figures">
              {/*
                `DESIGN_SYSTEM §4.1` 🔒 — CII는 **소수 3자리 고정**이고
                `required_cii`도 같다. 서버가 주는 원본 문자열은 6자리라
                그대로 쓰면 다른 화면(CII 예측·항로 비교)과 자릿수가 어긋난다.
                §4.1이 「내부에는 API 원본을 그대로 보관하고 **반올림은 표시
                시점에만**」이라고 정한 그 표시 시점이 여기다.
              */}
              <div>
                <dt>실적 (attained)</dt>
                <dd className="num">
                  {/*
                    `dataAvailable`이 참이어도 타입은 `string | null`이다. 종전에는
                    값을 그대로 넣어 null이 **빈칸**으로 렌더됐다 — 옆 항목처럼
                    `—`로 적어 「값이 없다」를 눈에 보이게 한다.
                  */}
                  {current.attainedCii === null
                    ? '—'
                    : formatDecimalString(current.attainedCii, DISPLAY_DIGITS.cii)}
                </dd>
              </div>
              <div>
                <dt>기준 (required)</dt>
                <dd className="num">
                  {current.requiredCii === null
                    ? '—'
                    : formatDecimalString(current.requiredCii, DISPLAY_DIGITS.cii)}
                </dd>
              </div>
              <div>
                <dt>항차</dt>
                <dd className="num">{current.voyageCount}</dd>
              </div>
            </dl>
            {/* 단위는 서버가 준 축에서 파생한다 — 고정 문자열 금지(§4.1 🔒). */}
            <p className="ytd__unit">단위 {unit}</p>
          </div>
        ) : (
          <p className="vd__nodata">{noDataText(current)}</p>
        )}

        <p className="vd__note">
          올해 값은 연중 누적 예측값이며 <b>공식 등급이 아닙니다</b>. 공식 등급은 연말
          DCS 보고·검증 후 확정됩니다.
        </p>
      </section>

      <div className="vd__split">
        {/* ── 연도별 이력 ────────────────────────────────────────── */}
        <section className="card vd__main" aria-label="연도별 CII 이력">
          <div className="card__head">
            <h2 className="card__title">연도별 CII 이력</h2>
            <span className="card__meta">단위 {unit}</span>
          </div>
          <CiiHistoryChart years={years} basis={capacityBasis} />
        </section>

        {/* ── 제원 · 현재 상태 ───────────────────────────────────── */}
        <div className="vd__side">
          <section className="card" aria-label="선박 제원">
            <div className="card__head">
              <h2 className="card__title">제원</h2>
            </div>
            <dl className="spec">
              <Spec label="선종" value={shipTypeLabel(vessel.shipType)} />
              <Spec label="IMO 번호" value={vessel.imoNumber} />
              {/* 축에 해당하는 제원을 앞에 둔다 — 그 값이 CII 분모다. */}
              {capacityBasis === 'DWT' ? (
                <Spec label="재화중량톤수 (DWT)" value={vessel.deadweight} />
              ) : (
                <Spec label="총톤수 (GT)" value={vessel.grossTonnage} />
              )}
              <Spec label="기준 속력" value={vessel.referenceSpeedKn} suffix=" kn" />
              <Spec
                label="기준 일일 연료"
                value={vessel.referenceDailyFocTon}
                suffix=" t"
              />
              <Spec label="기본 연료" value={vessel.defaultFuelType} />
            </dl>
          </section>

          <section className="card" aria-label="현재 상태">
            <div className="card__head">
              <h2 className="card__title">현재 상태</h2>
            </div>
            <dl className="spec">
              <Spec label="운항 상태" value={stateText(vessel.underwayState)} />
              {/* `UIFLOW 2-4`가 정한 7값 표기. 코드를 그대로 내지 않는다. */}
              <Spec label="세부 상태" value={detailStatusText(vessel.detailStatus)} />
              <Spec
                label="현재 위치"
                value={
                  vessel.lat && vessel.lon ? `${vessel.lat}, ${vessel.lon}` : null
                }
              />
              <Spec
                label="위치 갱신"
                value={
                  vessel.positionUpdatedAt
                    ? new Date(vessel.positionUpdatedAt).toLocaleString('ko-KR', {
                        hour12: false,
                      })
                    : null
                }
              />
            </dl>
            {/*
             * 진행 중 항차로 내려가는 경로. 항차 목록을 여기서 따로 부르지 않는다 —
             * 실시간 화면(#357)이 자기 데이터를 스스로 가져오는 편이 경계가 맞다.
             */}
            {/*
             * 위치·상태 입력 (`API_SPEC §2.6` · `#369`). 이 카드는 네 값을 보여
             * 주면서 **읽기만 가능했다** — 쓰는 경로가 없어 위치가 시드 이후
             * 고정됐고, 대시보드 `PositionChart`가 빈 채로 떴다.
             *
             * 정박 **구간 기록**은 아래 `NotUnderwayPanel`이 소유한다. 여기서 바꾸는
             * 것은 「지금 무엇을 하고 있나」라는 **표시 상태**뿐이다 — 세부 상태 6값이
             * `period_type`과 같은 집합인 것은 그 둘이 같은 사실을 가리키기 때문이지
             * 한쪽이 다른 쪽을 쓰기 때문이 아니다.
             */}
            <PositionForm
              vessel={vessel}
              provider={provider}
              onSaved={(updated: VesselSpec) =>
                setDetail((prev) => (prev ? { ...prev, vessel: updated } : prev))
              }
            />

            {vessel.underwayState === 'UNDER_WAY' ? (
              <Link className="vd__drill" to={`/vessels/${vessel.id}/voyages/current`}>
                진행 중 항차의 실시간 CII 보기
              </Link>
            ) : null}
          </section>
        </div>
      </div>

      {/*
       * 정박 기록 입력 (#370). 선박 상세 아래에 두는 이유는, 이 기록이 바로 위
       * 「올해 누적」의 분자를 늘리기 때문이다 — 값을 본 자리에서 고칠 수 있어야 한다.
       */}
      {/*
        항차가 먼저다 — 정박·묘박은 항차와 항차 사이의 구간이라,
        운항 기록을 위에서 아래로 읽으면 순서가 이렇게 된다.
      */}
      <VoyagePanel vesselId={vessel.id} />
      <NotUnderwayPanel vesselId={vessel.id} />

      <DisclaimerBanner />
      <p className="fleet__source">일부 값은 사용자 입력 또는 모델 추정값입니다.</p>
    </div>
  )
}

function BackLink() {
  return (
    <Link className="vd__back" to="/dashboard">
      ← 대시보드
    </Link>
  )
}

function Spec({
  label,
  value,
  suffix = '',
}: {
  label: string
  value: string | null
  suffix?: string
}) {
  return (
    <div>
      <dt>{label}</dt>
      {/* 값이 없으면 「—」로 둔다. 빈칸이면 항목 자체가 없는 것으로 읽힌다. */}
      <dd className={value ? 'num' : 'num muted'}>{value ? `${value}${suffix}` : '—'}</dd>
    </div>
  )
}

/** 상태 미기록을 「정박」으로 적지 않는다 — 없는 사실이 된다. */
function stateText(state: 'UNDER_WAY' | 'NOT_UNDER_WAY' | null): string | null {
  if (state === 'UNDER_WAY') return '운항 중'
  if (state === 'NOT_UNDER_WAY') return '정박 중'
  return null
}

/** 데이터가 없는 이유를 사유별로 구분해 말한다. */
function noDataText(year: CiiYear | null): string {
  if (year === null) return '표시할 연도가 없습니다.'
  if (year.reason === 'NO_REGULATION_PARAMS') {
    return `${year.regulationYear}년 규정 파라미터가 등록되지 않아 산출할 수 없습니다.`
  }
  return '올해 등록된 항차 실적이 없습니다. 항차를 등록하면 누적값이 계산됩니다.'
}
