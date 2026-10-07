import { AccountPanel } from '../features/account/AccountPanel'
import { RegulationParametersSection } from '../features/parameters/RegulationParametersSection'
import { PageHeader } from '../components/PageHeader'
import { isAdmin, useAuthUser } from '../auth/session'
import { Tabs, type TabDef } from '../components/Tabs'
import { REGULATION_PARAMETERS_ANCHOR } from '../features/parameters/referenceRules'
import { useEffect, useState } from 'react'
import './SettingsPage.css'

/**
 * 설정 화면 — `UIFLOW 2-6` (`#506` · `#1516`).
 *
 * ## 두 절 — 계정 · 규제 기준값
 *
 * `#506`은 이 화면을 계정 관리로 좁혀 넣었다 — `UIFLOW`가 「판정 보류」로 둔 이유가
 * `#359`(어드민 계정·권한 도입 범위)였고, 자기 계정 관리는 권한과 무관했기 때문이다.
 * 규제 파라미터는 그때 *「`#359`가 정해질 때 붙인다」*로 미뤄 두었다.
 *
 * 그 판정이 `#1239`(결정 A·B)로 났다 — `PRD §5.1` MUST이고 자리는 **설정 안의 절**이다.
 * 네 표 50행을 1년에 한두 번 보는 화면에 사이드바 탭은 과하고, 「왜 이 등급인가」가
 * 시작되는 세 자리가 이 절로 링크한다. 조회는 세 역할 모두이므로(결정 D) 이 화면에는
 * 역할 가드가 없다 — 적재·기록(`#1517`)만 사무직이다.
 */
type SettingsTab = 'account' | 'team' | 'regulation'

/**
 * 탭 셋 (10/7 디자인 결정) — 절 여섯이 한 장에 쌓여 2.24 화면이던 것을 「내 계정 · 팀 · 역할 ·
 * 규제 기준값」으로 가른다. 밖에서 오는 `#regulation-parameters` 링크(`regulationParametersPath`)는
 * 규제 기준값 탭을 연다 — 앵커가 가리키던 절이 그 탭 안에 그대로 있다.
 */
function initialTab(admin: boolean): SettingsTab {
  if (typeof window === 'undefined') return 'account'
  const fromQuery = new URLSearchParams(window.location.search).get('tab')
  if (fromQuery === 'regulation' || window.location.hash === `#${REGULATION_PARAMETERS_ANCHOR}`) return 'regulation'
  if (fromQuery === 'team' && admin) return 'team'
  return 'account'
}

export function SettingsPage() {
  const admin = isAdmin(useAuthUser())
  const [tab, setTab] = useState<SettingsTab>(() => initialTab(admin))
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === `#${REGULATION_PARAMETERS_ANCHOR}`) setTab('regulation')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const items: TabDef[] = [
    { id: 'account', label: '내 프로필', render: () => <AccountPanel part="account" /> },
    ...(admin
      ? [{ id: 'team', label: '팀 · 역할', render: () => <AccountPanel part="team" /> }]
      : []),
    { id: 'regulation', label: '규제 기준값', render: () => <RegulationParametersSection /> },
  ]

  return (
    <div className="page settings">
      <PageHeader screen="SETTINGS" />
      <Tabs
        label="설정 구획"
        items={items}
        current={tab}
        onSelect={(id) => setTab(id as SettingsTab)}
      />
    </div>
  )
}
