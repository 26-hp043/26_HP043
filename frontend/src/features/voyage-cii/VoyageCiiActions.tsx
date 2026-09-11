import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import './VoyageCiiActions.css'
import { vesselPath } from '../../layout/globalContext'
import {
  createApiVoyageManagementProvider,
  type VoyageManagementProvider,
} from '../voyage-management/apiProvider'
import {
  annualSimulatorPath,
  csvExportQuery,
  csvFallbackName,
  initialPlanSaveForm,
  planDraftFrom,
  planPolicy,
  validatePlanSave,
  type PlanSaveErrors,
  type PlanSaveForm,
} from './actionRules'
import type { ResultState } from './resultRules'

/**
 * 기능① 결과 화면의 사용자 액션 3종 (`PRD §10.5` · #891).
 *
 * 「계산하기」 한 버튼뿐이던 자리에 **계획 저장 · 연간 시뮬레이터에서 보기 · CSV 다운로드**를
 * 붙인다. 규칙은 `actionRules.ts`에 있고, 이 컴포넌트는 상태를 옮기고 서버를 부른다.
 *
 * ## 입력이 바뀌면 멈춘다
 *
 * 결과 카드가 「입력이 바뀌었다」를 표시하는 상태(`#727`)에서는 세 액션을 막는다. 저장·
 * 내보내기는 **보낸 요청**의 값으로 하므로 동작은 맞지만, 화면의 입력과 다른 값으로 항차가
 * 만들어지면 사용자는 방금 고친 값이 저장된 줄 안다.
 *
 * ## 계획 저장은 작은 입력 단계를 거친다
 *
 * 계산은 거리·속력·연료만 알아 **어디서 어디로 언제 떠나는지를 모른다.** 그 셋을 묻는다 —
 * 원본 값을 몰래 채우지 않는 것이 기능②의 「새 항차로 채택」과 같은 규율이다.
 */
