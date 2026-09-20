import type { MessageKey } from './ko'

/**
 * 영문 사전 (#1215).
 *
 * `Record<MessageKey, string>` — 키를 하나라도 빠뜨리면 **컴파일이 실패한다.**
 * 사전 완전성을 런타임 테스트(`i18n.test.tsx`)와 이중으로 잡는다.
 *
 * 문체 — 짧게. 라벨은 Title case 없이 sentence case, 안내문은 마침표 없이
 * 마친다(한국어 원문의 「값 자리 한 줄」 규칙 `PRD §6.4` 현행 관례 ②와 같은 자리다).
 */
export const en: Record<MessageKey, string> = {
  'shell.vessel': 'Vessel',
  'shell.voyage': 'Voyage',
  'shell.vessel.loading': 'Loading vessels…',
  'shell.vessel.failed': 'Failed to load vessels',
  'shell.vessel.none': 'No vessels',
  'shell.vessel.unselected': 'No vessel selected',
  'shell.voyage.selectVesselFirst': 'Select a vessel first',
  'shell.voyage.loading': 'Loading…',
  'shell.voyage.failed': 'Failed to load voyages',
  'shell.voyage.none': 'No voyages',
  'shell.voyage.unselected': 'No voyage selected',

  'shell.notification.aria': 'Notifications (coming soon)',
  'shell.notification.title': 'Notifications — coming soon',

  'shell.navTag': 'Coming soon',
  'shell.navTagOffice': 'Office only',

  'shell.logout': 'Sign out',

  'account.noDisplayName': 'No display name',
  'account.verified': 'Email verified',
  'account.unverified': 'Email verification pending',
  'account.theme': 'Theme',
  'account.language': 'Language',
  'account.settings': 'Settings',
  'account.settingsSub': 'Account · Password',

  'i18n.groupLabel': 'Language',
  'i18n.korean': 'Korean',
  'i18n.english': 'English',
}
