import { csrfHeaders, redirectToLogin } from '../../auth/session'
import { DEFAULT_API_BASE_URL } from '../voyage-cii/apiProvider'
import { filenameFrom, isReportable } from './reportRules'
import type {
  DownloadFormat,
  ReportTarget,
  ReportsProvider,
  VesselOption,
  VoyageOption,
} from './types'

/**
 * 리포트 provider — `API_SPEC §8.3~§8.5` (`#362`).
 *
 * ## 링크가 아니라 fetch로 받는다
 *
 * `<a href>`로 걸면 브라우저가 알아서 저장하지만, 그때 실패는 **화면 밖에서** 일어난다 —
 * 401이면 로그인 HTML이 `.pdf`로 저장되고, 500이면 오류 JSON이 저장된다. 사용자는
 * 파일을 열고 나서야 잘못을 안다.
 *
 * fetch로 받으면 상태 코드를 보고 **화면에서** 실패를 말할 수 있다. 성공했을 때만
 * blob을 만들어 저장한다.
 *
 * ## 미리보기와 PDF가 같은 소스다
 *
 * `format=html`이 PDF와 같은 문서를 낸다(`API_SPEC §8.3`). 화면이 따로 그리면
 * 미리보기와 받은 파일이 달라지고, 그 차이는 사용자가 파일을 연 뒤에야 드러난다.
 */

export class ReportsError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, { cause: options?.cause })
    this.name = 'ReportsError'
  }
}

/** 대상 → 경로. 두 리포트가 서로 다른 리소스에 걸린다. */
export function pathOf(target: ReportTarget, format: string): string {
  if (target.kind === 'VOYAGE') {
    return `/voyages/${target.voyageId}/report?format=${format}`
  }
  return `/vessels/${target.vesselId}/annual-report?year=${target.year}&format=${format}`
}

interface ServerVessel {
  id: string
  name: string
  imo_number: string
}

/**
 * 항차 목록 응답의 **부분집합** — 셀렉트에 필요한 6필드만 받는다.
 *
 * **공용화하지 않는 이유**는 `voyage-management/apiProvider.ts`의 같은 이름 위에
 * 판단과 근거를 적어 두었다 (`#627`). 요약하면 세 벌은 같은 타입이 아니다 —
 * `realtime-cii` 쪽은 **다른 엔드포인트**이고, 이 파일과 `voyage-management`는 같은
 * 엔드포인트지만 **안전성 전략이 반대**다(확정 타입 vs `unknown` + 런타임 파싱).
 */
interface ServerVoyage {
  id: string
  voyage_no: string | null
  status: string
  regulation_year: number | null
  departure_port_name: string | null
  arrival_port_name: string | null
}

