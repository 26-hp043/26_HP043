"""필드명 → 한글 라벨 매핑 (API_SPEC §1.3.2 ``details[].field_label``, §11).

오류 응답에서 ``distance_nm`` 같은 필드명을 사용자용 한글 라벨("운항 거리")로
바꾼다.

#49가 **조회 실패 계약**을 확정했다 — 미등록 필드는 ``KeyError``가 아니라 필드명
원문을 그대로 반환한다. 그 위에서 각 필드를 검증하는 이슈가 라벨을 채워 넣는다.

**#55(기능① 계산)가 채운 분이 아래 「기능① 요청 필드」 묶음이다.** 그 이슈에서
빠뜨렸다가 실 API 시연 준비 중에 드러났다 — 오류 응답의 ``field_label``이
``fuel_uses[0].fuel_ton``처럼 필드명 그대로 나가고 있었다.

배열 필드는 **인덱스가 붙은 경로**로 조회된다(``fuel_uses[0].fuel_ton``). 인덱스는
요청마다 달라지므로 정적 dict로는 덮을 수 없다 — :func:`field_label`이 인덱스를
지운 형태로 한 번 더 찾는다.
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
    #
    # --- #900: 나머지 요청 필드 전부 ---
    # 종전에는 위 두 묶음뿐이라 인증·선박·항차·정박 구간 요청의 422가 필드명 원문
    # (``display_name``)을 라벨로 냈다. 이제 **모든 엔드포인트의 요청 필드**가 여기 있어야
    # 한다 — ``tests/test_validation_messages.py``가 OpenAPI로 전부 대조한다.
    # 라벨은 **화면의 입력칸 이름**을 따른다(같은 칸이 오류에서 다른 이름으로 불리지 않게).
    #
    # 인증 (API_SPEC §1.2)
    "email": "이메일",
    "password": "비밀번호",
    "current_password": "현재 비밀번호",
    "new_password": "새 비밀번호",
    "display_name": "표시 이름",
    "invite_code": "초대 코드",
    "token": "메일 링크",
    # 선박 (§2)
    "imo_number": "IMO 번호",
    "name": "선명",
    "gross_tonnage": "총톤수(GT)",
    "deadweight": "재화중량톤수(DWT)",
    "default_fuel_type": "기본 연료",
    "reference_speed_kn": "기준속도",
    "reference_daily_foc_ton": "기준 일일 연료소모량",
    "current_lat": "현재 위도",
    "current_lon": "현재 경도",
    "detail_status": "세부 상태",
    "underway_state": "운항 상태",
    "as_of": "기준 시각",
    "year": "연도",
    "from": "시작 연도",
    "to": "끝 연도",
    "sort": "정렬 기준",
    # 항차 (§3)
    "voyage_id": "항차",
    "voyage_no": "항차 번호",
    "departure_port_name": "출발항",
    "arrival_port_name": "도착항",
    "departure_lat": "출발지 위도",
    "departure_lon": "출발지 경도",
    "arrival_lat": "도착지 위도",
    "arrival_lon": "도착지 경도",
    "planned_distance_nm": "계획 거리",
    "planned_speed_kn": "계획 속력",
    "planned_departure_at": "계획 출항 시각",
    "planned_arrival_at": "계획 도착 시각",
    "notes": "메모",
    "fuel_uses[].planned_fuel_ton": "계획 연료량",
    "fuel_uses[].actual_fuel_ton": "실제 연료량",
    "fuel_uses[].source": "연료 기록 출처",
    "actual_departure_at": "실제 출항 시각",
    "actual_arrival_at": "실제 도착 시각",
    "actual_distance_nm": "실제 거리",
    "actual_avg_speed_kn": "평균 속력",
    "to_status": "바꿀 상태",
    "annual_inclusion_policy": "연간 반영 구분",
    "status": "상태",
    # 정박·묘박 구간 (§3.8)
    "period_id": "정박·묘박 구간",
    "period_type": "구간 유형",
    "started_at": "시작 시각",
    "ended_at": "종료 시각",
    "started_from": "시작 시각(부터)",
    "started_to": "시작 시각(까지)",
    "port_name": "항구",
    "lat": "위도",
    "lon": "경도",
    "fuel_use_id": "연료 기록",
    "fuel_type": "연료 종류",
    "fuel_ton": "연료량",
    "consumer_type": "소비원",
    "fuel_uses[].consumer_type": "소비원",
    # 기능② 항로 비교 (§5)
    "scenario_id": "시나리오",
    "destination_port_name": "목적항",
    "destination_lat": "목적지 위도",
    "destination_lon": "목적지 경도",
    "direct_distance_nm": "직항 거리",
    "detour_distance_nm": "우회 거리",
    "current_speed_kn": "현재 속력",
    "slow_speed_kn": "감속 속력",
    "base_daily_foc_ton": "기준 일일 연료소모량",
    "adopt_mode": "채택 방식",
    "target_voyage_id": "대상 항차",
    # 기능③ 연간 시뮬레이션 (§6)
    "simulation_run_id": "시뮬레이션 실행",
    "simulation_runs": "반복 횟수",
    "random_seed": "난수 시드(seed)",
    "target_rating": "목표 등급",
    "distribution_profile": "분포 프로파일",
    # 조회·내보내기·가져오기 (§1.9 · §8)
    "type": "종류",
    "format": "파일 형식",
    "calculation_run_id": "계산 이력",
    "input_hash": "입력 해시",
    "parameter_hash": "파라미터 해시",
    "file": "파일",
    "dry_run": "검증만 실행",
    # 규정 파라미터 (§7)
    "active": "사용 여부",
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
