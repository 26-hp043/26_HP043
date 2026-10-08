"""CUBRID 이미지의 Python 3.6/CCI로 argv 없이 dba를 인증한다 (#2117).

비밀번호는 stdin의 원시 바이트다. 끝 줄바꿈을 자르지 않는다.
probe는 SELECT 1만 수행하고 initialize는 빈 암호 dba의 최초 설정만 수행한다.
운영 이미지의 공개 CCI ABI(cas_cci.h)를 사용하며 프로젝트 패키지는 필요 없다.
"""

import ctypes
import os
import re
import signal
import sys


class CciError(ctypes.Structure):
    # CUBRID 11.4.6.1963 cas_cci.h의 T_CCI_ERROR와 같다.
    _fields_ = [("code", ctypes.c_int), ("message", ctypes.c_char * 1024)]


def load_cci():
    library = ctypes.CDLL(os.path.join(os.environ["CUBRID"], "lib", "libcascci.so"))
    error_pointer = ctypes.POINTER(CciError)
    signatures = {
        "cci_connect_ex": [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            error_pointer,
        ],
        "cci_prepare": [ctypes.c_int, ctypes.c_char_p, ctypes.c_char, error_pointer],
        "cci_execute": [ctypes.c_int, ctypes.c_char, ctypes.c_int, error_pointer],
        "cci_end_tran": [ctypes.c_int, ctypes.c_char, error_pointer],
        "cci_close_req_handle": [ctypes.c_int],
        "cci_disconnect": [ctypes.c_int, error_pointer],
        "cci_escape_string": [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            error_pointer,
        ],
    }
    for name, arguments in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = ctypes.c_long if name == "cci_escape_string" else ctypes.c_int
    return library


def execute(library, database, password, initialize=False):
    error = CciError()
    login_password = b"" if initialize else password
    connection = library.cci_connect_ex(
        b"127.0.0.1",
        33000,
        database.encode("ascii"),
        b"dba",
        login_password,
        ctypes.byref(error),
    )
    if connection < 0:
        return 1
    request = -1
    try:
        query = b"SELECT 1 FROM db_root"
        if initialize:
            # 서버의 SQL 문자열 규칙으로 인용한다. CCI 오류 메시지는 출력하지 않는다.
            escaped = ctypes.create_string_buffer(len(password) * 2 + 1)
            length = library.cci_escape_string(
                connection,
                escaped,
                password,
                len(password),
                ctypes.byref(error),
            )
            if length < 0:
                return 1
            query = b"ALTER USER dba PASSWORD '" + escaped.raw[:length] + b"'"
        request = library.cci_prepare(connection, query, b"\0", ctypes.byref(error))
        if request < 0:
            return 1
        result = library.cci_execute(request, b"\0", 0, ctypes.byref(error))
        if result < 0:
            return 1
        if initialize and library.cci_end_tran(connection, b"\x01", ctypes.byref(error)) < 0:
            return 1
        return 0
    finally:
        if request >= 0:
            library.cci_close_req_handle(request)
        library.cci_disconnect(connection, ctypes.byref(error))


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("probe", "initialize"):
        return 2
    mode, database = sys.argv[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", database):
        return 2
    password = sys.stdin.buffer.read(32)
    if len(password) > 31 or b"\0" in password or (mode == "initialize" and not password):
        return 2
    # C 호출이 멎어도 probe는 Docker healthcheck의 5초보다 먼저 끝난다.
    signal.alarm(4 if mode == "probe" else 30)
    try:
        return execute(load_cci(), database, password, mode == "initialize")
    except (OSError, KeyError, ValueError):
        # 오류 버퍼/예외 원문에는 SQL·값이 들어갈 수 있어 남기지 않는다.
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    sys.exit(main())
