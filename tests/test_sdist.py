import os
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.distribution


def test_sdist_builds_and_runs_without_original_checkout(tmp_path):
    def run(*command, cwd=tmp_path):
        result = subprocess.run(
            command,
            cwd=cwd,
            env={k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    run("uv", "build", "--sdist", "--out-dir", str(tmp_path), cwd=ROOT)
    (sdist,) = tmp_path.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        names = {"/".join(name.split("/")[1:]) for name in archive.getnames()}
        assert {
            "tests/__init__.py",
            "tests/conftest.py",
            "tests/support.py",
            "tests/roster_support.py",
            "examples/assignment.json",
            "demo/server.py",
            "demo/app.js",
            "uv.lock",
            "docs/distribution.md",
            "GLOSSARY.md",
            "MANIFEST.in",
            "src/shift_schedula/py.typed",
            "src/shift_schedula/__init__.pyi",
        } <= names
        assert not any(
            name.startswith(
                (
                    "docs/reference/",
                    "docs/evaluations/results/",
                    ".git/",
                    ".venv/",
                    "build/",
                    "dist/",
                    "test-results/",
                )
            )
            or "__pycache__" in name
            for name in names
        )
        archive.extractall(tmp_path, filter="data")
    (source,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    for document in source.rglob("*.md"):
        for link in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if ":" not in link and not link.startswith("#"):
                assert (document.parent / link.split("#", 1)[0]).exists(), (document, link)
    run("uv", "build", "--wheel", "--out-dir", str(tmp_path / "wheel"), cwd=source)
    (wheel,) = (tmp_path / "wheel").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        for version in (
            "0.1",
            "0.2",
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
        ):
            for kind in ("request", "response"):
                assert f"shift_schedula/schemas/{version}/{kind}.schema.json" in archive.namelist()
        assert any(n.endswith("/licenses/LICENSE") for n in archive.namelist())
        assert any(n.endswith("/licenses/THIRD_PARTY_NOTICES.md") for n in archive.namelist())
        assert not any(n.startswith(("docs/", "tests/", "demo/")) for n in archive.namelist())
    # 実装の元checkoutをimportさせず、sdist由来wheelと同梱テストだけを使う。
    run("uv", "venv", "--python", sys.executable, str(tmp_path / "consumer"))
    python = (
        tmp_path / "consumer" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    run(
        "uv",
        "export",
        "--locked",
        "--extra",
        "cp-sat",
        "--no-dev",
        "--no-emit-project",
        "--output-file",
        str(tmp_path / "constraints.txt"),
        cwd=source,
    )
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--constraints",
        str(tmp_path / "constraints.txt"),
        f"{wheel}[cp-sat]",
        "pytest==9.1.1",
    )
    run(
        str(python),
        "-I",
        "-c",
        "import shift_schedula, sys; "
        "assert all(p not in shift_schedula.__file__ for p in sys.argv[1:]); "
        "print(shift_schedula.__file__)",
        str(ROOT),
        str(source),
    )
    for filename in ("assignment.json", "linked_assignment.json", "roster.json"):
        run(str(python), "-I", "-m", "shift_schedula", "solve", f"examples/{filename}", cwd=source)
    run(str(python), "demo/server.py", "--help", cwd=source)
    run(
        str(python),
        "-m",
        "pytest",
        "-q",
        "-ra",
        "-m",
        "not repository and not distribution",
        "--junitxml=" + str(tmp_path / "sdist-tests.xml"),
        cwd=source,
    )
    assert not ET.parse(tmp_path / "sdist-tests.xml").findall(".//skipped")
