import { useEffect, useMemo, useState } from 'react'
import './ScenarioComparison.css'
import { useShellContext } from '../../layout/shellContext'
import {
  FIELD,
  NO_VESSEL_MESSAGE,
  initialFormState,
  toRequest,
  validateForm,
  type ComparisonFormState,
  type FormErrors,
} from './requestRules'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, formatGrouped, formatPercent } from '../../display/format'
import { ciiUnit, marginDisplay, riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import { ESTIMATE_NOTICE, NO_AUTO_DECISION_NOTICE } from './notices'
import { selectScenarioProvider } from './providerSelection'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { useYearOptions } from '../parameters/yearCatalog'
import { pickDefaultYear } from '../voyage-cii/formRules'
import { lowestSummary } from './comparisonRules'
import type { ScenarioComparisonResponse, ScenarioResult } from './types'

/**
 * 기능② 시나리오 비교 (#156).
 *
 * ## 추천하지 않는다 — `PRD §11.2`
 *
 * > 시스템은 `추천 시나리오`를 표시하지 않는다. 대신 각 지표별 최소값을
 * > **중립적으로** 표시한다.
 *
 * 종합 점수를 매기거나 하나를 강조하지 않는다. 지표마다 따로 최소값을 적고,
 * 어느 지표가 중요한지는 사용자가 정한다(`PRD §6.3` 「자동 결정 금지」).
 *
 * ## 조건 입력 폼 (#511)
 *
 * 종전에는 입력 폼 없이 `DEMO_REQUEST` 상수를 마운트 즉시 보냈다. 그 상수의
 * `vessel_id`(`…0003`)가 demo 고정표에 없어 **데모 모드에서 항로 비교가 아무 입력
 * 없이 언제나 실패**했다. 상수를 `…0001`로 바꾸면 이번에는 실 API가 422를 낸다
 * (그 배는 `reference_speed_kn`이 비어 있다) — 어느 쪽을 골라도 한쪽이 깨진다.
 *
 * 그래서 선박을 **provider의 목록**에서 읽고 조건을 사용자가 넣는다. 규칙은
 * `requestRules.ts`에 있다.
 *
 * `PRD §11.3`의 나머지 입력(현재 좌표·목적항 등)은 아직 `#139` 소관으로 남는다 —
 * 이 화면이 받는 것은 계산에 실제로 필요한 여섯 값이다.
 *
 * ## 표시 규칙은 기능①과 같다
 *
 * 자릿수·구분자는 `format.ts`, 단위·위험도·경고 문구는 `voyage-cii/resultRules.ts`를
 * 그대로 쓴다. 두 화면이 각자 규칙을 두면 한쪽만 정본을 따라가게 된다.
 */

/**
 * 비교 결과의 적재 상태.
 *
 * `idle`이 기본이다 — **마운트 시 계산을 걸지 않는다.** 사용자가 조건을 정하기
 * 전의 계산은 누구의 질문도 아니고, 실패하면 화면이 오류로 시작한다(#511).
 */
type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; response: ScenarioComparisonResponse }
  | { status: 'error'; message: string }

