import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import './ScenarioAdoptPanel.css'
import { ErrorState } from '../../components/ErrorState'
import { voyagePath } from '../../layout/globalContext'
import { createApiVoyageCatalog, type VoyageOption } from '../../layout/voyageCatalog'
import { STATUS_LABELS } from '../voyage-management/voyageRules'
import type { VoyageStatus } from '../voyage-management/types'
import type { ScenarioComparisonProvider } from './provider'
import type { ScenarioAdoptResult, ScenarioResult } from './types'
import { adoptConfirmMessage, fieldLabel, isPlanning } from './adoptRules'

/**
 * 비교한 시나리오를 **항차 계획에 반영**한다 (`#580` · `API_SPEC §5.2`).
 *
 * 서버(`POST /scenarios/{id}/adopt`)는 `#58`로 있었고 화면 소비처가 0곳이었다. 사용자는
 * 세 안을 비교만 하고, 고른 값을 항차 계획으로 옮기려면 손으로 옮겨 적어야 했다.
 *
 * ## 흐름은 디자인 판정(`#580` 2026-08-23 · `rlatnals4114`)을 따른다
 *
 * - **계획만 바꾼다** — 서버가 이미 계획 단계(`DRAFT`·`PLANNED`) 항차만 받는다. 출항 뒤
 *   계획을 갈아 끼우면 계획 대비 실적 비교의 기준선이 사라진다(`services/scenario_adopt.py`)
 * - **같은 화면에 남는다** — 비교는 여러 안을 견주는 화면이라 채택했다고 끝나지 않는다.
 *   바뀐 것 · 재계산이 필요해졌다는 사실 · 그 항차로 가는 링크를 이 자리에 낸다
 * - **되돌리기는 없고, 채택 전에 알린다** — 서버가 이전 계획값을 보관하지 않아 되돌릴
 *   값이 없다. 다른 시나리오를 다시 반영하면 바뀐다는 것을 함께 알린다
 * - **`UPDATE_EXISTING_PLAN`만 연다** — 새 항차 만들기는 항구·출발 시각 입력이 더 붙는다
 *
 * ## 재계산 건수는 보이지 않는다
 *
 * 디자인 판정은 응답의 `invalidated_calculation_runs`를 보이자고 했으나, `#817`
 * (`calculation_run.voyage_id`가 늘 `NULL`)이 닫히기 전에는 그 수가 **항상 0이고
 * 참값이 아니다**(2026-09-08 착수 판정). 수 대신 **사실만** 말한다 — 계획이 바뀌었으니
 * 기존 결과는 다시 계산해야 한다. 이것은 무효화 표시가 실제로 붙었는지와 무관하게 참이다.
 *
 * ## 무엇을 근거로 고르는가
 *
 * 이 패널은 근거를 다시 보여 주지 않는다 — 위 카드가 CO₂·연료·소요 시간을 직항 대비로
 * 이미 보여 준다(`#799` · `#739`). 같은 속력의 우회는 CII가 같아 CII로는 고를 수 없다.
 * 어느 안이 낫다고 말하지 않는다(`PRD §11.2` 추천 금지).
 */

type VoyagesState = VoyageOption[] | 'loading' | 'failed'

type AdoptState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'done'; result: ScenarioAdoptResult; voyageName: string; scenarioName: string }
  | { status: 'error'; message: string }

