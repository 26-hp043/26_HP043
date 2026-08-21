import { useCallback, useEffect, useState } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatGrouped } from '../../display/format'
import { VoyageError, createApiVoyageManagementProvider } from './apiProvider'
import { ImportCsv } from './ImportCsv'
import type { VoyageManagementProvider } from './apiProvider'
import {
  POLICY_LABELS,
  STATUS_LABELS,
  canEnterActuals,
  hasErrors,
  nextStatuses,
  transitionBlocker,
  validateActuals,
  validateDraft,
} from './voyageRules'
import type { FieldErrors } from './voyageRules'
import type { ActualsDraft, ManagedVoyage, VoyageDraft } from './types'
import './VoyagePanel.css'

/**
 * 항차 기록 패널 — `2-8 선박 상세` 안의 한 구획 (`#610`).
 *
 * ## 새 화면을 만들지 않는다
 *
 * `UIFLOW`에 「항차 생성」·「실적 입력」이 없다. 화면 신설은 `AGENTS §3.2.1`상
 * UIFLOW 소관(화면 목록)이라 정본 개정이 선행하고, 마감 스프린트가 그것을
 * 컷라인 밖에 두었다. `NotUnderwayPanel`과 같은 자리·같은 방식으로 붙인다.
 *
 * ## 속력 표시 — 조건부 유예가 풀렸다
 *
 * 종전에는 `DESIGN_SYSTEM §4.2`에 **속력(kn) 자릿수가 없어** 목록에서 열을 뺐다.
 * 화면이 임의로 정하면 다른 화면과 갈라지기 때문이었고, 열을 비우는 대신 아예
 * 빼는 것으로 그 사실을 드러냈다(`AGENTS §6.1`).
 *
 * **`§4.2` v2.3이 1자리로 확정했다**(`#592`). 열을 되돌린다.
 */

const NO_VALUE = '—'

/** `periodRules.quantityText`와 같은 규율 — 없는 값은 `—`, 있으면 자릿수 고정. */
function quantity(value: number | null, digits: number): string {
  if (value === null || !Number.isFinite(value)) return NO_VALUE
  return formatGrouped(value.toFixed(6), digits)
}

function totalFuel(voyage: ManagedVoyage, kind: 'planned' | 'actual'): number | null {
  const values = voyage.fuelUses
    .map((use) => (kind === 'planned' ? use.plannedFuelTon : use.actualFuelTon))
    .filter((value): value is number => value !== null)
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0)
}

function routeText(voyage: ManagedVoyage): string {
  return `${voyage.departurePortName ?? NO_VALUE} \u2192 ${voyage.arrivalPortName ?? NO_VALUE}`
}

interface VoyagePanelProps {
  vesselId: string
  provider?: VoyageManagementProvider
}

