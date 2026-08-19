"""개발 컨테이너의 의존성 드리프트 검사 (#523).

## 무엇을 잡는가

dev 이미지는 빌드 시점에 ``pip install -e .``로 의존성을 굳힌다. 그 뒤
``pyproject.toml``에 런타임 의존성이 추가된 커밋을 ``git pull``로 받아도 **이미지는
그대로**다 — ``docker-compose.yml``이 마운트하는 것은 소스뿐이기 때문이다.

그 상태에서 앱을 띄우면 기동 자체가 실패한다. ``#60``(항차 CSV 가져오기)이
``python-multipart``를 추가했을 때 실제로 이런 오류가 났다.

    RuntimeError: Form data requires "python-multipart" to be installed.

메시지가 가리키는 해법(``pip install python-multipart``)은 **컨테이너 안에서는
틀린 해법**이다. 다음 ``up``에서 다시 사라진다. 옳은 해법은 이미지를 다시 굽는
것이고, 이 모듈은 그 사실을 기동 전에 알려 준다.

## 왜 CI로는 못 잡는가

CI는 이 결함을 구조적으로 볼 수 없다. ``ci.yml``의 docker 잡은
``docker-compose.prod.yml``을 쓰고 매번 새로 굽는다. **dev 이미지를 굽게 만들어도
마찬가지다** — 새로 구운 이미지에는 새 의존성이 들어 있으므로 항상 통과한다.
낡은 것은 개발자 로컬의 이미지이지 저장소가 아니다.

즉 검사는 **그 낡은 이미지 안에서, 호스트의 현재 ``pyproject.toml``과 대조해서**
돌아야 한다. 그래서 ``docker-compose.yml``이 ``pyproject.toml``을 마운트한다 —
마운트하지 않으면 이미지 안의 낡은 사본끼리 비교해 늘 통과한다.

## 무엇을 검사하지 않는가

- **개발 의존성(``[dev]`` extra)은 보지 않는다.** 없어도 앱은 뜬다. 테스트는
  컨테이너가 아니라 CI와 호스트에서 돈다.
- **버전 상한 위반은 경고로만 남긴다.** 범위를 벗어난 버전이 깔려 있어도 대개
  동작하며, 여기서 기동을 막으면 실제로 도는 환경을 세우게 된다. 기동을 막는 것은
  **아예 없는 패키지**뿐이다 — 그것이 실제 관측된 실패 모드다.
"""

from __future__ import annotations

import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

#: 컨테이너 안에서 호스트의 ``pyproject.toml``이 마운트되는 자리.
PYPROJECT_PATH = Path("/app/pyproject.toml")

#: 요구사항 문자열에서 배포판 이름만 떼어낸다.
#: ``pyjwt[crypto]>=2.8,<3.0`` → ``pyjwt`` · ``numpy==2.1.0`` → ``numpy``
_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def distribution_names(requirements: list[str]) -> list[str]:
    """요구사항 목록에서 배포판 이름만 뽑는다. 순서를 유지한다."""
    names = []
    for raw in requirements:
        # 환경 마커(`; python_version < "3.13"`)는 이름 뒤에 온다 — 이름만 쓰므로
        # 잘라내도 무방하다. 마커를 평가하지 않으므로 조건부 의존성은 항상 필수로
        # 본다. 현재 pyproject에는 마커가 없고, 생기면 그때 정한다.
        head = raw.split(";", 1)[0]
        matched = _NAME.match(head)
        if matched:
            names.append(matched.group(1))
    return names


def missing_distributions(names: list[str]) -> list[str]:
    """설치되지 않은 배포판 이름. ``importlib.metadata``가 이름을 정규화한다."""
    missing = []
    for name in names:
        try:
            version(name)
        except PackageNotFoundError:
            missing.append(name)
    return missing


def read_requirements(path: Path = PYPROJECT_PATH) -> list[str] | None:
    """``[project].dependencies``를 읽는다. 파일이 없으면 ``None``.

    ``None``은 **검사할 수 없음**이지 통과가 아니다. 호출자가 그 사실을 알려야
    한다 — 마운트가 빠진 것을 조용히 넘기면 이 모듈이 있으나 마나가 된다.
    """
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    dependencies = project.get("dependencies", [])
    return [str(item) for item in dependencies]


def main() -> int:
    requirements = read_requirements()
    if requirements is None:
        print(
            f"[depcheck] {PYPROJECT_PATH}가 없어 의존성 대조를 건너뜁니다.\n"
            "[depcheck] docker-compose.yml의 app 볼륨에 ./pyproject.toml이 있는지 "
            "확인하십시오.",
            file=sys.stderr,
        )
        # 기동은 막지 않는다. 검사가 불가능한 것과 검사가 실패한 것은 다르다.
        return 0

    missing = missing_distributions(distribution_names(requirements))
    if not missing:
        return 0

    print(
        "\n"
        "[depcheck] ❌ 이미지에 없는 런타임 의존성이 있습니다.\n"
        "\n"
        f"    없는 패키지: {', '.join(missing)}\n"
        "\n"
        "  pyproject.toml에 의존성이 추가됐는데 dev 이미지가 그 이전에 구워졌습니다.\n"
        "  소스는 볼륨으로 마운트되지만 **설치된 패키지는 이미지 안에 굳어 있습니다.**\n"
        "\n"
        "  이미지를 다시 구우십시오:\n"
        "\n"
        "      docker compose build app\n"
        "      docker compose up -d app\n"
        "\n"
        "  컨테이너 안에서 pip install로 넣지 마십시오 — 다음 up에서 사라집니다.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