export function ScenarioAdoptPanel({
  provider,
  vesselId,
  scenarios,
  stale,
  preferredVoyageId,
}: {
  provider: ScenarioComparisonProvider
  /** 비교를 **실행한** 선박 — 폼의 현재 값이 아니다. */
  vesselId: string
  scenarios: readonly ScenarioResult[]
  /** 입력이 바뀌어 결과가 이전 조건인가. 그때는 반영하지 않는다. */
  stale: boolean
  /** 상단바에서 고른 항차. 반영 가능한 항차면 기본 선택으로 쓴다. */
  preferredVoyageId: string | null
}) {
  const catalog = useMemo(() => createApiVoyageCatalog(), [])
  const [voyages, setVoyages] = useState<VoyagesState>('loading')
  const [scenarioId, setScenarioId] = useState('')
  const [voyageId, setVoyageId] = useState('')
  const [adopt, setAdopt] = useState<AdoptState>({ status: 'idle' })

  // 선박이 바뀌면 목록을 비우고 다시 받는다 — 앞 배의 항차를 뒤 배의 것으로 읽지 않게(`#874`).
  useEffect(() => {
    let alive = true
    setVoyages('loading')
    setVoyageId('')
    setAdopt({ status: 'idle' })
    catalog.listVoyages(vesselId).then(
      (rows) => {
        if (alive) setVoyages(rows.filter((row) => isPlanning(row.status)))
      },
      () => {
        // 실패를 `[]`로 두면 「반영할 항차가 없습니다」가 되어 원인이 뒤바뀐다.
        if (alive) setVoyages('failed')
      },
    )
    return () => {
      alive = false
    }
  }, [catalog, vesselId])

  // 사용자가 고르기 전의 기본값 — 상단바의 항차가 반영 가능하면 그것, 아니면 하나뿐일 때만.
  // 효과에서 상태를 덮지 않고 **렌더 중에 파생**한다 — 고른 값이 있으면 그것이 이긴다.
  const fallbackVoyageId = Array.isArray(voyages)
    ? (voyages.find((item) => item.id === preferredVoyageId)?.id ??
      (voyages.length === 1 ? voyages[0].id : ''))
    : ''
  const selectedVoyageId = voyageId || fallbackVoyageId

  const scenario = scenarios.find((item) => item.scenario_id === scenarioId)
  const voyage = Array.isArray(voyages)
    ? voyages.find((item) => item.id === selectedVoyageId)
    : undefined
  const ready = scenario !== undefined && voyage !== undefined && !stale

  const submit = async () => {
    if (!scenario || !voyage) return
    if (!globalThis.confirm(adoptConfirmMessage(voyage.displayName, scenario.scenario_name))) return
    setAdopt({ status: 'running' })
    try {
      const result = await provider.adopt(scenario.scenario_id, voyage.id)
      setAdopt({
        status: 'done',
        result,
        voyageName: voyage.displayName,
        scenarioName: scenario.scenario_name,
      })
    } catch (error: unknown) {
      setAdopt({
        status: 'error',
        message: error instanceof Error ? error.message : '계획에 반영하지 못했습니다.',
      })
    }
  }

  return (
    <section className="scenario-adopt" aria-labelledby="scenario-adopt-title">
      <h3 id="scenario-adopt-title" className="scenario-adopt__title">
        계획에 반영
        <span className="scenario-adopt__title-en"> Adopt to Plan</span>
      </h3>
      <p className="scenario-adopt__lead">
        고른 시나리오의 항해거리 · 평균 속력으로 <strong>계획 단계 항차</strong>(작성 중 ·
        계획 확정)의 계획값을 바꿉니다. 도착 예정 시각은 출발 예정 시각에 시나리오 소요
        시간을 더해 다시 정해집니다 — 출발 예정 시각이 없으면 비워집니다.
      </p>

      <div className="scenario-adopt__fields">
        <div className="scenario-adopt__field">
          <label htmlFor="scenario-adopt-scenario">시나리오</label>
          <select
            id="scenario-adopt-scenario"
            value={scenarioId}
            onChange={(event) => setScenarioId(event.target.value)}
          >
            <option value="">선택</option>
            {scenarios.map((item) => (
              <option key={item.scenario_id} value={item.scenario_id}>
                {item.scenario_name}
              </option>
            ))}
          </select>
        </div>

        {/* 목록이 없을 때 안내·실패가 **라벨 안**에 들어가지 않게 묶음을 `div`로 둔다. */}
        <div className="scenario-adopt__field">
          <label htmlFor="scenario-adopt-voyage">대상 항차</label>
          {voyages === 'loading' ? (
            <span className="scenario-adopt__note">항차 목록을 불러오는 중…</span>
          ) : voyages === 'failed' ? (
            <ErrorState level="region" size="compact" message="항차 목록을 불러오지 못했습니다." />
          ) : voyages.length === 0 ? (
            <span className="scenario-adopt__note">
              반영할 수 있는 항차가 없습니다. 작성 중이거나 계획 확정 상태인 항차만 바꿀 수 있습니다.
            </span>
          ) : (
            <select
              id="scenario-adopt-voyage"
              value={selectedVoyageId}
              onChange={(event) => setVoyageId(event.target.value)}
            >
              <option value="">선택</option>
              {voyages.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName} · {STATUS_LABELS[item.status as VoyageStatus] ?? item.status}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {stale ? (
        <p className="scenario-adopt__note" role="status">
          입력이 바뀌어 위 결과는 이전 조건의 값입니다. 다시 비교한 뒤 반영할 수 있습니다.
        </p>
      ) : null}

      <button
        type="button"
        className="scenario-adopt__submit"
        disabled={!ready || adopt.status === 'running'}
        onClick={submit}
      >
        {adopt.status === 'running' ? '반영하는 중…' : '계획에 반영'}
      </button>

      {adopt.status === 'error' ? (
        <ErrorState level="region" size="compact" message={adopt.message} />
      ) : null}

      {adopt.status === 'done' ? (
        <div className="scenario-adopt__result" role="status">
          <p>
            <strong>「{adopt.voyageName}」</strong> 항차의 계획에{' '}
            <strong>「{adopt.scenarioName}」</strong> 시나리오를 반영했습니다.
          </p>
          <p>
            바뀐 값 —{' '}
            {adopt.result.updated_fields.map(fieldLabel).join(' · ')}
          </p>
          <p>계획이 바뀌어 이 항차의 기존 계산 결과는 다시 계산해야 합니다.</p>
          <Link className="scenario-adopt__link" to={voyagePath(vesselId, adopt.result.voyage_id)}>
            반영한 항차 보기
          </Link>
        </div>
      ) : null}
    </section>
  )
}
