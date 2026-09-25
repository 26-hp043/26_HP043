/**
 * `/basemap/*` Range 서빙의 순수 부분 검사 (`#1909`).
 *
 * 케이스: (`TEST_PLAN §14.5` 정의 없음 — 배포 배선 회귀 테스트)
 *
 * Worker 런타임을 띄우지 않는다. 지키려는 것은 **헤더를 어떻게 구간으로 읽는가**이고
 * 그것은 순수 함수다. 런타임이 필요한 부분(자산을 받아 자르는 한 줄)은
 * `e2e/map-smoke.spec.ts`가 실제 지도가 뜨는지로 확인한다.
 *
 * 값의 근거는 RFC 9110 §14.1.2(`Range`)와 `pmtiles`의 `FetchSource`다 — 후자가
 * `bytes=0-16383`으로 헤더를 읽고, `416`이면 `Content-Range: bytes * /크기`를 보고
 * 다시 묻는다.
 */

import { describe, expect, it } from 'vitest'

import { contentRangeValue, parseByteRange, unsatisfiedRangeValue } from './_byteRange'

const SIZE = 15_017_319

describe('parseByteRange', () => {
  it('양끝을 적은 구간을 그대로 읽는다', () => {
    // PMTiles가 아카이브 머리를 읽을 때 실제로 보내는 값이다.
    expect(parseByteRange('bytes=0-16383', SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: 0, end: 16383 },
    })
    expect(parseByteRange('bytes=0-6', SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: 0, end: 6 },
    })
  })

  it('끝을 비우면 파일 끝까지다', () => {
    expect(parseByteRange('bytes=15017310-', SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: 15_017_310, end: SIZE - 1 },
    })
  })

  it('시작을 비우면 마지막 n바이트다', () => {
    expect(parseByteRange('bytes=-500', SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: SIZE - 500, end: SIZE - 1 },
    })
  })

  it('마지막 n바이트가 파일보다 크면 전체다', () => {
    // RFC 9110 §14.1.2 — 잘라 주지 않고 있는 데까지 준다.
    expect(parseByteRange(`bytes=-${SIZE + 1000}`, SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: 0, end: SIZE - 1 },
    })
  })

  it('끝을 파일 밖으로 적으면 있는 데까지 준다', () => {
    expect(parseByteRange(`bytes=15017310-${SIZE + 500}`, SIZE)).toEqual({
      kind: 'satisfiable',
      range: { start: 15_017_310, end: SIZE - 1 },
    })
  })

  it('시작이 파일 끝을 넘으면 만족시킬 수 없다', () => {
    // 여기서 전체를 주면 `pmtiles`가 「content-length가 요청보다 크다」로 멈춘다 —
    // `416`이어야 라이브러리가 크기를 보고 다시 묻는다.
    expect(parseByteRange(`bytes=${SIZE}-`, SIZE)).toEqual({ kind: 'unsatisfiable' })
    expect(parseByteRange(`bytes=${SIZE + 10}-${SIZE + 20}`, SIZE)).toEqual({
      kind: 'unsatisfiable',
    })
  })

  it('헤더가 없으면 손대지 않는다', () => {
    // 글리프(`fonts/*.pbf`)가 이 경로다 — 전체를 그대로 받아야 한다.
    expect(parseByteRange(null, SIZE)).toEqual({ kind: 'none' })
  })

  it('다루지 않는 형태는 전체로 접는다', () => {
    // 규격이 「서버는 Range를 무시해도 된다」로 적으므로(§14.2) 전체를 주는 쪽이 안전하다.
    expect(parseByteRange('bytes=0-1,5-6', SIZE)).toEqual({ kind: 'none' }) // 여러 구간
    expect(parseByteRange('items=0-6', SIZE)).toEqual({ kind: 'none' }) // 단위가 바이트가 아니다
    expect(parseByteRange('bytes=1.5-2', SIZE)).toEqual({ kind: 'none' })
    expect(parseByteRange('bytes=+1-2', SIZE)).toEqual({ kind: 'none' })
    expect(parseByteRange('bytes=6-1', SIZE)).toEqual({ kind: 'none' }) // 끝이 시작보다 앞
    expect(parseByteRange('bytes=-0', SIZE)).toEqual({ kind: 'none' }) // 0바이트 요청
    expect(parseByteRange('bytes=-', SIZE)).toEqual({ kind: 'none' })
  })

  it('빈 파일에는 줄 구간이 없다', () => {
    expect(parseByteRange('bytes=0-6', 0)).toEqual({ kind: 'none' })
  })
})

describe('contentRangeValue', () => {
  it('구간과 전체 크기를 적는다', () => {
    expect(contentRangeValue({ start: 0, end: 16383 }, SIZE)).toBe(`bytes 0-16383/${SIZE}`)
  })
})

describe('unsatisfiedRangeValue', () => {
  it('크기만 적는다', () => {
    expect(unsatisfiedRangeValue(SIZE)).toBe(`bytes */${SIZE}`)
  })
})
