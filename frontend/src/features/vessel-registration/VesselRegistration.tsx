import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import './VesselRegistration.css'
import { SCREEN_BY_ID } from '../../screens'
import {
  FIELD,
  NAME_MAX_LENGTH,
  initialFormState,
  selectableFuels,
  specGapNotice,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  type VesselFormState,
} from './formRules'
import {
  DEMO_UNAVAILABLE_MESSAGE,
  createVesselRegistrationProvider,
  isRegistrationAvailable,
} from './providerSelection'
import { applicabilityHint, numberOrMissing } from './resultRules'
import { SHIP_TYPES } from './shipTypes'
import type { Vessel } from './types'

/**
 * 선박 등록 화면 (`UIFLOW 1-2` · `PRD §6.2 SCR-002` · #441).
 *
 * **검증·변환 규칙은 이 파일에 없다** — `formRules.ts`의 순수 함수를 부른다. 이
 * 컴포넌트는 상태 보관, 규칙 호출, 결과 표시만 한다(`#135`와 같은 구성).
 *
 * ## 제원을 필수로 막지 않는다
 *
 * `PRD §20 O-11`이 수동 입력 경로를 열어 두었고 `vessel.deadweight`는 nullable이다.
 * 대신 **CII를 계산할 수 없다는 사실을 그 자리에서 알린다**(`specGapNotice`) — `#419`가
 * 선대 요약에 `MISSING_SPEC`을 넣은 것과 같은 말을 등록 시점에 한다.
 *
 * ## 등록 결과를 서버 응답으로 보여 준다
 *
 * 요청을 되보여 주지 않는다. 서버가 채운 값(`id`·`is_cii_applicable_hint`)이 빠지고,
 * 저장 실패를 성공으로 보이게 할 수 있다.
 *
 * ## 후속 흐름을 자동 전환하지 않는다
 *
 * `UIFLOW 1-2`는 「등록 완료 시 `1-3` 대시보드 상태로 전환」이라고 규정한다. 그
 * 전환을 **자동으로** 하면 방금 저장된 내용을 확인할 기회가 사라지고, 특히 제원 없이
 * 등록한 경우의 안내가 사용자를 지나친다. 그래서 결과 카드에 대시보드·선박 상세
 * 링크를 두어 **사용자가 넘어가게** 한다.
 *
 * **이동 대상의 우선순위는 대시보드다** (#510). `#490`이 요구한 「선박 상세로 이동」의
 * 근거(`UIFLOW v3.0 §4.11`)는 `PR #462`가 닫히며 사라졌고, 살아 있는 `UIFLOW 1-2`와
 * `#510`이 모두 대시보드를 가리킨다. 링크 순서가 그 판단을 반영한다.
 */
