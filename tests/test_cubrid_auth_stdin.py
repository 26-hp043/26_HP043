"""stdin 바이트 보존·CCI 오류/정리·비밀번호 없는 프로세스 argv (#2117)."""

from __future__ import annotations

import ast
import ctypes
import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cubrid_auth_stdin.py"
_SPEC = importlib.util.spec_from_file_location("cubrid_auth_stdin", _SCRIPT)
assert _SPEC and _SPEC.loader
auth = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(auth)


class FakeCci:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def cci_connect_ex(self, host, port, database, user, password, error):
        self.calls.append(("connect", password))
        error._obj.message = b"FAKE-ERROR-PASSWORD-MUST-NOT-BE-LOGGED"
        return -1 if self.fail == "connect" else 11

    def cci_escape_string(self, connection, destination, source, length, error):
        self.calls.append(("escape", source, length))
        destination.value = b"CCI_ESCAPED"
        return -1 if self.fail == "escape" else len(destination.value)

    def cci_prepare(self, connection, query, flag, error):
        self.calls.append(("prepare", query))
        return -1 if self.fail == "prepare" else 12

    def cci_execute(self, request, flag, max_size, error):
        self.calls.append(("execute", request))
        return -1 if self.fail == "execute" else 1

    def cci_end_tran(self, connection, action, error):
        self.calls.append(("commit", action))
        return -1 if self.fail == "commit" else 0

    def cci_close_req_handle(self, request):
        self.calls.append(("close", request))
        return 0

    def cci_disconnect(self, connection, error):
        self.calls.append(("disconnect", connection))
        return 0


def test_probe_uses_exact_stdin_password_bytes(monkeypatch):
    password = b"FAKE2117-'$\\\n\n"
    library = FakeCci()
    monkeypatch.setattr(auth, "load_cci", lambda: library)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "probe", "cii_test"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(password)))
    assert auth.main() == 0
    assert ("connect", password) in library.calls
    assert ("prepare", b"SELECT 1 FROM db_root") in library.calls
    assert library.calls[-2:] == [("close", 12), ("disconnect", 11)]


def test_initialize_uses_empty_login_native_escape_and_commit():
    library = FakeCci()
    password = b"FAKE2117-'$\n\n"
    assert auth.execute(library, "cii_test", password, initialize=True) == 0
    assert library.calls[0] == ("connect", b"")
    assert ("escape", password, len(password)) in library.calls
    assert ("prepare", b"ALTER USER dba PASSWORD 'CCI_ESCAPED'") in library.calls
    assert ("commit", b"\x01") in library.calls
    assert library.calls[-2:] == [("close", 12), ("disconnect", 11)]


@pytest.mark.parametrize("stage", ("connect", "escape", "prepare", "execute", "commit"))
def test_native_failure_is_a_failure_and_handles_are_closed(stage, capsys):
    library = FakeCci(fail=stage)
    assert auth.execute(library, "cii_test", b"FAKE2117", initialize=True) == 1
    names = [call[0] for call in library.calls]
    assert ("disconnect" in names) == (stage != "connect")
    assert ("close" in names) == (stage in ("execute", "commit"))
    output = capsys.readouterr()
    assert "FAKE-ERROR-PASSWORD" not in output.out + output.err


@pytest.mark.parametrize(
    ("mode", "database", "password"),
    (
        ("unknown", "cii_test", b"x"),
        ("probe", "bad;query", b"x"),
        ("probe", "cii_test", b"x" * 32),
        ("probe", "cii_test", b"a\0b"),
        ("initialize", "cii_test", b""),
    ),
)
def test_invalid_input_stops_before_loading_native_library(monkeypatch, mode, database, password):
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), mode, database])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(password)))

    def should_not_load():
        pytest.fail("거부할 입력인데 네이티브 인증을 시작했다")

    monkeypatch.setattr(auth, "load_cci", should_not_load)
    assert auth.main() == 2


def test_image_python_36_and_public_cci_error_layout():
    ast.parse(_SCRIPT.read_text(), feature_version=(3, 6))
    assert ctypes.sizeof(auth.CciError) == 1028
    assert auth.CciError.message.offset == ctypes.sizeof(ctypes.c_int)


def test_missing_library_fails_without_printing_exception_secret(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "probe", "cii_test"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"FAKE2117")))

    def unavailable():
        raise OSError("FAKE-PRIVATE-DETAIL-2117")

    monkeypatch.setattr(auth, "load_cci", unavailable)
    assert auth.main() == 1
    output = capsys.readouterr()
    assert "FAKE-PRIVATE-DETAIL" not in output.out + output.err
