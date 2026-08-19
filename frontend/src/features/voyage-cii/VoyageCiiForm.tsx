import { useEffect, useMemo, useState, type FormEvent } from 'react'
import './VoyageCiiForm.css'
import {
  FIELD,
  initialFormState,
  selectableFuels,
  selectableYears,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  type VoyageCiiFormState,
} from './formRules'
import { DISPLAY_UNITS } from '../../display/format'
import { createVoyageCiiProvider } from './providerSelection'
import { createVesselCatalog, type VesselOption } from './vesselCatalog'
import type { ResultState } from './resultRules'

/**
 * 기능① 항차 조건 입력 폼 (#135).
 *
 * **검증·변환 규칙은 이 파일에 없다** — `formRules.ts`의 순수 함수를 호출한다.
 * 이 컴포넌트가 하는 일은 상태 보관, 규칙 호출, 그 결과를 화면에 붙이는 것뿐이다.
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
  const fuels = useMemo(() => selectableFuels(), [])

  // 선택지 소스도 provider 경계 뒤에 둔다 (#236). demo면 고정표, 실 API면
  // GET /api/v1/vessels다 — 화면은 어느 쪽인지 알지 않는다.
  const catalog = useMemo(() => createVesselCatalog(), [])
  const [vessels, setVessels] = useState<VesselOption[]>([])
  const [vesselsLoading, setVesselsLoading] = useState(true)
  const [vesselsFailed, setVesselsFailed] = useState(false)

  const [state, setState] = useState<VoyageCiiFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)

  const years = useMemo(() => selectableYears(state.vesselId), [state.vesselId])
  // demo ↔ 실 API 전환은 providerSelection이 판단한다(#138). 화면은 어느 쪽이
  // 선택됐는지 알지 않는다 — 그것이 #134가 provider 경계를 그은 이유다.
  const provider = useMemo(() => createVoyageCiiProvider(), [])

  // 목록을 못 가져오면 폼을 「빈 선택지」로 두지 않고 실패를 명시한다 — 서버가
  // 없어서 비었는지 등록된 선박이 없어서 비었는지가 구분되어야 한다.
  useEffect(() => {
    let cancelled = false
    catalog
      .listVessels()
      .then((rows) => {
        if (cancelled) return
        setVessels(rows)
        // 첫 항목을 선택해 「아무것도 선택되지 않은 상태」를 만들지 않는다
        // (initialFormState와 같은 규칙).
        setState((prev) =>
          prev.vesselId || rows.length === 0 ? prev : { ...prev, vesselId: rows[0].id },
        )
      })
      .catch(() => {
        if (!cancelled) setVesselsFailed(true)
      })
      .finally(() => {
        if (!cancelled) setVesselsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [catalog])

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

  /** 선박을 바꾸면 연도도 그 선박이 지원하는 첫 값으로 맞춘다. */
  function changeVessel(vesselId: string) {
    const nextYear = selectableYears(vesselId)[0]
    setState((prev) => ({
      ...prev,
      vesselId,
      regulationYear: nextYear === undefined ? '' : String(nextYear),
    }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const found = validateForm(state)
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
        {vesselsLoading ? (
          <StaticField label="선박" labelEn="Vessel" value="선박 목록을 불러오는 중…" />
        ) : vesselsFailed ? (
          <StaticField
            label="선박"
            labelEn="Vessel"
            value="선박 목록을 불러오지 못했습니다"
          />
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

        {/* 규제연도 — 같은 규칙 */}
        {years.length > 1 ? (
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
          <StaticField
            label="규제연도"
            labelEn="Year"
            value={state.regulationYear || '지원 연도가 없습니다'}
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
