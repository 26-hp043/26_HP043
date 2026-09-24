import { createRoot } from 'react-dom/client'
import { SimulationMap25D } from './SimulationMap25D'

// 실험 전용 해상 좌표. 제품 항차나 연간 시뮬레이션 결과로 해석하지 않는다.
const EXPERIMENT_COORDINATES = [
  [129.04, 35.1], [128.0, 33.5], [125.8, 30.5], [123.0, 26.0],
  [120.0, 21.0], [115.5, 17.0], [111.0, 12.0], [107.0, 7.0], [103.85, 1.29],
] as const

createRoot(document.getElementById('root')!).render(
  <SimulationMap25D route={{ source: 'experiment', coordinates: EXPERIMENT_COORDINATES }} />,
)
