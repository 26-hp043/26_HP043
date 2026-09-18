"""이메일별 로그인 실패 지수 백오프 (#1203 · `#853` 분리 · v9 E-4).

잠그는 것 — 이 이슈의 완료 기준 셋을 그대로 검사로 옮긴다.

1. **곡선** — 5회까지 0초(오타는 벌하지 않는다), 6회째 0.4초, 지수, 상한 6.4초.
   순수 함수(``_delay_for_failures``)를 직접 본다 — 시간 재기는 흔들리지 않는다.
2. 🔒 **있는 계정과 없는 계정이 시간으로도 구분되지 않는다** — 지연의 키가 이메일
   문자열뿐임을 라우트 수준에서 잠근다. 없는 계정만 즉시 응답하면 그 자체가
   존재 오라클이다(`PRD §6.3`).
3. **구제 경로** — 성공 즉시 초기화, 15분 경과 후 잊음.

라우트 수준 검사는 ``_sleep``을 기록용으로 갈아끼운다 — 실제로 자지 않게.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from cii_platform.api.main import app
from cii_platform.auth import backoff as backoff_mod
from cii_platform.auth.backoff import (
    BASE_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    THRESHOLD,
    LoginBackoff,
    _delay_for_failures,
)

# ── ⑴ 곡선 (순수 함수) ────────────────────────────────────────────────────────


@pytest.mark.parametrize("failures", [0, 1, 2, 3, 4])
def test_typo_budget_has_no_delay(failures):
    """5회까지는 즉시 응답 — 정당한 사용자의 오타를 벌하지 않는다."""
    assert _delay_for_failures(failures) == 0.0


def test_curve_is_exponential_with_a_cap():
    """6회째 0.4초부터 2배씩 — 0.4·0.8·1.6·3.2·6.4(상한, 이후 고정)."""
    assert _delay_for_failures(THRESHOLD) == pytest.approx(BASE_DELAY_SECONDS)
    assert _delay_for_failures(THRESHOLD + 1) == pytest.approx(BASE_DELAY_SECONDS * 2)
    assert _delay_for_failures(THRESHOLD + 2) == pytest.approx(BASE_DELAY_SECONDS * 4)
    assert _delay_for_failures(THRESHOLD + 3) == pytest.approx(BASE_DELAY_SECONDS * 8)
    assert _delay_for_failures(THRESHOLD + 4) == pytest.approx(MAX_DELAY_SECONDS)
    assert _delay_for_failures(THRESHOLD + 20) == MAX_DELAY_SECONDS, "상한을 넘지 않는다"


def test_window_is_the_only_recovery():
    """15분이 지나면 잊는다 — 시간 경과가 유일한 구제 경로다."""
    box = LoginBackoff()
    for _ in range(THRESHOLD + 3):
        box.record_failure("a@example.com")
    assert box.delay_seconds("a@example.com") > 0

    real_monotonic = time.monotonic
    try:
        time.monotonic = lambda: real_monotonic() + 16 * 60  # type: ignore[assignment]
        assert box.delay_seconds("a@example.com") == 0.0, "창이 지났는데 지연이 남았다"
    finally:
        time.monotonic = real_monotonic  # type: ignore[assignment]


def test_success_resets_immediately():
    """성공은 즉시 초기화 — 다음 실패는 다시 5회 여유부터."""
    box = LoginBackoff()
    for _ in range(THRESHOLD + 2):
        box.record_failure("a@example.com")
    box.record_success("a@example.com")
    assert box.delay_seconds("a@example.com") == 0.0
    box.record_failure("a@example.com")
    assert box.delay_seconds("a@example.com") == 0.0, "성공 뒤 첫 실패에 지연이 남았다"


# ── ⑵ 라우트 — 존재 비노출 ────────────────────────────────────────────────────


@pytest.fixture
def recorder():
    """실제로 자지 않고 ``(이메일이 아니라) 지연 초``만 기록하는 sleep."""
    calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    original = backoff_mod._sleep
    backoff_mod._sleep = fake_sleep
    try:
        yield calls
    finally:
        backoff_mod._sleep = original


@pytest.fixture
def client(migrated_db, app_fresh_engine, monkeypatch: pytest.MonkeyPatch):
    from cii_platform.api.rate_limit import RateLimiter, RateLimits

    # 이 검사는 한 파일에서 12번 넘게 로그인을 때린다 — IP 한도(분 10)가 먼저
    # 429를 내면 백오프를 볼 수 없다. 한도만 넉넉히(미들웨어 순서는 그대로).
    app.state.rate_limiter = RateLimiter(
        RateLimits(default=1000, auth=1000, calculation=1000, chat=1000)
    )
    # 라우트의 전역 백오프를 새것으로 — 앞 검사가 남긴 카운터와 격리.
    fresh = LoginBackoff()
    monkeypatch.setattr("cii_platform.api.routes.auth.backoff", fresh)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _fail_login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "definitely-wrong-password"},
    )
    assert resp.status_code == 401, resp.text


async def test_existing_and_unknown_emails_wait_the_same(client, recorder):
    """🔴 있는 계정과 없는 계정의 지연이 같다 — 시간으로 계정 존재를 알 수 없다."""
    existing = f"backoff-real-{time.time_ns():x}@example.com"
    unknown = f"backoff-ghost-{time.time_ns():x}@example.com"
    # 있는 계정은 가입 API로 만든다 — 해시 형식·검증 경로가 실제와 같아야 한다.
    joined = client.post(
        "/api/v1/auth/signup",
        json={"email": existing, "password": "correct-horse-battery"},
    )
    assert joined.status_code == 201, joined.text

    for _ in range(THRESHOLD + 3):
        _fail_login(client, existing)
        _fail_login(client, unknown)

    # 지연 기록은 [existing 시도 지연, unknown 시도 지연]이 번갈아 쌓인다 —
    # 매 시도에서 두 이메일의 지연이 같아야 한다.
    assert len(recorder) == 2 * 3, "임계를 넘은 시도만 지연을 걸어야 한다"
    for i in range(0, len(recorder), 2):
        assert recorder[i] == recorder[i + 1], (
            f"{i}번째 시도: 있는 계정({recorder[i]})과 없는 계정({recorder[i + 1]})의 "
            "지연이 다르다 — 존재 오라클이다"
        )


def test_delay_does_not_change_the_response(client, recorder):
    """지연은 응답 형태를 바꾸지 않는다 — 같은 401·같은 문구로 늦게 답할 뿐."""
    email = f"backoff-shape-{time.time_ns():x}@example.com"
    first = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-1"})
    for _ in range(THRESHOLD + 1):
        _fail_login(client, email)
    assert recorder, "임계 뒤 지연이 걸리지 않았다"

    last = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-2"})
    assert last.status_code == first.status_code == 401
    assert last.json()["error"]["message"] == first.json()["error"]["message"]
    assert last.json()["error"]["code"] == first.json()["error"]["code"]
