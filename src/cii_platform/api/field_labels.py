"""필드명 → 한글 라벨 매핑 (API_SPEC §1.3.2 ``details[].field_label``, §11).

오류 응답에서 ``distance_nm`` 같은 필드명을 사용자용 한글 라벨("운항 거리")로
바꾼다.

#49가 **조회 실패 계약**을 확정했다 — 미등록 필드는 ``KeyError``가 아니라 필드명
원문을 그대로 반환한다. 그 위에서 각 필드를 검증하는 이슈가 라벨을 채워 넣는다.

**#55(기능① 계산)가 채운 분이 「기능① 요청 필드」 묶음이다.** 그 이슈에서
빠뜨렸다가 실 API 시연 준비 중에 드러났다 — 오류 응답의 ``field_label``이
``fuel_uses[0].fuel_ton``처럼 필드명 그대로 나가고 있었다.

**#900이 나머지 전 필드를 채웠다.** 인증 필드 6종이 하나도 등록되지 않은 것이
계기였고(가입 422의 ``field_label``이 ``"email"`` 그대로 나갔다), 실측해 보니
미등록 필드는 85종이었다. 이제 ``tests/test_korean_validation_422.py``가 실제
앱의 OpenAPI 스키마를 걸어 **모든 본문·쿼리·경로 필드에 라벨이 있는지**를
검사한다 — 다음 이슈가 필드를 추가하고 라벨을 잊으면 그 자리에서 실패한다.

배열 필드는 **인덱스가 붙은 경로**로 조회된다(``fuel_uses[0].fuel_ton``). 인덱스는
요청마다 달라지므로 정적 dict로는 덮을 수 없다 — :func:`field_label`이 인덱스를
지운 형태로 한 번 더 찾는다.

용어는 화면·문서가 이미 쓰는 표기를 옮겨 적는다(``reports/labels.py``와 같은
계약 — 여기서 새로 정하지 않는다). 출처는 각 묶음의 주석에 적었다.
"""

from __future__ import annotations

import re

#: 배열 인덱스를 지우는 패턴. ``fuel_uses[0].fuel_ton`` → ``fuel_uses[].fuel_ton``
_ARRAY_INDEX = re.compile(r"\[\d+\]")

