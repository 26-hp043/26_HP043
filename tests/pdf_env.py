"""PDF 종단 검사를 돌릴 수 있는 환경인가 — 제품 코드에 묻지 않고 가린다 (`#2143` · `#2276`).

`tests/test_reports.py`에 있던 것을 PDF 경로를 받는 통합 검사도 함께 쓰도록 옮겼다.
`tests/`에 `__init__.py`가 없어 pytest가 이 디렉터리를 `sys.path`에 넣으므로
`from pdf_env import pdf_environment_gap`으로 가져온다(`fixture_loader.py`와 같은 방식).
"""

from __future__ import annotations

import ctypes.util
import os
import shutil
import subprocess


def pdf_environment_gap() -> str | None:
    """PDF 종단 검사를 돌릴 수 없는 **환경 사정**. 없으면 ``None`` (`#2143`).

    **제품 코드에 묻지 않는다.** 종전에는 ``pdf.is_available()``·``pdf.has_korean_font()``가
    거짓이면 건너뛰었는데, 그러면 그 함수가 틀려서 「없다」고 답하는 결함도 같은 skip으로
    가려진다. 렌더러는 공유 라이브러리 탐색으로, 폰트는 ``fc-list``로 따로 본다.

    CI에서는 건너뛰지 않는다 — ``ci.yml``의 ``test`` 잡이 ``libpango``·``fonts-nanum``을
    설치하고 설치가 실패하면 잡을 중단하므로, 거기서 없다면 환경이 아니라 회귀다.
    """
    if os.environ.get("CI"):
        return None
    if ctypes.util.find_library("pango-1.0") is None:
        return "Pango 공유 라이브러리를 찾지 못한 환경 (WeasyPrint 런타임)"
    fc_list = shutil.which("fc-list")
    if fc_list is None:
        return "fc-list가 없어 한국어 폰트 유무를 가릴 수 없는 환경"
    listed = subprocess.run(
        [fc_list, ":lang=ko", "family"], capture_output=True, text=True, timeout=60
    )
    if listed.returncode != 0 or not listed.stdout.strip():
        return "한국어 폰트가 설치되지 않은 환경 (`fc-list :lang=ko`가 비었다)"
    return None
