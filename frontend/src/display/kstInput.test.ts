/**
 * 입력 칸의 시각은 KST다 — `DESIGN_SYSTEM §4.4` 🔒 (`#1686`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 표시 규칙 가드)
 *
 * ## 이 파일이 지키는 것
 *
 * `§4.4`는 기록 시각의 시간대를 **KST 고정**으로 못박고 *「브라우저 시간대를 따르지
 * 않는다」*고 적는다. 표시(`formatTimestamp`)는 그것을 따랐지만 **입력 칸은 규칙 밖에**
 * 있어, 같은 값이 목록과 편집 칸에서 다르게 보였다 — LA에서는 날짜까지 달랐다.
 *
 * 그래서 아래 기대값은 **어느 시간대에서 돌려도 같다.** 종전 구현으로 되돌리면 이 파일은
 * KST 기기에서만 초록이 되고, `TZ=UTC`·`TZ=America/Los_Angeles`에서 붉어진다. 그 성질이
 * 이 검사의 요점이므로 **기대값을 KST 리터럴로 적는다** — 기기에서 계산해 비교하면
 * 종전 구현도 통과한다(자기 자신과 비교하는 검사가 된다).
 */

import { describe, expect, it, vi } from 'vitest'

import { currentKstYear, formatTimestamp, kstInputToIso, kstYear, toKstInput } from './format'

/** `#1686` 본문의 실측 표에 쓰인 값이다. */
const INSTANT = '2026-09-20T00:30:00Z'