export function createApiReportsProvider(
  fetchImpl: typeof globalThis.fetch = globalThis.fetch,
  baseUrl: string = DEFAULT_API_BASE_URL,
  saveFile: (blob: Blob, filename: string) => void = defaultSaveFile,
): ReportsProvider {
  const call = async (path: string): Promise<Response> => {
    let response: Response
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method: 'GET',
        credentials: 'include',
        headers: { ...csrfHeaders() },
      })
    } catch (cause) {
      throw new ReportsError('서버에 연결하지 못했습니다.', { cause })
    }

    if (response.status === 401) {
      redirectToLogin()
      throw new ReportsError('세션이 만료되었습니다.')
    }
    if (!response.ok) {
      /*
       * 오류 본문은 JSON이다(`API_SPEC §1.3.2`). 파일 응답을 기대한 자리라도
       * 실패했으면 JSON이므로 여기서 읽어 서버 문구를 그대로 쓴다 — 「완료되지 않은
       * 항차는 리포트 대상이 아닙니다」 같은 문장은 화면이 다시 쓸 수 없다.
       */
      const body = (await response.json().catch(() => null)) as {
        error?: { message?: string }
      } | null
      throw new ReportsError(
        body?.error?.message ?? `생성하지 못했습니다 (HTTP ${response.status}).`,
      )
    }
    return response
  }

  return {
    async listVessels(): Promise<VesselOption[]> {
      const body = (await (await call('/vessels?limit=100')).json()) as {
        data?: ServerVessel[]
      }
      return (body.data ?? []).map((raw) => ({
        id: raw.id,
        name: raw.name,
        imoNumber: raw.imo_number,
      }))
    },

    /**
     * 항차 선택지 — **페이지를 끝까지 순회한다** (`#627`).
     *
     * 종전에는 `?limit=100` 한 번이었다. `#625`가 한 번에 1,000행을 넣을 수 있게 만든
     * 뒤 **101번째부터는 셀렉트에 뜨지 않아 보고서를 만들 수 없었다.**
     *
     * ## 왜 「더 보기」가 아니라 전부 부르는가
     *
     * 이 자리는 `<select>`다. 「더 보기」·검색을 넣으려면 컴포넌트를 다시 만들어야 하고,
     * 그것은 이 이슈의 범위가 아니다. 서버 상한이 100이라 1,000 항차면 **10회 요청**이고
     * 셀렉트는 한 번 열린다.
     *
     * ## 무한 루프를 페이지 상한으로 막지 않는다
     *
     * 임의의 상한(「20페이지까지」)을 두면 그 너머를 **조용히 자른다** — 화면은 전부
     * 보여 준다고 주장하면서 일부를 감춘다. 대신 **커서가 전진하지 않으면 중단**한다:
     * 서버가 같은 커서를 다시 주는 것은 계약 위반이고, 그때만 루프가 무한해진다.
     */
    async listVoyages(vesselId: string): Promise<VoyageOption[]> {
      const rows: ServerVoyage[] = []
      const seen = new Set<string>()
      let cursor: string | null = null

      for (;;) {
        const query = `limit=100${cursor === null ? '' : `&cursor=${encodeURIComponent(cursor)}`}`
        const raw = (await (await call(`/vessels/${vesselId}/voyages?${query}`)).json()) as {
          data?: ServerVoyage[]
          meta?: { next_cursor?: unknown; has_more?: unknown }
        }
        rows.push(...(raw.data ?? []))

        const next = raw.meta?.next_cursor
        const more = raw.meta?.has_more === true
        // 커서가 없거나·빈 문자열이거나·이미 지나온 값이면 멈춘다.
        if (!more || typeof next !== 'string' || next === '' || seen.has(next)) break
        seen.add(next)
        cursor = next
      }

      const body = { data: rows }

      return (body.data ?? []).map((raw) => ({
        id: raw.id,
        voyageNo: raw.voyage_no,
        status: raw.status,
        regulationYear: raw.regulation_year,
        departurePortName: raw.departure_port_name,
        arrivalPortName: raw.arrival_port_name,
        // 감추지 않고 비활성으로 둔다 — 감추면 「내 항차가 왜 없지」에 답이 없다.
        reportable: isReportable(raw.status),
      }))
    },

    async previewHtml(target: ReportTarget): Promise<string> {
      return (await call(pathOf(target, 'html'))).text()
    },

    async download(target: ReportTarget, format: DownloadFormat): Promise<string> {
      const response = await call(pathOf(target, format))
      const blob = await response.blob()

      // 서버가 준 이름을 쓴다. 없을 때만 대체 이름을 만든다.
      const filename =
        filenameFrom(response.headers.get('Content-Disposition')) ??
        `report-${new Date().toISOString().slice(0, 10)}.${format}`

      saveFile(blob, filename)
      return filename
    },
  }
}

/**
 * blob을 파일로 저장한다.
 *
 * 주입 가능한 인자로 둔 이유는 **테스트에 DOM이 없기** 때문이다. 이 저장소의
 * vitest는 node 환경이라 `document`가 없고, provider를 검증하려면 이 부분을
 * 갈아 끼울 수 있어야 한다.
 *
 * `revokeObjectURL`을 반드시 부른다 — 부르지 않으면 blob이 탭이 닫힐 때까지
 * 메모리에 남고, 리포트를 여러 번 받는 화면에서 그대로 누적된다.
 */
function defaultSaveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
