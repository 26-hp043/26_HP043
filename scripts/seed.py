#!/usr/bin/env python
"""IMO 규제 파라미터 seed 실행 스크립트 (#33).

``python scripts/seed.py``로 실행한다. 대상 DB는 ``DATABASE_URL`` 환경변수를 따르며,
미설정 시 ``cii_platform.config``의 기본값을 쓴다.

seed 데이터·적재 로직·진입점은 모두 ``cii_platform.db.seed``에 있다 — 이 파일은
**editable 설치 없이도 돌아가게 해 주는 개발용 래퍼**일 뿐이다(``sys.path`` 조작).
프로덕션 이미지는 wheel만 설치해 ``scripts/``가 없으므로, 배포 절차는
``python -m cii_platform.db.seed``를 쓴다 (#240). 실행 로직의 사본을 여기 두지
않는다 — 사본을 두면 한쪽만 고쳐지는 일이 생긴다 (#234).

재실행해도 결과가 같다(upsert). 스키마는 미리 ``alembic upgrade head``로 만들어 둔다.
"""

import asyncio
import sys
from pathlib import Path

# src 레이아웃을 sys.path에 추가하여 editable 설치 없이도 import할 수 있게 한다
# (alembic/env.py·tests/conftest.py와 동일 정책).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cii_platform.db.seed import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
