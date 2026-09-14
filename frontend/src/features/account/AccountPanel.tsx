import { useEffect, useState, type FormEvent } from 'react'
import {
  EMAIL_IMMUTABLE_NOTICE,
  ROLE_DESCRIPTION,
  ROLE_LABEL,
  WITHDRAWAL_NOTICE,
  splitSubmitFailure,
} from '../auth/authRules'
import {
  changePassword,
  deleteAccount,
  isOffice,
  leaveAfterPasswordChange,
  listUsers,
  updateDisplayName,
  updateUserRole,
  useAuthUser,
  type CurrentUser,
  type UserRole,
} from '../../auth/session'
import {
  MAX_DISPLAY_NAME_LENGTH,
  PASSWORD_CHANGE_NOTICE,
  displayNamePayload,
  hasAccountErrors,
  validateDisplayName,
  validatePasswordChange,
} from './accountRules'
import type { AccountFieldErrors, PasswordChangeDraft } from './accountRules'
import './AccountPanel.css'
import { ErrorState } from '../../components/ErrorState'

/**
 * 계정 관리 — `설정` 화면의 계정 절 (`#506`) + 계정 목록·역할 지정 (`#672`).
 *
 * ## 역할 2종
 *
 * `#359`가 미뤄 둔 어드민 범위가 `#672`로 정해졌다 — 사무직·현장직(`PRD §20 O-14` ·
 * `UIFLOW 2-6`). 계정 정보에 자기 역할을 보이고, **사무직에게만** 「계정 · 역할」 절을
 * 보인다(`RoleSection`). 조직·세부 권한 설정은 여전히 없다(`PRD §5.2`).
 *
 * ## 이메일은 읽기 전용이다
 *
 * 변경 엔드포인트가 없다(`API_SPEC §1.2`). 입력창을 두고 저장 단계에서 422를 내는
 * 대신, **처음부터 바꿀 수 없다는 것을 보인다.**
 */
export function AccountPanel() {
  const user = useAuthUser()
  if (!user) return null

  return (
    <div className="acc">
      <section className="card acc__section" aria-label="계정 정보">
        <h2 className="card__title">계정 정보</h2>

        <dl className="acc__facts">
          <div>
            <dt>이메일</dt>
            <dd>{user.email}</dd>
          </div>
          <div>
            <dt>역할</dt>
            <dd data-testid="acc-role">{ROLE_LABEL[user.role]}</dd>
          </div>
        </dl>
        <p className="acc__notice">{EMAIL_IMMUTABLE_NOTICE}</p>
        {/* `PRD §6.3` 「역할 설명」 — 정본 문구다. 두 역할 모두 자기 역할이 무엇을 뜻하는지 본다. */}
        <p className="acc__notice">{ROLE_DESCRIPTION}</p>

        <DisplayNameForm initial={user.displayName ?? ''} />
      </section>

      {isOffice(user) ? <RoleSection me={user} /> : null}
      <PasswordSection />
      <WithdrawalSection />
    </div>
  )
}

/**
 * 계정 목록 · 역할 지정 — 사무직 전용 (`UIFLOW 2-6` · `API_SPEC §1.2` · `#672`).
 *
 * ## 마지막 사무직은 서버가 막는다
 *
 * 사무직이 하나뿐이면 강등 요청은 `409`로 돌아오고 문구(`PRD §6.3` 「마지막 사무직」)가
 * 온다 — 화면은 그 문구를 그대로 보인다. 여기서 미리 세어 막지 않는다: 목록은 조회 시점의
 * 스냅샷이라 그 사이 다른 사무직이 바뀌었을 수 있고, **판정은 행을 잠근 서버 한 곳**이 한다.
 *
 * ## 셀렉트로 바꾼다
 *
 * 값이 둘뿐이고 「바꾼다」가 곧 저장이다. 별도 저장 버튼을 두면 바꿨는지 저장했는지가
 * 갈린다. 실패하면 셀렉트를 **원래 값으로 되돌린다** — 화면이 서버와 다르게 남지 않게.
 */
