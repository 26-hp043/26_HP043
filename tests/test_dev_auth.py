"""개발 환경 스텁 인증 테스트 (#276)."""

from __future__ import annotations

from cii_platform.api.routes.auth_dev import should_register_dev_auth


def test_should_register_dev_returns_true_in_development():
    """APP_ENV=development → True (#276)."""
    import cii_platform.api.routes.auth_dev as mod

    original = mod._ENV
    mod._ENV = "development"
    try:
        assert should_register_dev_auth() is True
    finally:
        mod._ENV = original


def test_should_register_dev_returns_false_in_production():
    """APP_ENV=production → False (#276)."""
    import cii_platform.api.routes.auth_dev as mod

    original = mod._ENV
    mod._ENV = "production"
    try:
        assert should_register_dev_auth() is False
    finally:
        mod._ENV = original