export function VesselRegistration() {
  const provider = useMemo(() => createVesselRegistrationProvider(), [])
  const available = useMemo(() => isRegistrationAvailable(), [])
  const fuels = useMemo(() => selectableFuels(), [])

  const [state, setState] = useState<VesselFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [registered, setRegistered] = useState<Vessel | null>(null)

  const notice = specGapNotice(state)

  /** 한 필드를 갱신하고 **그 필드의 오류만** 지운다. */
  function update<K extends keyof VesselFormState>(key: K, value: VesselFormState[K], field: string) {
    setState((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => {
      if (!(field in prev)) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const found = validateForm(state)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSubmitting(true)
    try {
      const vessel = await provider.register(toRequest(state))
      setRegistered(vessel)
      // 폼을 비운다 — 같은 값이 남아 있으면 두 번째 제출이 409를 맞는다.
      setState(initialFormState())
      setErrors({})
    } catch (error) {
      setErrors(toFormErrors(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="vessel-registration">
      <header className="vessel-registration__header">
        <h1 className="vessel-registration__title">
          {SCREEN_BY_ID.VESSEL_REGISTRATION.label}
          <span className="vessel-registration__title-en">
            {' '}
            {SCREEN_BY_ID.VESSEL_REGISTRATION.labelEn}
          </span>
        </h1>
        <p className="vessel-registration__lead">
          IMO 번호·선명·선종만 있으면 등록됩니다. 제원은 나중에 채울 수 있습니다.
        </p>
      </header>

      {available ? null : (
        <p className="vessel-registration__banner" role="status">
          {DEMO_UNAVAILABLE_MESSAGE}
        </p>
      )}

      {registered ? <RegisteredCard vessel={registered} /> : null}

      <form className="vessel-registration__form" onSubmit={handleSubmit} noValidate>
        {errors[FIELD.form] ? (
          <p className="vessel-registration__form-error" role="alert">
            {errors[FIELD.form]}
          </p>
        ) : null}

        <fieldset className="vessel-registration__fieldset">
          <legend className="vessel-registration__legend">필수 정보</legend>
          <div className="vessel-registration__grid">
            <Field
              id="imo-number"
              label="IMO 번호"
              labelEn="IMO Number"
              error={errors[FIELD.imoNumber]}
              hint="숫자 7자리"
            >
              <input
                id="imo-number"
                className="vessel-registration__control"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                maxLength={7}
                value={state.imoNumber}
                aria-invalid={FIELD.imoNumber in errors}
                aria-describedby={describedBy('imo-number', FIELD.imoNumber in errors, true)}
                onChange={(e) => update('imoNumber', e.target.value, FIELD.imoNumber)}
              />
            </Field>

            <Field id="name" label="선명" labelEn="Vessel Name" error={errors[FIELD.name]}>
              <input
                id="name"
                className="vessel-registration__control"
                type="text"
                autoComplete="off"
                maxLength={NAME_MAX_LENGTH}
                value={state.name}
                aria-invalid={FIELD.name in errors}
                aria-describedby={describedBy('name', FIELD.name in errors, false)}
                onChange={(e) => update('name', e.target.value, FIELD.name)}
              />
            </Field>

            <Field
              id="ship-type"
              label="선종"
              labelEn="Ship Type"
              error={errors[FIELD.shipType]}
            >
              <select
                id="ship-type"
                className="vessel-registration__control"
                value={state.shipType}
                aria-invalid={FIELD.shipType in errors}
                aria-describedby={describedBy('ship-type', FIELD.shipType in errors, false)}
                onChange={(e) => update('shipType', e.target.value, FIELD.shipType)}
              >
                <option value="">선택해 주세요</option>
                {/* 목록은 `shipTypes.ts`가 갖고, `capacity.py`와의 일치는 CI가 지킨다 */}
                {SHIP_TYPES.map((type) => (
                  <option key={type.code} value={type.code}>
                    {type.label} ({type.code})
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </fieldset>

        <fieldset className="vessel-registration__fieldset">
          <legend className="vessel-registration__legend">제원 · 선택 입력</legend>

          {notice ? (
            <p className="vessel-registration__notice" role="status">
              {notice}
            </p>
          ) : null}

          <div className="vessel-registration__grid">
            <Field
              id="deadweight"
              label="재화중량톤수"
              labelEn="Deadweight"
              unit="DWT"
              error={errors[FIELD.deadweight]}
            >
              <input
                id="deadweight"
                className="vessel-registration__control"
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                value={state.deadweight}
                aria-invalid={FIELD.deadweight in errors}
                aria-describedby={describedBy('deadweight', FIELD.deadweight in errors, false)}
                onChange={(e) => update('deadweight', e.target.value, FIELD.deadweight)}
              />
            </Field>

            <Field
              id="gross-tonnage"
              label="총톤수"
              labelEn="Gross Tonnage"
              unit="GT"
              error={errors[FIELD.grossTonnage]}
            >
              <input
                id="gross-tonnage"
                className="vessel-registration__control"
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                value={state.grossTonnage}
                aria-invalid={FIELD.grossTonnage in errors}
                aria-describedby={describedBy(
                  'gross-tonnage',
                  FIELD.grossTonnage in errors,
                  false,
                )}
                onChange={(e) => update('grossTonnage', e.target.value, FIELD.grossTonnage)}
              />
            </Field>

            <Field
              id="reference-speed"
              label="기준속도"
              labelEn="Reference Speed"
              unit="kn"
              error={errors[FIELD.referenceSpeedKn]}
            >
              <input
                id="reference-speed"
                className="vessel-registration__control"
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                value={state.referenceSpeedKn}
                aria-invalid={FIELD.referenceSpeedKn in errors}
                aria-describedby={describedBy(
                  'reference-speed',
                  FIELD.referenceSpeedKn in errors,
                  false,
                )}
                onChange={(e) =>
                  update('referenceSpeedKn', e.target.value, FIELD.referenceSpeedKn)
                }
              />
            </Field>

            <Field
              id="reference-foc"
              label="기준 일일 연료소모량"
              labelEn="Daily Fuel Consumption"
              unit="t/일"
              error={errors[FIELD.referenceDailyFocTon]}
            >
              <input
                id="reference-foc"
                className="vessel-registration__control"
                type="number"
                inputMode="decimal"
                min="0"
                step="any"
                value={state.referenceDailyFocTon}
                aria-invalid={FIELD.referenceDailyFocTon in errors}
                aria-describedby={describedBy(
                  'reference-foc',
                  FIELD.referenceDailyFocTon in errors,
                  false,
                )}
                onChange={(e) =>
                  update('referenceDailyFocTon', e.target.value, FIELD.referenceDailyFocTon)
                }
              />
            </Field>

            <Field
              id="default-fuel"
              label="기본 연료"
              labelEn="Default Fuel"
              error={errors[FIELD.defaultFuelType]}
            >
              <select
                id="default-fuel"
                className="vessel-registration__control"
                value={state.defaultFuelType}
                aria-invalid={FIELD.defaultFuelType in errors}
                aria-describedby={describedBy(
                  'default-fuel',
                  FIELD.defaultFuelType in errors,
                  false,
                )}
                onChange={(e) => update('defaultFuelType', e.target.value, FIELD.defaultFuelType)}
              >
                <option value="">선택하지 않음</option>
                {fuels.map((fuel) => (
                  <option key={fuel.code} value={fuel.code}>
                    {fuel.displayName} ({fuel.code})
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </fieldset>

        <button
          className="vessel-registration__submit"
          type="submit"
          disabled={submitting || !available}
        >
          {submitting ? '등록 중…' : '등록하기'}
        </button>
      </form>
    </section>
  )
}

/* ------------------------------------------------------------------ */

/**
 * 등록 결과.
 *
 * 서버가 저장한 값을 그대로 보인다. 제원이 비어 있으면 **그 사실을 값으로 적는다** —
 * 빈 칸으로 두면 「입력했는데 안 보인다」와 구분되지 않는다(`#449`가 경고를 값으로
 * 만든 것과 같은 원칙).
 */
function RegisteredCard({ vessel }: { vessel: Vessel }) {
  return (
    <div className="vessel-registration__result" role="status">
      <h2 className="vessel-registration__result-title">등록 완료</h2>
      <dl className="vessel-registration__result-list">
        <Spec label="선명" value={vessel.name} />
        <Spec label="IMO 번호" value={vessel.imo_number} />
        <Spec label="선종" value={vessel.ship_type} />
        <Spec label="재화중량톤수 (DWT)" value={numberOrMissing(vessel.deadweight)} />
        <Spec label="총톤수 (GT)" value={numberOrMissing(vessel.gross_tonnage)} />
        <Spec
          label="CII 적용 대상 추정"
          value={vessel.is_cii_applicable_hint ? '해당' : '미해당'}
        />
      </dl>
      <p className="vessel-registration__result-hint">{applicabilityHint(vessel)}</p>
      {/*
        후속 이동 대상은 **대시보드**다 (#510). `#490`은 `UIFLOW v3.0 §4.11`을 근거로
        「저장 후 SCR-008(선박 상세)로 이동」을 요구했으나, 그 문서는 `PR #462`가 머지
        없이 닫히며 사라졌다. 살아 있는 근거는 `UIFLOW 1-2`(「등록 완료 시 1-3
        대시보드 상태로 전환」)이며 `#510`이 같은 것을 요구한다. 선박 상세 링크는
        방금 등록한 배를 곧바로 확인하려는 경로로 남긴다.
      */}
      <div className="vessel-registration__result-links">
        <Link className="vessel-registration__link" to={SCREEN_BY_ID.MAINBOARD.path}>
          대시보드로 이동
        </Link>
        <Link className="vessel-registration__link" to={`/vessels/${vessel.id}`}>
          선박 상세 보기
        </Link>
        <Link
          className="vessel-registration__link"
          to={SCREEN_BY_ID.VESSEL_MANAGEMENT.path}
        >
          선박 관리
        </Link>
      </div>
    </div>
  )
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="vessel-registration__spec">
      <dt className="vessel-registration__spec-label">{label}</dt>
      <dd className="vessel-registration__spec-value">{value}</dd>
    </div>
  )
}

/** `aria-describedby` 조합. 오류·힌트가 있는 것만 잇는다. */
function describedBy(id: string, hasError: boolean, hasHint: boolean): string | undefined {
  return (
    [hasError ? `${id}-error` : null, hasHint ? `${id}-hint` : null]
      .filter(Boolean)
      .join(' ') || undefined
  )
}

interface FieldProps {
  id: string
  label: string
  /** 요청 본문의 필드명. `DESIGN_SYSTEM §14` 「한국어 라벨 + 영문 병기」. */
  labelEn: string
  unit?: string
  hint?: string
  error?: string
  children: ReactNode
}

/** 라벨 + 컨트롤 + 보조 문구 + 오류 한 벌. 오류는 컨트롤 **아래**에 둔다. */
function Field({ id, label, labelEn, unit, hint, error, children }: FieldProps) {
  return (
    <div className="vessel-registration__field">
      <label className="vessel-registration__label" htmlFor={id}>
        {label}
        <span className="vessel-registration__label-en"> {labelEn}</span>
        {unit ? <span className="vessel-registration__unit">{unit}</span> : null}
      </label>
      {children}
      {hint ? (
        <p className="vessel-registration__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="vessel-registration__error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
