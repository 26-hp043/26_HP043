import { SCREEN_BY_ID } from '../../screens'
import type { RegulationYearRow } from './referenceApiProvider'

/**
 * 「규제 기준값」 절의 순수 규칙 — `UIFLOW 2-6` 설정 안의 절 (`#1516` · `#1239` 결정 B·C·G).
 *
 * ## 절 앵커가 계약이다
 *
 * 세 자리(실시간 CII의 「기준(required)」 · 기능① 「계산 근거」 · 대시보드의 기준값 없음
 * 안내)가 **이 절로 온다.** 화면 ID는 늘리지 않는다 — 새 화면이 아니라 기존 설정 화면 안의
 * 절이므로(`screens.test.ts`가 `NAV_ORDER`를 잠근다) 링크는 **설정 경로 + 앵커**다. 앵커
 * 문자열이 두 곳(절의 `id` · 링크의 `href`)에 따로 적히면 한쪽만 바뀌어도 링크가 조용히
 * 페이지 맨 위로 떨어지므로 여기서 한 번만 정한다.
 */
export const REGULATION_PARAMETERS_ANCHOR = 'regulation-parameters'

/** 설정 화면의 「규제 기준값」 절로 가는 경로. 라우팅은 `screens.ts`의 설정 경로를 쓴다. */
export function regulationParametersPath(): string {
  return `${SCREEN_BY_ID.SETTINGS.path}#${REGULATION_PARAMETERS_ANCHOR}`
}

/**
 * 연료 탄소계수 표의 「이력 없음」 안내 — 표시 문구.
 *
 * 「없음」의 종류를 구분한다. 세 표(연도·기준선·경계)는 개정 때 옛 행을 **이행 행으로
 * 보존**하므로 「이전 판본 포함」이 무언가를 보여 주지만, 연료는 `DB_SCHEMA §7.2`의
 * 명시적 예외로 CF를 **제자리에서 갱신**해 옛 값이 남지 않는다. 같은 전환을 켰는데 연료
 * 표만 아무 변화가 없으면 사용자는 「고장」이나 「개정된 적 없음」으로 읽는다 — 둘 다
 * 아니므로 그 이유를 표 안에 적는다.
 */
export const FUEL_NO_HISTORY_NOTICE =
  '연료 탄소계수는 제자리 갱신이라 이전 값이 남지 않습니다. 개정되면 이 표의 값이 바로 바뀝니다.'

/**
 * 대시보드 머리의 「적용 기준」 한 줄 (`#1239` 결정 B) — 표시 문구.
 *
 * **그 연도의 활성 행이 없으면 `null`이다.** 값을 지어내지 않는다 — 없는 연도에 다른
 * 연도의 감축률을 붙여 보이면 화면은 멀쩡한데 내용이 틀린 상태가 된다(이 저장소가
 * 반복해 맞는 꼴). 이행 행(`isActive: false`)도 쓰지 않는다 — 계산은 활성 행만 본다
 * (`API_SPEC §7.5` 「개정의 반영 방식」).
 *
 * 감축률은 **서버 문자열 그대로** 잇는다(결정 G). 여기서 반올림하면 근거를 대조하려는
 * 사람에게 근거가 아닌 것을 보여 주게 된다(`VoyageCiiResult.tsx` 「계산 근거」와 같은 판단).
 */
export function appliedBaselineText(rows: readonly RegulationYearRow[], year: number): string | null {
  const row = rows.find((candidate) => candidate.isActive && candidate.year === year)
  if (!row) return null
  return `적용 기준 — ${row.sourceRef} · ${row.year}년 감축률 ${row.zFactorPercent}%`
}
