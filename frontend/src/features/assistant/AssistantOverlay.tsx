import { X } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import './AssistantOverlay.css'
import { createApiAssistantProvider, AssistantError } from './apiProvider'
import type { AssistantProvider, ChatTurn } from './types'
import { Field } from '../../components/Field'
import { Icon } from '../../components/Icon'

/**
 * AI 어시스턴트 오버레이 (`UIFLOW 2-7` · `#121`).
 *
 * ## ⚠️ 화면 규격이 확정되지 않았다 — **임시안**이다
 *
 * `UIFLOW 2-7`은 **행동**을 규정한다(오버레이로 열린다 · 라우트 전환이 없다 ·
 * 3대 봉쇄 · 장애 격리). **생김새는 정하지 않았다** — `DESIGN_SYSTEM`에 챗봇 항목이
 * 없다.
 *
 * 그래서 여기서는 **정해진 것만 구현하고, 나머지는 기존 토큰을 그대로 쓴다.**
 * 새 색·새 반경·새 그림자를 만들지 않았다 — 만들면 확정이 온 뒤 두 벌이 남는다.
 *
 * ## 격리가 화면에서도 성립해야 한다
 *
 * `PRD §16.2`는 서버 이야기로 읽히기 쉽지만, **챗봇 호출이 실패했을 때 대시보드가
 * 흔들리면** 화면 쪽 격리가 없는 것이다. 그래서 이 컴포넌트는 실패를 자기 안에서
 * 말풍선으로 만들고, 바깥으로 던지지 않는다.
 *
 * ## 버린 답을 **다르게 보인다**
 *
 * 서버가 답을 폐기하면 `discarded`가 참이다(`API_SPEC §15.2`). 같은 모양으로 두면
 * 사용자는 「답을 받았다」고 읽는다 — 받은 것은 답이 아니라 「못 드린 이유」다.
 */

/** 접근성 라벨 — 화면에 보이지 않고 스크린리더가 읽는다. */
const PANEL_LABEL = 'AI 어시스턴트'

/** 열기 버튼 문구. 실험 기능임을 **버튼에서부터** 밝힌다. */
const OPEN_LABEL = 'AI 어시스턴트 열기 (실험)'

const PLACEHOLDER = '계산 결과에 대해 물어보세요'

/**
 * 첫 화면 안내.
 *
 * **할 수 없는 것을 먼저 적는다.** 챗봇은 「무엇이든 물어보세요」로 열면 규제 판단을
 * 묻게 되고, 그 질문에는 답하지 않는 것이 맞는 동작이라 사용자가 고장으로 읽는다.
 */
const INTRO =
  '고른 선박으로 항차 CII · 속도 시나리오 · 연말 예상을 계산해 답합니다. 규제 판단이나 권고는 하지 않으며, 수치는 계산 엔진이 낸 값만 인용합니다.'
/*
 * #1613 — 종전 문구 「화면에 나온 계산 결과를 풀어 설명합니다」는 사실이 아니었다.
 * 챗봇은 화면의 값을 받지 않고 도구로 **새로 계산한다**(`chat_tools.py` 네 도구 · R18
 * `#1533`). 화면 값을 넘기게 되면 그때 다시 고친다.
 */

/**
 * 첫 화면 예시 질문 (#1613) — **서버 도구가 실제로 답할 수 있는 것만** 둔다.
 *
 * 연말 예상(`project_year_end`) · 속도 시나리오(`compare_scenarios`) · 용어 풀이(프롬프트의
 * 풀이집). 「어느 쪽이 나은가」처럼 도구가 답하지 않도록 막힌 질문은 넣지 않는다.
 * 누르면 **입력칸에만** 채운다 — 사용자가 고쳐서 보낼 수 있고, 한 번 누름이 비용이 드는
 * 호출이 되지 않는다.
 */
const EXAMPLES = [
  '올해 연말 예상 등급은 어떻게 되나요?',
  '지금 14노트 · 중유(HFO)로 가고 있어요. 속도 시나리오 셋의 CII를 보여 주세요.',
  'attained CII와 required CII는 무엇인가요?',
] as const

/*
 * 계산 대상 선박 (#1613). 선박명은 **화면에만** 보인다 — 외부 LLM으로 보내지 않는다
 * (`PRD §16.3.1` · 요청에는 `vesselId`만 간다). 그래서 답에는 이름이 나오지 않으므로,
 * 어느 배의 숫자인지는 이 줄이 말한다.
 */
const TARGET_LABEL = '계산 대상'
const TARGET_HINT = '상단에서 바꿉니다'
const TARGET_NONE = '선택한 선박 없음 — 계산 질문은 상단에서 선박을 고른 뒤 답합니다'

/** 보내는 중 표시 (`Q10` ⓑ — 스트리밍 대신 로딩 표시). */
const PENDING_TEXT = '답변을 준비하고 있습니다…'

