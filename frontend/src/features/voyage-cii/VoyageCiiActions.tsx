import { useEffect, useMemo, useState, type FormEvent } from 'react'
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
import type { ManagedVoyage } from '../voyage-management/types'
import type { ResultState } from './resultRules'
import { matchSamplePort, portOptionLabel, type SamplePort } from '../ports/samplePorts'
import type { VoyageCiiProvider } from './provider'
import { createVoyageCiiProvider } from './providerSelection'
import { Field } from '../../components/Field'

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
  estimator,
}: {
  state: ResultState
  stale: boolean
  /** 검사에서 갈아 끼우는 주입점. */
  provider?: VoyageManagementProvider
  /** 계획 저장 뒤 계산을 그 항차에 귀속해 한 번 더 기록할 때 쓴다 (#817). 검사 주입점. */
  estimator?: VoyageCiiProvider
}) {
  const api = useMemo(() => provider ?? createApiVoyageManagementProvider(), [provider])
  const calc = useMemo(() => estimator ?? createVoyageCiiProvider(), [estimator])
  const navigate = useNavigate()
  const [panelOpen, setPanelOpen] = useState(false)
  const [form, setForm] = useState<PlanSaveForm>(initialPlanSaveForm)
  const [errors, setErrors] = useState<PlanSaveErrors>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  /*
   * 전환에 실패한 DRAFT 항차 (`#1098` ⑵). 종전에는 `create`가 성공하고 `transition`이 409·네트워크
   * 오류로 실패하면 그 사실을 잊어, 다시 저장할 때마다 DRAFT·EXCLUDE 항차가 하나씩 쌓였다.
   * 같은 계획(같은 폼)으로 다시 저장하면 **전환만** 다시 한다. 폼이 바뀌었으면 새로 만든다.
   */
  const [pending, setPending] = useState<{ voyage: ManagedVoyage; draft: string } | null>(null)
  /*
   * 계산 결과가 바뀌면 앞 결과의 저장 문구·실패·보류 항차를 지운다 (`#1098` ⑴). 종전에는
   * 「계획 저장」을 다시 누를 때만 지워, 재계산한 새 결과 아래에 「저장했습니다」가 남았다.
   */
  const [failure, setFailure] = useState<string | null>(null)
  useEffect(() => {
    setSaved(null)
    setFailure(null)
    setPending(null)
  }, [state])
  const [exporting, setExporting] = useState(false)
  /* 샘플 항만 (#1005) — 못 받아도 항만명은 자유 입력이다. 패널을 열 때 한 번 받는다. */
  const [ports, setPorts] = useState<SamplePort[]>([])
  useEffect(() => {
    if (!panelOpen || ports.length > 0) return
    let alive = true
    api
      .samplePorts()
      .then((rows) => {
        if (alive) setPorts(rows)
      })
      .catch(() => {
        if (alive) setPorts([])
      })
    return () => {
      alive = false
    }
  }, [panelOpen, api, ports.length])

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
      const draft = planDraftFrom(request, form)
      const draftKey = JSON.stringify(draft)
      const created =
        pending !== null && pending.draft === draftKey
          ? pending.voyage
          : await api.create(request.vessel_id, draft)
      // 전환이 실패하면 다음 시도는 전환만 다시 한다 — DRAFT가 쌓이지 않는다 (⑵).
      setPending({ voyage: created, draft: draftKey })
      await api.transition(created, 'PLANNED', planPolicy(form))
      setPending(null)
      /*
       * 이 계산을 **새 항차에 귀속해 한 번 더 기록한다** (#817 · 결정 2-③ 「항차 컨텍스트가
       * 있는 요청만 귀속」). 방금 본 계산 이력은 항차가 생기기 전에 만들어져 항차가 없고,
       * 계산 이력은 고칠 수 없다(immutable). 같은 입력이라 값도 해시도 같다 — 달라지는 것은
       * 「이 항차의 계산」이라는 주소뿐이고, 그래야 이 항차의 계획이 바뀔 때 재계산 필요로 표시된다.
       */
      let attached = true
      try {
        await calc.estimate({ ...request, voyage_id: created.id })
      } catch {
        attached = false
      }
      const base = form.includeInAnnual
        ? '계획 항차로 저장했습니다. 연간 시뮬레이션의 잔여 계획에 반영됩니다.'
        : '계획 항차로 저장했습니다. 연간 시뮬레이션에는 반영하지 않았습니다.'
      setSaved(
        attached
          ? base
          : `${base} 다만 이 계산을 항차에 연결하지 못해, 계획이 바뀌어도 재계산 필요로 표시되지 않습니다.`,
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
        <p id="voyage-cii-actions-stale" className="voyage-cii-actions__note" role="status">
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
          /* 왜 못 누르는지 낭독에도 닿게 한다 (`§14` 「비활성의 사유」 · `#1170` ⑵). */
          aria-describedby={stale ? 'voyage-cii-actions-stale' : undefined}
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
          aria-describedby={stale ? 'voyage-cii-actions-stale' : undefined}
          onClick={() => navigate(annualSimulatorPath(request))}
        >
          연간 시뮬레이터에서 보기
        </button>
        <button
          type="button"
          className="voyage-cii-actions__button"
          disabled={stale || exporting}
          aria-describedby={stale ? 'voyage-cii-actions-stale' : undefined}
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
          <Field id="plan-voyage-no" label="항차 번호 (선택)" error={errors.voyageNo}>
            {(control) => (
              <input
                  {...control}
                className="voyage-cii-actions__control"
                value={form.voyageNo}
                onChange={(e) => update('voyageNo', e.target.value)}
              />
            )}
                    </Field>
          <datalist id="plan-ports">
            {ports.map((port) => (
              <option key={port.locode} value={port.name} label={portOptionLabel(port)} />
            ))}
          </datalist>
          <Field
            id="plan-departure"
            label="출발항"
            error={errors.departurePortName}
            hint={form.departureCoord ? '샘플 항만 — 좌표가 함께 저장됩니다.' : undefined}
          >
            {(control) => (
              <input
                  {...control}
                className="voyage-cii-actions__control"
                list="plan-ports"
                value={form.departurePortName}
                onChange={(e) => {
                  const match = matchSamplePort(ports, e.target.value)
                  update('departurePortName', match ? match.name : e.target.value)
                  update('departureCoord', match ? { lat: match.lat, lon: match.lon } : null)
                }}
              />
            )}
                    </Field>
          <Field
            id="plan-arrival"
            label="도착항"
            error={errors.arrivalPortName}
            hint={form.arrivalCoord ? '샘플 항만 — 좌표가 함께 저장됩니다.' : undefined}
          >
            {(control) => (
              <input
                  {...control}
                className="voyage-cii-actions__control"
                list="plan-ports"
                value={form.arrivalPortName}
                onChange={(e) => {
                  const match = matchSamplePort(ports, e.target.value)
                  update('arrivalPortName', match ? match.name : e.target.value)
                  update('arrivalCoord', match ? { lat: match.lat, lon: match.lon } : null)
                }}
              />
            )}
                    </Field>
          <Field
            id="plan-departure-at"
            label="출항 예정 시각"
            error={errors.plannedDepartureAt}
            hint="도착 예정 시각은 거리 ÷ 속력으로 채웁니다."
          >
            {(control) => (
              <input
                  {...control}
                className="voyage-cii-actions__control"
                type="datetime-local"
                value={form.plannedDepartureAt}
                onChange={(e) => update('plannedDepartureAt', e.target.value)}
              />
            )}
                    </Field>
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

