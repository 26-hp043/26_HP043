"""API 요청/응답 스키마 (Pydantic).

라우트(``api.routes``)가 주고받는 HTTP 요청/응답 본문의 형태를 Pydantic 모델로
정의한다. 사용자 입력 검증(형식·범위)의 1차 경계다. ORM 모델(``db.models``)과는
분리한다: ORM은 DB 표현, 스키마는 API 표현.

계층 규칙은 TECH_SPEC §16 참조. 응답 포맷은 API_SPEC §1.3 참조.
"""
