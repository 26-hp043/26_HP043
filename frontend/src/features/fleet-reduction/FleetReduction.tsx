import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ApplicabilityBadge } from '../../components/ApplicabilityBadge'
import { ErrorState } from '../../components/ErrorState'
import { Field } from '../../components/Field'
import { GradeBadge } from '../../components/GradeBadge'
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  currentKstYear,
  formatDecimalString,
  formatGrouped,
  formatTimestamp,
} from '../../display/format'
import { warningMessage } from '../voyage-cii/resultRules'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { fuelTypeText } from '../parameters/fuelTypes'
import { useYearOptions, yearStateText } from '../parameters/yearCatalog'
import { createApiFleetReductionProvider } from './apiProvider'
import { hasAnyPrice, hasInvalidPrice, hasVisiblePrice, isInvalidPrice } from './priceRules'
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
type EvalState = {
  result: EvaluateResult | null
  error: string | null
  /**
   * 마지막으로 응답(성공·실패)을 받은 요청과 그때의 재시도 횟수 — 지금 것과 다르면 응답을 기다리는 중이다 (#2120).
   * 「다시 시도」는 요청이 같으므로 횟수까지 대조해야 재시도 중이 잡힌다.
   */
  settledFor: { request: object; retryKey: number } | null
}

const EMPTY_PRICES: Prices = { charterUsdPerDay: {}, fuelUsdPerTon: {} }

