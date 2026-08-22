/**
 * 연료 표시 문구 (#598).
 *
 * ## 왜 화면이 이름을 갖는가
 *
 * 서버가 내려주는 `display_name`은 `MEPC.364(79)` 원문 표기다 — `Heavy Fuel Oil` ·
 * `Diesel/Gas Oil`. `DB_SCHEMA §3.2` 값 표에 그대로 실려 있고, **`AGENTS §4.6` 기준
 * 정본 문구**라 화면이 임의로 바꿀 수 없다. 규제 문서와 대조할 때 필요한 이름이다.
 *
 * 그런데 화면에 보여야 하는 것은 **읽는 사람의 언어**다. 선종이 정확히 같은 상황에서
 * 이미 답을 냈다 — `PRD §3.4.3`이 영문 선종명을 확정했는데도 화면·리포트는
 * `shipTypes.ts`의 한국어를 쓴다. 그것이 **표시 문구**다.
 *
 * 이 파일은 그 구조를 연료에 그대로 복제한 것이다.
 *
 * ```
 * 정본 문구  display_name   MEPC.364(79)      서버가 내려준다
 * 표시 문구  label          이 파일           화면·리포트가 쓴다
 * 계약값     code           API_SPEC §7.2     요청에 실린다
 * ```
 *
 * ## 코드를 함께 보인다
 *
 * `code`는 계약값이므로 셀렉트에 병기한다 — `중유 (HFO)`. `#135`가 연료 셀렉트에,
 * `shipTypes.ts`가 선종에 세운 같은 규칙이다. 병기가 `중유`·`경질중유`를 가르는
 * 역할도 한다.
 *
 * ## 서버(리포트)와 어긋나면 테스트가 실패한다
 *
 * 리포트 PDF·CSV는 서버가 만들고 같은 문구가 필요하다(`reports/labels.py`의
 * `FUEL_TYPE_LABELS`). **이 파일이 원본이고** 서버가 옮겨 적는다 —
 * `tests/test_reports.py`가 이 파일을 읽어 대조하므로 한쪽만 고치면 CI가 잡는다.
 * 선종이 같은 방식으로 잠겨 있다.
 *
 * ## 모르는 코드는 코드를 그대로 보인다
 *
 * 서버에 연료가 늘면 이 표에 없는 코드가 내려온다. 그때 **빈 칸이나 「기타」로
 * 뭉개지 않는다** — 사용자가 무엇을 고르는지 모르게 되고, 표가 낡았다는 사실도
 * 사라진다. 코드가 보이면 적어도 무엇인지 물어볼 수 있다.
 */

/**
 * 8종. 순서는 `DB_SCHEMA §3.2` 값 표를 따른다.
 *
 * ⚠️ **표시 문구다.** 디자인·도메인 담당이 문서 개정 없이 바꿀 수 있다
 * (`AGENTS §4.6`). 바꿀 때 `reports/labels.py`도 함께 고쳐야 하며, 잊으면
 * `test_reports.py`가 실패한다.
 */
export const FUEL_TYPE_LABELS: Readonly<Record<string, string>> = {
  DIESEL_GAS_OIL: '디젤·가스유',
  LFO: '경질중유',
  HFO: '중유',
  LPG_PROPANE: 'LPG(프로판)',
  LPG_BUTANE: 'LPG(부탄)',
  LNG: '액화천연가스',
  METHANOL: '메탄올',
  ETHANOL: '에탄올',
}

/** 표시 문구. 모르는 코드는 코드를 그대로 돌려준다. */
export function fuelTypeLabel(code: string): string {
  return FUEL_TYPE_LABELS[code] ?? code
}

/**
 * 셀렉트 한 줄 — `중유 (HFO)`.
 *
 * 모르는 코드는 `HFO (HFO)`가 되지 않도록 코드 하나만 낸다.
 */
export function fuelTypeOptionText(code: string): string {
  const label = FUEL_TYPE_LABELS[code]
  return label === undefined ? code : `${label} (${code})`
}
