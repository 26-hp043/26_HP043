import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { EMAIL_IMMUTABLE_NOTICE } from '../auth/authRules'
import {
  LOGIN_PATH,
  AuthRequestError,
  changePassword,
  updateDisplayName,
  useAuthUser,
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

/**
 * 계정 관리 — `설정` 화면의 계정 절 (`#506`).
 *
 * ## 어드민 범위를 건드리지 않는다
 *
 * `UIFLOW 2-6`은 `#359`(어드민 계정·권한 도입 범위) 결정 대기로 「판정 보류」다.
 * **자기 계정 관리는 권한과 무관하므로** `PRD §5` 계정 관리 MUST 근거로 먼저 넣고,
 * 조직·권한 설정은 손대지 않는다. 그래서 정본 개정이 선행하지 않는다.
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
        </dl>
        <p className="acc__notice">{EMAIL_IMMUTABLE_NOTICE}</p>

        <DisplayNameForm initial={user.displayName ?? ''} />
      </section>

      <PasswordSection />
    </div>
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
      setFailure(
        caught instanceof AuthRequestError ? caught.message : '표시 이름을 바꾸지 못했습니다.',
      )
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
        <p className="acc__error" role="alert">
          {failure}
        </p>
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
      setFailure(
        caught instanceof AuthRequestError ? caught.message : '비밀번호를 바꾸지 못했습니다.',
      )
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
        <Link className="acc__submit acc__submit--link" to={LOGIN_PATH}>
          로그인 화면으로
        </Link>
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
          <p className="acc__error" role="alert">
            {failure}
          </p>
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
