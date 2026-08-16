import { describe, expect, it } from 'vitest'
import {
  filenameFrom,
  isReportable,
  sameTarget,
  statusLabel,
  targetOf,
  voyageLabel,
  yearOptions,
} from './reportRules'
import type { VoyageOption } from './types'

/**
 * 리포트 화면 규칙 (`#362`).
 *
 * 고정하는 것 셋.
 *
 * * **진행 중 항차를 리포트 대상으로 보지 않는 것** — 서버가 422로 막지만, 화면이
 *   먼저 알려 줘야 사용자가 다 고르고 나서 거부당하지 않는다.
 * * **미리보기가 지금 선택의 것인지 판정하는 것** — 아니면 다른 대상의 문서를
 *   보면서 다운로드를 누른다.
 * * **서버가 준 파일명을 쓰는 것** — 우리가 지어 내면 「서버 이름」과 「우리 이름」이
 *   섞여 어느 쪽인지 알 수 없다.
 */

const VOYAGE: VoyageOption = {
  id: 'vy-1',
  voyageNo: '2026-01',
  status: 'COMPLETED',
  regulationYear: 2026,
  departurePortName: 'Busan',
  arrivalPortName: 'MANILA',
  reportable: true,
}

describe('리포트 대상 판정', () => {
  it('완료·확정 항차만 대상이다', () => {
    expect(isReportable('COMPLETED')).toBe(true)
    expect(isReportable('CONFIRMED')).toBe(true)
  })

  it('진행 중 항차는 대상이 아니다', () => {
    // 실적이 확정되지 않은 값으로 문서를 만들면 리포트가 시점마다 달라진다.
    expect(isReportable('IN_PROGRESS')).toBe(false)
    expect(isReportable('PLANNED')).toBe(false)
    expect(isReportable('DRAFT')).toBe(false)
  })

  it('모르는 상태는 대상이 아니다 — 모르는 것을 되는 쪽으로 단정하지 않는다', () => {
    expect(isReportable('SOMETHING_NEW')).toBe(false)
  })
})

describe('표시', () => {
  it('항차 번호가 없어도 라벨을 만든다', () => {
    expect(voyageLabel({ ...VOYAGE, voyageNo: null })).toContain('(번호 없음)')
  })

  it('항구가 비면 경로를 지어 내지 않는다', () => {
    const label = voyageLabel({ ...VOYAGE, arrivalPortName: null })
    expect(label).not.toContain('→')
  })

  it('모르는 상태 코드는 코드를 그대로 보여 준다', () => {
    expect(statusLabel('COMPLETED')).toBe('완료')
    expect(statusLabel('WHATEVER')).toBe('WHATEVER')
  })
})

describe('연도 선택지', () => {
  it('올해부터 과거로 만든다 — 미래 연도는 언제나 빈 문서다', () => {
    expect(yearOptions(2026, 3)).toEqual([2026, 2025, 2024])
  })

  it('2019보다 이전으로 내려가지 않는다', () => {
    // voyage.regulation_year의 CHECK 하한이다 — 그보다 이전 해는 데이터가 있을 수 없다.
    expect(yearOptions(2021, 5)).toEqual([2021, 2020, 2019])
  })
})

describe('요청 대상 만들기', () => {
  it('연간 리포트는 선박과 연도로 만든다', () => {
    expect(targetOf('ANNUAL', { vesselId: 'v-1', voyageId: '', year: 2026 })).toEqual({
      kind: 'ANNUAL',
      vesselId: 'v-1',
      year: 2026,
    })
  })

  it('항차 리포트는 항차만 있으면 된다 — 항차가 선박을 안다', () => {
    expect(
      targetOf('VOYAGE', { vesselId: 'v-1', voyageId: 'vy-1', year: 2026 }),
    ).toEqual({ kind: 'VOYAGE', voyageId: 'vy-1' })
  })

  it('빠진 선택을 사유로 돌려준다 — 버튼만 비활성하면 왜인지 알 수 없다', () => {
    expect(targetOf('ANNUAL', { vesselId: '', voyageId: '', year: 2026 })).toContain(
      '선박',
    )
    expect(targetOf('VOYAGE', { vesselId: 'v-1', voyageId: '', year: 2026 })).toContain(
      '항차',
    )
  })
})

describe('미리보기 신선도', () => {
  it('같은 대상이면 같다', () => {
    const a = { kind: 'ANNUAL', vesselId: 'v-1', year: 2026 } as const
    expect(sameTarget(a, { kind: 'ANNUAL', vesselId: 'v-1', year: 2026 })).toBe(true)
  })

  it('연도만 달라도 다르다', () => {
    const a = { kind: 'ANNUAL', vesselId: 'v-1', year: 2026 } as const
    expect(sameTarget(a, { kind: 'ANNUAL', vesselId: 'v-1', year: 2025 })).toBe(false)
  })

  it('종류가 다르면 다르다', () => {
    expect(
      sameTarget(
        { kind: 'ANNUAL', vesselId: 'v-1', year: 2026 },
        { kind: 'VOYAGE', voyageId: 'vy-1' },
      ),
    ).toBe(false)
  })

  it('한쪽이 없으면 같지 않다', () => {
    expect(sameTarget(null, { kind: 'VOYAGE', voyageId: 'vy-1' })).toBe(false)
    expect(sameTarget(null, null)).toBe(true)
  })
})

describe('파일명 추출', () => {
  it('UTF-8 이름을 우선한다 — 사람이 읽는 쪽이다', () => {
    const header =
      'attachment; filename="annual-report-x.csv"; ' +
      "filename*=UTF-8''%EC%97%B0%EA%B0%84%20%EC%8B%A4%EC%A0%81.csv"
    expect(filenameFrom(header)).toBe('연간 실적.csv')
  })

  it('UTF-8이 없으면 ASCII로 내려간다', () => {
    expect(filenameFrom('attachment; filename="annual-report-x.pdf"')).toBe(
      'annual-report-x.pdf',
    )
  })

  it('깨진 인코딩으로 다운로드 전체를 실패시키지 않는다', () => {
    const header = 'attachment; filename="ok.csv"; filename*=UTF-8\'\'%E0%A4%A'
    expect(filenameFrom(header)).toBe('ok.csv')
  })

  it('헤더가 없으면 null이다 — 여기서 이름을 지어 내지 않는다', () => {
    expect(filenameFrom(null)).toBeNull()
    expect(filenameFrom('attachment')).toBeNull()
  })
})
