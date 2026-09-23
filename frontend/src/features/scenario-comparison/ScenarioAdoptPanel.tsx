import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import './ScenarioAdoptPanel.css'
import { ErrorState } from '../../components/ErrorState'
import { voyagePath } from '../../layout/globalContext'
import { createApiVoyageCatalog, voyageOptionLabel, type VoyageOption } from '../../layout/voyageCatalog'
import { useSamplePorts } from '../ports/samplePorts'
import { STATUS_LABELS } from '../voyage-management/voyageRules'
import type { VoyageStatus } from '../voyage-management/types'
import type { ScenarioComparisonProvider } from './provider'
import type { ScenarioAdoptResult, ScenarioResult } from './types'
import { adoptConfirmMessage, fieldLabel, invalidatedMessage, isPlanning } from './adoptRules'
import { isOffice, useAuthUser } from '../../auth/session'
import { OFFICE_ONLY_ACTION_HINT } from '../auth/authRules'
import { useShowsLabelEn } from '../../i18n/core'

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
 * ## 재계산 건수를 보인다 (`#1077`)
 *
 * 디자인 판정은 응답의 `invalidated_calculation_runs`를 보이자고 했으나, `#817`
 * (`calculation_run.voyage_id`가 늘 `NULL`)이 닫히기 전에는 그 수가 **항상 0이고
 * 참값이 아니라** 유예했다(2026-09-08 착수 판정). **`#817`이 2026-09-11에 닫혀** 해제
 * 조건이 충족됐으므로 판정대로 보인다(`AGENTS §6.1` 유예 처리).
 *
 * 문구는 `invalidatedMessage`가 만든다 — **「없음」이 세 종류**라서다(미수신 · `0` ·
 * `n`건). 특히 `0`은 「계산 이력이 없다」와 「이미 전부 표시돼 있다」 **둘 다**일 수 있어
 * (`API_SPEC §5.2` 명시) 둘 중 하나로 단정하지 않는다. 어느 경우든 **사실**은 그대로
 * 남는다 — 계획이 바뀌었으니 기존 결과는 다시 계산해야 한다.
 *
 * ## 무엇을 근거로 고르는가
 *
 * 이 패널은 근거를 다시 보여 주지 않는다 — 위 카드가 CO₂·연료·소요 시간을 직항 대비로
 * 이미 보여 준다(`#799` · `#739`). 같은 속력의 우회는 CII가 같아 CII로는 고를 수 없다.
 * 어느 안이 낫다고 말하지 않는다(`PRD §11.2` 추천 금지).
 *
 * ## 채택은 사무직 전용이다 (`API_SPEC §1.2` · `#1325`)
 *
 * 비교(`POST /scenarios/compare`)는 두 역할 모두 쓰지만, 계획을 확정하는 반영
 * (`POST /scenarios/{id}/adopt`)은 사무직(`ADMIN` 포함)만 부른다. 현장직이 폼을 다
 * 채우고 확인 대화상자까지 지난 뒤에야 `403`을 받는 것은 「되는 것처럼 보이는」
 * 경험이라(`VesselManagement`·`AnnualSimulation`과 같은 이유), 버튼을 미리 잠그고
 * 이유를 `OFFICE_ONLY_ACTION_HINT`로 옆에 남긴다.
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
  const showsLabelEn = useShowsLabelEn()
  const catalog = useMemo(() => createApiVoyageCatalog(), [])
  // 항차 선택지의 구간을 저장 코드가 아니라 보이는 이름으로 적는다 (#1812). 조회에는
  // 쓰지 않는다 — 그리는 시점에 `voyageOptionLabel`로만 쓴다(아래 참조).
  const samplePorts = useSamplePorts()
  // 채택은 사무직 전용이다 (`API_SPEC §1.2` · #1325). 현장직은 폼을 읽되 반영 버튼이 잠긴다.
  const office = isOffice(useAuthUser())
  const [voyages, setVoyages] = useState<VoyagesState>('loading')
  const [scenarioId, setScenarioId] = useState('')
  const [voyageId, setVoyageId] = useState('')
  const [adopt, setAdopt] = useState<AdoptState>({ status: 'idle' })

  /*
   * 선박이 바뀌면 목록을 비우고 다시 받는다 — 앞 배의 항차를 뒤 배의 것으로 읽지 않게(`#874`).
   *
   * `samplePorts`를 의존성에 넣지 않는다(`#1812` 재작업) — 항구 목록이 항차 목록보다
   * 늦게 도착할 때 이 effect가 다시 돌면 `setVoyageId('')`·`setAdopt({status:'idle'})`가
   * 사용자가 이미 고른 항차 선택과 채택 상태를 지운다. 표시 이름은 조회와 무관하게
   * `voyageOptionLabel`이 그릴 때 만든다.
   */
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
    const voyageLabel = voyageOptionLabel(voyage, samplePorts)
    if (!globalThis.confirm(adoptConfirmMessage(voyageLabel, scenario.scenario_name))) return
    setAdopt({ status: 'running' })
    try {
      const result = await provider.adopt(scenario.scenario_id, voyage.id)
      setAdopt({
        status: 'done',
        result,
        voyageName: voyageLabel,
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
        {showsLabelEn ? (
          <span className="scenario-adopt__title-en" lang="en">
            {' '}
            Adopt to Plan
          </span>
        ) : null}
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
                  {voyageOptionLabel(item, samplePorts)} ·{' '}
                  {STATUS_LABELS[item.status as VoyageStatus] ?? item.status}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {stale ? (
        <p id="scenario-adopt-stale" className="scenario-adopt__note" role="status">
          입력이 바뀌어 위 결과는 이전 조건의 값입니다. 다시 비교한 뒤 반영할 수 있습니다.
        </p>
      ) : null}

      <button
        type="button"
        className="scenario-adopt__submit"
        disabled={!ready || adopt.status === 'running' || !office}
        /*
         * `ready`가 거짓인 세 이유 중 **화면에 사유가 뜨는 것은 `stale`뿐**이고,
         * 나머지 둘(시나리오·항차 미선택)은 바로 위 선택칸이 비어 있는 것으로
         * 드러난다 (`§14` 「비활성의 사유」 · `#1170` ⑵). 사무직 가드는 `stale`과
         * 겹치면 더 근본적인 사유(`office`)를 앞세운다 (`#1325`).
         */
        aria-describedby={
          !office ? 'scenario-adopt-office-only' : stale ? 'scenario-adopt-stale' : undefined
        }
        onClick={submit}
      >
        {adopt.status === 'running' ? '반영하는 중…' : '계획에 반영'}
      </button>

      {office ? null : (
        <span id="scenario-adopt-office-only" className="scenario-adopt__note">
          {OFFICE_ONLY_ACTION_HINT}
        </span>
      )}

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
          <p>{invalidatedMessage(adopt.result.invalidated_calculation_runs)}</p>
          <Link className="scenario-adopt__link" to={voyagePath(vesselId, adopt.result.voyage_id)}>
            반영한 항차 보기
          </Link>
        </div>
      ) : null}
    </section>
  )
}
