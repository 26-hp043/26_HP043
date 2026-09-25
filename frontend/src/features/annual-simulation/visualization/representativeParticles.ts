import type { Rating } from '../../voyage-cii/types'

const RATINGS: readonly Rating[] = ['A', 'B', 'C', 'D', 'E']

interface RepresentativeParticle {
  readonly id: number
  readonly rating: Rating
  readonly order: number
}

function seedOf(value: string): number {
  let hash = 2166136261
  for (const character of value) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619)
  return hash >>> 0
}

/** 확률을 100개 대표 점에 largest-remainder로 배분한다. raw sample을 재구성하지 않는다. */
export function representativeParticles(simulationId: string, probabilities: Readonly<Record<Rating, string>>): readonly RepresentativeParticle[] {
  const weights = RATINGS.map((rating) => Math.max(0, Number(probabilities[rating]) || 0))
  const total = weights.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return []
  const exact = weights.map((value) => value / total * 100)
  const counts = exact.map(Math.floor)
  const remaining = 100 - counts.reduce((sum, value) => sum + value, 0)
  const remainderOrder = exact.map((value, index) => ({ index, remainder: value - counts[index] }))
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index)
  for (let index = 0; index < remaining; index += 1) counts[remainderOrder[index].index] += 1

  let state = seedOf(simulationId)
  const random = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 2 ** 32 }
  return RATINGS.flatMap((rating, ratingIndex) => Array.from({ length: counts[ratingIndex] }, (_, index) => ({
    id: ratingIndex * 100 + index, rating, order: Math.floor(random() * 10_000),
  }))).sort((a, b) => a.order - b.order || a.id - b.id)
}
