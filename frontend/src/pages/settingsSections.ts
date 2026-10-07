import { REGULATION_PARAMETERS_ANCHOR } from '../features/parameters/referenceRules'

/**
 * 설정 화면의 절 목록 (`UIFLOW 2-6` · #1791).
 *
 * ## 목차가 절 목록을 따로 갖지 않는다
 *
 * 목차와 절이 각자 목록을 가지면 **목차에 없는 절**이나 **없는 자리로 가는 링크**가
 * 생기는데, 그 상태는 화면을 봐서는 드러나지 않는다 — 사용자는 없는 항목을 그리워할 수
 * 없고, 링크는 누르고 나서야 아무 데도 가지 않는다. `#441`이 선종 목록에서 세운 것과
 * 같은 판단이며, 여기서는 아예 **한 목록에서 둘 다** 만든다.
 *
 * `id`가 곧 앵커다. 규제 기준값의 것은 **밖에서 들어오는 링크가 이미 쓰고 있으므로**
 * (`#1239`의 세 자리) 여기서 새로 짓지 않고 그 상수를 가져온다.
 */
export interface SettingsSection {
  /** 앵커이자 절의 `id`. */
  id: string
  /** 목차에 적는 이름이자 절의 제목. 둘이 갈릴 자리를 만들지 않는다. */
  label: string
  /** 관리자에게만 보이는 절인가 (`#1301`). */
  adminOnly?: boolean
}

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  { id: 'account-info', label: '프로필' },
  /*
   * 표시 이름은 **자기 절**이다 (#2074).
   *
   * 종전에는 「계정 정보」 절 안쪽 맨 아래에 제목 없는 폼으로 들어 있어 **목차로는
   * 찾을 수 없었다** — 성격이 같은 「비밀번호 변경」·「탈퇴」는 각자 절을 갖는데
   * 이것만 아니었다. 「계정 정보」는 이제 **바꿀 수 없는 사실**(이메일 · 역할)만 진다.
   *
   * 이름은 `UIFLOW 2-6` 구성 표의 표현을 따른다(「프로필 · 계정 관리」 ·
   * `rlatnals4114` 2026-09-30 확정 · `AGENTS §7.3`).
   */
  { id: 'account-role', label: '팀 계정 · 역할', adminOnly: true },
  { id: 'password', label: '비밀번호 변경' },
  { id: 'withdrawal', label: '탈퇴' },
  { id: REGULATION_PARAMETERS_ANCHOR, label: '규제 기준값' },
]

/**
 * 지금 이 사람에게 보이는 절.
 *
 * **없는 자리로 가는 링크를 두지 않는다** — 관리자 전용 절(`계정 · 역할`)은 다른
 * 역할에게는 그려지지 않으므로 목차에도 없어야 한다. 두면 눌러서 아무 일도 일어나지
 * 않는 것을 겪고 나서야 안다.
 */
export function visibleSections(admin: boolean): SettingsSection[] {
  return SETTINGS_SECTIONS.filter((section) => admin || section.adminOnly !== true)
}

/** 절 하나를 `id`로 찾는다 — 절을 그리는 쪽이 제목을 여기서 가져간다. */
export function settingsSection(id: string): SettingsSection {
  const found = SETTINGS_SECTIONS.find((section) => section.id === id)
  if (found === undefined) throw new Error(`설정에 없는 절이다: ${id}`)
  return found
}
