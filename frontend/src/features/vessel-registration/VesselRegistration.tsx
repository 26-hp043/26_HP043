import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import './VesselRegistration.css'
import { DISPLAY_UNITS, DISPLAY_UNIT_DAILY_FUEL } from '../../display/format'
import { useFuelOptions } from '../parameters/fuelCatalog'
import { fuelTypeOptionText } from '../parameters/fuelTypes'
import { SCREEN_BY_ID } from '../../screens'
import {
  FIELD,
  NAME_MAX_LENGTH,
  initialFormState,
  specGapNotice,
  toFormErrors,
  toRequest,
  validateForm,
  type FormErrors,
  type VesselFormState,
} from './formRules'
import { createVesselRegistrationProvider } from './providerSelection'
import { applicabilityHint, applicabilityValue, numberOrMissing } from './resultRules'
import {
  SAMPLE_FILLED_FIELDS,
  SAMPLE_LOAD_FAILED_MESSAGE,
  applySample,
  hasDivergedFields,
  sampleOverwriteConfirmMessage,
  useSampleVessels,
  type SampleVessel,
} from './sampleVessels'
import { SHIP_TYPES, shipTypeLabel } from './shipTypes'
import type { Vessel } from './types'
import { Field } from '../../components/Field'
import { useI18n, useTextLang } from '../../i18n/core'

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
 * ## 샘플 선박에서 채우기 (#982)
 *
 * `PRD §5.1` 「샘플 선박 선택」. 고르면 선종·제원을 채우고 **IMO·선명은 그대로 둔다**
 * (`sampleVessels.ts`). 채운 뒤에도 고칠 수 있고, 목록을 못 불러와도 화면은 그대로 쓴다.
 *
 * **이동 대상의 우선순위는 대시보드다** (#510). `#490`이 요구한 「선박 상세로 이동」의
 * 근거(`UIFLOW v3.0 §4.11`)는 `PR #462`가 닫히며 사라졌고, 살아 있는 `UIFLOW 1-2`와
 * `#510`이 모두 대시보드를 가리킨다. 링크 순서가 그 판단을 반영한다.
 */
export function VesselRegistration() {
  const { language } = useI18n()
  const textLang = useTextLang()
  const provider = useMemo(() => createVesselRegistrationProvider(), [])
  // 연료 선택지는 서버가 준다 (#542). 종전에는 고정표(`referenceTable.ts`)를 읽어,
  // 등록 화면이 보여 주는 연료와 서버가 받는 연료가 갈릴 수 있었다.
  const { fuels, loading: fuelsLoading, failed: fuelsFailed } = useFuelOptions()

  const [state, setState] = useState<VesselFormState>(initialFormState)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [registered, setRegistered] = useState<Vessel | null>(null)
  const { samples, loading: samplesLoading, failed: samplesFailed } = useSampleVessels()
  const [sampleId, setSampleId] = useState('')
  // 마지막으로 적용한 샘플 (`#1526`). `hasDivergedFields`가 이 값을 기준으로 사용자가
  // 직접 고친 칸이 있는지 판정한다 — 없으면(첫 선택이면) 빈 폼 여부로 판정한다.
  const [lastAppliedSample, setLastAppliedSample] = useState<SampleVessel | null>(null)

  /**
   * 샘플을 고르면 제원을 채우고 **채운 필드의 오류만** 지운다. 비우면 아무것도 바꾸지 않는다.
   *
   * `#1526` — 마지막으로 적용한 샘플과 달라진(=사용자가 직접 남긴) 값이 있으면 덮기 전에
   * 한 번 확인한다(`hasDivergedFields`). 빈 폼에서 고르거나 샘플→샘플로 바로 바꾸는 것은
   * 묻지 않는다. 취소하면 아무것도 바꾸지 않는다 — 선택 상자도 이전 값 그대로 둔다.
   */
  function chooseSample(id: string) {
    const sample = samples.find((s) => s.sample_id === id)
    if (!sample) {
      // 선택 해제(id === ''). 제원 칸은 여전히 `lastAppliedSample`이 채운 값을 담고
      // 있으므로 그 값은 그대로 둔다 — 지우면 다음에 같은 샘플을 다시 골랐을 때
      // 「바뀐 게 없는데도 확인을 구하는」 오탐이 생긴다.
      setSampleId(id)
      return
    }
    if (
      hasDivergedFields(state, lastAppliedSample, sample) &&
      !globalThis.confirm(sampleOverwriteConfirmMessage())
    ) {
      return
    }
    setSampleId(id)
    setState((prev) => applySample(prev, sample))
    setLastAppliedSample(sample)
    setErrors((prev) => {
      const next = { ...prev }
      for (const field of SAMPLE_FILLED_FIELDS) delete next[field]
      return next
    })
  }

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

    // 새 시도가 시작되면 이전 결과 카드를 거둔다 (#1102 ⑷). 두 번째 등록이 실패해도
    // 첫 선박의 「등록 완료」가 남아 있으면 실패한 쪽이 등록된 것처럼 읽힌다.
    setRegistered(null)

    const found = validateForm(state, fuels)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSubmitting(true)
    try {
      const vessel = await provider.register(toRequest(state))
      setRegistered(vessel)
      // 폼을 비운다 — 같은 값이 남아 있으면 두 번째 제출이 409를 맞는다.
      setState(initialFormState())
      setSampleId('')
      // 빈 폼이 됐으니 「마지막 적용 샘플」도 함께 잊는다 — 다음 선택은 빈 폼에서
      // 고르는 것과 같다(`hasDivergedFields`가 어차피 빈 칸은 건드리지 않지만,
      // 이전 등록의 샘플을 들고 있을 이유가 없다).
      setLastAppliedSample(null)
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
        {/* 화면 이름은 언어에 맞는 것 하나만 적는다 (`#1426` · `PageHeader`와 같은 판단). */}
        <h1 className="vessel-registration__title" lang={textLang}>
          {language === 'en'
            ? SCREEN_BY_ID.VESSEL_REGISTRATION.labelEn
            : SCREEN_BY_ID.VESSEL_REGISTRATION.label}
        </h1>
        <p className="vessel-registration__lead">
          IMO 번호·선명·선종만 있으면 등록됩니다. 제원은 나중에 채울 수 있습니다.
        </p>
      </header>

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
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={7}
                  value={state.imoNumber}
                  onChange={(e) => update('imoNumber', e.target.value, FIELD.imoNumber)}
                />
              )}
                        </Field>

            <Field id="name" label="선명" labelEn="Vessel Name" error={errors[FIELD.name]}>
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  autoComplete="off"
                  maxLength={NAME_MAX_LENGTH}
                  value={state.name}
                  onChange={(e) => update('name', e.target.value, FIELD.name)}
                />
              )}
                        </Field>

            <Field
              id="ship-type"
              label="선종"
              labelEn="Ship Type"
              error={errors[FIELD.shipType]}
            >
              {(control) => (
                <select
                  {...control}
                  className="vessel-registration__control"
                  value={state.shipType}
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
              )}
                        </Field>
          </div>
        </fieldset>

        {/*
          샘플 선박 (`#982`) — **식별 정보 뒤, 제원 앞이다** (`#1423`).

          종전에는 폼의 **첫 섹션**이었다. 등록 화면을 열면 IMO·선명보다 먼저 「샘플
          선박에서 채우기」가 보여, 자기 배를 등록하러 온 사람이 **샘플 목록부터**
          만났다. `UIFLOW 1-2`는 샘플을 한 줄로 적을 뿐 순서를 정하지 않는다.

          ## 왜 맨 아래가 아닌가

          `applySample`은 선종·제원 여섯 칸을 덮어쓰고, 샘플에 값이 없는 칸은
          비운다(두 샘플이 섞인 제원을 막으려고 그렇게 정했다). 첫 섹션일 때는
          아무것도 입력하기 전에 고르므로 덮을 것이 없었다. 등록 버튼 위로 내리면
          **제원을 다 입력한 뒤에 샘플을 만난다** — 그래서 직접 입력한 값이 있으면
          덮기 전에 한 번 확인한다(`#1526`, `hasDivergedFields`). 빈 폼에서 고르거나
          샘플→샘플로 바로 바꾸는 것은 묻지 않는다.

          여기라면 확인이 필요할 일은 바로 위의 선종 한 칸뿐이고, 「제원을 모르면
          샘플에서」가 자기가 채우는 섹션 바로 앞에서 읽힌다.
        */}
        <fieldset className="vessel-registration__fieldset">
          <legend className="vessel-registration__legend">샘플 선박 · 선택 입력</legend>
          <div className="vessel-registration__grid">
            <Field
              id="sample-vessel"
              label="샘플 선박에서 채우기"
              labelEn="Sample Vessel"
              hint="선종·제원을 샘플 값으로 채웁니다 — 직접 적은 값이 있으면 바꾸기 전에 묻습니다. IMO 번호·선명은 그대로 둡니다."
            >
              {(control) => (
                <select
                  {...control}
                  className="vessel-registration__control"
                  value={sampleId}
                  onChange={(e) => chooseSample(e.target.value)}
                >
                  <option value="">
                    {samplesLoading
                      ? '샘플 목록을 불러오는 중…'
                      : samplesFailed
                        ? '샘플 목록을 불러오지 못했습니다'
                        : '선택하지 않음'}
                  </option>
                  {samples.map((sample) => (
                    <option key={sample.sample_id} value={sample.sample_id}>
                      {sample.label}
                    </option>
                  ))}
                </select>
              )}
                        </Field>
          </div>
          {samplesFailed ? (
            <p className="vessel-registration__notice" role="status">
              {SAMPLE_LOAD_FAILED_MESSAGE}
            </p>
          ) : null}
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
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="decimal"
                  value={state.deadweight}
                  onChange={(e) => update('deadweight', e.target.value, FIELD.deadweight)}
                />
              )}
                        </Field>

            <Field
              id="gross-tonnage"
              label="총톤수"
              labelEn="Gross Tonnage"
              unit="GT"
              error={errors[FIELD.grossTonnage]}
            >
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="decimal"
                  value={state.grossTonnage}
                  onChange={(e) => update('grossTonnage', e.target.value, FIELD.grossTonnage)}
                />
              )}
                        </Field>

            <Field
              id="reference-speed"
              label="기준속도"
              labelEn="Reference Speed"
              unit={DISPLAY_UNITS.speed}
              error={errors[FIELD.referenceSpeedKn]}
            >
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="decimal"
                  value={state.referenceSpeedKn}
                  onChange={(e) =>
                    update('referenceSpeedKn', e.target.value, FIELD.referenceSpeedKn)
                  }
                />
              )}
                        </Field>

            <Field
              id="reference-foc"
              label="기준 일일 연료소모량"
              labelEn="Daily Fuel Consumption"
              unit={DISPLAY_UNIT_DAILY_FUEL}
              error={errors[FIELD.referenceDailyFocTon]}
            >
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="decimal"
                  value={state.referenceDailyFocTon}
                  onChange={(e) =>
                    update('referenceDailyFocTon', e.target.value, FIELD.referenceDailyFocTon)
                  }
                />
              )}
                        </Field>

            <Field
              id="block-coefficient"
              label="방형계수"
              labelEn="Block Coefficient"
              error={errors[FIELD.blockCoefficient]}
            >
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  inputMode="decimal"
                  value={state.blockCoefficient}
                  onChange={(e) =>
                    update('blockCoefficient', e.target.value, FIELD.blockCoefficient)
                  }
                />
              )}
            </Field>

            {/* #1197 — 호출부호(선택). 공공데이터(해양수산부_선박운항정보)가 IMO가 아니라
                이 값으로 질의하므로 교차 대조의 키다. 서버가 대문자로 접어 저장한다. */}
            <Field
              id="call-sign"
              label="호출부호"
              labelEn="Call Sign"
              error={errors[FIELD.callSign]}
            >
              {(control) => (
                <input
                  {...control}
                  className="vessel-registration__control"
                  type="text"
                  autoCapitalize="characters"
                  spellCheck={false}
                  value={state.callSign}
                  onChange={(e) => update('callSign', e.target.value, FIELD.callSign)}
                />
              )}
            </Field>

            <Field
              id="default-fuel"
              label="기본 연료"
              labelEn="Default Fuel"
              error={errors[FIELD.defaultFuelType]}
            >
              {(control) => (
                <select
                  {...control}
                  className="vessel-registration__control"
                  value={state.defaultFuelType}
                  onChange={(e) => update('defaultFuelType', e.target.value, FIELD.defaultFuelType)}
                >
                  <option value="">
                    {fuelsLoading
                      ? '연료 목록을 불러오는 중…'
                      : fuelsFailed
                        ? '연료 목록을 불러오지 못했습니다'
                        : '선택하지 않음'}
                  </option>
                  {fuels.map((fuel) => (
                    <option key={fuel.code} value={fuel.code}>
                      {fuelTypeOptionText(fuel.code)}
                    </option>
                  ))}
                </select>
              )}
                        </Field>
          </div>
        </fieldset>

        <button
          className="vessel-registration__submit"
          type="submit"
          disabled={submitting}
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
      <h2 className="card__title vessel-registration__result-title">등록 완료</h2>
      <dl className="vessel-registration__result-list">
        <Spec label="선명" value={vessel.name} />
        <Spec label="IMO 번호" value={vessel.imo_number} />
        {/* 목록·상세와 같은 한글명 (#1102 ⑷). 코드(`BULK_CARRIER`)는 사용자 언어가 아니다. */}
        <Spec label="선종" value={shipTypeLabel(vessel.ship_type)} />
        <Spec label="재화중량톤수 (DWT)" value={numberOrMissing(vessel.deadweight)} />
        <Spec label="총톤수 (GT)" value={numberOrMissing(vessel.gross_tonnage)} />
        {/*
          「미해당」의 두 원인을 값 칸에서도 가른다 (`#1656`). GT가 비어 있으면
          서버 판정도 `false`이므로(`API_SPEC §2.3`), 종전의 boolean 표시는
          **총톤수를 넣지 않은 배를 규제 대상이 아니라고** 적고 있었다.
        */}
        <Spec label="CII 적용 대상 추정" value={applicabilityValue(vessel)} />
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

