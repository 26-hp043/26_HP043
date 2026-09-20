import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { GradeBadge } from '../../components/GradeBadge'
import { formatGrouped } from '../../display/format'
import { warningMessage } from '../voyage-cii/resultRules'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { useYearOptions } from '../parameters/yearCatalog'
import { createApiFleetReductionProvider } from './apiProvider'
import { hasInvalidPrice, isInvalidPrice } from './priceRules'
import { FLEET_REDUCTION_COPY as COPY, TARGET_TEXT, UNAVAILABLE_TEXT } from './copy'
import {
  MAX_REDUCTION_PERCENT,
  TARGETS,
  type EvaluateResult,
  type FleetReductionProvider,
  type Prices,
  type Rating,
  type SavedPlanSummary,
  type Target,
  type VesselResult,
} from './types'
import './FleetReduction.css'

/**
 * `UIFLOW 2-10` 함대 감축 계획 — 선대 계층 (#513).
 *
 * ## 슬라이더를 움직이면 서버에 다시 묻는다
 *
 * 계산은 서버(`API_SPEC §2.17.1`)가 한다 — 화면이 연료·등급을 다시 계산하면 연간 등급 관리와
 * 다른 식이 하나 더 생긴다. **결정론만** 쓰므로 한 번 묻는 비용이 작고, 연속 조작은 짧게 모아 묻는다.
 *
 * ## 7:5 두 단 (`DESIGN_SYSTEM §7.1` · `UIFLOW 2-10`)
 *
 * 왼쪽은 선박별 조정, 오른쪽은 그 결과(상태 · 비용 · 분포 · 저장)다.
 */

/** 연속 조작을 모으는 시간(ms). 슬라이더를 끄는 동안 요청이 쌓이지 않게 한다. */
const EVALUATE_DELAY_MS = 300
const FLEET_KEY = 'fleet'
const RATINGS: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

/**
 * 계산 상태 — **실패해도 마지막 성공 결과를 버리지 않는다** (#1069).
 *
 * 종전에는 `loading | error | ready` 중 하나라 실패하는 순간 선박 표·단가 칸·저장이 함께 사라졌다.
 * 실패 원인이 입력(예: 음수 단가 → 422)이면 **고칠 칸이 없어** 새로고침 말고는 빠져나올 수 없었다.
 */
type EvalState = { result: EvaluateResult | null; error: string | null }

const EMPTY_PRICES: Prices = { charterUsdPerDay: {}, fuelUsdPerTon: {} }

