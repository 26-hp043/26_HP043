import { AccountPanel } from '../features/account/AccountPanel'
import { RegulationParametersSection } from '../features/parameters/RegulationParametersSection'
import { PageHeader } from '../components/PageHeader'
import { isAdmin, useAuthUser } from '../auth/session'
import { visibleSections } from './settingsSections'
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
export function SettingsPage() {
  const sections = visibleSections(isAdmin(useAuthUser()))

  return (
    <div className="page">
      <PageHeader screen="SETTINGS">
        <p className="page-head__sub">
          계정 정보와 비밀번호를 관리하고, CII 계산이 쓰는 규제 기준값을 확인합니다.
        </p>
      </PageHeader>

      {/*
        ── 절 목차 (#1791) ────────────────────────────────────────────────

        이 화면은 절이 여섯이고 **2.24 화면**이다 — 실측(1440 × 900)으로 문서 높이
        `2,012px`이고 **규제 기준값이 `1,021px`(1.13 화면) 아래**에서 시작한다. 이 화면에서
        가장 자주 찾는 절이 첫 화면에 없고 내려가는 길이 스크롤뿐이었다.

        **하위 메뉴를 만들지 않는다**(`#1239` 결정 A·B) — 「네 표 50행을 1년에 한두 번 보는
        화면에 사이드바 탭은 과하다」. 실제 불편은 「스크롤이 길다」 하나이므로 그만 덜어낸다.

        밖에서 들어오는 링크(`regulationParametersPath()` · `#1239`의 세 자리)는 이미
        동작한다 — 이 줄은 **화면 안에서** 내려가는 길이다.

        목록은 `settingsSections`가 소유한다. 절도 같은 목록에서 제목과 `id`를 가져가므로
        목차에 없는 절이나 없는 자리로 가는 링크가 생길 자리가 없다.
      */}
      <nav className="settings-toc" aria-label="설정 절 바로가기">
        {sections.map((section) => (
          <a key={section.id} className="settings-toc__link" href={`#${section.id}`}>
            {section.label}
          </a>
        ))}
      </nav>

      <AccountPanel />
      <RegulationParametersSection />
    </div>
  )
}
