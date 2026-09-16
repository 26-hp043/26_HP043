"""CUBRID 접속 URL 정규화 (#234 → #1058).

alembic · seed · pytest · 앱 세션의 4곳이 같은 정책을 공유한다.
"""

from __future__ import annotations


def normalize_to_async(url: str) -> str:
    """``cubrid+aiopycubrid://``로 정규화한다."""
    if url.startswith("cubrid+aiopycubrid://"):
        return url
    if url.startswith("cubrid://"):
        return "cubrid+aiopycubrid://" + url.split("://", 1)[1]
    if url.startswith("cubrid+"):
        return "cubrid+aiopycubrid://" + url.split("://", 1)[1]
    return url


def normalize_to_sync(url: str) -> str:
    """``cubrid+pycubrid://``로 정규화한다 (Alembic·seed 등 동기 컨텍스트용)."""
    if url.startswith("cubrid+pycubrid://"):
        return url
    if url.startswith("cubrid://"):
        return "cubrid+pycubrid://" + url.split("://", 1)[1]
    if url.startswith("cubrid+"):
        return "cubrid+pycubrid://" + url.split("://", 1)[1]
    return url
