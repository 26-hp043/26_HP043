"""DB 레이어 — 데이터베이스 접근.

ORM 모델(``db.models``)과 저장소(``db.repositories``)를 포함한다. DB와 관련된
코드(모델 정의, 마이그레이션 연결, 쿼리)는 모두 이 트리 아래에 둔다. 비즈니스
로직은 여기 두지 않는다(그건 ``services``의 몫).

계층 규칙은 TECH_SPEC §16 참조.
"""

# CUBRID가 트리거로 강제하는 제약 위반을 `IntegrityError`로 올린다 (`#1058`).
# 임포트만으로 `Engine`에 핸들러가 등록된다 — 이 패키지를 쓰는 모든 경로가 같은
# 예외를 받게 하려고 여기 둔다. 자세한 이유는 그 모듈의 docstring.
from cii_platform.db import cubrid_errors as _cubrid_errors  # noqa: E402,F401
