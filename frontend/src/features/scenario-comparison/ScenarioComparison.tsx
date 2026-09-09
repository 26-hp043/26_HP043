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
import {
  DISPLAY_DIGITS,
  DISPLAY_UNITS,
  formatDecimalString,
  formatGrouped,
  formatPercent,
  toDecimalInput,
} from '../../display/format'
import { ciiUnit, marginDisplay, riskLabel, warningMessage } from '../voyage-cii/resultRules'
import { GradeBadge } from '../../components/GradeBadge'
import { ESTIMATE_NOTICE, NO_AUTO_DECISION_NOTICE } from './notices'
import { selectScenarioProvider } from './providerSelection'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { useYearOptions } from '../parameters/yearCatalog'
import { pickDefaultYear, sameInputs } from '../voyage-cii/formRules'
import {
  deltaFromDirect,
  isZeroDelta,
  lowestSummary,
  type ScenarioDelta,
} from './comparisonRules'
import { ScenarioRouteGlyph } from './ScenarioRouteGlyph'
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
 * `PRD §11.3`의 나머지 입력(우회 거리·감속 속력·기상 모델·현재 좌표·목적항)은
 * `#892` 소관으로 남는다 — 이 화면이 받는 것은 계산에 실제로 필요한 여섯 값이다.
 * 종전 주석이 가리키던 `#139`는 2026-08-16에 닫혔고, 그 뒤로 **열린 추적처가
 * 없었다**(`AGENTS §6.1`). `#826`이 그 사실을 잡아 `#892`로 갈랐다.
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
  | { status: 'success'; response: ScenarioComparisonResponse; snapshot: ResultSnapshot }
  | { status: 'error'; message: string }

/**
 * 계산 시점에 고정해 두는 것들 (#875).
 *
 * **숫자는 스냅샷인데 제목만 살아 있었다.** 제목의 선박명·연도가 `form`을 직접
 * 읽어, 결과를 본 뒤 상단바에서 배를 바꾸면 **A선의 계산 결과 위에 B선의 이름**이
 * 붙었다(연도도 같다 — 「2027년 기준」 제목 아래 2026년 계산이 남았다).
 *
 * 스냅샷을 응답 옆에 함께 둔다. 「제목만 따로 조심한다」로는 같은 결함이 다음에
 * 추가되는 표시값에서 되풀이된다 — **계산 시점 값은 계산 결과와 같은 자리에**
 * 있어야 한다.
 *
 * `inputs`는 제목의 출처이자 「결과가 낡음」의 비교 기준이다. 연도를 따로 복사해
 * 두지 않는 것은 두 곳이 갈라지지 않게 하기 위해서다.
 */