export function FleetReduction({ provider }: { provider?: FleetReductionProvider }) {
  const api = useMemo(() => provider ?? createApiFleetReductionProvider(), [provider])
  const yearOptions = useYearOptions(FLEET_KEY, { throughCurrentYear: true })
  const { years, loading: yearsLoading } = yearOptions
  /** 목록이 없으면 연도 칸 자리에 보일 상태 문구 — 로딩·실패·빈 목록이 서로 다르다 (#2120). */
  const yearText = yearStateText(yearOptions)
  /** 사용자가 고른 해(저장한 계획을 불러온 해 포함). 화면에 쓰는 값은 아래 `year`다 — 목록과 대조해 렌더 중에 정한다. */
  const [chosenYear, setChosenYear] = useState('')
  const [target, setTarget] = useState<Target>('NO_AT_RISK')
  const [percents, setPercents] = useState<Record<string, number>>({})
  const [prices, setPrices] = useState<Prices>(EMPTY_PRICES)
  /*
   * 원화 환산 환율 (10/7) — 비용은 서버가 USD로 계산한다. 한국 사용자가 읽기 쉽게 원화를 곁에
   * 적되, 환율은 **사용자가 넣은 값**만 쓴다(화면이 시세를 지어내지 않는다). 계획 저장 계약에는
   * 없는 값이라 이 브라우저에만 기억한다.
   */
  const [krwPerUsd, setKrwPerUsd] = useState(() => {
    try {
      return window.localStorage.getItem(KRW_RATE_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [evaluation, setEvaluation] = useState<EvalState>({ result: null, error: null, settledFor: null })
  const [retryKey, setRetryKey] = useState(0)
  const [plans, setPlans] = useState<SavedPlanSummary[]>([])
  const [plansFailed, setPlansFailed] = useState(false)
  const [plansKey, setPlansKey] = useState(0)
  const [planName, setPlanName] = useState('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const pricesSeeded = useRef(false)
  /**
   * 지금 단가 칸이 **이어받은 그대로**라면 그 출처 계획 (#2020). 사용자가 한 칸이라도 고치거나,
   * 저장한 계획을 불러오거나, 이 단가로 새 계획을 저장하면 `null`이다 — 그때부터 칸의 값은
   * 이어받은 것이 아니라 사용자가 정한(또는 연) 계획의 가정이다. 고친 값을 원래대로 되돌려도
   * 복원하지 않는다 — 결정(#2020 ②)이 「고치면 내린다」이고, 한 번 손댄 값은 사용자가 확인한 값이다.
   */
  const [inheritedFrom, setInheritedFrom] = useState<SavedPlanSummary | null>(null)

  /*
   * 기본 연도는 **렌더 중에 파생**한다 (`#1616` · `DataQuality`와 같은 형태). 종전에는
   * 목록이 오면 effect가 상태를 채워, 목록 도착과 기본값 사이에 연도가 빈 렌더가 한 번
   * 있었다. 목록이 비어 있으면 `''`이고 그때는 요청을 보내지 않는다(아래 `request` · 평가 효과 · `save`) — 기기 시계의 해로 대신 계산하지 않는다(#2120).
   * 고른 해가 목록에 없으면(예: 불러온 계획의 해) 올해로 떨어진다 — 셀렉트가 보여 주는
   * 값과 요청에 실리는 값이 늘 같다.
   */
  const year = pickDefaultYear(years, currentKstYear(), chosenYear)

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
          // 단가 없이 저장한 계획이면 이어받은 값이 없다 — 「이어받았습니다」를 적지 않는다.
          if (hasAnyPrice(rows[0].prices)) setInheritedFrom(rows[0])
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
      regulationYear: Number(year),
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
    // oxlint-disable-next-line react/set-state-in-effect -- 값이 잘못되는 시점에 한 번 펼치는 동기화 — 그 뒤 접힘은 사용자 몫이라 파생값으로 둘 수 없다
    if (pricesInvalid) setPricesOpen(true)
  }, [pricesInvalid])

  useEffect(() => {
    if (yearsLoading) return
    // 연도를 못 골랐으면(목록 실패·빈 목록) 값을 지어내 묻지 않는다 (#2120).
    if (year === '') return
    // 잘못된 단가로는 묻지 않는다 — 칸에 오류를 보이고 마지막 결과를 그대로 둔다.
    if (pricesInvalid) return
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .evaluate(request)
        .then((result) => {
          if (!cancelled) setEvaluation({ result, error: null, settledFor: { request, retryKey } })
        })
        .catch((error: unknown) => {
          if (cancelled) return
          setEvaluation((prev) => ({
            result: prev.result,
            error: error instanceof Error ? error.message : COPY.evaluateFailed,
            settledFor: { request, retryKey },
          }))
        })
    }, EVALUATE_DELAY_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [api, request, year, yearsLoading, pricesInvalid, retryKey])

  const shown = evaluation.result

  /*
   * 표의 줄 순서는 **연도 · 목표 · 선박 구성이 바뀔 때만** 다시 정한다 (#2345).
   *
   * 미달 선박을 위로 올리는 정렬(10/7 시안 04)을 계산이 돌 때마다 다시 하면, 감속률을 올려 그
   * 배가 목표를 넘는 순간 줄이 **아래로 뛰어** 잡고 있던 슬라이더가 손에서 빠진다. 「손볼 배부터」는
   * 조건을 처음 고른 시점의 판단으로 충분하고, 조정 중에는 줄이 제자리에 있어야 한다.
   * 렌더 중 파생(`#1616`)이라 effect를 쓰지 않는다 — 키가 바뀐 렌더에서 한 번 상태를 고친다.
   */
  const orderKey =
    shown === null ? null : `${year}|${target}|${shown.vessels.map((v) => v.vesselId).join(',')}`
  const [rowOrder, setRowOrder] = useState<{ key: string | null; ids: readonly string[] }>({
    key: null,
    ids: [],
  })
  if (shown !== null && rowOrder.key !== orderKey) {
    setRowOrder({
      key: orderKey,
      ids: [...shown.vessels]
        .sort((a, b) => Number(b.meetsTarget === false) - Number(a.meetsTarget === false))
        .map((v) => v.vesselId),
    })
  }
  const orderedVessels =
    shown === null
      ? []
      : rowOrder.key === orderKey
        ? rowOrder.ids
            .map((id) => shown.vessels.find((v) => v.vesselId === id))
            .filter((v): v is VesselResult => v !== undefined)
        : shown.vessels
  /**
   * 재계산 중 (#2120) — 지금 입력의 응답이 아직 오지 않았다. 이 동안 `shown`은 **이전 입력의 결과**다.
   * 응답을 받은 요청과 지금 요청을 대조한다(성공·실패 모두 `settledFor`를 채운다).
   * 잘못된 단가는 요청을 보내지 않으므로 기다릴 응답이 없다.
   */
  const pending =
    year !== '' &&
    !pricesInvalid &&
    (evaluation.settledFor?.request !== request || evaluation.settledFor.retryKey !== retryKey)

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
    if (name === '' || pricesInvalid || year === '' || pending) return
    setSaving(true)
    setSaveMessage(null)
    try {
      const saved = await api.save({ ...request, planName: name })
      setPlans((prev) => [saved, ...prev])
      setInheritedFrom(null)
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
    setChosenYear(String(plan.regulationYear))
    setTarget(plan.target)
    setPercents(Object.fromEntries(plan.adjustments.map((a) => [a.vesselId, a.percent])))
    setPrices(plan.prices)
    // 불러오기는 그 계획을 연 것이다 — 단가도 그 계획 자신의 가정이지 이어받은 값이 아니다.
    setInheritedFrom(null)
  }

  /** 단가 칸을 고친다 — 고친 순간부터 칸의 값은 이어받은 것이 아니다 (#2020). */
  const editPrices = (update: (prev: Prices) => Prices) => {
    setInheritedFrom(null)
    setPrices(update)
  }

  /** 감속률을 한 칸이라도 움직였는가 — 상태 문장이 「아직」과 「모자람」을 가른다. */
  const adjusted = Object.values(percents).some((value) => value > 0)
  const filledFuelPrices = fuelCodes.filter(
    (code) => (prices.fuelUsdPerTon[code] ?? '').trim() !== '',
  ).length

  return (
    <section className={pending && shown !== null ? 'fr fr--stale' : 'fr'} aria-busy={pending}>
      {/*
        결론 띠 (#1757 · `§8.6` 🔒). 종전에는 이 답(「목표를 달성합니다」)이 오른쪽 기둥
        맨 위의 한 줄짜리 상태 문장이었고, 그 아래로 비용 · 단가 · 분포 · 저장이 네 장 더
        쌓여 **표보다 긴 기둥**이 됐다.
      */}
      {/* 10/7 시안 04 — 조건(연도 · 목표 · 단가 · 저장)을 결과보다 먼저 */}
      <div className="fr__tools">
        <Field id="fr-year" label={COPY.yearLabel}>
          {(control) => (
            yearText !== null ? (
              // 라벨이 가리키는 id를 문구가 받는다 — 셀렉트가 없을 때 라벨이 허공을 가리키지 않게.
              <span id={control.id} className="fr__hint">{yearText}</span>
            ) : (
              <select
                {...control}
                className="fr__control"
                value={year}
                onChange={(e) => setChosenYear(e.target.value)}
              >
                {years.map((y) => (
                  <option key={y} value={String(y)}>
                    {y}
                  </option>
                ))}
              </select>
            )
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
            <p className="fr__caption">{COPY.pricesNote} 환율은 비용을 원화로도 적는 데만 쓰며 이 브라우저에만 기억합니다.</p>
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
                    label={fuelTypeText(code)}
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
                          editPrices((prev) => ({
                            ...prev,
                            fuelUsdPerTon: { ...prev.fuelUsdPerTon, [code]: e.target.value },
                          }))
                        }
                      />
                    )}
                  </Field>
                )
              })}
              <Field id="fr-krw-rate" label="환율 (원/USD)">
                {(control) => (
                  <input
                    {...control}
                    className="fr__control"
                    type="number"
                    min={0}
                    inputMode="decimal"
                    value={krwPerUsd}
                    onChange={(e) => {
                      setKrwPerUsd(e.target.value)
                      try {
                        window.localStorage.setItem(KRW_RATE_KEY, e.target.value)
                      } catch {
                        // 기억하지 못해도 이번 화면에서는 그대로 쓴다.
                      }
                    }}
                  />
                )}
              </Field>
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
                disabled={saving || pending || year === '' || planName.trim() === '' || pricesInvalid}
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

      {shown !== null ? (
        <FleetVerdict
          result={shown}
          adjusted={adjusted}
          krwRate={validRate(krwPerUsd)}
          onOpenCharter={(vesselId) => {
            const input = document.querySelector<HTMLInputElement>(`[data-charter-for="${vesselId}"]`)
            input?.scrollIntoView({ block: 'center' })
            input?.focus()
          }}
          onOpenPrices={() => {
            setPricesOpen(true)
            requestAnimationFrame(() =>
              document.querySelector('.fr__tool[open] input')?.scrollIntoView({ block: 'center' }),
            )
          }}
        />
      ) : null}

      {/*
        `PRD §6.3` 결정론 안내 — 띠 묶음(띠 · 상태 문장 · 2열 목록) **바로 아래 한 줄**이다
        (`§8.6` · `§13` · `#1578`).

        **띠 안에 두지 않는다.** 이 문구는 계산 전 · 실패에도 보여야 한다 — 연간 등급 관리와
        값이 다르게 보이는 이유를 말하는 자리라, 결과가 없을 때 사라지면 그때 들어온 사용자가
        두 화면 중 하나가 틀렸다고 읽는다(`UIFLOW 2-10`).

        색 띠를 걷었다 — 바로 위 상태 문장이 그 자리를 쓰고, 색 띠가 둘이면 어느 쪽이 상태인지
        가려진다(`§2.3` 경고색은 한 자리에 한 번).
      */}

      {/*
        도구 줄 (#1757). 연도 · 목표 · 연료 단가 · 계획 저장을 표 위 한 줄에 모은다.
        **면을 띄우지 않는다** — 조건을 다루는 자리는 「한 덩어리의 데이터」가 아니다
        (`§5` 카드 예산). 단가 · 저장은 접어 두고 쓸 때만 편다.
      */}

      {/*
        이어받은 단가의 출처 (#2020). **접힌 연료 단가 안에 두지 않는다** — 이어받은 값은
        연료 단가(접힘)와 용선료(아래 표) 두 곳에 들어가고, 접힌 안쪽에만 적으면 표의 용선료를
        보는 사용자에게는 보이지 않는다. 안에 든 값을 겉에서 알 수 있어야 한다는 `#1417` ·
        `#1757`(채운 칸 수를 겉에 적는다)과 같은 판단이다.
      */}
      {inheritedFrom !== null &&
      shown !== null &&
      hasVisiblePrice(
        prices,
        shown.vessels.map((v) => v.vesselId),
      ) ? (
        <p className="fr__caption" role="status">
          {COPY.inheritedPrices(
            inheritedFrom.planName,
            inheritedFrom.createdAt === null ? null : formatTimestamp(inheritedFrom.createdAt),
          )}
        </p>
      ) : null}

      {/* 연도를 못 골랐으면 계산하지 않으므로 「계산하는 중」을 적지 않는다 — 연도 칸이 사유를 말한다. */}
      {pending ? (
        <p className="fr__placeholder" aria-live="polite">
          {COPY.loading}
        </p>
      ) : null}
      {/* 다시 묻는 동안에는 지난 실패를 보이지 않는다 — 지금 입력의 답이 아니다. */}
      {!pending && evaluation.error !== null ? (
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
                  {/* 미달 선박을 위로 (10/7 시안 04) — 순서는 조건을 고를 때 정하고 조정 중에는 고정 (#2345) */}
                  {orderedVessels.map((vessel) => (
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
                        editPrices((prev) => ({
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
          {/* 결정론 안내 (`PRD §6.3` · `UIFLOW 2-10`) — 결과 맨 아래 한 줄로 (10/7) */}
          <p className="fr__notice fr__notice--foot">{COPY.deterministicNotice}</p>
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
function FleetVerdict({
  result,
  adjusted,
  onOpenPrices,
  onOpenCharter,
  krwRate,
}: {
  result: EvaluateResult
  adjusted: boolean
  onOpenPrices: () => void
  /** 그 선박의 일일 용선료 칸으로 옮겨 초점을 준다. */
  onOpenCharter: (vesselId: string) => void
  /** 원/USD — 사용자가 넣었을 때만 원화를 곁에 적는다. */
  krwRate: number | null
}) {
  const counted = result.vessels.filter((vessel) => vessel.meetsTarget !== null)
  const met = counted.filter((vessel) => vessel.meetsTarget).length
  const missed = counted.filter((vessel) => vessel.meetsTarget === false)
  const cuts = missed.filter((v) => v.achievable !== false && v.requiredCutFuelTon)
  const cutTotal = cuts.length === 0 ? null : cuts.reduce((sum, v) => sum + Number(v.requiredCutFuelTon), 0)
  const costs = result.costs
  const netNumber = costs.net === null ? null : Number(costs.net)
  /*
   * 무엇이 비었는지를 말한다 (10/7) — 종전에는 연료 단가를 넣어도 일일 용선료가 비면 똑같이
   * 「단가 입력 필요」라, 사용자가 이미 넣은 칸을 다시 찾았다. 서버가 빈 것을 알려 준다
   * (`missing_charter_rates` 선박 ID · `missing_fuel_prices` 유종 · `API_SPEC §2.17.1`).
   */
  const missingCharterNames = costs.missingCharterRates.map(
    (id) => result.vessels.find((v) => v.vesselId === id)?.vesselName ?? id,
  )
  const missingFuel = costs.missingFuelPrices.length > 0
  const missingCharter = missingCharterNames.length > 0
  const needsText = missingFuel && missingCharter
    ? '연료 단가 · 일일 용선료 입력 필요'
    : missingFuel
      ? '연료 단가 입력 필요'
      : missingCharter
        ? '일일 용선료 입력 필요'
        : COPY.needsPrice

  /*
   * 10/7 디자인 결정 — **이 화면의 주인공은 비용이다.** 감속을 정하면 연료비가 얼마 줄고 용선료가
   * 얼마 나가는지, 그래서 남는 돈이 얼마인지가 이 화면에만 있는 답이다. 순손익을 가장 크게, 그
   * 내역(연료비 절감 · 용선료 손실 · 추가 항해일)을 바로 아래에 두고, 목표 달성 여부는 오른쪽에
   * 보조로 둔다. 단가가 비면 0이 아니라 「단가 입력 필요」이고(`PRD §12.3.2`), 그 자리에서 바로
   * 단가 칸을 연다.
   */
  return (
    <>
      <section className="fr-hero" aria-label={`비용과 ${TARGET_TEXT[result.target]} 달성 현황`}>
        <div className="fr-hero__cost">
          <span className="fr-hero__label">
            {COPY.net} <span className="fr-hero__formula">연료비 절감 − 용선료 손실</span>
          </span>
          {netNumber === null ? (
            <span className="fr-hero__value fr-hero__value--empty">
              {needsText}
              <button
                type="button"
                className="fr-hero__price-btn"
                onClick={() => (missingFuel || !missingCharter ? onOpenPrices() : onOpenCharter(costs.missingCharterRates[0]))}
              >
                {missingFuel || !missingCharter ? '연료 단가 입력' : '용선료 입력'}
              </button>
            </span>
          ) : null}
          {netNumber === null && missingCharter ? (
            <span className="fr-hero__note">
              일일 용선료가 빈 선박 — {missingCharterNames.join(', ')} · 아래 표 맨 오른쪽 칸
            </span>
          ) : null}
          {netNumber === null ? null : (
            <span className="fr-hero__value">
              {netNumber > 0 ? '+' : netNumber < 0 ? '−' : ''}
              {formatGrouped(String(Math.abs(netNumber)), 0)}
              <span className="fr-hero__unit">USD</span>
            </span>
          )}
          {netNumber !== null && krwRate !== null ? (
            <span className="fr-hero__krw">
              ≈ {netNumber < 0 ? '−' : netNumber > 0 ? '+' : ''}
              {krwText(Math.abs(netNumber) * krwRate)}
              <span className="fr-hero__krw-rate"> · 환율 {formatGrouped(String(krwRate), 0)}원/USD 기준</span>
            </span>
          ) : null}
          <dl className="fr-hero__breakdown">
            <div>
              <dt>{COPY.fuelSaving}</dt>
              <dd>
                <Money value={costs.fuelSaving} krwRate={krwRate} missingText="연료 단가 입력 필요" />
              </dd>
            </div>
            <div>
              <dt>{COPY.charterLoss}</dt>
              <dd>
                <Money value={costs.charterLoss} krwRate={krwRate} missingText="일일 용선료 입력 필요" />
              </dd>
            </div>
            <div>
              <dt>{COPY.extraDays}</dt>
              <dd className="fr__num">
                {formatDecimalString(costs.extraDays, DISPLAY_DIGITS.days)} {DISPLAY_UNITS.day}
              </dd>
            </div>
          </dl>
        </div>

        <div className="fr-hero__target">
          <span className="fr-hero__label">목표 · {TARGET_TEXT[result.target]}</span>
          {counted.length === 0 ? (
            <span className="fr-hero__status">{NO_VALUE}</span>
          ) : (
            <span className="fr-hero__status">
              {missed.length > 0 ? (
                <b className="fr-hero__missed">미달 {missed.length}척</b>
              ) : (
                <b>모두 충족</b>
              )}
              <span className="fr-hero__met"> · 충족 {met}척</span>
            </span>
          )}
          {missed.length > 0 ? (
            <span className="fr-hero__note">
              {missed.map((v) => `${v.vesselName}${v.after ? ` (연말 ${v.after.rating})` : ''}`).join(', ')}
            </span>
          ) : null}
          {cutTotal !== null ? (
            <span className="fr-hero__note">
              추가 감축 필요 <b>연료 {formatGrouped(String(cutTotal), DISPLAY_DIGITS.fuelTon)} {DISPLAY_UNITS.fuel}</b>
            </span>
          ) : missed.length > 0 ? (
            <span className="fr-hero__note">{COPY.unreachable}</span>
          ) : null}
        </div>
      </section>
      <Status result={result} adjusted={adjusted} />
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
    <tr className={vessel.meetsTarget === false ? 'fr__row--missed' : undefined}>
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
        {/*
          CII 적용 대상 배지 — 선박을 식별하는 자리마다 같은 배지를 둔다 (`#653` · `#2132` 결정 3).
          「위험 선박 0척」 목표에서 적용 대상이 아닌 선박은 E여도 「목표 달성」이다(`PRD §12.3.2`
          ⑸). 그 이유를 같은 행에서 읽게 한다. 적용 대상이면 아무것도 그리지 않는다.
          링크가 블록이라 배지는 이름 아래 줄에 놓인다 — 이름의 말줄임 폭을 빼앗지 않는다.
        */}
        <ApplicabilityBadge
          isCiiApplicableHint={vessel.isCiiApplicableHint}
          grossTonnage={vessel.grossTonnage}
          vesselName={vessel.vesselName}
        />
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
          {/*
            숫자로도 넣는다 (#2345) — 슬라이더만으로는 12.3%처럼 정한 값에 맞추기 어렵다. 값 자리는
            종전 `<output>`이 있던 **행 오른쪽 고정 위치** 그대로다(`§8` 🔒). 두 컨트롤은 같은 값을 쥔다.
          */}
          <PercentField
            id={`${sliderId}-number`}
            value={percent}
            disabled={unavailable}
            label={`${vessel.vesselName} ${COPY.colReduction} (%)`}
            onCommit={onPercent}
          />
        </div>
        {vessel.skippedVoyages > 0 ? (
          <p className="fr__hint">{COPY.skippedHint(vessel.skippedVoyages)}</p>
        ) : null}
      </td>
      {/* 일수 0자리 · 연료 1자리+천단위 · 단위는 `DISPLAY_UNITS` (`DESIGN_SYSTEM §4.2` · #1813) */}
      <td className="fr__num">
        {vessel.extraDays === null
          ? '—'
          : `${formatDecimalString(vessel.extraDays, DISPLAY_DIGITS.days)} ${DISPLAY_UNITS.day}`}
      </td>
      <td className="fr__num">
        {vessel.fuelSavedTon === null
          ? '—'
          : `${formatGrouped(vessel.fuelSavedTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`}
      </td>
      <td>
        <input
          className="fr__charter"
          data-charter-for={vessel.vesselId}
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
        ? COPY.cutHint(
            `${formatGrouped(vessel.requiredCutFuelTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`,
          )
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
/**
 * 감속률 숫자 칸 (#2345). 치는 동안(「12.」처럼 덜 친 값)은 글자 그대로 두고, 범위 안의 수가 되는
 * 순간 계산에 반영한다. 칸을 떠날 때 범위 밖이면 0 ~ `MAX_REDUCTION_PERCENT`로 맞추고 0.1 단위로
 * 반올림한다(슬라이더 `step`과 같은 `§4.2` 자릿수).
 */
function PercentField({
  id,
  value,
  disabled,
  label,
  onCommit,
}: {
  id: string
  value: number
  disabled: boolean
  label: string
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const clampRound = (n: number) =>
    Math.round(Math.min(MAX_REDUCTION_PERCENT, Math.max(0, n)) * 10) / 10
  return (
    <span className="fr__percent">
      <input
        id={id}
        className="fr__percent-input fr__num"
        type="number"
        inputMode="decimal"
        min={0}
        max={MAX_REDUCTION_PERCENT}
        step={0.1}
        value={draft ?? value.toFixed(1)}
        disabled={disabled}
        aria-label={label}
        onChange={(e) => {
          const raw = e.target.value
          setDraft(raw)
          const n = Number(raw)
          if (raw.trim() !== '' && Number.isFinite(n) && n >= 0 && n <= MAX_REDUCTION_PERCENT) {
            onCommit(Math.round(n * 10) / 10)
          }
        }}
        onBlur={() => {
          if (draft !== null) {
            const n = Number(draft)
            if (draft.trim() !== '' && Number.isFinite(n)) onCommit(clampRound(n))
          }
          setDraft(null)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
        }}
      />
      <span className="fr__percent-unit" aria-hidden="true">
        %
      </span>
    </span>
  )
}

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
  /*
   * 기준을 이 줄에 적는다 (#1593).
   *
   * `§8.6`이 **추정 고지는 띠 바로 아래 한 줄**로 정했고, 이 줄이 이미 그 자리다 —
   * 줄을 새로 만들지 않고 끝에 붙인다. 목표 이름을 이미 들고 있는 줄이라, 이름과
   * 기준이 **떨어지지 않는다**.
   *
   * 대시보드 쪽에는 더하지 않는다. 그 화면은 배너 바로 위 부제가 이미
   * 「{year}년 누적(YTD) 기준」을 말한다 — 실측하니 부제 아래끝 166, 배너 위끝 226으로
   * **60px 간격**이고 사이에 「기준 {시각}」 한 줄뿐이다(1440 · 1920 동일). 같은 말을
   * 한 화면에 두 번 두지 않는다.
   */
  return (
    <p className={`fr__status fr__status--${tone}`} role="status">
      <strong>{TARGET_TEXT[result.target]}</strong> — {text}{' '}
      <span className="fr__status-basis">{COPY.statusBasis}</span>
    </p>
  )
}

function Money({
  value,
  krwRate = null,
  missingText = COPY.needsPrice,
}: {
  value: string | null
  krwRate?: number | null
  missingText?: string
}) {
  if (value === null) return <span className="fr__muted">{missingText}</span>
  return (
    <>
      <span className="fr__num">{formatGrouped(value, 0)} USD</span>
      {krwRate !== null && Number.isFinite(Number(value)) ? (
        <span className="fr__krw">≈ {krwText(Math.abs(Number(value)) * krwRate)}</span>
      ) : null}
    </>
  )
}

const KRW_RATE_KEY = 'bluelog.fleetReduction.krwPerUsd'

/** 사용자가 넣은 환율 — 양수일 때만 쓴다. */
function validRate(text: string): number | null {
  const n = Number(text)
  return text.trim() !== '' && Number.isFinite(n) && n > 0 ? n : null
}

/**
 * 원화를 읽기 쉬운 단위로 (10/7) — 1억 이상은 「1억 7,145만 원」, 1만 이상은 「4,512만 원」 꼴로
 * 만 원 아래를 반올림한다. 환산값이라 원 단위까지 적으면 정밀해 보이기만 한다.
 */
function krwText(won: number): string {
  const man = Math.round(won / 10_000)
  if (man === 0) return `${Math.round(won).toLocaleString('ko-KR')}원`
  const eok = Math.floor(man / 10_000)
  const rest = man % 10_000
  if (eok === 0) return `${rest.toLocaleString('ko-KR')}만 원`
  return rest === 0 ? `${eok.toLocaleString('ko-KR')}억 원` : `${eok.toLocaleString('ko-KR')}억 ${rest.toLocaleString('ko-KR')}만 원`
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