describe('입력 칸의 KST 변환 (#1686 · §4.4 🔒)', () => {
  it('표시와 입력 칸이 같은 시각을 말한다', () => {
    // 이것이 이슈가 관측한 어긋남이다 — 목록 09:30 / 편집 칸 00:30(UTC 브라우저).
    expect(formatTimestamp(INSTANT)).toContain('09:30')
    expect(toKstInput(INSTANT)).toBe('2026-09-20T09:30')
  })

  it('넣은 값과 되돌린 값이 같다 — 왕복', () => {
    const local = '2026-09-20T09:30'
    // `toISOString()`은 밀리초를 적는다 — 순간이 같은지를 본다.
    expect(kstInputToIso(local)).toBe('2026-09-20T00:30:00.000Z')
    expect(new Date(kstInputToIso(local) as string).getTime()).toBe(new Date(INSTANT).getTime())
    expect(toKstInput(kstInputToIso(local) as string)).toBe(local)
  })

  it('날짜가 바뀌는 자리에서도 KST로 끊는다', () => {
    // UTC 자정 직후는 KST로 그날 오전 9시다. 기기 시간대로 읽으면 날짜가 갈린다.
    expect(toKstInput('2026-01-01T00:00:00Z')).toBe('2026-01-01T09:00')
    // KST 자정은 UTC 전날 15시다 — `hour12: false`가 `24`를 내는 구현에서도 `00`이어야 한다.
    expect(toKstInput('2025-12-31T15:00:00Z')).toBe('2026-01-01T00:00')
    expect(kstInputToIso('2026-01-01T00:00')).toBe('2025-12-31T15:00:00.000Z')
  })

  it('한국은 서머타임이 없다 — 1월과 7월의 시차가 같다', () => {
    /*
     * `kstInputToIso`가 `+09:00`을 문자열로 붙이는 근거다(1988년이 마지막이었다).
     * 제도가 바뀌면 이 검사가 먼저 붉어진다 — 전제를 주석에만 두면 아무도 모른다.
     */
    const offset = (iso: string): number => {
      const at = new Date(iso)
      const kst = new Date(
        new Intl.DateTimeFormat('en-US', {
          timeZone: 'Asia/Seoul',
          hour12: false,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
          .format(at)
          .replace(/(\d+)\/(\d+)\/(\d+), (\d+):(\d+):(\d+)/, '$3-$1-$2T$4:$5:$6Z'),
      )
      return (kst.getTime() - at.getTime()) / 3_600_000
    }
    expect(offset('2026-01-15T00:00:00Z')).toBe(9)
    expect(offset('2026-07-15T00:00:00Z')).toBe(9)
  })

  it('읽을 수 없는 값은 빈칸과 `null`이다 — 틀린 시각을 보여 주지 않는다', () => {
    expect(toKstInput('')).toBe('')
    expect(toKstInput(null)).toBe('')
    expect(toKstInput('어제')).toBe('')
    expect(kstInputToIso('')).toBeNull()
    // 초가 붙은 값은 입력 칸의 꼴이 아니다 — 칸 모양이 항차마다 달라진다(`#873`).
    expect(kstInputToIso('2026-09-20T09:30:00')).toBeNull()
    expect(kstInputToIso('2026-13-40T99:99')).toBeNull()
  })

  it('달력에 없는 날짜는 `null`이다 — 다음 달로 굴리지 않는다 (#2124)', () => {
    // 종전에는 `2026-02-31T09:30`이 `2026-03-03T00:30:00.000Z`가 됐다.
    expect(kstInputToIso('2026-02-31T09:30')).toBeNull()
    expect(kstInputToIso('2026-02-30T09:30')).toBeNull()
    expect(kstInputToIso('2026-04-31T00:00')).toBeNull()
    expect(kstInputToIso('2026-00-10T09:30')).toBeNull()
    expect(kstInputToIso('2026-06-00T09:30')).toBeNull()
  })

  it('윤년의 2월 29일만 받는다 (#2124)', () => {
    expect(kstInputToIso('2024-02-29T09:30')).toBe('2024-02-29T00:30:00.000Z')
    expect(kstInputToIso('2026-02-29T09:30')).toBeNull()
    // 100으로 나뉘는 해는 400으로도 나뉘어야 윤년이다.
    expect(kstInputToIso('2000-02-29T09:30')).not.toBeNull()
    expect(kstInputToIso('2100-02-29T09:30')).toBeNull()
  })

  it('월말은 그 달의 마지막 날까지 받는다 (#2124)', () => {
    expect(kstInputToIso('2026-02-28T23:59')).toBe('2026-02-28T14:59:00.000Z')
    expect(kstInputToIso('2026-04-30T23:59')).toBe('2026-04-30T14:59:00.000Z')
    expect(kstInputToIso('2026-12-31T23:59')).toBe('2026-12-31T14:59:00.000Z')
  })

  it('`24:00`·`23:60`은 다음 날·다음 시로 굴리지 않는다 (#2124)', () => {
    // `Date`는 `T24:00:00`을 다음 날 0시로 읽는다 — 사용자가 적은 날짜와 다른 날이 된다.
    expect(kstInputToIso('2026-09-20T24:00')).toBeNull()
    expect(kstInputToIso('2026-09-20T23:60')).toBeNull()
    expect(kstInputToIso('2026-09-20T23:59')).not.toBeNull()
    expect(kstInputToIso('2026-09-20T00:00')).toBe('2026-09-19T15:00:00.000Z')
  })

  it('받은 값은 적은 그대로 되돌아온다 — 굴렀으면 왕복이 깨진다 (#2124)', () => {
    for (const local of ['2024-02-29T09:30', '2026-02-28T23:59', '2026-12-31T23:59', '2026-01-01T00:00']) {
      expect(toKstInput(kstInputToIso(local) as string), local).toBe(local)
    }
  })
})

/**
 * 「올해」의 해도 KST로 센다 — `DESIGN_SYSTEM §4.4` 🔒 (`#2056`).
 *
 * 연간 등급 관리의 「이대로면 …」 한 줄은 실행한 규제연도가 기준 시각 `as_of`의 해와 같을 때만
 * 싣는다. 서버는 `as_of`를 UTC로 주므로 UTC 달력으로 읽으면 KST 1월 1일 0시~9시의 실행이
 * 지난해가 되고, 기기 시간대로 읽으면 기기마다 다른 해가 된다. 기대값은 위와 같은 이유로
 * **KST 리터럴**이다 — 기기에서 계산해 비교하면 기기 시간대 구현도 통과한다.
 */
describe('순간의 KST 달력 해 (#2056 · §4.4 🔒)', () => {
  it('UTC로는 아직 지난해인 새해 첫 아홉 시간을 올해로 센다', () => {
    // UTC 2025-12-31 15:00 = KST 2026-01-01 00:00 — 여기서 갈린다.
    expect(kstYear('2025-12-31T15:00:00Z')).toBe(2026)
    expect(kstYear('2025-12-31T14:59:59Z')).toBe(2025)
    // UTC 달력과 KST 달력이 갈리는 값 — UTC 해(2025)를 내면 시간대를 고정하지 않은 것이다.
    expect(kstYear('2025-12-31T23:30:00Z')).toBe(2026)
  })

  it('해가 갈리지 않는 값은 그대로다 — `Date`도 받는다', () => {
    expect(kstYear('2026-09-21T05:24:00Z')).toBe(2026)
    expect(kstYear(new Date('2026-09-21T05:24:00Z'))).toBe(2026)
  })

  it('읽을 수 없는 값은 `null` — 지어낸 해로 판정하지 않는다', () => {
    expect(kstYear('어제')).toBeNull()
    expect(kstYear('')).toBeNull()
  })

  it('오프셋이 없는 문자열은 `null` — 기기 시간대로 읽지 않는다(닫힌 실패)', () => {
    // `Date`는 오프셋 없는 값을 기기 시간대로 읽는다 — 통과시키면 기기마다 다른 해가 뒷문으로 돌아온다.
    expect(kstYear('2025-12-31T23:30:00')).toBeNull()
    expect(kstYear('2026-01-01')).toBeNull()
    expect(kstYear('2026-01-01T09:30')).toBeNull()
    // 오프셋 세 꼴은 모두 받는다 — `Z` · `±hh:mm` · `±hhmm`.
    expect(kstYear('2025-12-31T23:30:00Z')).toBe(2026)
    expect(kstYear('2025-12-31T23:30:00+00:00')).toBe(2026)
    expect(kstYear('2025-12-31T23:30:00+0000')).toBe(2026)
    expect(kstYear('2026-01-01T08:59:00+09:00')).toBe(2026)
    expect(kstYear('2025-12-31T23:59:00-05:00')).toBe(2026)
  })
})

describe('연도를 고르지 않았을 때의 올해 (#2131)', () => {
  it('지금 순간의 KST 달력 해다 — 기기 시간대와 무관하다', () => {
    // UTC 2025-12-31 17:00 = KST 2026-01-01 02:00 — UTC 기기라면 `getFullYear()`는 2025다.
    expect(currentKstYear(new Date('2025-12-31T17:00:00Z'))).toBe(2026)
    expect(currentKstYear(new Date('2025-12-31T14:59:59Z'))).toBe(2025)
  })

  it('인자 없이 부르면 시스템 시각을 읽는다', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      vi.setSystemTime(new Date('2025-12-31T17:00:00Z'))
      expect(currentKstYear()).toBe(2026)
    } finally {
      vi.useRealTimers()
    }
  })
})