interface ResultSnapshot {
  /** 계산 시점 셸 목록에서 읽은 이름. 목록이 아직 없거나 지워진 배면 `null`. */
  vesselName: string | null
  /** 계산에 실제로 쓴 조건 전부. */
  inputs: ComparisonFormState
}

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
    /*
     * 스냅샷은 **응답이 온 뒤가 아니라 지금** 뜬다 (#875). 계산이 도는 동안에도
     * 상단바에서 배를 바꿀 수 있으므로, 응답 시점에 읽으면 사용자가 「비교하기」를
     * 누를 때 화면에 있던 이름이 아니라 그 사이에 바뀐 이름이 박힌다.
     */
    const snapshot: ResultSnapshot = {
      vesselName: vessels?.find((option) => option.id === form.vesselId)?.displayName ?? null,
      inputs: form,
    }
    setState({ status: 'loading' })
    provider.compare(toRequest(form, fuels)).then(
      (response) => {
        setState({ status: 'success', response, snapshot })
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
      <h2 className="card__title scenario-comparison__form-title">
        비교 조건
        <span className="scenario-comparison__form-title-en"> Comparison Input</span>
      </h2>
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

  const { response, snapshot } = state
  const unit = ciiUnit(response.transport_capacity_basis)
  const summary = lowestSummary(response.scenarios)

  /*
   * 제목의 선박명 (#821 · #875).
   *
   * **서버 응답에는 이 값이 없다.** 종전에는 provider가 `vessel_display_name: ''`을
   * 응답 타입에 채워 넣었고, 제목이 `` · 2026년 기준 · …``처럼 **구분점만 남은**
   * 상태로 배포됐다. 그 필드가 응답 타입에 있던 것이 「서버가 준다」는 오해를
   * 만들었으므로 타입에서 없앴다.
   *
   * 여기서 `GET /vessels/{id}`를 부르지 않는다 — **셸이 이미 목록을 들고 있고**,
   * 위 선박 드롭다운이 같은 `displayName`을 렌더한다. 사용자가 고른 그 이름을
   * 그대로 쓰는 것이 서버에서 다시 조회해 오는 것보다 화면과 일치한다.
   *
   * 목록이 아직 안 왔거나 그 사이 선박이 지워졌으면 `null`이라 이름 칸을 통째로
   * 뺀다 — 빈 문자열을 두면 구분점만 남아 **레이아웃이 깨진 것처럼 보인다.**
   *
   * `#875`가 여기서 **`form`이 아니라 스냅샷을 읽게** 바꿨다. 종전에는 결과를 본 뒤
   * 상단바에서 배를 바꾸면 옛 숫자 위에 새 이름이 붙었다.
   */
  const { vesselName } = snapshot

  /*
   * 결과가 낡았는가 (#875 · 선례 `#727`).
   *
   * 제목을 고정하면 이번에는 **제목·숫자와 폼이 어긋난 상태**가 화면에 남는다.
   * 어긋남 자체는 정상이다(결과를 보며 조건을 고치는 것이 이 화면의 사용법이다) —
   * 다만 **그 사실을 화면이 말해야** 사용자가 옛 숫자를 현재 조건의 답으로 읽지
   * 않는다. 기능①이 같은 이유로 같은 표시를 갖고 있다.
   *
   * 비교는 폼 전체를 본다 — 선박·연도만 보면 거리나 연료만 고쳤을 때 안내가
   * 빠진다. 판정은 `sameInputs`가 하고, 그 함수는 키를 열거하지 않아 폼에 칸이
   * 늘어도 자동으로 포함된다.
   */
  const stale = !sameInputs(snapshot.inputs, form)

  const nameOf = (type: string | null) =>
    response.scenarios.find((s) => s.scenario_type === type)?.scenario_name ?? '—'

  /*
   * 동률이면 **전부 적고 동률임을 밝힌다** (`PRD §11.2`, `#799`).
   *
   * 같은 값 중 하나만 지목하는 것은 그 자체가 추천이다 — 사용자는 두 시나리오의
   * CII가 표에 같게 찍혀 있는데 한쪽만 「가장 낮은」으로 불리는 것을 보고 그쪽이
   * 낫다고 읽는다. 「(동률)」을 붙이는 이유는 이름 두 개만으로는 **둘 다 최소인지**
   * **둘을 함께 추천하는지** 읽는 사람이 가릴 수 없기 때문이다.
   */
  const namesOf = (types: readonly string[]) =>
    types.length === 0
      ? '—'
      : types.length === 1
        ? nameOf(types[0])
        : `${types.map(nameOf).join(' · ')} (동률)`

  return (
    <section className="scenario-comparison">
      {/* 결과를 본 뒤 조건을 바꿔 다시 비교할 수 있어야 한다 — 폼을 남긴다. */}
      {conditionForm}
      {/*
        결과 전체를 한 겹으로 묶는다. 묶지 않으면 12컬럼 자동 배치가 `__header`만
        폼 옆에 올리고 `__notice`부터는 아래 줄로 흘려보낸다 — 결과가 두 단에
        걸쳐 쪼개진다.
      */}
      <div
        className={`scenario-comparison__results${stale ? ' scenario-comparison__results--stale' : ''}`}
      >
        <header className="scenario-comparison__header">
          <h2 className="scenario-comparison__title">
            시나리오 비교
            <span className="scenario-comparison__title-en"> Scenario Comparison</span>
          </h2>
          <p className="scenario-comparison__context">
            {vesselName !== null && `${vesselName} · `}
            {snapshot.inputs.regulationYear}년 기준 · 기준 CII{' '}
            {formatDecimalString(response.required_cii, DISPLAY_DIGITS.cii)} {unit}
          </p>
        </header>

        {/*
          입력이 바뀌었는데 결과가 그대로 남아 있는 상태 (#875, 선례 `#727`).
          문구를 기능①과 같은 형태로 두되 버튼 이름만 이 화면의 것(`비교하기`)을
          쓴다 — 다시 눌러야 할 버튼이 화면에 실제로 있는 이름이어야 한다.
        */}
        {stale ? (
          <p className="scenario-comparison__stale" role="status">
            <strong>입력이 바뀌었습니다.</strong> 아래는 이전 입력으로 계산한 값입니다 —
            <strong> 비교하기</strong>를 다시 눌러 주세요.
          </p>
        ) : null}

        {/* PRD §6.3 — 「추정값 사용」·「자동 결정 금지」 문구를 그대로 쓴다 */}
        <p className="scenario-comparison__notice">
          {ESTIMATE_NOTICE} {NO_AUTO_DECISION_NOTICE}
        </p>

        <div className="scenario-comparison__cards">
          {/*
            기준은 `DIRECT`다 (#739). 배열 첫 번째가 아니라 **타입으로** 찾는다 —
            `PRD §11.2` 표 순서가 배열 순서와 같지만, 순서가 바뀌어도 기준이
            따라 움직이면 안 된다. 없으면 `deltaFromDirect`가 `null`을 내고
            차이 표시가 통째로 빠진다(잘못된 기준으로 빼는 것보다 낫다).
          */}
          {response.scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.scenario_type}
              scenario={scenario}
              direct={response.scenarios.find((s) => s.scenario_type === 'DIRECT')}
              unit={unit}
            />
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
              <dd>{namesOf(item.scenarioTypes)}</dd>
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

function ScenarioCard({
  scenario,
  direct,
  unit,
}: {
  scenario: ScenarioResult
  direct: ScenarioResult | undefined
  unit: string
}) {
  const margin = marginDisplay(
    scenario.estimated_rating,
    scenario.next_worse_boundary_margin_ratio,
  )
  const risk = riskLabel(scenario.risk_level)
  const delta = deltaFromDirect(scenario, direct)

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

      <ScenarioRouteGlyph type={scenario.scenario_type} />

      <p className="scenario-card__cii">
        {formatDecimalString(scenario.attained_cii, DISPLAY_DIGITS.cii)}
        <span className="scenario-card__cii-unit"> {unit}</span>
      </p>

      <CiiComparison scenario={scenario} direct={direct} delta={delta} />

      <p className="scenario-card__margin">
        <span className="scenario-card__margin-label">다음 경계까지</span>
        {margin.text}
      </p>

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

      {/*
        차이를 값 **바로 옆**에 둔다 (#739). 아래에 「직항 대비」 묶음을 따로
        만들면 같은 지표가 카드 안에서 두 번 나오고, 어느 숫자가 어느 차이인지를
        다시 눈으로 짝지어야 한다.
      */}
      <dl className="scenario-card__rows">
        <Row label="항해거리" value={formatGrouped(toDecimalInput(scenario.distance_nm), DISPLAY_DIGITS.distanceNm)} unit={DISPLAY_UNITS.distance} delta={delta?.distanceNm} deltaDigits={DISPLAY_DIGITS.distanceNm} />
        {/*
          `#822` — 종전에는 `String(...)` 그대로였다. 이 `<dl>`의 나머지 5행은 전부
          포매터를 거치는데 이 한 행만 빠져 있었다. `12.8`은 우연히 1자리라 눈에
          띄지 않지만 `12`나 `12.75`가 오면 같은 표 안에서 자릿수가 갈린다.
        */}
        <Row
          label="평균 속력"
          value={formatDecimalString(toDecimalInput(scenario.speed_kn), DISPLAY_DIGITS.speedKn)}
          unit={DISPLAY_UNITS.speed}
        />
        <Row label="예상 소요시간" value={formatDecimalString(scenario.duration_hours, DISPLAY_DIGITS.durationHours)} unit={DISPLAY_UNITS.duration} delta={delta?.durationHours} deltaDigits={DISPLAY_DIGITS.durationHours} />
        <Row label="예상 연료" value={formatGrouped(scenario.fuel_ton, DISPLAY_DIGITS.fuelTon)} unit={DISPLAY_UNITS.fuel} delta={delta?.fuelTon} deltaDigits={DISPLAY_DIGITS.fuelTon} />
        <Row label="CO₂ 배출량" value={formatGrouped(scenario.co2_emission_ton, DISPLAY_DIGITS.co2Ton)} unit={DISPLAY_UNITS.co2} delta={delta?.co2Ton} deltaDigits={DISPLAY_DIGITS.co2Ton} />
        <Row label="기준 대비" value={`${formatPercent(scenario.ratio_to_required)}%`} />
      </dl>
    </article>
  )
}

/* ------------------------------------------------------------------ */

/**
 * CII가 직항과 어떻게 다른가 — `#739`.
 *
 * ## 같은 숫자 두 개를 그냥 두지 않는다
 *
 * 같은 속력으로 우회하면 **CII가 정확히 같다.** 연료가 시간에, 시간이 거리에
 * 비례하므로 `attained = M / (용량 × 거리)`의 분자와 분모가 같은 비율로 늘기
 * 때문이다. 화면은 그 사실을 말하지 않고 `6.614`와 `6.614`를 나란히 놓았고,
 * **보는 사람은 계산이 틀렸다고 읽는다.**
 *
 * 이것은 추천이 아니라 사실 설명이므로 `PRD §11.2`의 「추천 시나리오를 표시하지
 * 않는다」에 걸리지 않는다. 어느 쪽이 낫다고 말하지 않고, CO₂ 차이는 표가 따로
 * 보여 준다 — 등급은 같아도 총량은 다르다는 것을 사용자가 직접 읽는다.
 */
function CiiComparison({
  scenario,
  direct,
  delta,
}: {
  scenario: ScenarioResult
  direct: ScenarioResult | undefined
  delta: ScenarioDelta | null
}) {
  if (delta === null) {
    return <p className="scenario-card__baseline">기준 시나리오</p>
  }

  if (!isZeroDelta(delta.cii)) {
    return (
      <p className="scenario-card__cii-delta">
        <span className="scenario-card__delta-label">직항 대비</span>
        <DeltaValue value={delta.cii} digits={DISPLAY_DIGITS.cii} />
      </p>
    )
  }

  // 거리가 같은데 CII도 같은 것은 설명할 일이 아니다 — 같은 조건이니 같은 값이다.
  const longer = direct !== undefined && scenario.distance_nm > direct.distance_nm

  return (
    <p className="scenario-card__cii-same">
      <strong>직항과 같습니다.</strong>{' '}
      {longer
        ? 'CII는 거리당 값이라, 같은 속력이면 거리가 늘어도 연료가 같은 비율로 늘어 값이 변하지 않습니다.'
        : '같은 속력·같은 거리이므로 값이 같습니다.'}
    </p>
  )
}

/**
 * 직항 대비 한 값 — `#739`.
 *
 * **색을 주지 않는다.** 늘어난 쪽을 빨강, 줄어든 쪽을 초록으로 칠하면 그것이 곧
 * 「이쪽이 낫다」가 되어 `PRD §11.2`의 추천 금지에 걸린다. 게다가 항해거리가
 * 늘어난 것이 나쁘다고 단정할 수도 없다 — 우회에는 이유가 있다. 방향은 `+`·`−`
 * 문자가 말하고, 좋고 나쁨의 판단은 사용자에게 남긴다(`PRD §6.3`).
 */
function DeltaValue({ value, digits, unit }: { value: string; digits: number; unit?: string }) {
  if (isZeroDelta(value)) {
    return <span className="scenario-card__delta">동일</span>
  }

  const negative = value.startsWith('-')
  const magnitude = formatGrouped(negative ? value.slice(1) : value, digits)

  return (
    <span className="scenario-card__delta">
      {/* U+2212 MINUS SIGN — 하이픈은 좁아서 `+`와 폭이 어긋난다 */}
      {negative ? '−' : '+'}
      {magnitude}
      {unit ? <span className="scenario-card__row-unit"> {unit}</span> : null}
    </span>
  )
}

function Row({
  label,
  value,
  unit,
  delta,
  deltaDigits,
}: {
  label: string
  value: string
  unit?: string
  delta?: string
  deltaDigits?: number
}) {
  return (
    <div className="scenario-card__row">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit ? <span className="scenario-card__row-unit"> {unit}</span> : null}
      </dd>
      {delta !== undefined && deltaDigits !== undefined ? (
        <dd className="scenario-card__row-delta">
          <DeltaValue value={delta} digits={deltaDigits} />
        </dd>
      ) : null}
    </div>
  )
}
