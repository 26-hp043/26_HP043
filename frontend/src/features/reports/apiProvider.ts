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

    async listVoyages(vesselId: string): Promise<VoyageOption[]> {
      const body = (await (
        await call(`/vessels/${vesselId}/voyages?limit=100`)
      ).json()) as { data?: ServerVoyage[] }

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