/**
 * 버린 답의 접두 문구 — 2026-09-17 확정 ⓐ (`#1051` 3절).
 *
 * `§14`가 **색 단독 구분을 금지**하는데, 종전에는 줄무늬 하나로 나누려 했고
 * 그마저 면책과 겹쳤다 — **배경·줄무늬·글자색 셋이 모두 같았다.** 문구를 앞에
 * 붙이면 낭독에 그대로 실리고 색각 이상·저시력에서도 작동한다.
 *
 * ⚠️ **서버가 준 사유를 대체하지 않는다.** 폐기 사유의 원문은 서버 소관이며
 * (`API_SPEC §15.2`) 이 접두는 그 **앞에** 붙는다.
 *
 * 문구를 이 파일이 들고 있는 것은 `#1051` 5절(문구 소유)이 미정이기 때문이다 —
 * 위 네 상수와 같은 자리이며, 5절이 정해지면 **함께** 옮긴다.
 */
const DISCARDED_PREFIX = '답을 드리지 못했습니다 — '
/*
 * #1243 — 선박이 정해지지 않은 턴의 안내. 계산은 선박 없이 못 돌았다는 사실을
 * 말풍선 스스로 알린다(도구 오류 봉투가 모델의 말로만 전해지면 흩어진다).
 */
const VESSEL_UNRESOLVED_NOTE = '선박을 먼저 골라 주세요 — 계산은 선택한 선박으로 돕니다. '

let turnSeq = 0
function nextId(): string {
  turnSeq += 1
  return `turn-${turnSeq}`
}

export interface AssistantOverlayProps {
  /** 검사가 갈아 끼운다. */
  readonly provider?: AssistantProvider
  /** 화면이 보고 있는 선박. 계산 도구가 이 선박으로 돈다. */
  readonly vesselId?: string
  /** 그 선박의 이름 — 화면 표시에만 쓴다(#1613 · `PRD §16.3.1`). 목록이 아직 없으면 비어 있다. */
  readonly vesselName?: string
  /**
   * 패널이 열리고 닫힐 때 셸에 알린다 (#1613). 넓은 화면에서 셸이 본문 오른쪽에 패널 폭만큼
   * 비워 패널이 본문을 덮지 않게 한다.
   */
  readonly onOpenChange?: (open: boolean) => void
}

