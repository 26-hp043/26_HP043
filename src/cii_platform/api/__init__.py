"""API 레이어 — HTTP 요청/응답 처리.

FastAPI app·라우트·Pydantic 스키마·오류 변환을 포함한다. 업무 처리와 계산은
services를 호출한다. 입력 범위·라벨·검증 문구는 중립 validation에 둔다.
DB 직접 접근은 TECH_SPEC §16.3의 인증·감사·챗봇 파일/목적 예외로 한정한다.
세션 주입과 감사의 원자 commit/rollback은 직접 쿼리와 구분하며 기존 경계를 유지한다.
하위→API, 라우트→계산/DB 경계는 tests/test_layer_boundaries.py가 검사한다.
"""
