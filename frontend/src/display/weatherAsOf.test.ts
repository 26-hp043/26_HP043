/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { WEATHER_AS_OF_LABEL, WEATHER_NOT_APPLIED_TEXT, weatherAsOfText } from './weatherAsOf'
import { WARNING_MESSAGE } from '../features/voyage-cii/resultRules'

/**
 * 기상 기준 시각 한 줄의 문구 (`PRD §6.3` · #2135).
 *
 * 문구는 정본(`PRD §6.3` 표)과 같아야 한다 — 상수가 정본과 어긋나면 화면이 문서와 다른 말을 한다.
 */
const REPO = fileURLToPath(new URL('../../../', import.meta.url))
const PRD = readFileSync(`${REPO}PRD.md`, 'utf-8')
const API_SPEC = readFileSync(`${REPO}API_SPEC.md`, 'utf-8')

describe('기상 기준 시각 문구 (#2135)', () => {
  it('정본 문구 (PRD §6.3) — 「기상 기준 시각」 행의 문구와 같다', () => {
    expect(PRD).toContain(`\`${WEATHER_AS_OF_LABEL}: {시각}\``)
  })

  it('정본 문구 (PRD §6.3 · API_SPEC §1.6) — 보정 없이 계산한 문구가 세 곳에서 같다', () => {
    expect(PRD).toContain(`\`${WEATHER_NOT_APPLIED_TEXT}\``)
    expect(API_SPEC).toContain(`| \`WEATHER_NONE_FALLBACK\` | `)
    expect(API_SPEC).toContain(`| ${WEATHER_NOT_APPLIED_TEXT} |`)
    expect(WARNING_MESSAGE.WEATHER_NONE_FALLBACK).toBe(WEATHER_NOT_APPLIED_TEXT)
  })

  it('시각이 있으면 KST로 분까지 적는다 — DESIGN_SYSTEM §4.4', () => {
    expect(weatherAsOfText('2026-10-06T00:00:00Z')).toBe('기상 기준 시각: 2026. 10. 6. 09:00')
  })

  it('시각이 없으면 보정 없이 계산했다고 적는다', () => {
    expect(weatherAsOfText(null)).toBe(WEATHER_NOT_APPLIED_TEXT)
    expect(weatherAsOfText(undefined)).toBe(WEATHER_NOT_APPLIED_TEXT)
  })

  it('시각이 있는데 읽을 수 없으면 줄을 뺀다 — 보정했는데 「보정 없이」라고 적지 않는다', () => {
    expect(weatherAsOfText('2026-10-06T00:00')).toBeNull()
  })
})
