"""저장소(Repository) — DB 접근만 담당.

SELECT/INSERT/UPDATE/DELETE 등 DB 쿼리만 수행한다. 계산이나 비즈니스 규칙
(예: 상태 전환 검증, fallback 정책 결정)은 여기 두지 않는다. 그건 서비스
(``services``)의 몫이다. 저장소는 ORM 모델(``db.models``)을 다루고 도메인
객체를 반환한다.

계층 규칙은 TECH_SPEC §16 참조.
"""
