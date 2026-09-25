// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { SimulationEffects } from './SimulationEffects'
import { representativeParticles } from './representativeParticles'
import { getKnownRouteSource } from '../../map/routeGeometry'

const probabilities = { A: '0.10', B: '0.20', C: '0.30', D: '0.25', E: '0.15' } as const

afterEach(cleanup)

describe('Monte Carlo 대표 분포·배출 보조 표시', () => {
  it('100개를 확률 비율로 배분하고 simulation id별 배치를 재현한다', () => {
    const first = representativeParticles('simulation-1', probabilities)
    const again = representativeParticles('simulation-1', probabilities)
    expect(first).toEqual(again)
    expect(first).not.toEqual(representativeParticles('simulation-2', probabilities))
    expect(Object.fromEntries(['A', 'B', 'C', 'D', 'E'].map((rating) => [rating, first.filter((item) => item.rating === rating).length])))
      .toEqual({ A: 10, B: 20, C: 30, D: 25, E: 15 })
  })

  it('raw sample·실제 항차가 아니라는 설명과 문자 legend를 함께 제공한다', () => {
    render(<SimulationEffects simulationId="simulation-1" probabilities={probabilities} route={undefined} suppressParticles={false} />)
    expect(screen.getByText(/실제 Monte Carlo 표본이나 개별 항차가 아닙니다/)).toBeTruthy()
    expect(screen.getByRole('img', { name: /대표 분포 100개/ })).toBeTruthy()
    expect(screen.getByText('C: 0.30')).toBeTruthy()
    expect(screen.queryByLabelText('배출 보조 지표')).toBeNull()
  })

  it('실제 provider 배출 필드만 단위·물리 농도 아님 고지와 표시한다', () => {
    const route = {
      snapshotVoyageId: 'voyage-1', coordinates: [[129, 35], [130, 34]] as const,
      source: getKnownRouteSource('searoute/marnet')!, distanceNm: null,
      emission: { co2Value: '1200', co2Unit: 'kgCO₂' as const, intensityValue: '4.2', intensityUnit: 'gCO₂/(capacity·nm)', relativeIntensity: 0.6 },
    }
    render(<SimulationEffects simulationId="simulation-1" probabilities={probabilities} route={route} suppressParticles />)
    expect(screen.queryByRole('img', { name: /대표 분포/ })).toBeNull()
    expect(screen.getByText('CO₂ 1200 kgCO₂')).toBeTruthy()
    expect(screen.getByText(/물리적 배기가스 농도/)).toBeTruthy()
    expect(screen.getByRole('meter')).toHaveProperty('value', 0.6)
  })
})