export function VoyagePanel({ vesselId, provider }: VoyagePanelProps) {
  const [voyages, setVoyages] = useState<ManagedVoyage[] | null>(null)
  const [fuelTypes, setFuelTypes] = useState<string[]>([])
  const [failure, setFailure] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  const api = provider ?? createApiVoyageManagementProvider()

  const load = useCallback(async () => {
    setFailure(null)
    try {
      const result = await api.list(vesselId)
      setVoyages(result.voyages)
      setFuelTypes(result.fuelTypes)
    } catch (error) {
      setVoyages([])
      setFailure(error instanceof Error ? error.message : '항차를 불러오지 못했습니다.')
    }
    // provider는 렌더마다 새로 만들어지므로 의존에 넣지 않는다 — 넣으면 무한 루프다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vesselId])

  useEffect(() => {
    void load()
  }, [load])

  const replace = (updated: ManagedVoyage) => {
    setVoyages((rows) => (rows ?? []).map((row) => (row.id === updated.id ? updated : row)))
  }

  return (
    <section className="card vy" aria-label="항차 기록">
      <div className="vy__head">
        <h2 className="card__title">항차 기록</h2>
        <button
          type="button"
          className="vy__toggle"
          onClick={() => setFormOpen((open) => !open)}
          aria-expanded={formOpen}
        >
          {formOpen ? '취소' : '항차 추가'}
        </button>
      </div>

      <p className="vy__why">
        계획을 먼저 만들고, 항해가 끝나면 실적을 입력합니다. 계획값은 실적을 넣어도 그대로
        남습니다 — 계획 대비 실적 차이가 다음 항차의 예측을 다듬는 근거입니다.
      </p>

      {failure ? (
        <p className="vy__error" role="alert">
          {failure}
        </p>
      ) : null}

      {formOpen ? (
        <VoyageForm
          fuelTypes={fuelTypes}
          onCancel={() => setFormOpen(false)}
          onSubmit={async (draft) => {
            const created = await api.create(vesselId, draft)
            setVoyages((rows) => [created, ...(rows ?? [])])
            setFormOpen(false)
          }}
        />
      ) : null}

      {voyages === null ? (
        <p className="vy__loading" aria-busy="true">
          항차를 불러오는 중입니다…
        </p>
      ) : voyages.length === 0 && !failure ? (
        <p className="vy__empty">
          기록된 항차가 없습니다. 「항차 추가」로 하나씩 만들거나, 아래에서 CSV로
          한 번에 가져올 수 있습니다.
        </p>
      ) : (
        <ul className="vy__list">
          {voyages.map((voyage) => (
            <VoyageRow key={voyage.id} voyage={voyage} api={api} onChange={replace} />
          ))}
        </ul>
      )}

      {/*
       * 가져오기를 **목록 아래**에 둔다. 이 구획의 주 용도는 기록을 읽고 상태를
       * 옮기는 것이고, 대량 입력은 처음 한 번에 몰린다. 위에 두면 매번 지나쳐야 한다.
       *
       * 확정에 성공하면 목록을 다시 부른다 — 들어간 행을 화면이 스스로 만들지
       * 않는다. 서버가 `DRAFT`·`EXCLUDE`로 확정한 항차를 그대로 받아야 상태 전환
       * 버튼이 옳게 그려진다(`API_SPEC §8.2`).
       */}
      <ImportCsv vesselId={vesselId} provider={api} onImported={() => void load()} />
    </section>
  )
}

function VoyageRow({
  voyage,
  api,
  onChange,
}: {
  voyage: ManagedVoyage
  api: VoyageManagementProvider
  onChange: (updated: ManagedVoyage) => void
}) {
  const [busy, setBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [actualsOpen, setActualsOpen] = useState(false)

  const run = async (task: () => Promise<ManagedVoyage>) => {
    setBusy(true)
    setRowError(null)
    try {
      onChange(await task())
    } catch (error) {
      setRowError(
        error instanceof VoyageError || error instanceof Error
          ? error.message
          : '처리하지 못했습니다.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="vy__row">
      <div className="vy__row-main">
        <span className="vy__no">{voyage.voyageNo ?? NO_VALUE}</span>
        <span className={`vy__badge vy__badge--${voyage.status.toLowerCase()}`}>
          {STATUS_LABELS[voyage.status]}
        </span>
        <span className="vy__route">{routeText(voyage)}</span>
        <span className="vy__policy">{POLICY_LABELS[voyage.inclusionPolicy]}</span>
      </div>

      <dl className="vy__figures">
        <div>
          <dt>계획 거리</dt>
          <dd className="num">
            {quantity(voyage.plannedDistanceNm, DISPLAY_DIGITS.distanceNm)} {DISPLAY_UNITS.distance}
          </dd>
        </div>
        <div>
          <dt>실제 거리</dt>
          <dd className="num">
            {quantity(voyage.actualDistanceNm, DISPLAY_DIGITS.distanceNm)} {DISPLAY_UNITS.distance}
          </dd>
        </div>
        <div>
          <dt>계획 속력</dt>
          <dd className="num">
            {quantity(voyage.plannedSpeedKn, DISPLAY_DIGITS.speedKn)} {DISPLAY_UNITS.speed}
          </dd>
        </div>
        <div>
          <dt>실제 평균 속력</dt>
          <dd className="num">
            {quantity(voyage.actualAvgSpeedKn, DISPLAY_DIGITS.speedKn)} {DISPLAY_UNITS.speed}
          </dd>
        </div>
        <div>
          <dt>계획 연료</dt>
          <dd className="num">
            {quantity(totalFuel(voyage, 'planned'), DISPLAY_DIGITS.fuelTon)} {DISPLAY_UNITS.fuel}
          </dd>
        </div>
        <div>
          <dt>실제 연료</dt>
          <dd className="num">
            {quantity(totalFuel(voyage, 'actual'), DISPLAY_DIGITS.fuelTon)} {DISPLAY_UNITS.fuel}
          </dd>
        </div>
      </dl>

      {rowError ? (
        <p className="vy__error" role="alert">
          {rowError}
        </p>
      ) : null}

      <div className="vy__row-actions">
        {nextStatuses(voyage.status).map((to) => {
          const blocker = transitionBlocker(voyage, to)
          return (
            <span className="vy__action" key={to}>
              <button
                type="button"
                className="vy__transition"
                disabled={busy || blocker !== null}
                onClick={() => void run(() => api.transition(voyage, to))}
              >
                {STATUS_LABELS[to]}(으)로
              </button>
              {/* 왜 못 누르는지 버튼 옆에 적는다 — 눌러 보고 422를 받는 것보다 낫다. */}
              {blocker ? <span className="vy__blocker">{blocker}</span> : null}
            </span>
          )
        })}

        {canEnterActuals(voyage.status) ? (
          <button
            type="button"
            className="vy__toggle"
            onClick={() => setActualsOpen((open) => !open)}
            aria-expanded={actualsOpen}
          >
            {actualsOpen ? '실적 닫기' : '실적 입력'}
          </button>
        ) : null}
      </div>

      {actualsOpen ? (
        <ActualsForm
          voyage={voyage}
          onCancel={() => setActualsOpen(false)}
          onSubmit={async (draft) => {
            await run(() => api.saveActuals(voyage.id, draft))
            setActualsOpen(false)
          }}
        />
      ) : null}
    </li>
  )
}

function VoyageForm({
  fuelTypes,
  onCancel,
  onSubmit,
}: {
  fuelTypes: string[]
  onCancel: () => void
  onSubmit: (draft: VoyageDraft) => Promise<void>
}) {
  const [draft, setDraft] = useState<VoyageDraft>({
    voyageNo: '',
    departurePortName: '',
    arrivalPortName: '',
    plannedDistanceNm: '',
    plannedSpeedKn: '',
    regulationYear: '',
    fuelType: fuelTypes[0] ?? '',
    plannedFuelTon: '',
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const set = (key: keyof VoyageDraft) => (value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  if (fuelTypes.length === 0) {
    /*
     * 선택지를 못 받으면 폼을 그리지 않는다. 화면이 기본값을 지어내면 서버의
     * 연료 목록과 갈라지고, 사용자는 저장 단계에서야 거부를 만난다.
     */
    return (
      <p className="vy__error" role="alert">
        연료 선택지를 불러오지 못해 항차를 추가할 수 없습니다.
      </p>
    )
  }

  return (
    <form
      className="vy__form"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const found = validateDraft(draft)
        setErrors(found)
        if (hasErrors(found)) return

        setBusy(true)
        setFailure(null)
        try {
          await onSubmit(draft)
        } catch (error) {
          setFailure(error instanceof Error ? error.message : '항차를 만들지 못했습니다.')
        } finally {
          setBusy(false)
        }
      }}
    >
      {failure ? (
        <p className="vy__error" role="alert">
          {failure}
        </p>
      ) : null}

      <Field id="vy-no" label="항차 번호" value={draft.voyageNo} onChange={set('voyageNo')} error={errors.voyageNo} />
      <Field id="vy-from" label="출발항" value={draft.departurePortName} onChange={set('departurePortName')} error={errors.departurePortName} />
      <Field id="vy-to" label="도착항" value={draft.arrivalPortName} onChange={set('arrivalPortName')} error={errors.arrivalPortName} />
      <Field id="vy-dist" label={`계획 거리 (${DISPLAY_UNITS.distance})`} value={draft.plannedDistanceNm} onChange={set('plannedDistanceNm')} error={errors.plannedDistanceNm} inputMode="decimal" />
      <Field id="vy-speed" label={`계획 속력 (${DISPLAY_UNITS.speed})`} value={draft.plannedSpeedKn} onChange={set('plannedSpeedKn')} error={errors.plannedSpeedKn} inputMode="decimal" />
      <Field id="vy-fuel" label={`계획 연료 (${DISPLAY_UNITS.fuel})`} value={draft.plannedFuelTon} onChange={set('plannedFuelTon')} error={errors.plannedFuelTon} inputMode="decimal" />

      <div className="vy__field">
        <label className="vy__label" htmlFor="vy-fuel-type">
          연료 종류
        </label>
        <select
          id="vy-fuel-type"
          className="vy__input"
          value={draft.fuelType}
          onChange={(event) => set('fuelType')(event.target.value)}
        >
          {fuelTypes.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
      </div>

      <Field
        id="vy-year"
        label="기준연도 (선택)"
        value={draft.regulationYear}
        onChange={set('regulationYear')}
        error={errors.regulationYear}
        inputMode="numeric"
        hint="연간 등급에 반영하려면 필요합니다. 나중에 지정해도 됩니다."
      />

      <div className="vy__form-actions">
        <button type="submit" className="vy__submit" disabled={busy}>
          {busy ? '만드는 중' : '항차 만들기'}
        </button>
        <button type="button" className="vy__cancel" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
    </form>
  )
}

function ActualsForm({
  voyage,
  onCancel,
  onSubmit,
}: {
  voyage: ManagedVoyage
  onCancel: () => void
  onSubmit: (draft: ActualsDraft) => Promise<void>
}) {
  const [draft, setDraft] = useState<ActualsDraft>({
    actualDistanceNm: voyage.actualDistanceNm?.toString() ?? '',
    actualAvgSpeedKn: voyage.actualAvgSpeedKn?.toString() ?? '',
    actualFuelTon: Object.fromEntries(
      voyage.fuelUses.map((use) => [use.fuelType, use.actualFuelTon?.toString() ?? '']),
    ),
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)

  return (
    <form
      className="vy__form vy__form--actuals"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const found = validateActuals(draft)
        setErrors(found)
        if (hasErrors(found)) return
        setBusy(true)
        try {
          await onSubmit(draft)
        } finally {
          setBusy(false)
        }
      }}
    >
      <p className="vy__hint">
        비워 두면 그 항목은 바뀌지 않습니다. 실거리만 먼저 알고 연료가 나중에 오는 경우를 위해
        모든 칸이 선택입니다.
      </p>

      <Field
        id={`ac-dist-${voyage.id}`}
        label={`실제 거리 (${DISPLAY_UNITS.distance})`}
        value={draft.actualDistanceNm}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualDistanceNm: value }))}
        error={errors.actualDistanceNm}
        inputMode="decimal"
        hint={`계획 ${quantity(voyage.plannedDistanceNm, DISPLAY_DIGITS.distanceNm)} ${DISPLAY_UNITS.distance}`}
      />

      <Field
        id={`ac-speed-${voyage.id}`}
        label={`실제 평균 속력 (${DISPLAY_UNITS.speed})`}
        value={draft.actualAvgSpeedKn}
        onChange={(value) => setDraft((prev) => ({ ...prev, actualAvgSpeedKn: value }))}
        error={errors.actualAvgSpeedKn}
        inputMode="decimal"
      />

      {voyage.fuelUses.map((use) => (
        <Field
          key={use.fuelType}
          id={`ac-fuel-${voyage.id}-${use.fuelType}`}
          label={`실제 ${use.fuelType} (${DISPLAY_UNITS.fuel})`}
          value={draft.actualFuelTon[use.fuelType] ?? ''}
          onChange={(value) =>
            setDraft((prev) => ({
              ...prev,
              actualFuelTon: { ...prev.actualFuelTon, [use.fuelType]: value },
            }))
          }
          error={errors[`actualFuelTon.${use.fuelType}`]}
          inputMode="decimal"
          hint={`계획 ${quantity(use.plannedFuelTon, DISPLAY_DIGITS.fuelTon)} ${DISPLAY_UNITS.fuel}`}
        />
      ))}

      <div className="vy__form-actions">
        <button type="submit" className="vy__submit" disabled={busy}>
          {busy ? '저장 중' : '실적 저장'}
        </button>
        <button type="button" className="vy__cancel" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
    </form>
  )
}

/**
 * 입력 한 칸.
 *
 * 오류를 `aria-describedby`로 잇고 `aria-invalid`를 세운다 — 색만으로 표시하면
 * 스크린 리더 사용자가 무엇이 잘못됐는지 알 수 없다(`DESIGN_SYSTEM §14`).
 * `AuthField`와 같은 규율이다.
 */
function Field({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  inputMode,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  hint?: string
  inputMode?: 'decimal' | 'numeric'
}) {
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  return (
    <div className="vy__field">
      <label className="vy__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={error ? 'vy__input vy__input--error' : 'vy__input'}
        value={value}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      {hint ? (
        <p className="vy__hint" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="vy__field-error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