function RoleSection({ me }: { me: CurrentUser }) {
  const [users, setUsers] = useState<CurrentUser[] | null>(null)
  const [loadFailure, setLoadFailure] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    listUsers().then(
      (rows) => {
        if (alive) setUsers(rows)
      },
      (caught: unknown) => {
        if (alive) setLoadFailure(caught instanceof Error ? caught.message : '계정 목록을 불러오지 못했습니다.')
      },
    )
    return () => {
      alive = false
    }
  }, [])

  const change = async (target: CurrentUser, role: UserRole) => {
    setBusyId(target.id)
    setFailure(null)
    setNotice(null)
    try {
      const changed = await updateUserRole(target.id, role)
      setUsers((prev) => prev?.map((row) => (row.id === changed.id ? changed : row)) ?? prev)
      setNotice(`${changed.email}: ${ROLE_LABEL[changed.role]}으로 바꿨습니다.`)
    } catch (caught) {
      setFailure(caught instanceof Error ? caught.message : '역할을 바꾸지 못했습니다.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="card acc__section" aria-label="계정 · 역할">
      <h2 className="card__title">계정 · 역할</h2>
      <p className="acc__notice">
        사무직만 다른 계정의 역할을 바꿀 수 있습니다. 마지막 남은 사무직은 현장직으로 바꿀 수
        없습니다.
      </p>

      {loadFailure !== null ? (
        <ErrorState level="region" size="compact" message={loadFailure} />
      ) : users === null ? (
        // `role="status"` — `aria-busy` 단독은 낭독되지 않는다 (`a11yWiring.test.ts`).
        <p className="acc__hint" role="status" aria-busy="true">
          계정 목록을 불러오는 중…
        </p>
      ) : (
        <ul className="acc__users" data-testid="acc-users">
          {users.map((row) => {
            const selectId = `acc-role-${row.id}`
            return (
              <li key={row.id} className="acc__user">
                <label className="acc__label" htmlFor={selectId}>
                  {row.email}
                  {row.id === me.id ? ' (나)' : ''}
                  {row.displayName ? ` · ${row.displayName}` : ''}
                </label>
                <select
                  id={selectId}
                  className="acc__input acc__input--select"
                  value={row.role}
                  disabled={busyId !== null}
                  onChange={(event) => void change(row, event.target.value as UserRole)}
                >
                  <option value="OFFICE">{ROLE_LABEL.OFFICE}</option>
                  <option value="FIELD">{ROLE_LABEL.FIELD}</option>
                </select>
              </li>
            )
          })}
        </ul>
      )}

      {failure !== null ? <ErrorState level="region" size="compact" message={failure} /> : null}
      {notice !== null ? (
        <p className="acc__ok" role="status">
          {notice}
        </p>
      ) : null}
    </section>
  )
}

function DisplayNameForm({ initial }: { initial: string }) {
  const [name, setName] = useState(initial)
  const [error, setError] = useState<string | undefined>()
  const [failure, setFailure] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = validateDisplayName(name)
    setError(found)
    if (found) return

    setBusy(true)
    setFailure(null)
    setDone(false)
    try {
      await updateDisplayName(displayNamePayload(name).display_name)
      setDone(true)
    } catch (caught) {
      const next = splitSubmitFailure(caught, '표시 이름을 바꾸지 못했습니다.', {
        display_name: 'name',
      } as const)
      setError(next.errors.name)
      setFailure(next.failure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="acc__form" onSubmit={submit} noValidate>
      <div className="acc__field">
        <label className="acc__label" htmlFor="acc-name">
          표시 이름
        </label>
        <input
          id="acc-name"
          className={error ? 'acc__input acc__input--error' : 'acc__input'}
          value={name}
          maxLength={MAX_DISPLAY_NAME_LENGTH}
          onChange={(event) => {
            setName(event.target.value)
            setDone(false)
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'acc-name-error' : 'acc-name-hint'}
        />
        <p className="acc__hint" id="acc-name-hint">
          비워 두면 이름 없이 표시됩니다.
        </p>
        {error ? (
          <p className="acc__error" id="acc-name-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      {failure ? (
        <ErrorState level="region" size="compact" message={failure} />
      ) : null}
      {done ? (
        <p className="acc__ok" role="status">
          표시 이름을 바꿨습니다.
        </p>
      ) : null}

      <button type="submit" className="acc__submit" disabled={busy}>
        {busy ? '저장 중' : '표시 이름 저장'}
      </button>
    </form>
  )
}

function PasswordSection() {
  const [draft, setDraft] = useState<PasswordChangeDraft>({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  })
  const [errors, setErrors] = useState<AccountFieldErrors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [changed, setChanged] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (key: keyof PasswordChangeDraft) => (value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = validatePasswordChange(draft)
    setErrors(found)
    if (hasAccountErrors(found)) return

    setBusy(true)
    setFailure(null)
    try {
      const message = await changePassword(draft.currentPassword, draft.newPassword)
      setChanged(message)
    } catch (caught) {
      // 서버가 짚은 칸(현재·새 비밀번호)은 그 입력칸에, 나머지는 폼 위에 (#877 ⑴).
      const next = splitSubmitFailure(caught, '비밀번호를 바꾸지 못했습니다.', {
        current_password: 'currentPassword',
        new_password: 'newPassword',
      } as const)
      setErrors(next.errors)
      setFailure(next.failure)
    } finally {
      setBusy(false)
    }
  }

  /*
   * 성공하면 폼을 걷고 안내만 남긴다. 이 기기의 세션도 이미 죽어 있어 다음 조작은
   * 어차피 로그인 화면으로 간다 — 그 전에 **왜 그렇게 되는지**를 읽게 한다.
   */
  if (changed) {
    return (
      <section className="card acc__section" aria-label="비밀번호 변경">
        <h2 className="card__title">비밀번호 변경</h2>
        <p className="acc__ok" role="status">
          {changed}
        </p>
        <p className="acc__notice">{PASSWORD_CHANGE_NOTICE}</p>
        {/*
          라우터 링크가 아니라 **전체 페이지 이동**이다 (`#1099`). 세션 캐시가 살아 있는 동안
          `/login`은 `next`로 되돌려 보내 안내를 읽은 사용자가 로그인 폼에 닿지 못했다.
        */}
        <button type="button" className="acc__submit" onClick={leaveAfterPasswordChange}>
          로그인 화면으로
        </button>
      </section>
    )
  }

  return (
    <section className="card acc__section" aria-label="비밀번호 변경">
      <h2 className="card__title">비밀번호 변경</h2>

      {/* 미리 고지하지 않으면 사용자는 「왜 튕겼지」로 받는다. */}
      <p className="acc__notice">{PASSWORD_CHANGE_NOTICE}</p>

      <form className="acc__form" onSubmit={submit} noValidate>
        <PasswordField
          id="acc-current"
          label="현재 비밀번호"
          value={draft.currentPassword}
          onChange={set('currentPassword')}
          error={errors.currentPassword}
          autoComplete="current-password"
        />
        <PasswordField
          id="acc-new"
          label="새 비밀번호"
          value={draft.newPassword}
          onChange={set('newPassword')}
          error={errors.newPassword}
          autoComplete="new-password"
        />
        <PasswordField
          id="acc-confirm"
          label="새 비밀번호 확인"
          value={draft.confirmPassword}
          onChange={set('confirmPassword')}
          error={errors.confirmPassword}
          autoComplete="new-password"
        />

        {failure ? (
          <ErrorState level="region" size="compact" message={failure} />
        ) : null}

        <button type="submit" className="acc__submit" disabled={busy}>
          {busy ? '바꾸는 중' : '비밀번호 바꾸기'}
        </button>
      </form>
    </section>
  )
}

function PasswordField({
  id,
  label,
  value,
  onChange,
  error,
  autoComplete,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  autoComplete: string
}) {
  const errorId = `${id}-error`
  return (
    <div className="acc__field">
      <label className="acc__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="password"
        className={error ? 'acc__input acc__input--error' : 'acc__input'}
        value={value}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
      />
      {error ? (
        <p className="acc__error" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

/**
 * 탈퇴 (`PRD §5.1` MUST · `#754`).
 *
 * ## 왜 화면이 없었나
 *
 * 서버(`DELETE /auth/me`)·정본(`API_SPEC §1.2`·`§12`·`PRD §5.1`·`§6.3`)·`UIFLOW 2-6`이
 * 전부 갖춰졌는데 **화면만 없었다.** `#506`이 계정 관리를 넣을 때 탈퇴는 「범위」가
 * 아니라 「결정이 필요한 것」이었고, 그 결정이 `PRD §6.3` 문구와 `§5.1` MUST로 내려진
 * 뒤 서버는 따라왔으나 화면이 따라오지 않았다.
 *
 * 그 사이 **이메일을 바꿀 유일한 경로가 막혀 있었다** — 위 「계정 정보」 절이
 * *「다른 주소를 쓰려면 탈퇴 후 다시 가입해 주세요」*라고 안내하는데 탈퇴할 수가 없었다.
 *
 * ## 브라우저 `confirm()`을 쓰지 않는다
 *
 * 선박 삭제(`vessel-management`)는 `globalThis.confirm()`을 쓴다. 여기서는 쓰지 않는다.
 *
 * * `PRD §6.3` 문구는 **세 절짜리 고지**다. 브라우저 대화상자는 서식이 없어 읽히지 않는다
 * * 계정 삭제는 선박 삭제보다 되돌리기 어렵다 — 세션이 전량 무효화되고 즉시 로그아웃된다
 * * 완료 기준이 「확인 단계에 그 문구가 **그대로 나온다**」를 요구한다. 대화상자 안의
 *   문자열은 화면에 렌더되지 않아 검사할 수도, 스타일을 줄 수도 없다
 *
 * ## 2단계인 이유
 *
 * 버튼 하나로 끝내면 오조작이 곧 계정 삭제다. 첫 단계는 **문구를 읽게 하는 자리**이고,
 * 두 번째 버튼이 실제 요청을 보낸다. 「취소」를 함께 두어 되돌릴 길을 남긴다.
 */
function WithdrawalSection() {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function withdraw() {
    setBusy(true)
    setError(null)
    try {
      /*
       * 성공하면 `deleteAccount`가 캐시를 비우고 로그인 화면으로 보낸다 — 여기서
       * 이동시키지 않는다. 상태 초기화와 이동이 갈리면 「로그아웃된 화면에 옛 사용자
       * 이름이 남는」 상태가 생긴다.
       */
      await deleteAccount()
    } catch (err) {
      setError(err instanceof Error ? err.message : '탈퇴하지 못했습니다.')
      setBusy(false)
    }
  }

  return (
    <section className="card acc__section acc__section--danger" aria-label="탈퇴">
      <h2 className="card__title">탈퇴</h2>

      {/*
        `PRD §6.3`이 원문을 확정한 **정본 문구**다. 화면에서 새로 적지 않는다
        (`AGENTS §4.6`). 확인 단계 전에도 보여 준다 — 무엇을 누르려는지 알고 눌러야 한다.
      */}
      <p className="acc__notice">{WITHDRAWAL_NOTICE}</p>

      {error !== null ? (
        <ErrorState level="region" size="compact" message={error} />
      ) : null}

      {confirming ? (
        <div className="acc__confirm">
          <p className="acc__confirm-ask">정말 탈퇴하시겠습니까?</p>
          <div className="acc__confirm-actions">
            <button
              type="button"
              className="acc__submit acc__submit--danger"
              onClick={() => void withdraw()}
              disabled={busy}
            >
              {busy ? '탈퇴 중…' : '탈퇴합니다'}
            </button>
            <button
              type="button"
              className="acc__submit"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="acc__submit acc__submit--danger"
          onClick={() => setConfirming(true)}
        >
          탈퇴하기
        </button>
      )}
    </section>
  )
}
