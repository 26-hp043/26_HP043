import { useEffect, useMemo, useState, type FormEvent } from 'react'
import './VoyageCiiForm.css'
import {
  FIELD,
  initialFormState,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  type VoyageCiiFormState,
  pickDefaultYear,
} from './formRules'
import { DISPLAY_UNITS } from '../../display/format'
import { createVoyageCiiProvider } from './providerSelection'
import { useShellContext } from '../../layout/shellContext'
import { createYearCatalog } from '../parameters/yearCatalog'
import { useFuelOptions } from '../parameters/fuelCatalog'
import type { ResultState } from './resultRules'

/**
 * 기능① 항차 조건 입력 폼 (#135).
 *
 * **검증·변환 규칙은 이 파일에 없다** — `formRules.ts`의 순수 함수를 호출한다.
 * 이 컴포넌트가 하는 일은 상태 보관, 규칙 호출, 그 결과를 화면에 붙이는 것뿐이다.
 *
 * ## 선택지는 전부 provider 경계 뒤에 있다
 *
 * 선박은 **셸의 전역 컨텍스트**(#484 · #535), 연도는 `yearCatalog`(#534)가 맡는다.
 * 이 컴포넌트는 어느 쪽이 고정표이고 어느 쪽이 서버인지 알지 않는다. **연료만 아직 `formRules`의
 * 고정표를 읽는다** — `/parameters/fuel-types`가 이미 있으므로(`#444`) 옮길 수 있으나
 * 이번 이슈 범위 밖이다.
 *
 * ## 선박·연도를 왜 셀렉트로 두지 않는가
 *
 * 선택지가 **1개면 고정 표시, 2개 이상이면 셀렉트**로 렌더한다.
 * 항목이 하나뿐인 드롭다운은 사용자가 다른 선택이 가능한 것으로 오해하게 만든다
 * (#135 코멘트 2026-08-02). 그렇다고 값을 화면에 하드코딩하면 `#34` 회신으로 선박이
 * 늘 때 이 파일을 고쳐야 한다. **선택지는 `formRules`가 고정표에서 만들고, 개수에
 * 따라 렌더 방식만 갈린다** — 고정표에 행이 추가되면 화면이 저절로 셀렉트가 된다.
 *
 * ## 상태를 문자열로 들고 있는 이유
 *
 * `formRules.VoyageCiiFormState` 주석 참조 — 입력 도중의 중간 상태 때문이다.
 *
 * ## 결과는 부모가 보관한다
 *
 * `onStateChange`로 상태를 넘긴다. 결과 표시는 `VoyageCiiResult`(#136)가 맡는다.
 * 이 컴포넌트가 응답을 렌더하면 입력과 결과가 같은 자리를 두고 겹친다.
 *
 * ## 오류를 어디에 붙이는가
 *
 * | 종류 | 위치 |
 * |---|---|
 * | 입력 검증 실패 (필드별) | 해당 입력창 아래 |
 * | 입력 검증 실패 (폼 전체) | 폼 상단 배너 |
 * | provider 오류 중 필드가 있는 것 | 해당 입력창 아래 — 사용자가 고칠 수 있다 |
 * | provider 오류 중 필드가 없는 것 | **결과 영역의 실패 상태** |
 *
 * 마지막 줄이 중요하다. 폼 상단과 결과 영역 양쪽에 같은 메시지를 띄우면 사용자가
 * 두 개의 다른 문제로 읽는다. **고칠 수 있는 것은 입력 쪽, 계산 자체의 실패는
 * 결과 쪽**으로 나눈다.
 */

interface VoyageCiiFormProps {
  /** 계산 상태 변화. 결과 렌더는 `VoyageCiiResult`(#136)가 맡는다. */
  onStateChange?: (state: ResultState) => void
}

