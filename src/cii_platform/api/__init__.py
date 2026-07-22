"""API 레이어 — HTTP 요청/응답 처리.

FastAPI app 구성, 라우트(``api.routes``), 요청/응답 스키마(``api.schemas``),
오류 핸들러(``api.error_handlers``)를 포함한다. 이 레이어는 서비스(``services``)만
호출하며 저장소(``db.repositories``)나 계산 엔진(``calc``)을 직접 호출하지 않는다.

계층 규칙은 TECH_SPEC §16 참조.
"""
