import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.repository

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_release.py"


@pytest.mark.parametrize(
    ("tag", "version", "on_main", "success"),
    [
        ("v0.2.0", "0.2.0", True, True),
        ("v0.2.1", "0.2.0", True, False),
        ("v0.2.0rc1", "0.2.0rc1", True, False),
        ("0.2.0", "0.2.0", True, False),
        ("v0.2.0", "0.2.0", False, False),
    ],
)
def test_release_requires_matching_stable_tag_on_main(tmp_path, tag, version, on_main, success):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Release test")
    git("config", "user.email", "release@example.invalid")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    git("add", ".")
    git("commit", "-m", "main")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    if not on_main:
        git("commit", "--allow-empty", "-m", "unmerged")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env={**os.environ, "RELEASE_TAG": tag},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
