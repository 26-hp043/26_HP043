/**
 * 운항 기록 내보내기 규칙 — `API_SPEC §8.1` (`#890` · `PRD §5.1` MUST · `SCR-007`).
 *
 * ## 왜 이 폴더인가
 *
 * `PRD:636`은 `SCR-007`을 **「Data Import/Export」 한 항목**으로 규정하고, 가져오기는
 * 이미 이 폴더의 `ImportCsv.tsx`가 항차 패널 안에 두고 있다. 한쪽만 다른 화면에 두면
 * 정본이 한 화면으로 정한 것이 두 화면에 쪼개진다.
 *
 * `UIFLOW`에는 `SCR-007`이 없다 — `screens.ts` 주석이 적어 둔 대로 `UIFLOW`는
 * `SCR-00x` ID를 부여하지 않는다. `SCR-002`도 같은 상황을 **상위 문서 `PRD`를
 * 근거로** 해소한 선례가 있다(`screens.ts`의 「UIFLOW §2.2 매핑 표에 SCR-002 행이
 * 없다」 주석). 화면을 새로 만들지 않으므로 `AGENTS §3.2.1`의 UIFLOW 선행 요건에도
 * 걸리지 않는다.
 *
 * ## 서버가 정본이다
 *
 * 종류·형식 목록은 `services/data_export.py`의 `EXPORT_TYPES`·`EXPORT_FORMATS`가
 * 소유한다. 여기 사본을 두는 이유는 **선택지를 그릴 것이 필요해서**이고, 어긋나면
 * 서버가 422로 막는다 — 안전한 쪽으로 틀린다.
 */

/** `EXPORT_TYPES`의 사본 (`services/data_export.py`). */
export const EXPORT_TYPES = ['voyages', 'calculations', 'simulations'] as const
export type ExportType = (typeof EXPORT_TYPES)[number]

/** `EXPORT_FORMATS`의 사본. */
export const EXPORT_FORMATS = ['csv', 'json'] as const
export type ExportFormat = (typeof EXPORT_FORMATS)[number]

/**
 * 종류의 화면 이름.
 *
 * 서버 값을 그대로 보이지 않는다 — `calculations`가 무엇을 담는지는 영문 키가
 * 말해 주지 않는다. `#723`(등급 라벨)·`fuelTypes.ts`와 같은 규율이다.
 */
export const EXPORT_TYPE_LABELS: Record<ExportType, string> = {
  voyages: '항차 기록',
  calculations: '계산 이력',
  simulations: '연간 시뮬레이션',
}

/** 각 종류가 무엇을 담는지 한 줄. 고르기 전에 알아야 하는 것이다. */
export const EXPORT_TYPE_HINTS: Record<ExportType, string> = {
  voyages: '항차별 거리·연료·상태. 가져오기와 같은 표다.',
  calculations: '실행한 CII 계산의 입력·결과·해시.',
  simulations: '연간 시뮬레이션 실행 기록과 확률.',
}

/** 폼 상태. 전부 문자열이다 — 입력창의 값이 곧 상태다. */
export interface ExportFormState {
  type: string
  /** 빈 문자열이면 「전체 연도」 — 서버에 `year`를 보내지 않는다. */
  year: string
  format: string
}

export function initialExportForm(): ExportFormState {
  return { type: 'voyages', year: '', format: 'csv' }
}

export type ExportErrors = Record<string, string>

/**
 * 내보내기 조건 검증.
 *
 * **연도는 선택이다** — `§8.1`의 `year`가 optional이고, 「이 선박 전체」를 받는 것이
 * 정상 사용이다. 비어 있는 것은 오류가 아니다.
 */
export function validateExport(state: ExportFormState): ExportErrors {
  const errors: ExportErrors = {}

  if (!(EXPORT_TYPES as readonly string[]).includes(state.type)) {
    // 셀렉트로는 도달하지 않으나 오래된 상태가 남았을 때 서버 422를 기다리지 않는다.
    errors.type = `알 수 없는 종류입니다: ${state.type}`
  }
  if (!(EXPORT_FORMATS as readonly string[]).includes(state.format)) {
    errors.format = `알 수 없는 형식입니다: ${state.format}`
  }

  const year = state.year.trim()
  if (year !== '') {
    const parsed = Number(year)
    if (!Number.isInteger(parsed) || parsed < 2000 || parsed > 2100) {
      errors.year = '연도를 네 자리로 입력해 주세요.'
    }
  }

  return errors
}

/**
 * 검증을 통과한 상태를 쿼리스트링으로.
 *
 * **빈 연도는 키 자체를 넣지 않는다** — `year=`를 보내면 서버가 빈 문자열을 정수로
 * 읽으려다 422를 낸다. 생략이 「전체」다.
 */
export function exportQuery(state: ExportFormState): string {
  const params = new URLSearchParams({ type: state.type, format: state.format })
  const year = state.year.trim()
  if (year !== '') params.set('year', year)
  return params.toString()
}

/**
 * 서버가 이름을 주지 않았을 때 쓸 파일명.
 *
 * 서버는 `attachment; filename="voyages_2026.csv"`를 보내므로 평소에는 쓰이지 않는다.
 * 그래도 두는 이유는 **이름 없는 파일을 내려보내지 않기 위해서**다 — 브라우저가
 * `download`라는 이름으로 저장하면 사용자가 무엇을 받았는지 알 수 없다.
 */
export function fallbackFilename(state: ExportFormState): string {
  const year = state.year.trim()
  const stem = year === '' ? state.type : `${state.type}_${year}`
  return `${stem}.${state.format}`
}
