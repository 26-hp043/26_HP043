"""샘플 항만 — 항차 입력에서 출발·도착항의 이름과 좌표를 채우는 출발점 (#760 · `PRD §15.1`).

`PRD §15.1`이 「샘플 항만 테이블」을 **MUST**로 두었으나 없었다. 화면은 항만명을 자유
텍스트로만 받았고 좌표는 사람이 직접 넣어야 했다 — 시연 참석자에게 「부산항 좌표를
입력하세요」를 요구하는 자리였다(`#808` 공개 배포 · 참석자가 각자 가입해 첫 항차를 넣는다).

## 값은 어디서 오는가

**NGA World Port Index(Pub. 150)** — 미국 정부 저작물이라 공개 영역이다. 2026-09-12에
`msi.nga.mil/api/publications/world-port-index`에서 받은 값을 **그대로** 옮겼다(분 단위 좌표를
소수 4자리로). 각 행의 마지막 값이 WPI 항만 번호라 원본과 한 줄씩 대조할 수 있다.

- ``locode``는 **WPI가 적어 둔 UN/LOCODE 그대로**다. 싱가포르가 ``SGKEP``(Keppel Harbour)인
  것처럼 흔히 쓰는 코드와 다를 수 있으나, 이 목록 안에서 행을 가리키는 식별자일 뿐이다
- ``name``은 항차에 **저장되는 항만명**이다 — 데모 시드가 쓰는 대문자 영문 표기(``BUSAN``)를
  따른다. ``name_ko``는 목록에 보이는 이름이다
- UN/LOCODE 목록(UNECE)은 데모 항만 중 가오슝·마닐라·하코다테에 좌표가 없어 쓰지 않았다

## 무엇을 넣었나 — 43곳

데모 시드의 항차가 쓰는 **9곳 전부**(검사가 대조한다) + 한국 주요 항 · 동아시아 컨테이너 허브 ·
유럽 북서부 · 수에즈 · 북미 서안 · 벌크 선적항(포트헤들랜드 · 투바랑 · 리처즈베이)이다.
목록에 없는 항은 **자유 입력**으로 넣는다(`PRD §20 O-11`) — 목록은 편의이지 제한이 아니다.

## 코드 상수로 둔다

규제 파라미터가 아니고 사용자가 바꾸는 값도 아니다. 테이블로 두면 마이그레이션·시드·
보존 분류가 따라오는데 얻는 것이 없다 — 샘플 선박(``services/sample_vessels.py`` · #982)과 같다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

from cii_platform.calc.distance import great_circle_distance_nm


class SamplePort(NamedTuple):
    locode: str
    name: str
    name_ko: str
    country_code: str
    lat: str
    lon: str
    wpi_number: int


#: WPI(Pub. 150) · 2026-09-12 조회. 순서가 화면 목록 순서다(지역별 · 데모 항로 먼저).
SAMPLE_PORTS: tuple[SamplePort, ...] = (
    SamplePort("KRPUS", "BUSAN", "부산", "KR", "35.1000", "129.0333", 60390),
    SamplePort("KRUSN", "ULSAN", "울산", "KR", "35.4500", "129.4000", 60400),
    SamplePort("KRINC", "INCHEON", "인천", "KR", "37.4667", "126.6167", 60320),
    SamplePort("KRPTK", "PYEONGTAEK", "평택", "KR", "37.0000", "126.8000", 60325),
    SamplePort("SGKEP", "SINGAPORE", "싱가포르", "SG", "1.2833", "103.8500", 50000),
    SamplePort("CNSGH", "SHANGHAI", "상하이", "CN", "31.2167", "121.5000", 59970),
    SamplePort("CNNBO", "NINGBO", "닝보", "CN", "29.8833", "121.5500", 59940),
    SamplePort("CNQIN", "QINGDAO", "칭다오", "CN", "36.0333", "120.2667", 60140),
    SamplePort("CNTXG", "TIANJIN", "톈진", "CN", "38.9667", "117.8333", 60190),
    SamplePort("CNYTN", "YANTIAN", "옌톈", "CN", "22.5833", "114.2667", 57857),
    SamplePort("HKHKG", "HONG KONG", "홍콩", "HK", "22.2667", "114.2000", 57840),
    SamplePort("TWKHH", "KAOHSIUNG", "가오슝", "TW", "22.6167", "120.2500", 57920),
    SamplePort("JPOSA", "OSAKA", "오사카", "JP", "34.6500", "135.4333", 61550),
    SamplePort("JPTYO", "TOKYO", "도쿄", "JP", "35.6667", "139.7500", 61380),
    SamplePort("JPYOK", "YOKOHAMA", "요코하마", "JP", "35.4500", "139.5833", 61390),
    SamplePort("JPUKB", "KOBE", "고베", "JP", "34.6500", "135.1833", 61560),
    SamplePort("JPNGO", "NAGOYA", "나고야", "JP", "35.0667", "136.8667", 61480),
    SamplePort("JPHKD", "HAKODATE", "하코다테", "JP", "41.7833", "140.7167", 61190),
    SamplePort("PHMNL", "MANILA", "마닐라", "PH", "14.5833", "120.9667", 58370),
    SamplePort("VNSGN", "HO CHI MINH", "호찌민", "VN", "10.7667", "106.7167", 57580),
    SamplePort("VNHPH", "HAIPHONG", "하이퐁", "VN", "20.9167", "106.6833", 57680),
    SamplePort("THLCH", "LAEM CHABANG", "램차방", "TH", "13.0833", "100.8833", 57462),
    SamplePort("MYPKG", "PORT KLANG", "포트클랑", "MY", "3.0000", "101.4000", 49930),
    SamplePort("NLRTM", "ROTTERDAM", "로테르담", "NL", "51.9000", "4.4833", 31140),
    SamplePort("DEHAM", "HAMBURG", "함부르크", "DE", "53.5500", "9.9333", 30780),
    SamplePort("BEANR", "ANTWERP", "앤트워프", "BE", "51.2167", "4.4000", 31250),
    SamplePort("GBFXT", "FELIXSTOWE", "펠릭스토", "GB", "51.9500", "1.3167", 31560),
    SamplePort("FRLEH", "LE HAVRE", "르아브르", "FR", "49.4833", "0.1167", 35840),
    SamplePort("ESALG", "ALGECIRAS", "알헤시라스", "ES", "36.1333", "-5.4333", 38310),
    SamplePort("ITGOA", "GENOA", "제노바", "IT", "44.3980", "8.9220", 39470),
    SamplePort("EGSUZ", "SUEZ", "수에즈", "EG", "29.9667", "32.5500", 48040),
    SamplePort("EGPSD", "PORT SAID", "포트사이드", "EG", "31.2667", "32.3000", 45140),
    SamplePort("USLAX", "LOS ANGELES", "로스앤젤레스", "US", "33.7500", "-118.2500", 16080),
    SamplePort("USLGB", "LONG BEACH", "롱비치", "US", "33.7667", "-118.1833", 16070),
    SamplePort("USSEA", "SEATTLE", "시애틀", "US", "47.6000", "-122.3333", 17730),
    SamplePort("USNYC", "NEW YORK", "뉴욕", "US", "40.7000", "-74.0167", 7640),
    SamplePort("USHOU", "HOUSTON", "휴스턴", "US", "29.7500", "-95.2833", 9240),
    SamplePort("CAVAN", "VANCOUVER", "밴쿠버", "CA", "49.2833", "-123.1167", 18150),
    SamplePort("AUPHE", "PORT HEDLAND", "포트헤들랜드", "AU", "-20.3167", "118.5833", 54620),
    SamplePort("BRSSZ", "SANTOS", "산투스", "BR", "-23.9500", "-46.3000", 12970),
    SamplePort("BRTUB", "TUBARAO", "투바랑", "BR", "-20.2833", "-40.2500", 12855),
    SamplePort("ZARCB", "RICHARDS BAY", "리처즈베이", "ZA", "-28.8100", "32.0983", 46855),
    SamplePort("PABLB", "BALBOA", "발보아", "PA", "8.9500", "-79.5667", 15410),
)

#: 좌표 기반 추정 거리의 산출 방식 — ``PRD §15.2`` 「좌표 기반 대권거리」.
METHOD_GREAT_CIRCLE = "GREAT_CIRCLE"


def list_sample_ports() -> list[dict[str, object]]:
    """`GET /ports/samples` 응답의 ``data``. 좌표는 CRUD 층 수치라 JSON 숫자다(`API_SPEC §1.7`)."""
    return [
        {
            "locode": p.locode,
            "name": p.name,
            "name_ko": p.name_ko,
            "country_code": p.country_code,
            "lat": float(Decimal(p.lat)),
            "lon": float(Decimal(p.lon)),
        }
        for p in SAMPLE_PORTS
    ]


def estimate_distance(
    from_lat: Decimal, from_lon: Decimal, to_lat: Decimal, to_lon: Decimal
) -> dict[str, object]:
    """두 좌표의 대권거리 — ``PRD §15.2`` 「거리 미입력 시 fallback」의 **추정값**.

    **실제 항로보다 짧다** — 운하·해협을 돌아가는 항로(상하이→로테르담 등)는 크게 짧게
    나온다. 그래서 화면이 「좌표 기반 추정 거리」라고 표시하고(`§15.2`), 사용자가 실제
    항로거리를 넣으면 그것이 우선이다. 오차 방향은 `PRD §15.2` [#358] ①(거리 과소 →
    등급이 실제보다 나쁘게)이다. 계산식은 기능②와 **같은 함수**다(`calc/distance.py`).
    """
    distance = great_circle_distance_nm(from_lat, from_lon, to_lat, to_lon)
    return {"distance_nm": float(distance), "method": METHOD_GREAT_CIRCLE}