export function AssistantOverlay({ provider, vesselId, vesselName, onOpenChange }: AssistantOverlayProps) {
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<readonly ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [disclaimer, setDisclaimer] = useState<string | null>(null)
  const [stopped, setStopped] = useState(false)
  const sessionRef = useRef<string | undefined>(undefined)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const logRef = useRef<HTMLDivElement | null>(null)
  const launcherRef = useRef<HTMLButtonElement | null>(null)
  /** 한 번이라도 열렸는지. 첫 렌더에서 초점을 빼앗지 않기 위한 표시다. */
  const openedOnceRef = useRef(false)
  const panelId = useId()

  const client = provider ?? createApiAssistantProvider()

  useEffect(() => {
    onOpenChange?.(open)
  }, [open, onOpenChange])

  useEffect(() => {
    if (open) {
      openedOnceRef.current = true
      inputRef.current?.focus()
      return
    }
    /*
     * 닫으면 **여는 버튼으로 초점을 돌려준다** (WCAG 2.4.3 · `#1101`).
     * 돌려주지 않으면 초점이 `body`로 떨어져, 키보드 사용자는 방금 있던 자리를
     * 잃고 문서 처음부터 다시 Tab을 눌러야 한다.
     *
     * 첫 렌더에서는 돌려주지 않는다 — 열어 본 적이 없는데 초점을 가져오면
     * 화면에 들어오자마자 초점이 이 버튼으로 끌려간다.
     */
    if (openedOnceRef.current) {
      openedOnceRef.current = false
      launcherRef.current?.focus()
    }
  }, [open])

  useEffect(() => {
    // 새 말풍선이 생기면 아래로 붙인다 — 사용자가 스크롤을 찾아 내려가지 않게.
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [turns, pending])

  const send = useCallback(async () => {
    const message = draft.trim()
    if (!message || pending || stopped) return

    setTurns((prev) => [...prev, { id: nextId(), role: 'user', text: message }])
    setDraft('')
    setPending(true)
    try {
      const answer = await client.ask({
        message,
        sessionId: sessionRef.current,
        vesselId,
      })
      sessionRef.current = answer.sessionId
      setDisclaimer(answer.disclaimer)
      setTurns((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          text: answer.answer,
          discarded: answer.discarded,
          vesselUnresolved: answer.vesselResolved === false && !answer.discarded,
        },
      ])
    } catch (error) {
      /*
       * 실패를 **말풍선으로** 만든다 — 던지면 화면 단위 에러 경계가 잡아
       * 대시보드가 오류 화면이 된다. 그것이 곧 격리 실패다.
       */
      const unavailable = error instanceof AssistantError && error.unavailable
      setTurns((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          text: error instanceof Error ? error.message : '답변을 받지 못했습니다.',
          failed: true,
        },
      ])
      // 설정이 없는 상태면 다시 눌러도 소용없다 — 입력을 닫는다.
      if (unavailable) setStopped(true)
    } finally {
      setPending(false)
    }
  }, [client, draft, pending, stopped, vesselId])

  if (!open) {
    return (
      <button
        type="button"
        className="assistant__launcher"
        ref={launcherRef}
        aria-expanded={false}
        onClick={() => setOpen(true)}
      >
        {OPEN_LABEL}
      </button>
    )
  }

  return (
    <section
      className="assistant"
      id={panelId}
      aria-label={PANEL_LABEL}
      /*
       * Escape를 **패널 안에서만** 받는다 (`#1101`). 종전에는 `window`에 걸어
       * 두어, 본문 다른 입력에서 Escape를 눌러도(조합 취소·검색어 지우기 같은
       * 보통의 동작이다) 이 패널이 함께 닫혔다.
       */
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false)
      }}
      /*
       * 로그 같은 초점을 받지 못하는 자리를 눌러도 초점이 패널 안에 머물게 한다 —
       * `body`로 떨어지면 위의 Escape가 닿지 않는다.
       */
      tabIndex={-1}
    >
      <header className="assistant__head">
        <h2 className="assistant__title">
          {PANEL_LABEL}
          <span className="assistant__tag">실험</span>
        </h2>
        <button
          type="button"
          className="assistant__close"
          aria-label="AI 어시스턴트 닫기"
          onClick={() => setOpen(false)}
        >
          <Icon glyph={X} size="inline" />
        </button>
      </header>

      <p className="assistant__target">
        <span className="assistant__target-label">{TARGET_LABEL}</span>{' '}
        {vesselId ? (
          <>
            <strong>{vesselName || '선택한 선박'}</strong>
            <span className="assistant__target-hint"> · {TARGET_HINT}</span>
          </>
        ) : (
          TARGET_NONE
        )}
      </p>

      <p className="assistant__intro">{INTRO}</p>

      {/* 대화를 시작하면 걷는다 — 그 뒤에는 로그가 자리를 쓴다. */}
      {turns.length === 0 ? (
        <ul className="assistant__examples" role="list" aria-label="예시 질문">
          {EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                className="assistant__example"
                disabled={stopped}
                onClick={() => {
                  setDraft(example)
                  inputRef.current?.focus()
                }}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {/*
        `aria-live="polite"` — 답이 도착한 것을 스크린리더가 알린다. `assertive`를
        쓰지 않는 이유는 사용자가 읽던 것을 끊기 때문이다.
      */}
      <div className="assistant__log" ref={logRef} aria-live="polite" role="log">
        {turns.map((turn) => (
          <p
            key={turn.id}
            className={[
              'assistant__turn',
              `assistant__turn--${turn.role}`,
              turn.discarded || turn.failed ? 'assistant__turn--discarded' : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            {turn.discarded ? DISCARDED_PREFIX : null}
            {turn.vesselUnresolved ? VESSEL_UNRESOLVED_NOTE : null}
            {turn.text}
          </p>
        ))}
        {pending ? (
          <p className="assistant__turn assistant__turn--pending">{PENDING_TEXT}</p>
        ) : null}
      </div>

      {/*
        면책은 **답이 있을 때만** 보인다. 대화가 비어 있을 때 띄우면 무엇에 대한
        면책인지가 없다.
      */}
      {disclaimer ? <p className="assistant__disclaimer">{disclaimer}</p> : null}

      <form
        className="assistant__form"
        onSubmit={(event) => {
          event.preventDefault()
          void send()
        }}
      >
        <Field id={`${panelId}-input`} label="질문" labelHidden>
          {(control) => (
            <textarea
              {...control}
              ref={inputRef}
              className="assistant__input"
              rows={2}
              maxLength={2000}
              placeholder={PLACEHOLDER}
              value={draft}
              disabled={stopped}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                /*
                 * 한글 IME는 **조합 중에도 Enter를 보낸다**. 그 Enter는 조합을
                 * 확정하는 키이지 전송이 아니다 — 여기서 보내면 마지막 음절이
                 * 깨진 채 나간다(`#1101`).
                 *
                 * `keyCode === 229`도 함께 본다. `isComposing`을 채우지 않는 조합
                 * 경로가 남아 있고, 그 값은 이 한 자리에서만 읽는다.
                 */
                if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
                // Enter로 보내고 Shift+Enter로 줄을 바꾼다 — 채팅의 관례다.
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void send()
                }
              }}
            />
          )}
        </Field>
        <button
          type="submit"
          className="assistant__send"
          disabled={pending || stopped || draft.trim().length === 0}
        >
          보내기
        </button>
      </form>
    </section>
  )
}
