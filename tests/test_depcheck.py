"""의존성 드리프트 검사 (#523).

여기서 잠그는 것은 **「이미지에 없는 런타임 의존성을 기동 전에 잡는다」**는 성질이다.
`#60`이 `python-multipart`를 추가한 뒤 재빌드하지 않은 환경에서 앱이 기동조차 못 했고,
그때 나온 오류는 컨테이너 안에서는 **틀린 해법**(`pip install …`)을 안내했다.

이 파일은 순수 함수만 본다. 컨테이너 기동 자체는 CI docker 잡과 사람이 확인한다.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from cii_platform.depcheck import (
    distribution_names,
    missing_distributions,
    read_requirements,
)


class TestDistributionNames:
    def test_extras와_버전_범위를_떼어낸다(self) -> None:
        assert distribution_names(
            [
                "numpy==2.1.0",
                "sqlalchemy[asyncio]>=2.0.52,<2.1",
                "pyjwt[crypto]>=2.8,<3.0",
                "uvicorn[standard]>=0.52.1,<0.60",
            ]
        ) == ["numpy", "sqlalchemy", "pyjwt", "uvicorn"]

    def test_하이픈과_점이_있는_이름을_보존한다(self) -> None:
        # `python-multipart`가 이 이슈의 발단이다. 하이픈에서 잘리면 잡지 못한다.
        assert distribution_names(["python-multipart>=0.0.20,<0.1", "argon2-cffi>=25.1.0,<26"]) == [
            "python-multipart",
            "argon2-cffi",
        ]

    def test_환경_마커를_무시한다(self) -> None:
        assert distribution_names(['tomli>=2.0; python_version < "3.11"']) == ["tomli"]

    def test_빈_목록은_빈_결과다(self) -> None:
        assert distribution_names([]) == []


class TestMissingDistributions:
    def test_설치된_것은_보고하지_않는다(self) -> None:
        # 이 테스트가 도는 환경에는 반드시 있는 것들이다.
        assert missing_distributions(["pytest", "fastapi"]) == []

    def test_없는_것을_보고한다(self) -> None:
        missing = missing_distributions(["definitely-not-installed-9f3a"])

        assert missing == ["definitely-not-installed-9f3a"]

    def test_순서를_유지한다(self) -> None:
        missing = missing_distributions(["zzz-not-installed-1", "pytest", "aaa-not-installed-2"])

        assert missing == ["zzz-not-installed-1", "aaa-not-installed-2"]


class TestReadRequirements:
    def test_project_dependencies를_읽는다(self, tmp_path: Path) -> None:
        target = tmp_path / "pyproject.toml"
        target.write_text(
            textwrap.dedent(
                """
                [project]
                name = "sample"
                dependencies = ["numpy==2.1.0", "fastapi>=0.141.1"]
                """
            ),
            encoding="utf-8",
        )

        assert read_requirements(target) == ["numpy==2.1.0", "fastapi>=0.141.1"]

    def test_파일이_없으면_None이다(self, tmp_path: Path) -> None:
        # None은 「검사 불가」이지 통과가 아니다 — 호출자가 그 사실을 알려야 한다.
        assert read_requirements(tmp_path / "nope.toml") is None

    def test_dependencies가_없으면_빈_목록이다(self, tmp_path: Path) -> None:
        target = tmp_path / "pyproject.toml"
        target.write_text('[project]\nname = "sample"\n', encoding="utf-8")

        assert read_requirements(target) == []

    def test_dev_extra는_읽지_않는다(self, tmp_path: Path) -> None:
        # 개발 의존성이 없어도 앱은 뜬다. 기동을 막을 이유가 없다.
        target = tmp_path / "pyproject.toml"
        target.write_text(
            textwrap.dedent(
                """
                [project]
                name = "sample"
                dependencies = ["numpy==2.1.0"]

                [project.optional-dependencies]
                dev = ["pytest>=8"]
                """
            ),
            encoding="utf-8",
        )

        assert read_requirements(target) == ["numpy==2.1.0"]


class TestAgainstRealPyproject:
    """저장소의 실제 `pyproject.toml`로 돈다 — 파서가 현실과 어긋나면 잡힌다."""

    def test_저장소_런타임_의존성이_전부_설치돼_있다(self) -> None:
        repo_pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        requirements = read_requirements(repo_pyproject)
        assert requirements is not None, "저장소에 pyproject.toml이 있어야 한다"

        missing = missing_distributions(distribution_names(requirements))

        assert missing == [], (
            f"런타임 의존성이 설치돼 있지 않습니다: {missing}. "
            "테스트 환경이 pyproject와 어긋났다는 뜻입니다."
        )

    def test_python_multipart가_런타임_의존성에_있다(self) -> None:
        # `#60`이 넣은 것이며 이 이슈의 발단이다. 선택 의존성으로 내려가면
        # `UploadFile` 라우트 등록 시점에 앱이 기동하지 못한다 (`API_SPEC §8.2`).
        repo_pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        requirements = read_requirements(repo_pyproject)
        assert requirements is not None

        assert "python-multipart" in distribution_names(requirements)
