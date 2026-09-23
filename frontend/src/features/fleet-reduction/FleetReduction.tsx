import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { GradeBadge } from '../../components/GradeBadge'
import { VerdictStrip } from '../../components/VerdictStrip'
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
 * ## 분할하지 않는다 (`DESIGN_SYSTEM §7.1` v2.25 · `UIFLOW 2-10` · #1756 · #1757)
 *
 * 결론(「목표 달성 n / m척」)은 `§8.6` 결론 띠가 가져가고, 그 아래는 **선박별 조정 표 하나가
 * 전폭**이다. 종전의 7:5 두 단(오른쪽 기둥에 상태 · 비용 · 단가 · 저장)은 `#1757`이 걷었다 —
 * 결론이 띠로 올라가면 나란히 둘 부(副)가 없기 때문이다. 분할하지 않으므로 전환점도 없고,
 * 좁아지면 표가 제자리에서 가로로 스크롤한다. 근거와 표 최소 폭(760 실측)은 `FleetReduction.css`,
 * 분할이 되살아나지 않는지는 `layout.sync.test.ts`가 본다 (#1785).
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
  const { years, loading: yearsLoading } = useYearOptions(FLEET_KEY, { throughCurrentYear: true })
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
  /*
   * 연료 단가 접기 (#1757). 값이 잘못된 동안에는 **스스로 펼친다** — 접힌 채로 두면
   * 오류가 보이지 않는데 저장 버튼만 잠긴다(`#1417`이 항로 비교의 「고급 설정」에서
   * 같은 판단을 했다).
   */
  const [pricesOpen, setPricesOpen] = useState(false)
  useEffect(() => {
    if (pricesInvalid) setPricesOpen(true)
  }, [pricesInvalid])

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

  /** 감속률을 한 칸이라도 움직였는가 — 상태 문장이 「아직」과 「모자람」을 가른다. */
  const adjusted = Object.values(percents).some((value) => value > 0)
  const filledFuelPrices = fuelCodes.filter(
    (code) => (prices.fuelUsdPerTon[code] ?? '').trim() !== '',
  ).length

  return (
    <section className="fr">
      {/*
        결론 띠 (#1757 · `§8.6` 🔒). 종전에는 이 답(「목표를 달성합니다」)이 오른쪽 기둥
        맨 위의 한 줄짜리 상태 문장이었고, 그 아래로 비용 · 단가 · 분포 · 저장이 네 장 더
        쌓여 **표보다 긴 기둥**이 됐다.
      */}
      {shown !== null ? <FleetVerdict result={shown} adjusted={adjusted} /> : null}

      {/*
        `PRD §6.3` 결정론 안내 — 띠 묶음(띠 · 상태 문장 · 2열 목록) **바로 아래 한 줄**이다
        (`§8.6` · `§13` · `#1578`).

        **띠 안에 두지 않는다.** 이 문구는 계산 전 · 실패에도 보여야 한다 — 연간 등급 관리와
        값이 다르게 보이는 이유를 말하는 자리라, 결과가 없을 때 사라지면 그때 들어온 사용자가
        두 화면 중 하나가 틀렸다고 읽는다(`UIFLOW 2-10`).

        색 띠를 걷었다 — 바로 위 상태 문장이 그 자리를 쓰고, 색 띠가 둘이면 어느 쪽이 상태인지
        가려진다(`§2.3` 경고색은 한 자리에 한 번).
      */}
      <p className="fr__notice">{COPY.deterministicNotice}</p>

      {/*
        도구 줄 (#1757). 연도 · 목표 · 연료 단가 · 계획 저장을 표 위 한 줄에 모은다.
        **면을 띄우지 않는다** — 조건을 다루는 자리는 「한 덩어리의 데이터」가 아니다
        (`§5` 카드 예산). 단가 · 저장은 접어 두고 쓸 때만 편다.
      */}
      <div className="fr__tools">
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

        {/*
          채운 칸 수를 접힌 겉에 적는다 (`#1417`과 같은 판단) — 안에 값이 들어 있는데
          겉에서 안 보이면 사용자는 단가 없이 계산했다고 믿는다. 값이 잘못된 동안에는
          **스스로 펼친다**: 접힌 채로는 오류가 보이지 않는다.
        */}
        <details
          className="fr__tool"
          open={pricesOpen}
          onToggle={(e) => setPricesOpen(e.currentTarget.open)}
        >
          <summary>
            {COPY.fuelPricesTitle}
            {fuelCodes.length > 0 ? (
              <span className="fr__tool-count">{` · ${filledFuelPrices} / ${fuelCodes.length} 입력함`}</span>
            ) : null}
          </summary>
          <div className="fr__tool-body">
            <p className="fr__caption">{COPY.pricesNote}</p>
            {/* 어느 연료가 필요한지 서버가 말하기 전과 「필요 없음」을 가른다 (`#1273`). */}
            {fuelCodes.length === 0 ? (
              <p className="fr__muted">{shown ? COPY.fuelPricesNone : COPY.fuelPricesBeforeRun}</p>
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
          </div>
        </details>

        <details className="fr__tool">
          <summary>{COPY.saveTitle}</summary>
          <div className="fr__tool-body">
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
                 * 단가 오류는 **다른 접기(연료 단가)에 있다** — 이 버튼 옆에서는
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
                    {plans.map((pl) => (
                      <option key={pl.planId} value={pl.planId}>
                        {pl.planName}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
          </div>
        </details>
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
        <>
          {/*
            표는 전폭이다 (#1757 · `§7.1` v2.25 「분할하지 않는 화면이 있다」). 결론이 띠로
            올라가면 이 화면의 주 내용은 표 하나뿐이라 나란히 둘 부(副)가 없다 — 전환점도
            없앴다(종전 1734 이하 1단).
          */}
          <section className="card fr__table-card" aria-labelledby="fr-vessels-title">
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

          <Distribution result={shown} />
        </>
      ) : null}
    </section>
  )
}

/* ------------------------------------------------------------------ */

/** 값이 없을 때 — 0으로 지어내지 않는다. */
const NO_VALUE = '—'

/**
 * 결론 띠 — `§8.6` 🔒 표의 「함대 감축 계획」 행 (#1757).
 *
 * ## 주 결론은 척수다
 *
 * 이 화면의 답은 「목표를 몇 척이 달성하는가」 하나다. 등급 배지는 붙지 않는다 — 답이
 * 등급이 아니다(연간 등급 관리의 「목표 달성 확률」과 같은 꼴).
 *
 * **분모는 계산할 수 있는 선박이다.** `unavailableReason`이 있는 선박은 `meetsTarget`이
 * `null`이라 분자에도 분모에도 넣지 않는다 — 「계산하지 못함」을 「달성하지 못함」으로
 * 세면 사용자가 손댈 수 없는 이유로 숫자가 나빠진다. 셀 수 있는 선박이 0척이면 척수
 * 대신 `—`를 두고 그 사실을 아래 줄이 말한다.
 *
 * ## 위험도 pill은 두지 않는다
 *
 * 이 화면의 데이터에 위험도 값이 없다 — `§8.6` v2.23이 「값이 있을 때만 둔다」로 정했고
 * 다른 경로를 더 불러 채우지 않는다 (#1728).
 *
 * ## 보조는 순손익 하나다
 *
 * 추가 항해일 · 용선료 손실 · 연료비 절감은 **띠 아래 2열 「라벨 · 값」 목록**이다
 * (`§8.6` v2.25 · #1756). 종전에는 그 넷이 「비용 요약」 카드 한 장이었다.
 */
function FleetVerdict({ result, adjusted }: { result: EvaluateResult; adjusted: boolean }) {
  const counted = result.vessels.filter((vessel) => vessel.meetsTarget !== null)
  const met = counted.filter((vessel) => vessel.meetsTarget).length
  const costs = result.costs

  return (
    <>
      <VerdictStrip
        label={`${TARGET_TEXT[result.target]} 달성 현황`}
        main={{
          label: `${TARGET_TEXT[result.target]} 달성`,
          value: counted.length === 0 ? NO_VALUE : `${met} / ${counted.length}`,
          unit: counted.length === 0 ? undefined : '척',
        }}
        /*
         * ⚠️ 단가가 비면 **0이 아니라 「단가 입력 필요」다** (`PRD §12.3.2`). 0으로 두면
         * 「손익 영향 없음」으로 읽힌다 — 표 아래 `Money`가 쓰는 문구를 그대로 쓴다.
         */
        sub={{
          label: COPY.net,
          value: costs.net === null ? COPY.needsPrice : formatGrouped(costs.net, 0),
          unit: costs.net === null ? undefined : 'USD',
        }}
      />
      <Status result={result} adjusted={adjusted} />
      <dl className="fr__costs">
        <div>
          <dt>{COPY.extraDays}</dt>
          <dd className="fr__num">{costs.extraDays}일</dd>
        </div>
        <div>
          <dt>{COPY.charterLoss}</dt>
          <dd>
            <Money value={costs.charterLoss} />
          </dd>
        </div>
        <div>
          <dt>{COPY.fuelSaving}</dt>
          <dd>
            <Money value={costs.fuelSaving} />
          </dd>
        </div>
      </dl>
    </>
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
    <p className={`fr__status fr__status--${tone}`} role="status">
      <strong>{TARGET_TEXT[result.target]}</strong> — {text}
    </p>
  )
}

function Money({ value }: { value: string | null }) {
  if (value === null) return <span className="fr__muted">{COPY.needsPrice}</span>
  return <span className="fr__num">{formatGrouped(value, 0)} USD</span>
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
