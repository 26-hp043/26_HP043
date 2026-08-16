/**
 * 리포트 화면 타입 — `API_SPEC §8.3~§8.5` (`#362`).
 */

/** 리포트 2종 (`PRD §25.2`·`§25.3`). */
export type ReportKind = 'VOYAGE' | 'ANNUAL'

/** 내보내기 포맷. `html`은 화면 미리보기 전용이라 다운로드 선택지에 없다. */
export type DownloadFormat = 'pdf' | 'csv'

export interface VesselOption {
  id: string
  name: string
  imoNumber: string
}

export interface VoyageOption {
  id: string
  voyageNo: string | null
  status: string
  regulationYear: number | null
  departurePortName: string | null
  arrivalPortName: string | null
  /**
   * 리포트를 만들 수 있는 항차인가.
   *
   * **진행 중 항차는 대상이 아니다**(`PRD §25.2`) — 실적이 확정되지 않은 값으로
   * 문서를 만들면 같은 항차의 리포트가 시점마다 달라진다. 목록에서 **감추지 않고
   * 비활성으로 둔다**: 감추면 사용자가 「내 항차가 왜 없지」를 묻게 되고, 답이
   * 화면 어디에도 없다.
   */
  reportable: boolean
}

/** 어떤 리포트를 만들 것인가. */
export type ReportTarget =
  | { kind: 'VOYAGE'; voyageId: string }
  | { kind: 'ANNUAL'; vesselId: string; year: number }

export interface ReportsProvider {
  listVessels(): Promise<VesselOption[]>
  listVoyages(vesselId: string): Promise<VoyageOption[]>
  /** 미리보기용 HTML. PDF와 **같은 소스**다 (`API_SPEC §8.3` `format=html`). */
  previewHtml(target: ReportTarget): Promise<string>
  /** 파일을 받아 저장한다. 반환값은 저장된 파일명. */
  download(target: ReportTarget, format: DownloadFormat): Promise<string>
}