export function FleetReduction({ provider }: { provider?: FleetReductionProvider }) {
  const api = useMemo(() => provider ?? createApiFleetReductionProvider(), [provider])
  const { years, loading: yearsLoading } = useYearOptions(FLEET_KEY)
  const [year, setYear] = useState('')
  const [target, setTarget] = useState<Target>('NO_AT_RISK')
  const [percents, setPercents] = useState<Record<string, number>>({})
  const [prices, setPrices] = useState<Prices>(EMPTY_PRICES)
  const [evaluation, setEvaluation] = useState<EvalState>({ result: null, error: null })
  const [retryKey, setRetryKey] = useState(0)
  const [plans, setPlans] = useState<SavedPlanSummary[]>([])
  const [plansFailed, setPlansFailed] = useState(false)
  const [plansKey, setPlansKey] = useState(0)
  const [planName, setPlanName] = useState('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const pricesSeeded = useRef(false)

  useEffect(() => {
    if (years.length === 0) return
    setYear((prev) => pickDefaultYear(years, new Date().getFullYear(), prev))
  }, [years])

  // 저장한 계획 목록 — 가장 최근 계획의 단가를 **새 계획의 기본값**으로 쓴다(`API_SPEC §2.17.3`).
  useEffect(() => {
    let cancelled = false
    api
      .list()
      .then((rows) => {
        if (cancelled) return
        setPlans(rows)
        setPlansFailed(false)
        if (!pricesSeeded.current && rows.length > 0) {
          pricesSeeded.current = true
          setPrices(rows[0].prices)
        }
      })
      .catch(() => {
        // 조회 실패를 「저장한 계획이 없습니다」로 보이지 않는다 — 없는 것과 못 가져온 것은 다르다.
        if (!cancelled) setPlansFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [api, plansKey])

  const request = useMemo(
    () => ({
      regulationYear: year === '' ? new Date().getFullYear() : Number(year),
      target,
      adjustments: Object.entries(percents).map(([vesselId, percent]) => ({ vesselId, percent })),
      prices,
    }),
    [year, target, percents, prices],
  )
  const pricesInvalid = hasInvalidPrice(prices)

  useEffect(() => {
    if (yearsLoading) return
    if (years.length > 0 && year === '') return
    // 잘못된 단가로는 묻지 않는다 — 칸에 오류를 보이고 마지막 결과를 그대로 둔다.
    if (pricesInvalid) return
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .evaluate(request)
        .then((result) => {
          if (!cancelled) setEvaluation({ result, error: null })
        })
        .catch((error: unknown) => {
          if (cancelled) return
          setEvaluation((prev) => ({
            result: prev.result,
            error: error instanceof Error ? error.message : COPY.evaluateFailed,
          }))
        })
    }, EVALUATE_DELAY_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, request, years.length, year, yearsLoading, pricesInvalid, retryKey])

  const shown = evaluation.result

  /**
   * 단가를 물을 연료 (`#1273`).
   *
   * 종전에는 **서버 연료 목록 전체에 `missingFuelPrices`를 더했다** — 방향이 반대라
   * 보유 선박이 쓰지도 않는 연료까지 8종이 전부 떴고, 그동안 우측 비용 요약은
   * 통째로 `단가 입력 필요`로 남았다.
   *
   * 서버가 `costs.missing_fuel_prices`로 **이 계획에 단가가 필요한데 없는 연료**를
   * 이미 알려준다(`calc/fleet_reduction.py`). 그것을 기준으로 좁힌다.
   *
   * ⚠️ **이미 입력한 코드를 합쳐야 한다.** `missingFuelPrices`는 「없는 것」만 담으므로
   * 값을 넣는 순간 그 코드가 목록에서 빠져 **방금 채운 칸이 사라진다.** 저장한 계획에서
   * 이어받은 단가(`plans[0].prices`)도 이 합집합으로 남는다 — 요청에 실려 나가는 값이라
   * 화면에서 감추면 고칠 수단이 없어진다.
   */
  const fuelCodes = useMemo(() => {
    if (!shown) return []
    const codes = new Set(shown.costs.missingFuelPrices)
    for (const [code, value] of Object.entries(prices.fuelUsdPerTon)) {
      if (value.trim() !== '') codes.add(code)
    }
    return [...codes].sort()
  }, [shown, prices.fuelUsdPerTon])

  const save = async () => {
    const name = planName.trim()
    if (name === '' || pricesInvalid) return
    setSaving(true)
    setSaveMessage(null)
    try {
      const saved = await api.save({ ...request, planName: name })
      setPlans((prev) => [saved, ...prev])
      setSaveMessage(COPY.saved(saved.planName))
      setPlanName('')
    } catch (error: unknown) {
      setSaveMessage(error instanceof Error ? error.message : COPY.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  const loadPlan = (planId: string) => {
    const plan = plans.find((p) => p.planId === planId)
    if (!plan) return
    setYear(String(plan.regulationYear))
    setTarget(plan.target)
    setPercents(Object.fromEntries(plan.adjustments.map((a) => [a.vesselId, a.percent])))
    setPrices(plan.prices)
  }

  return (
    <section className="fr">
      <p className="fr__notice">{COPY.deterministicNotice}</p>

      <div className="fr__controls">
        <Field id="fr-year" label={COPY.yearLabel}>
          {(control) => (
            <select
              {...control}
              className="fr__control"
              value={year}
              disabled={years.length === 0}
              onChange={(e) => setYear(e.target.value)}
            >
              {years.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field id="fr-target" label={COPY.targetLabel}>
          {(control) => (
            <select
              {...control}
              className="fr__control"
              value={target}
              onChange={(e) => setTarget(e.target.value as Target)}
            >
              {TARGETS.map((t) => (
                <option key={t} value={t}>
                  {TARGET_TEXT[t]}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      {shown === null && evaluation.error === null ? (
        <p className="fr__placeholder" aria-live="polite">
          {COPY.loading}
        </p>
      ) : null}
      {evaluation.error !== null ? (
        <ErrorState
          level="region"
          subject={COPY.loadSubject}
          message={shown === null ? evaluation.error : `${evaluation.error} ${COPY.staleResult}`}
          onRetry={() => setRetryKey((k) => k + 1)}
        />
      ) : null}

      {shown !== null ? (
        <div className="fr__grid">
          <section className="card fr__main" aria-labelledby="fr-vessels-title">
            <h2 id="fr-vessels-title" className="card__title">
              {COPY.vesselsTitle}
            </h2>
            <div className="fr__table-wrap">
              <table className="fr__table">
                <thead>
                  <tr>
                    <th scope="col">{COPY.colVessel}</th>
                    <th scope="col">{COPY.colGrade}</th>
                    <th scope="col">{COPY.colReduction}</th>
                    <th scope="col">{COPY.colExtraDays}</th>
                    <th scope="col">{COPY.colFuelSaved}</th>
                    <th scope="col">{COPY.colCharter}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.vessels.map((vessel) => (
                    <VesselRow
                      key={vessel.vesselId}
                      vessel={vessel}
                      percent={percents[vessel.vesselId] ?? 0}
                      charter={prices.charterUsdPerDay[vessel.vesselId] ?? ''}
                      charterInvalid={isInvalidPrice(prices.charterUsdPerDay[vessel.vesselId] ?? '')}
                      onPercent={(value) =>
                        setPercents((prev) => ({ ...prev, [vessel.vesselId]: value }))
                      }
                      onCharter={(value) =>
                        setPrices((prev) => ({
                          ...prev,
                          charterUsdPerDay: { ...prev.charterUsdPerDay, [vessel.vesselId]: value },
                        }))
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
            {shown.warnings.length > 0 ? (
              <ul className="fr__warnings">
                {shown.warnings.map((code) => (
                  <li key={code}>{warningMessage(code)}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <aside className="fr__side">
            <Status result={shown} adjusted={Object.values(percents).some((p) => p > 0)} />
            <Costs result={shown} />
            <section className="card" aria-labelledby="fr-fuel-title">
              <h2 id="fr-fuel-title" className="card__title">
                {COPY.fuelPricesTitle}
              </h2>
              <p className="fr__caption">{COPY.pricesNote}</p>
              {fuelCodes.length === 0 ? (
                <p className="fr__muted">
                  {shown ? COPY.fuelPricesNone : COPY.fuelPricesBeforeRun}
                </p>
              ) : null}
              <div className="fr__prices">
                {fuelCodes.map((code) => {
                  const invalid = isInvalidPrice(prices.fuelUsdPerTon[code] ?? '')
                  return (
                    <Field
                      key={code}
                      id={`fr-fuel-${code}`}
                      /* 서버 `displayName`은 MEPC.364(79) 원문 표기라 정본 문구다 —
                         화면에 내는 이름은 `fuelTypes.ts`가 갖는다 (`#598` · `AGENTS §4.6`). */
                      label={fuelTypeOptionText(code)}
                      error={invalid ? COPY.priceInvalid : undefined}
                    >
                      {(control) => (
                        <input
                          {...control}
                          className="fr__control"
                          type="number"
                          min={0}
                          inputMode="decimal"
                          value={prices.fuelUsdPerTon[code] ?? ''}
                          onChange={(e) =>
                            setPrices((prev) => ({
                              ...prev,
                              fuelUsdPerTon: { ...prev.fuelUsdPerTon, [code]: e.target.value },
                            }))
                          }
                        />
                      )}
                    </Field>
                  )
                })}
              </div>
            </section>
            <Distribution result={shown} />
            <section className="card" aria-labelledby="fr-save-title">
              <h2 id="fr-save-title" className="card__title">
                {COPY.saveTitle}
              </h2>
              <div className="fr__save">
                <Field id="fr-plan-name" label={COPY.planNameLabel}>
                  {(control) => (
                    <input
                      {...control}
                      className="fr__control"
                      type="text"
                      maxLength={100}
                      value={planName}
                      onChange={(e) => setPlanName(e.target.value)}
                    />
                  )}
                </Field>
                <button
                  type="button"
                  className="fr__button"
                  disabled={saving || planName.trim() === '' || pricesInvalid}
                  /*
                   * 단가 오류는 **다른 절(연료 단가)에 있다** — 이 버튼 옆에서는
                   * 왜 잠겼는지 알 길이 없었다. 이름이 비어 있는 쪽은 바로 위 칸이
                   * 말하므로 적지 않는다 (`§14` 「비활성의 사유」 · `#1170` ⑵).
                   */
                  aria-describedby={pricesInvalid ? 'fr-save-blocked' : undefined}
                  onClick={() => void save()}
                >
                  {saving ? COPY.saving : COPY.saveButton}
                </button>
              </div>
              {pricesInvalid ? (
                <p id="fr-save-blocked" className="fr__caption" role="status">
                  {COPY.saveBlockedByPrice}
                </p>
              ) : null}
              {saveMessage ? (
                <p className="fr__caption" role="status">
                  {saveMessage}
                </p>
              ) : null}
              {plansFailed || plans.length === 0 ? (
                <div className="fr__field">
                  <span className="fr__label">{COPY.loadLabel}</span>
                  {plansFailed ? (
                    <ErrorState
                      level="region"
                      size="compact"
                      message={COPY.plansFailed}
                      onRetry={() => setPlansKey((k) => k + 1)}
                    />
                  ) : (
                    <span className="fr__caption">{COPY.noPlans}</span>
                  )}
                </div>
              ) : (
                <Field id="fr-load" label={COPY.loadLabel}>
                  {(control) => (
                    <select
                      {...control}
                      className="fr__control"
                      value=""
                      onChange={(e) => loadPlan(e.target.value)}
                    >
                      <option value="">{COPY.loadPlaceholder}</option>
                      {plans.map((p) => (
                        <option key={p.planId} value={p.planId}>
                          {p.planName}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              )}
            </section>
          </aside>
        </div>
      ) : null}
    </section>
  )
}

function VesselRow({
  vessel,
  percent,
  charter,
  charterInvalid,
  onPercent,
  onCharter,
}: {
  vessel: VesselResult
  percent: number
  charter: string
  charterInvalid: boolean
  onPercent: (value: number) => void
  onCharter: (value: string) => void
}) {
  const sliderId = `fr-slider-${vessel.vesselId}`
  const unavailable = vessel.unavailableReason !== null
  return (
    <tr>
      {/*
        선박명은 **한 줄로 고정한다** (`#1427`).

        종전에는 「샘플 로로 여객선 (25,000 GT)」 같은 이름이 넉 줄로 꺾여 행 높이가
        들쭉날쭉했다 — 감속률 슬라이더가 행마다 다른 높이에 놓여 **세로로 훑기가
        어려웠다.** `nowrap`은 머리글과 숫자 칸에만 걸려 있었다.

        `title`은 **넘치는 이름을 마우스로 확인하는 보조 수단**이다. 잘린 이름이
        유일한 채널이 아니라는 점이 `#1424`(툴팁을 쓰지 않기로 한 자리)와 다르다 —
        링크의 접근성 이름은 **잘리지 않은 전체 텍스트**이고(말줄임은 그리기일 뿐
        DOM을 자르지 않는다), 이름 전체는 선박 상세에도 있다.
      */}
      <th scope="row" className="fr__vessel">
        <Link to={`/vessels/${vessel.vesselId}`} title={vessel.vesselName}>
          {vessel.vesselName}
        </Link>
      </th>
      <td>
        {vessel.before && vessel.after ? (
          <>
            <Transition before={vessel.before.rating} after={vessel.after.rating} />
            <TargetLine vessel={vessel} />
          </>
        ) : (
          <span className="fr__muted">
            {UNAVAILABLE_TEXT[vessel.unavailableReason ?? ''] ?? vessel.unavailableReason}
          </span>
        )}
      </td>
      <td>
        <div className="fr__slider">
          {/*
            `DESIGN_SYSTEM §8` 슬라이더 🔒 — 채움은 Primary 단색, 키보드 단위는 `§4.2` 자릿수(0.1%),
            값은 **행 오른쪽 고정 위치**에 둔다(툴팁이면 위아래 행을 덮고 열 정렬이 무너진다).
            계산할 수 없는 선박은 비활성 + 사유 텍스트(왼쪽 칸).
          */}
          <input
            id={sliderId}
            type="range"
            min={0}
            max={MAX_REDUCTION_PERCENT}
            step={0.1}
            value={percent}
            disabled={unavailable}
            aria-label={`${vessel.vesselName} ${COPY.colReduction}`}
            aria-valuetext={`${percent.toFixed(1)}%`}
            onChange={(e) => onPercent(Number(e.target.value))}
          />
          <output htmlFor={sliderId} className="fr__num">
            {percent.toFixed(1)}%
          </output>
        </div>
        {vessel.skippedVoyages > 0 ? (
          <p className="fr__hint">{COPY.skippedHint(vessel.skippedVoyages)}</p>
        ) : null}
      </td>
      <td className="fr__num">{vessel.extraDays === null ? '—' : `${vessel.extraDays}일`}</td>
      <td className="fr__num">
        {vessel.fuelSavedTon === null ? '—' : `${formatGrouped(vessel.fuelSavedTon, 1)}t`}
      </td>
      <td>
        <input
          className="fr__charter"
          type="number"
          min={0}
          inputMode="decimal"
          aria-label={`${vessel.vesselName} ${COPY.colCharter}`}
          value={charter}
          disabled={unavailable}
          /* Field 예외(#936): 표 칸이라 보이는 `<label>`이 없다 — 이름은 열 제목과
             `aria-label`이 준다. `Field`를 씌우면 셀마다 라벨이 한 줄씩 생긴다. */
          aria-invalid={charterInvalid ? true : undefined}
          onChange={(e) => onCharter(e.target.value)}
        />
        {charterInvalid ? (
          <em className="fr__field-error" role="alert">
            {COPY.priceInvalid}
          </em>
        ) : null}
      </td>
    </tr>
  )
}

/** 목표 판정 한 줄 — 미달이면 **무엇이 더 필요한지**까지(`PRD §12.3.2` ⑹). */
function TargetLine({ vessel }: { vessel: VesselResult }) {
  if (vessel.meetsTarget === null) return null
  if (vessel.meetsTarget) return <span className="fr__hint">{COPY.meets}</span>
  const more =
    vessel.achievable === false
      ? COPY.unreachable
      : vessel.requiredCutFuelTon
        ? COPY.cutHint(formatGrouped(vessel.requiredCutFuelTon, 1))
        : null
  return (
    <span className="fr__hint">
      {COPY.misses}
      {more ? ` — ${more}` : ''}
    </span>
  )
}

/**
 * 등급 전이 — `DESIGN_SYSTEM §8.3` 🔒. `GradeBadge` 둘 + **중립 연결자**. 바뀌지 않으면 하나만.
 */
function Transition({ before, after }: { before: Rating; after: Rating }) {
  if (before === after) return <GradeBadge rating={after} size="sm" />
  return (
    <span className="fr__transition" role="img" aria-label={`조정 전 ${before}, 조정 후 ${after}`}>
      <GradeBadge rating={before} size="xs" />
      <span className="fr__connector" aria-hidden="true">
        →
      </span>
      <GradeBadge rating={after} size="xs" />
    </span>
  )
}

/**
 * 상태 분기 **4종** — 선박 없음 · 초기 · 목표 달성 · 목표 미달
 * (`UIFLOW 2-10` · 2026-09-18 확정 · `#1052` ⓸).
 *
 * ## 넷째가 셋째와 같은 톤을 쓰고 있었다
 *
 * 주석은 「3종」이라 적혀 있었는데 분기는 넷이었고, **「선박이 없다」와
 * 「아직 조정하지 않았다」가 같은 `idle`** 로 떨어졌다. 게다가 `.fr__status--idle`
 * 규칙이 CSS에 없어 둘 다 기본 띠로 그려졌다 — 화면에서 가를 수 없었다.
 *
 * 둘은 성질이 다르다. **「아직」은 조작 이전이라 움직이면 풀리고, 「선박 없음」은
 * **조작할 대상이 없는 것**이라 슬라이더를 움직여도 아무 일도 안 난다.
 */
function Status({ result, adjusted }: { result: EvaluateResult; adjusted: boolean }) {
  let text: string
  let tone: 'empty' | 'idle' | 'met' | 'missed'
  if (result.targetMet === null) {
    text = COPY.statusNoVessel
    tone = 'empty'
  } else if (result.targetMet) {
    text = COPY.statusMet
    tone = 'met'
  } else if (!adjusted) {
    text = COPY.statusIdle
    tone = 'idle'
  } else {
    text = COPY.statusMissed
    tone = 'missed'
  }
  return (
    <p className={`card fr__status fr__status--${tone}`} role="status">
      <strong>{TARGET_TEXT[result.target]}</strong> — {text}
    </p>
  )
}

function Money({ value }: { value: string | null }) {
  if (value === null) return <span className="fr__muted">{COPY.needsPrice}</span>
  return <span className="fr__num">{formatGrouped(value, 0)} USD</span>
}

function Costs({ result }: { result: EvaluateResult }) {
  const c = result.costs
  return (
    <section className="card" aria-labelledby="fr-costs-title">
      <h2 id="fr-costs-title" className="card__title">
        {COPY.costsTitle}
      </h2>
      <dl className="fr__costs">
        <div>
          <dt>{COPY.extraDays}</dt>
          <dd className="fr__num">{c.extraDays}일</dd>
        </div>
        <div>
          <dt>{COPY.charterLoss}</dt>
          <dd>
            <Money value={c.charterLoss} />
          </dd>
        </div>
        <div>
          <dt>{COPY.fuelSaving}</dt>
          <dd>
            <Money value={c.fuelSaving} />
          </dd>
        </div>
        <div>
          <dt>{COPY.net}</dt>
          <dd>
            <Money value={c.net} />
          </dd>
        </div>
      </dl>
    </section>
  )
}

function Distribution({ result }: { result: EvaluateResult }) {
  return (
    <section className="card" aria-labelledby="fr-dist-title">
      <h2 id="fr-dist-title" className="card__title">
        {COPY.distributionTitle}
      </h2>
      <div className="fr__table-wrap">
        <table className="fr__table fr__dist">
          <thead>
            <tr>
              <th scope="col" />
              {RATINGS.map((r) => (
                <th key={r} scope="col">
                  <GradeBadge rating={r} size="xs" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(['before', 'after'] as const).map((row) => (
              <tr key={row}>
                <th scope="row">{row === 'before' ? COPY.before : COPY.after}</th>
                {RATINGS.map((r) => (
                  <td key={r} className="fr__num">
                    {result.distribution[row][r]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