export function VoyageCiiForm({ onStateChange }: VoyageCiiFormProps) {
  // 연료 선택지도 선박·연도와 같은 경계 뒤에 둔다 (#542). 종전에는 `selectableFuels()`가
  // 고정표(`referenceTable.ts`)를 직행으로 읽어, 실 API 모드에서도 서버가 아는 연료와
  // 화면이 보여 주는 연료가 갈릴 수 있었다.
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  // 선박 선택은 **셸이 소유한다** (#484 · #535). 종전에는 이 폼이 자기 목록과
  // 선택을 따로 들고 있어, 상단바에서 배를 바꿔도 폼은 그대로였다.
  const shell = useShellContext()
  const { vessels, vesselsState, selectVesselId } = shell

  const [state, setState] = useState<VoyageCiiFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)

  // 연도 선택지도 같은 경계 뒤에 둔다 (#534). 종전에는 `selectableYears()`가
  // 고정표를 직행으로 읽어, 실 API 모드에서 고정표에 없는 선박(= 벌크선 외 전부)이
  // 연도를 못 받아 계산 자체가 불가능했다.
  const yearCatalog = useMemo(() => createYearCatalog(), [])
  const [years, setYears] = useState<number[]>([])
  const [yearsLoading, setYearsLoading] = useState(true)
  const [yearsFailed, setYearsFailed] = useState(false)

  // demo ↔ 실 API 전환은 providerSelection이 판단한다(#138). 화면은 어느 쪽이
  // 선택됐는지 알지 않는다 — 그것이 #134가 provider 경계를 그은 이유다.
  const provider = useMemo(() => createVoyageCiiProvider(), [])

  /**
   * 셸의 선택을 폼 상태에 반영한다 (#535).
   *
   * **폼은 선박을 「소유」하지 않고 셸의 값을 따라간다.** 상단바에서 배를 바꾸면
   * 주소가 바뀌고, 그 주소가 셸을 거쳐 여기로 돌아온다.
   *
   * 셸에 선택이 없으면 **목록의 첫 배를 골라 셸에 알린다.** 폼만 몰래 정하면
   * 상단바는 「선택 안 함」인데 폼은 특정 배로 계산하는, `#535`가 지적한 어긋남이
   * 그대로 남는다. `#543`(초기값이 고정표 UUID라 서버에 없는 배를 가리킨다)도
   * 이 경로로 함께 해소된다 — 첫 배는 항상 서버 목록에서 고른다.
   */
  const shellVesselId = shell.vesselId
  useEffect(() => {
    if (shellVesselId !== null) {
      setState((prev) => (prev.vesselId === shellVesselId ? prev : { ...prev, vesselId: shellVesselId }))
      return
    }
    if (vessels.length > 0) selectVesselId(vessels[0].id)
  }, [shellVesselId, vessels, selectVesselId])

  /**
   * 선박이 정해진 뒤 그 선박의 연도 선택지를 받는다.
   *
   * **선박 로딩과 한 효과로 묶지 않는다.** 사용자가 선박을 바꿀 때마다 다시 돌아야
   * 하는데, 선박 목록은 한 번만 받으면 되기 때문이다. demo 구현은 고정표를
   * `(vesselId, year)` 키로 들고 있어 선박마다 결과가 갈린다.
   */
  useEffect(() => {
    if (!state.vesselId) return
    let cancelled = false
    setYearsLoading(true)
    setYearsFailed(false)
    yearCatalog
      .listYears(state.vesselId)
      .then((rows) => {
        if (cancelled) return
        setYears(rows)
        /*
         * 기본 선택은 `pickDefaultYear`가 정한다 — 이미 고른 해는 유지하고, 없으면
         * 올해를, 올해가 목록에 없으면 가장 최근 해를 고른다.
         *
         * 올해를 **여기서 읽어** 순수 함수에 넘긴다. 함수 안에서 `new Date()`를
         * 부르면 테스트가 해를 고정할 수 없다. 이 값은 셀렉트의 초기 선택을 정할
         * 뿐이고 **서버로 가는 것은 사용자가 고른 값**이다(함수 주석 참조).
         */
        const thisYear = new Date().getFullYear()
        setState((prev) => {
          const next = pickDefaultYear(rows, thisYear, prev.regulationYear)
          return next === prev.regulationYear ? prev : { ...prev, regulationYear: next }
        })
      })
      .catch(() => {
        if (cancelled) return
        setYearsFailed(true)
        setYears([])
      })
      .finally(() => {
        if (!cancelled) setYearsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [yearCatalog, state.vesselId])

  const selectedVessel = vessels.find((v) => v.id === state.vesselId)

  /** 한 필드를 갱신하고 그 필드의 오류만 지운다. 다른 필드의 오류는 그대로 둔다. */
  function update<K extends keyof VoyageCiiFormState>(
    key: K,
    value: VoyageCiiFormState[K],
    field?: string,
  ) {
    setState((prev) => ({ ...prev, [key]: value }))
    if (field) {
      setErrors((prev) => {
        if (!(field in prev)) return prev
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  /**
   * 선박을 바꾼다. **폼 상태를 직접 고치지 않고 셸에 알린다** (#535).
   *
   * 셸이 주소를 갱신하면 위 효과가 그 값을 받아 폼에 반영한다. 여기서 `setState`를
   * 직접 하면 폼만 바뀌고 상단바는 그대로여서, 고치려는 어긋남을 반대 방향으로
   * 다시 만든다.
   *
   * 연도도 여기서 정하지 않는다 — `vesselId`가 바뀌면 연도 효과가 다시 돈다(`#534`).
   */
  function changeVessel(vesselId: string) {
    shell.selectVesselId(vesselId)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const found = validateForm(state, fuels)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      onStateChange?.({ status: 'idle' })
      return
    }

    setSubmitting(true)
    onStateChange?.({ status: 'loading' })
    try {
      const response = await provider.estimate(toRequest(state))
      onStateChange?.({ status: 'success', response })
    } catch (error) {
      // provider 검증은 화면 검증의 방어선이다. 여기 도달하면 두 규칙이 어긋난 것이다.
      const mapped = toFormErrors(error)
      if (FIELD.form in mapped) {
        // 입력창에 붙일 수 없는 오류는 결과 영역의 실패 상태로 보낸다.
        onStateChange?.({ status: 'error', message: mapped[FIELD.form] })
      } else {
        setErrors(mapped)
        onStateChange?.({ status: 'idle' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="voyage-cii-form" onSubmit={handleSubmit} noValidate>
      <h2 className="voyage-cii-form__title">
        항차 조건 입력
        <span className="voyage-cii-form__title-en"> Voyage Input</span>
      </h2>

      {errors[FIELD.form] ? (
        <p className="voyage-cii-form__form-error" role="alert">
          {errors[FIELD.form]}
        </p>
      ) : null}

      <div className="voyage-cii-form__grid">
        {/* 선박 — 1척이면 고정 표시, 2척 이상이면 셀렉트 */}
        {vesselsState === 'loading' ? (
          <StaticField label="선박" labelEn="Vessel" value="선박 목록을 불러오는 중…" />
        ) : vesselsState === 'failed' ? (
          <StaticField label="선박" labelEn="Vessel" value="선박 목록을 불러오지 못했습니다" />
        ) : vessels.length > 1 ? (
          <Field id="vessel" label="선박" labelEn="Vessel">
            <select
              id="vessel"
              className="voyage-cii-form__control"
              value={state.vesselId}
              onChange={(e) => changeVessel(e.target.value)}
            >
              {vessels.map((vessel) => (
                <option key={vessel.id} value={vessel.id}>
                  {vessel.displayName}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <StaticField
            label="선박"
            labelEn="Vessel"
            value={selectedVessel?.displayName ?? '등록된 선박이 없습니다'}
          />
        )}

        {/* 규제연도 — 선박과 같은 규칙. 로딩·실패를 빈 선택지와 구분해 보인다 */}
        {yearsLoading ? (
          <StaticField label="규제연도" labelEn="Year" value="규제연도 목록을 불러오는 중…" />
        ) : yearsFailed ? (
          <StaticField label="규제연도" labelEn="Year" value="규제연도 목록을 불러오지 못했습니다" />
        ) : years.length > 1 ? (
          <Field id="year" label="규제연도" labelEn="Year">
            <select
              id="year"
              className="voyage-cii-form__control"
              value={state.regulationYear}
              onChange={(e) => update('regulationYear', e.target.value)}
            >
              {years.map((year) => (
                <option key={year} value={String(year)}>
                  {year}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          /*
           * 목록이 비었을 때의 문구 (#534).
           *
           * 종전 문구는 「지원 연도가 없습니다」였다. 연도 파라미터가 없다는 뜻으로
           * 읽히는데 실제 원인은 그게 아니었고, 그 오독이 #534 본문의 원인 추정을
           * 그대로 만들어 냈다 — 없는 백엔드 작업이 P0로 등재됐다.
           *
           * 이제 이 자리가 비는 경우는 `regulation_year` 테이블이 실제로 비어 있을
           * 때뿐이므로 그렇게 적는다. **선종별 기준선 부재는 여기서 드러나지 않는다**
           * — Z계수는 전 선종 공통이라 연도 목록은 채워지고, 기준선이 없는 선박은
           * 계산 실행 시 서버가 「선종의 기준선이 없습니다: <선종>」을 돌려준다
           * (`services/voyage_cii.py`). 그 메시지는 `toVoyageCiiError` →
           * `toFormErrors`를 거쳐 결과 영역의 실패 상태로 그대로 표시된다.
           */
          <StaticField
            label="규제연도"
            labelEn="Year"
            value={state.regulationYear || '등록된 규제연도가 없습니다'}
          />
        )}

        <Field
          id="distance"
          label="항해거리"
          labelEn="Distance"
          unit={DISPLAY_UNITS.distance}
          error={errors[FIELD.distanceNm]}
        >
          <input
            id="distance"
            className="voyage-cii-form__control"
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            value={state.distanceNm}
            aria-invalid={FIELD.distanceNm in errors}
            aria-describedby={FIELD.distanceNm in errors ? 'distance-error' : undefined}
            onChange={(e) => update('distanceNm', e.target.value, FIELD.distanceNm)}
          />
        </Field>

        <Field
          id="speed"
          label="평균 속력"
          labelEn="Speed"
          unit={DISPLAY_UNITS.speed}
          error={errors[FIELD.speedKn]}
          hint="요청에는 포함되지만 이 구성에서는 결과를 바꾸지 않습니다. 연료량과 거리가 같으면 속력만 바꿔도 값이 같습니다."
        >
          <input
            id="speed"
            className="voyage-cii-form__control"
            type="number"
            inputMode="decimal"
            min="1"
            step="any"
            value={state.speedKn}
            aria-invalid={FIELD.speedKn in errors}
            aria-describedby={
              [
                FIELD.speedKn in errors ? 'speed-error' : null,
                'speed-hint',
              ]
                .filter(Boolean)
                .join(' ') || undefined
            }
            onChange={(e) => update('speedKn', e.target.value, FIELD.speedKn)}
          />
        </Field>

        {/* 연료 종류 — 규제연도와 같은 규칙. 로딩·실패를 빈 선택지와 구분해 보인다 (#542) */}
        {fuelsLoading ? (
          <StaticField label="연료 종류" labelEn="Fuel Type" value="연료 목록을 불러오는 중…" />
        ) : fuelsFailed ? (
          <StaticField label="연료 종류" labelEn="Fuel Type" value="연료 목록을 불러오지 못했습니다" />
        ) : (
          <Field
            id="fuel-type"
            label="연료 종류"
            labelEn="Fuel Type"
            error={errors[FIELD.fuelType]}
          >
            <select
              id="fuel-type"
              className="voyage-cii-form__control"
              value={state.fuelType}
              aria-invalid={FIELD.fuelType in errors}
              aria-describedby={FIELD.fuelType in errors ? 'fuel-type-error' : undefined}
              onChange={(e) => update('fuelType', e.target.value, FIELD.fuelType)}
            >
              <option value="">선택해 주세요</option>
              {fuels.map((fuel) => (
                <option key={fuel.code} value={fuel.code}>
                  {fuel.displayName} ({fuel.code})
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field
          id="fuel-ton"
          label="연료 사용량"
          labelEn="Fuel Consumption"
          unit={DISPLAY_UNITS.fuel}
          error={errors[FIELD.fuelTon]}
        >
          <input
            id="fuel-ton"
            className="voyage-cii-form__control"
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            value={state.fuelTon}
            aria-invalid={FIELD.fuelTon in errors}
            aria-describedby={FIELD.fuelTon in errors ? 'fuel-ton-error' : undefined}
            onChange={(e) => update('fuelTon', e.target.value, FIELD.fuelTon)}
          />
        </Field>
      </div>

      <button className="voyage-cii-form__submit" type="submit" disabled={submitting}>
        {submitting ? '계산 중…' : '계산하기'}
      </button>
    </form>
  )
}

/* ------------------------------------------------------------------ */

interface FieldProps {
  id: string
  label: string
  /** 요청 본문의 필드명. `DESIGN_SYSTEM §14` 「한국어 라벨 + 영문 병기」. */
  labelEn: string
  unit?: string
  hint?: string
  error?: string
  children: React.ReactNode
}

/**
 * 라벨 + 컨트롤 + 보조 문구 + 오류 한 벌.
 *
 * 오류를 컨트롤 **아래**에 두는 것은 `#135` 완료 기준이다.
 * `role="alert"`을 붙여 스크린 리더가 갱신을 읽도록 한다(`DESIGN_SYSTEM §14`).
 */
function Field({ id, label, labelEn, unit, hint, error, children }: FieldProps) {
  return (
    <div className="voyage-cii-form__field">
      <label className="voyage-cii-form__label" htmlFor={id}>
        {label}
        <span className="voyage-cii-form__label-en"> {labelEn}</span>
        {unit ? <span className="voyage-cii-form__unit">{unit}</span> : null}
      </label>
      {children}
      {hint ? (
        <p className="voyage-cii-form__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="voyage-cii-form__error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

interface StaticFieldProps {
  label: string
  labelEn: string
  value: string
}

/**
 * 선택지가 하나뿐인 항목의 고정 표시.
 *
 * 컨트롤을 두지 않는다 — 항목이 하나뿐인 드롭다운은 다른 선택이 가능한 것으로
 * 오해하게 만든다(#135 코멘트). 값은 요청에 그대로 실린다.
 */
function StaticField({ label, labelEn, value }: StaticFieldProps) {
  return (
    <div className="voyage-cii-form__field">
      <p className="voyage-cii-form__label">
        {label}
        <span className="voyage-cii-form__label-en"> {labelEn}</span>
      </p>
      <p className="voyage-cii-form__static">{value}</p>
    </div>
  )
}