export function ScenarioComparison({
  onDisclaimer,
}: {
  /** 면책 배너는 페이지가 항상 렌더한다(`DESIGN_SYSTEM §13` 🔒). */
  onDisclaimer?: (text: string | undefined) => void
}) {
  // 화면은 provider가 어떻게 만들어지는지 알지 않는다 (#134). demo 갈래는 #542가
  // 없앴다.
  const provider = useMemo(() => selectScenarioProvider(), [])
  // 선택지도 같은 원칙이다 (#236). 계산은 서버로 가는데 선택지는 고정표에서 오는
  // 상태가 이번 결함의 뿌리였다 — 연료 축이 마지막 조각이었다 (#542 · #558).
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  // 선박 목록·선택은 **셸이 소유한다** (#484 · #535). 종전에는 이 화면이 목록을
  // 따로 조회하고 선택도 따로 들어, 상단바에서 배를 바꿔도 여기는 그대로였다.
  const shell = useShellContext()
  const { vesselsState, selectVesselId } = shell
  const vessels = vesselsState === 'loading' ? null : shell.vessels
  const catalogError = vesselsState === 'failed' ? '선박 목록을 불러오지 못했습니다.' : null

  const [form, setForm] = useState<ComparisonFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [state, setState] = useState<LoadState>({ status: 'idle' })

  /*
   * 규제연도 선택지 (`#632`).
   *
   * 종전에는 **이 화면만 자유 입력**이라 파라미터가 없는 해를 넣을 수 있었고, 그때
   * 서버가 `PARAMETER_ERROR`로 거부했다 — `#236`이 「선박·연도·연료」 세 축을 고치며
   * 연도만 유예했고, `#534`가 두 화면을 옮기며 이 화면을 빠뜨렸다.
   */
  const { years, loading: yearsLoading, failed: yearsFailed } = useYearOptions(form.vesselId)

  /*
   * 목록이 오면 기본 선택을 맞춘다. **이미 고른 해가 목록에 있으면 그대로 둔다** —
   * 사용자가 고른 값을 덮으면 폼이 스스로 되돌아간다.
   *
   * 올해를 **여기서 읽어** 순수 함수에 넘긴다. 함수 안에서 `new Date()`를 부르면
   * 테스트가 해를 고정할 수 없다 (`formRules.ts` 주석과 같은 이유).
   */
  useEffect(() => {
    if (years.length === 0) return
    const thisYear = new Date().getFullYear()
    setForm((prev) => {
      const next = pickDefaultYear(years, thisYear, prev.regulationYear)
      return next === prev.regulationYear ? prev : { ...prev, regulationYear: next }
    })
  }, [years])

  /**
   * 셸의 선택을 폼에 반영한다 (#535).
   *
   * **선택이 없을 때 임의로 고르지 않는다.** `#511`의 완료 기준이 「선박 미선택
   * 상태에서 에러 대신 입력 UI가 보인다」이므로, 고르지 않은 상태 자체가 이 화면의
   * 정상 상태다. 목록이 한 척뿐일 때만 미리 채운다 — 고를 것이 없기 때문이다.
   */
  const shellVesselId = shell.vesselId
  useEffect(() => {
    if (shellVesselId !== null) {
      setForm((prev) => (prev.vesselId === shellVesselId ? prev : { ...prev, vesselId: shellVesselId }))
      return
    }
    if (vessels !== null && vessels.length === 1) selectVesselId(vessels[0].id)
  }, [shellVesselId, vessels, selectVesselId])

  const runComparison = () => {
    const found = validateForm(form, fuels)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      return
    }
    setErrors({})
    setState({ status: 'loading' })
    provider.compare(toRequest(form, fuels)).then(
      (response) => {
        setState({ status: 'success', response })
        onDisclaimer?.(response.disclaimer)
      },
      (error: unknown) => {
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '비교에 실패했습니다.',
        })
      },
    )
  }

  const noVessel = vessels !== null && vessels.length === 0

  const conditionForm = (
    <form
      className="scenario-comparison__form"
      onSubmit={(event) => {
        event.preventDefault()
        runComparison()
      }}
    >
      <h3 className="scenario-comparison__form-title">
        비교 조건
        <span className="scenario-comparison__form-title-en"> Comparison Input</span>
      </h3>
      {catalogError !== null && (
        <p className="scenario-comparison__error-message" role="alert">
          {catalogError}
        </p>
      )}
      {noVessel && (
        <p className="scenario-comparison__error-message" role="status">
          {NO_VESSEL_MESSAGE}
        </p>
      )}

      <label className="scenario-comparison__field">
        <span>선박</span>
        <select
          value={form.vesselId}
          onChange={(e) => selectVesselId(e.target.value || null)}
          disabled={vessels === null || noVessel}
          aria-invalid={FIELD.vesselId in errors}
        >
          <option value="">{vessels === null ? '불러오는 중…' : '선택'}</option>
          {(vessels ?? []).map((option) => (
            <option key={option.id} value={option.id}>
              {option.displayName}
            </option>
          ))}
        </select>
        {errors[FIELD.vesselId] !== undefined && (
          <span className="scenario-comparison__field-error">{errors[FIELD.vesselId]}</span>
        )}
      </label>

      {/*
        * 규제연도 — 다른 두 화면과 같은 규칙 (`#632`).
        * 로딩·실패를 **빈 선택지와 구분해** 보인다. 셋을 한 문구로 뭉치면
        * 「목록이 아직 안 왔다」와 「등록된 해가 없다」를 사용자가 가를 수 없다.
        */}
      <label className="scenario-comparison__field">
        <span>규제연도</span>
        {yearsLoading ? (
          <span className="scenario-comparison__field-note">규제연도 목록을 불러오는 중…</span>
        ) : yearsFailed ? (
          <span className="scenario-comparison__field-note">규제연도 목록을 불러오지 못했습니다</span>
        ) : years.length > 0 ? (
          <select
            value={form.regulationYear}
            onChange={(e) => setForm({ ...form, regulationYear: e.target.value })}
            aria-invalid={FIELD.regulationYear in errors}
          >
            {years.map((year) => (
              <option key={year} value={String(year)}>
                {year}
              </option>
            ))}
          </select>
        ) : (
          <span className="scenario-comparison__field-note">등록된 규제연도가 없습니다</span>
        )}
        {errors[FIELD.regulationYear] !== undefined && (
          <span className="scenario-comparison__field-error">
            {errors[FIELD.regulationYear]}
          </span>
        )}
      </label>

      <label className="scenario-comparison__field">
        <span>직항 거리 ({DISPLAY_UNITS.distance})</span>
        <input
          inputMode="decimal"
          value={form.baseDistanceNm}
          onChange={(e) => setForm({ ...form, baseDistanceNm: e.target.value })}
          aria-invalid={FIELD.baseDistanceNm in errors}
        />
        {errors[FIELD.baseDistanceNm] !== undefined && (
          <span className="scenario-comparison__field-error">
            {errors[FIELD.baseDistanceNm]}
          </span>
        )}
      </label>

      <label className="scenario-comparison__field">
        <span>현재 속력 ({DISPLAY_UNITS.speed})</span>
        <input
          inputMode="decimal"
          value={form.baseSpeedKn}
          onChange={(e) => setForm({ ...form, baseSpeedKn: e.target.value })}
          aria-invalid={FIELD.baseSpeedKn in errors}
        />
        {errors[FIELD.baseSpeedKn] !== undefined && (
          <span className="scenario-comparison__field-error">
            {errors[FIELD.baseSpeedKn]}
          </span>
        )}
      </label>

      <label className="scenario-comparison__field">
        {/* 선박 등록 화면과 **같은 필드인데 단위가 갈려 있었다** — 이쪽은 `(t)`,
            저쪽은 `t/일`. `§4.2`에 「일수」가 없어 각자 정한 결과다 (#592). */}
        <span>
          기준 일일 연료소모량 ({DISPLAY_UNITS.fuel}/{DISPLAY_UNITS.day})
        </span>
        <input
          inputMode="decimal"
          value={form.baseDailyFocTon}
          onChange={(e) => setForm({ ...form, baseDailyFocTon: e.target.value })}
          aria-invalid={FIELD.baseDailyFocTon in errors}
        />
        {errors[FIELD.baseDailyFocTon] !== undefined && (
          <span className="scenario-comparison__field-error">
            {errors[FIELD.baseDailyFocTon]}
          </span>
        )}
        {/*
          `PRD §11.4` 우선순위 ⑴이 이 칸이다. 선박에 `reference_daily_foc_ton`이
          없어도 여기 값을 넣으면 계산된다 — 데모 선박 4척이 모두 그 상태다.
        */}
        <span className="scenario-comparison__field-hint">
          선박 정보에 이 값이 없어도 여기 입력한 값으로 계산합니다.
        </span>
      </label>

      <label className="scenario-comparison__field">
        <span>연료 종류</span>
        <select
          value={form.fuelType}
          onChange={(e) => setForm({ ...form, fuelType: e.target.value })}
          aria-invalid={FIELD.fuelType in errors}
          disabled={fuelsLoading || fuelsFailed}
        >
          {/* 로딩·실패를 「선택」과 구분해 보인다 — 빈 목록과 못 불러온 것은 다른 상태다 (#542) */}
          <option value="">
            {fuelsLoading
              ? '연료 목록을 불러오는 중…'
              : fuelsFailed
                ? '연료 목록을 불러오지 못했습니다'
                : '선택'}
          </option>
          {fuels.map((fuel) => (
            <option key={fuel.code} value={fuel.code}>
              {fuelTypeOptionText(fuel.code)}
            </option>
          ))}
        </select>
        {errors[FIELD.fuelType] !== undefined && (
          <span className="scenario-comparison__field-error">{errors[FIELD.fuelType]}</span>
        )}
      </label>

      <div className="scenario-comparison__form-actions">
        <button
          type="submit"
          className="scenario-comparison__submit"
          disabled={state.status === 'loading' || noVessel}
        >
          {state.status === 'loading' ? '계산 중…' : '비교하기'}
        </button>
      </div>
    </form>
  )

  if (state.status !== 'success') {
    return (
      <section className="scenario-comparison">
        {conditionForm}
        {/*
          결과가 없을 때도 오른쪽 단을 비워 두지 않는다. 빈 칸으로 두면 화면이
          고장 난 것처럼 보이고, 계산 후에 폼이 옆으로 밀리는 것처럼도 읽힌다.
          `2-1 CII 예측`의 `VoyageCiiResult`가 idle에 자리표시자를 두는 것과 같다.
        */}
        <div className="scenario-comparison__results">
          {state.status === 'idle' && (
            <p className="scenario-comparison__placeholder">
              비교 조건을 입력하고 <strong>비교하기</strong>를 누르면 결과가 표시됩니다.
            </p>
          )}
          {state.status === 'loading' && (
            <p className="scenario-comparison__placeholder" aria-live="polite">
              시나리오를 계산하는 중입니다…
            </p>
          )}
          {state.status === 'error' && (
            <div className="scenario-comparison__error" aria-live="assertive">
              <p className="scenario-comparison__error-title">비교에 실패했습니다</p>
              <p className="scenario-comparison__error-message">{state.message}</p>
            </div>
          )}
        </div>
      </section>
    )
  }

  const { response } = state
  const unit = ciiUnit(response.transport_capacity_basis)
  const summary = lowestSummary(response.scenarios)
  const nameOf = (type: string | null) =>
    response.scenarios.find((s) => s.scenario_type === type)?.scenario_name ?? '—'

  return (
    <section className="scenario-comparison">
      {/* 결과를 본 뒤 조건을 바꿔 다시 비교할 수 있어야 한다 — 폼을 남긴다. */}
      {conditionForm}
      {/*
        결과 전체를 한 겹으로 묶는다. 묶지 않으면 12컬럼 자동 배치가 `__header`만
        폼 옆에 올리고 `__notice`부터는 아래 줄로 흘려보낸다 — 결과가 두 단에
        걸쳐 쪼개진다.
      */}
      <div className="scenario-comparison__results">
        <header className="scenario-comparison__header">
          <h2 className="scenario-comparison__title">
            시나리오 비교
            <span className="scenario-comparison__title-en"> Scenario Comparison</span>
          </h2>
          <p className="scenario-comparison__context">
            {response.vessel_display_name} · {form.regulationYear}년 기준 ·
            기준 CII {formatDecimalString(response.required_cii, DISPLAY_DIGITS.cii)} {unit}
          </p>
        </header>

        {/* PRD §6.3 — 「추정값 사용」·「자동 결정 금지」 문구를 그대로 쓴다 */}
        <p className="scenario-comparison__notice">
          {ESTIMATE_NOTICE} {NO_AUTO_DECISION_NOTICE}
        </p>

        <div className="scenario-comparison__cards">
          {response.scenarios.map((scenario) => (
            <ScenarioCard key={scenario.scenario_type} scenario={scenario} unit={unit} />
          ))}
        </div>

        {/*
          PRD §11.2 — 추천 시나리오를 표시하지 않고 지표별 최소값만 중립적으로 적는다.
          하나를 고르지 않으므로 세 줄의 답이 서로 다를 수 있다.
        */}
        <dl className="scenario-comparison__lowest">
          {summary.map((item) => (
            <div key={item.metric} className="scenario-comparison__lowest-row">
              <dt>{item.label}</dt>
              <dd>{nameOf(item.scenarioType)}</dd>
            </div>
          ))}
        </dl>

        {response.warnings.length > 0 ? (
          <ul className="scenario-comparison__warnings">
            {response.warnings.map((code) => (
              <li key={code} className="scenario-comparison__warning">
                <span aria-hidden="true">⚠</span> {warningMessage(code)}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */

function ScenarioCard({ scenario, unit }: { scenario: ScenarioResult; unit: string }) {
  const margin = marginDisplay(
    scenario.estimated_rating,
    scenario.next_worse_boundary_margin_ratio,
  )
  const risk = riskLabel(scenario.risk_level)

  return (
    <article className="scenario-card">
      <header className="scenario-card__head">
        <div>
          <p className="scenario-card__name">{scenario.scenario_name}</p>
          <p className="scenario-card__type">{scenario.scenario_type}</p>
        </div>
        <GradeBadge
          rating={scenario.estimated_rating}
          label={`${scenario.scenario_name} 참고 등급 ${scenario.estimated_rating}`}
          size="sm"
        />
      </header>

      <p className="scenario-card__cii">
        {formatDecimalString(scenario.attained_cii, DISPLAY_DIGITS.cii)}
        <span className="scenario-card__cii-unit"> {unit}</span>
      </p>

      <p className="scenario-card__margin">{margin.text}</p>

      <p className="scenario-card__risk">
        <span className="scenario-card__risk-label">위험도</span>
        {risk.withIcon ? (
          // §2.5 (b) — 라벨이 항상 옆에 있으므로 aria-hidden
          <span className="scenario-card__risk-icon" aria-hidden="true">
            ⚠
          </span>
        ) : null}
        <span
          className={`scenario-card__risk-value scenario-card__risk-value--${scenario.risk_level.toLowerCase()}`}
        >
          {risk.text}
        </span>
      </p>

      <dl className="scenario-card__rows">
        <Row label="항해거리" value={formatGrouped(String(scenario.distance_nm), DISPLAY_DIGITS.distanceNm)} unit={DISPLAY_UNITS.distance} />
        <Row label="평균 속력" value={String(scenario.speed_kn)} unit={DISPLAY_UNITS.speed} />
        <Row label="예상 소요시간" value={formatDecimalString(scenario.duration_hours, DISPLAY_DIGITS.durationHours)} unit={DISPLAY_UNITS.duration} />
        <Row label="예상 연료" value={formatGrouped(scenario.fuel_ton, DISPLAY_DIGITS.fuelTon)} unit={DISPLAY_UNITS.fuel} />
        <Row label="CO₂ 배출량" value={formatGrouped(scenario.co2_emission_ton, DISPLAY_DIGITS.co2Ton)} unit={DISPLAY_UNITS.co2} />
        <Row label="기준 대비" value={`${formatPercent(scenario.ratio_to_required)}%`} />
      </dl>
    </article>
  )
}

function Row({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="scenario-card__row">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit ? <span className="scenario-card__row-unit"> {unit}</span> : null}
      </dd>
    </div>
  )
}