_FIELD_LABELS: dict[str, str] = {
    # --- 기능① 요청 필드 (#55 · API_SPEC §4.1) ---
    "vessel_id": "선박",
    "regulation_year": "규제연도",
    "distance_nm": "운항 거리",  # API_SPEC §1.3.2 예시, §11 VAL-002
    "speed_kn": "속력",  # API_SPEC §11 VAL-009
    "fuel_uses": "연료 사용량",
    "fuel_uses[].fuel_type": "연료 종류",  # VAL-006
    "fuel_uses[].fuel_ton": "연료 사용량",  # VAL-002
    "weather_model": "기상 모델",
    # --- 목록 조회 쿼리 파라미터 (#51 · API_SPEC §2.1) ---
    "limit": "페이지 크기",
    "cursor": "커서",
    "ship_type": "선종",
    "search": "검색어",
    # --- 인증 (#900 · API_SPEC §1.2) ---
    "email": "이메일",
    "password": "비밀번호",
    "display_name": "표시 이름",
    "invite_code": "초대 코드",
    "current_password": "현재 비밀번호",
    "new_password": "새 비밀번호",
    "token": "인증 토큰",
    # --- 선박 제원 (#900 · API_SPEC §3.1) · 용어는 VesselDetail.tsx ---
    "imo_number": "IMO 번호",
    "name": "선박명",
    "gross_tonnage": "총톤수(GT)",
    "deadweight": "재화중량톤수(DWT)",
    "default_fuel_type": "기본 연료",
    "reference_speed_kn": "기준 속력",
    "reference_daily_foc_ton": "기준 일일 연료소모량",
    "underway_state": "운항 상태",
    "detail_status": "상세 운항 상태",
    "current_lat": "현재 위도",
    "current_lon": "현재 경도",
    # --- 항차 (#900 · API_SPEC §3.3) · 용어는 VoyagePanel.tsx ---
    "voyage_no": "항차 번호",
    "voyage_id": "항차",
    "departure_port_name": "출발항",
    "departure_lat": "출발 위도",
    "departure_lon": "출발 경도",
    "arrival_port_name": "도착항",
    "arrival_lat": "도착 위도",
    "arrival_lon": "도착 경도",
    "planned_distance_nm": "계획 거리",
    "planned_speed_kn": "계획 속력",
    "planned_departure_at": "출항 예정 시각",
    "planned_arrival_at": "도착 예정 시각",
    "actual_departure_at": "출항 실적 시각",
    "actual_arrival_at": "도착 실적 시각",
    "actual_distance_nm": "실제 거리",
    "actual_avg_speed_kn": "실제 평균 속력",
    "planned_fuel_ton": "계획 연료 사용량",
    "actual_fuel_ton": "실적 연료 사용량",
    "fuel_uses[].planned_fuel_ton": "계획 연료 사용량",
    "fuel_uses[].actual_fuel_ton": "실적 연료 사용량",
    "fuel_uses[].source": "데이터 출처",
    "notes": "메모",
    "to_status": "변경 후 상태",
    "annual_inclusion_policy": "연간 집계 정책",
    # --- not under way (#900 · API_SPEC §2.10) ---
    "fuel_uses[].consumer_type": "소비 설비",
    "consumer_type": "소비 설비",  # POST …/{period_id}/fuel-uses 는 스키마가 최상위로 온다
    "fuel_uses[]": "연료 사용량",
    "fuel_type": "연료 종류",
    "fuel_ton": "연료 사용량",
    "period_type": "운항 정지 구분",
    "port_name": "항구명",
    "lat": "위도",
    "lon": "경도",
    "started_at": "시작 시각",
    "ended_at": "종료 시각",
    "period_id": "운항 정지 기간",
    "fuel_use_id": "연료 사용 기록",
    # --- 기능② 시나리오 (#900 · API_SPEC §5) ---
    "current_speed_kn": "현재 속력",
    "destination_port_name": "목적지 항구",
    "destination_lat": "목적지 위도",
    "destination_lon": "목적지 경도",
    "base_daily_foc_ton": "기준 일일 연료소모량",
    "direct_distance_nm": "직항 거리",
    "detour_distance_nm": "우회 거리",
    "slow_speed_kn": "감속 속력",
    "target_voyage_id": "대상 항차",
    "adopt_mode": "반영 모드",
    "scenario_id": "시나리오",
    # --- 기능③ 연간 시뮬레이션 (#900 · API_SPEC §6.1) ---
    "target_rating": "목표 등급",
    "simulation_runs": "시뮬레이션 횟수",
    "random_seed": "랜덤 시드",
    "distribution_profile": "분포 프로파일",
    "as_of": "기준 시각",
    "simulation_run_id": "시뮬레이션 실행",
    # --- 공통 쿼리·업로드 (#900) ---
    "file": "파일",  # voyage_import.py field_label과 같은 표기
    "year": "연도",
    "from": "시작 연도",
    "to": "종료 연도",
    "status": "상태",
    "type": "유형",
    "active": "활성 여부",
    "format": "파일 형식",
    "dry_run": "시험 실행",
    "input_hash": "입력 해시",
    "parameter_hash": "파라미터 해시",
    "started_from": "시작 시각(부터)",
    "started_to": "시작 시각(까지)",
}


def field_label(field: str) -> str:
    """필드명에 대응하는 한글 라벨을 반환한다.

    **두 번 찾는다.** 먼저 경로 그대로, 없으면 **배열 인덱스를 지운 형태**로 —
    ``fuel_uses[0].fuel_ton``과 ``fuel_uses[3].fuel_ton``은 같은 필드이고 인덱스는
    요청마다 달라지므로 정적 dict에 모두 적을 수 없다.

    미등록 필드는 예외를 던지지 않고 필드명 원문을 그대로 돌려준다(조회 실패 계약).
    """
    if field in _FIELD_LABELS:
        return _FIELD_LABELS[field]
    return _FIELD_LABELS.get(_ARRAY_INDEX.sub("[]", field), field)