export function VoyageCiiActions({
  state,
  stale,
  provider,
}: {
  state: ResultState
  stale: boolean
  /** 검사에서 갈아 끼우는 주입점. */
  provider?: VoyageManagementProvider
}) {
  const api = useMemo(() => provider ?? createApiVoyageManagementProvider(), [provider])
  const navigate = useNavigate()
  const [panelOpen, setPanelOpen] = useState(false)
  const [form, setForm] = useState<PlanSaveForm>(initialPlanSaveForm)
  const [errors, setErrors] = useState<PlanSaveErrors>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  if (state.status !== 'success') return null
  const { request, response } = state

  function update<K extends keyof PlanSaveForm>(key: K, value: PlanSaveForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  async function savePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving) return
    const found = validatePlanSave(form)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSaving(true)
    setFailure(null)
    try {
      // 생성은 늘 `DRAFT`·`EXCLUDE`다(`API_SPEC §3.3` [EXT-P0-4]) — `PLANNED` 전환에서 정책을 싣는다.
      const created = await api.create(request.vessel_id, planDraftFrom(request, form))
      await api.transition(created, 'PLANNED', planPolicy(form))
      setSaved(
        form.includeInAnnual
          ? '계획 항차로 저장했습니다. 연간 시뮬레이션의 잔여 계획에 반영됩니다.'
          : '계획 항차로 저장했습니다. 연간 시뮬레이션에는 반영하지 않았습니다.',
      )
      setPanelOpen(false)
      setForm(initialPlanSaveForm())
    } catch (error) {
      setFailure(error instanceof Error ? error.message : '계획을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  async function downloadCsv() {
    if (exporting) return
    setExporting(true)
    setFailure(null)
    try {
      await api.exportData(request.vessel_id, csvExportQuery(response), csvFallbackName(response))
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'CSV를 받지 못했습니다.')
    } finally {
      setExporting(false)
    }
  }

  return (
    <section className="voyage-cii-actions" aria-labelledby="voyage-cii-actions-title">
      <h3 id="voyage-cii-actions-title" className="voyage-cii-actions__title">
        이 결과로
      </h3>

      {stale ? (
        <p className="voyage-cii-actions__note" role="status">
          입력이 바뀌었습니다. 다시 계산한 뒤 저장하거나 내보내 주세요.
        </p>
      ) : null}

      <div className="voyage-cii-actions__buttons">
        <button
          type="button"
          className="voyage-cii-actions__button"
          aria-expanded={panelOpen}
          aria-controls="voyage-cii-plan-save"
          disabled={stale}
          onClick={() => {
            setSaved(null)
            setPanelOpen((open) => !open)
          }}
        >
          계획 저장
        </button>
        <button
          type="button"
          className="voyage-cii-actions__button"
          disabled={stale}
          onClick={() => navigate(annualSimulatorPath(request))}
        >
          연간 시뮬레이터에서 보기
        </button>
        <button
          type="button"
          className="voyage-cii-actions__button"
          disabled={stale || exporting}
          onClick={downloadCsv}
        >
          {exporting ? 'CSV 준비 중…' : 'CSV 다운로드'}
        </button>
      </div>

      {saved ? (
        <p className="voyage-cii-actions__done" role="status">
          {saved}{' '}
          <Link className="voyage-cii-actions__link" to={vesselPath(request.vessel_id)}>
            선박 상세에서 항차 보기
          </Link>
        </p>
      ) : null}
      {failure ? (
        <p className="voyage-cii-actions__error" role="alert">
          {failure}
        </p>
      ) : null}

      {panelOpen && !stale ? (
        <form
          id="voyage-cii-plan-save"
          className="voyage-cii-actions__panel"
          onSubmit={savePlan}
          noValidate
        >
          <p className="voyage-cii-actions__lead">
            이 계산의 거리·속력·연료로 계획 항차를 만듭니다. 출발·도착과 출항 시각을 넣어 주세요.
          </p>
          <PlanField id="plan-voyage-no" label="항차 번호 (선택)" error={errors.voyageNo}>
            <input
              id="plan-voyage-no"
              value={form.voyageNo}
              onChange={(e) => update('voyageNo', e.target.value)}
            />
          </PlanField>
          <PlanField id="plan-departure" label="출발항" error={errors.departurePortName}>
            <input
              id="plan-departure"
              value={form.departurePortName}
              aria-invalid={Boolean(errors.departurePortName)}
              onChange={(e) => update('departurePortName', e.target.value)}
            />
          </PlanField>
          <PlanField id="plan-arrival" label="도착항" error={errors.arrivalPortName}>
            <input
              id="plan-arrival"
              value={form.arrivalPortName}
              aria-invalid={Boolean(errors.arrivalPortName)}
              onChange={(e) => update('arrivalPortName', e.target.value)}
            />
          </PlanField>
          <PlanField
            id="plan-departure-at"
            label="출항 예정 시각"
            error={errors.plannedDepartureAt}
            hint="도착 예정 시각은 거리 ÷ 속력으로 채웁니다."
          >
            <input
              id="plan-departure-at"
              type="datetime-local"
              value={form.plannedDepartureAt}
              aria-invalid={Boolean(errors.plannedDepartureAt)}
              onChange={(e) => update('plannedDepartureAt', e.target.value)}
            />
          </PlanField>
          <label className="voyage-cii-actions__check" htmlFor="plan-include">
            <input
              id="plan-include"
              type="checkbox"
              checked={form.includeInAnnual}
              onChange={(e) => update('includeInAnnual', e.target.checked)}
            />
            연간 시뮬레이션의 잔여 계획에 반영
          </label>
          <div className="voyage-cii-actions__buttons">
            <button type="submit" className="voyage-cii-actions__submit" disabled={saving}>
              {saving ? '저장 중…' : '계획으로 저장'}
            </button>
            <button
              type="button"
              className="voyage-cii-actions__button"
              onClick={() => setPanelOpen(false)}
            >
              취소
            </button>
          </div>
        </form>
      ) : null}
    </section>
  )
}

function PlanField({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="voyage-cii-actions__field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? <p className="voyage-cii-actions__hint">{hint}</p> : null}
      {error ? (
        <p className="voyage-cii-actions__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
