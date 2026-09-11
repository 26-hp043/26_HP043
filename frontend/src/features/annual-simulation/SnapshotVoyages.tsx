import { useState } from 'react'
import { DISPLAY_DIGITS, DISPLAY_UNITS, formatDecimalString, toDecimalInput } from '../../display/format'
import { ErrorState } from '../../components/ErrorState'
import { POLICY_LABELS, STATUS_LABELS } from '../voyage-management/voyageRules'
import type { InclusionPolicy, VoyageStatus } from '../voyage-management/types'
import { ANNUAL_COPY } from './copy'
import type { AnnualSimulationProvider, SnapshotVoyage } from './types'

/**
 * 「이 실행에 쓴 항차」 (`API_SPEC §6.3` · #992 · 결정 3-② 「범위 밖은 없다」).
 *
 * 확률·p50이 **어느 항차 목록으로** 나온 것인지 보여 준다. 스냅샷은 실행 시점의 사본이고
 * immutable이라(`TECH_SPEC §11`) 그 뒤에 항차를 고쳐도 여기 값은 바뀌지 않는다 — 그래서
 * 「지금 항차 목록」과 다를 수 있다는 것을 캡션이 말한다.
 *
 * **펼칠 때 불러온다.** 대부분의 사용자는 이 목록을 보지 않는다 — 결과마다 미리 받으면
 * 쓰지 않을 조회가 실행마다 한 번씩 는다.
 */
type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; rows: SnapshotVoyage[] }
  | { status: 'error'; message: string }

function number(value: number | string | null, digits: number): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = typeof value === 'number' ? toDecimalInput(value) : value
  return formatDecimalString(text, digits)
}

function statusText(status: string): string {
  return STATUS_LABELS[status as VoyageStatus] ?? status
}

function policyText(policy: string): string {
  return POLICY_LABELS[policy as InclusionPolicy] ?? policy
}

function fuelText(row: SnapshotVoyage): string {
  if (row.fuel_uses.length === 0) return '—'
  return row.fuel_uses
    .map((fu) => `${fu.fuel_type} ${number(fu.fuel_ton, DISPLAY_DIGITS.fuelTon)}${DISPLAY_UNITS.fuel}`)
    .join(' · ')
}

export function SnapshotVoyages({
  simulationId,
  voyageCount,
  provider,
}: {
  simulationId: string
  voyageCount: number
  provider: AnnualSimulationProvider
}) {
  const [state, setState] = useState<LoadState>({ status: 'idle' })

  async function load() {
    if (state.status !== 'idle' && state.status !== 'error') return
    setState({ status: 'loading' })
    try {
      setState({ status: 'ready', rows: await provider.snapshotVoyages(simulationId) })
    } catch (error: unknown) {
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : '항차를 불러오지 못했습니다.',
      })
    }
  }

  return (
    <details
      className="annual-sim__snapshot"
      onToggle={(event) => {
        if ((event.currentTarget as HTMLDetailsElement).open) void load()
      }}
    >
      <summary>
        {ANNUAL_COPY.snapshotVoyagesToggle} ({voyageCount}건)
      </summary>
      <p className="annual-sim__caption">{ANNUAL_COPY.snapshotVoyagesCaption}</p>
      {state.status === 'loading' ? (
        <p className="annual-sim__hint" role="status">
          {ANNUAL_COPY.snapshotVoyagesLoading}
        </p>
      ) : null}
      {state.status === 'error' ? (
        <ErrorState
          level="region"
          subject={ANNUAL_COPY.snapshotVoyagesErrorSubject}
          message={state.message}
        />
      ) : null}
      {state.status === 'ready' ? (
        <div className="annual-sim__tablewrap">
          <table className="annual-sim__table">
            <thead>
              <tr>
                <th scope="col">항차</th>
                <th scope="col">연간 반영</th>
                <th scope="col">당시 상태</th>
                <th scope="col" className="num">
                  거리 ({DISPLAY_UNITS.distance})
                </th>
                <th scope="col" className="num">
                  속력 ({DISPLAY_UNITS.speed})
                </th>
                <th scope="col">연료</th>
              </tr>
            </thead>
            <tbody>
              {state.rows.map((row) => (
                <tr key={row.snapshot_voyage_id}>
                  <th scope="row">{row.voyage_no || '—'}</th>
                  <td>{policyText(row.annual_inclusion_policy)}</td>
                  <td>{statusText(row.status_at_snapshot)}</td>
                  <td className="num">{number(row.distance_nm, DISPLAY_DIGITS.distanceNm)}</td>
                  <td className="num">{number(row.speed_kn, DISPLAY_DIGITS.speedKn)}</td>
                  <td>{fuelText(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </details>
  )
}
