import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.repository

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_release.py"


@pytest.mark.parametrize(
    ("tag", "version", "on_main", "ci_state", "success"),
    [
        ("v0.2.0", "0.2.0", True, "success", True),
        ("v0.2.1", "0.2.0", True, "success", False),
        ("v0.2.0rc1", "0.2.0rc1", True, "success", False),
        ("0.2.0", "0.2.0", True, "success", False),
        ("v0.2.0", "0.2.0", False, "success", False),
        *[
            ("v0.2.0", "0.2.0", True, state, False)
            for state in (
                "missing",
                "failure",
                "cancelled",
                "in_progress",
                "wrong_sha",
                "wrong_branch",
                "wrong_event",
                "wrong_workflow",
                "api_error",
                "older_success",
            )
        ],
    ],
)
def test_release_requires_matching_stable_tag_and_successful_main_ci(
    tmp_path, tag, version, on_main, ci_state, success
):
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
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    run = {
        "head_sha": commit,
        "head_branch": "main",
        "event": "push",
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/release-test/repo/actions/runs/1",
    }
    if ci_state in {"failure", "cancelled", "older_success"}:
        run["conclusion"] = "failure" if ci_state == "older_success" else ci_state
    elif ci_state == "in_progress":
        run.update(status="in_progress", conclusion=None)
    elif ci_state.startswith("wrong_"):
        key = {
            "wrong_sha": "head_sha",
            "wrong_branch": "head_branch",
            "wrong_event": "event",
            "wrong_workflow": "path",
        }[ci_state]
        run[key] = "other"
    runs = [] if ci_state == "missing" else [run]
    if ci_state == "older_success":
        runs.append({**run, "conclusion": "success"})
    (tmp_path / "ci.json").write_text(json.dumps({"workflow_runs": runs}))
    arguments = [
        "api",
        "--method",
        "GET",
        "repos/release-test/repo/actions/workflows/ci.yml/runs",
        "-f",
        "branch=main",
        "-f",
        "event=push",
        "-f",
        f"head_sha={commit}",
        "-f",
        "per_page=1",
    ]
    binary = tmp_path / "bin/gh"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        f"assert sys.argv[1:] == {arguments!r}\n"
        + (
            "raise SystemExit(1)\n"
            if ci_state == "api_error"
            else "print(Path('ci.json').read_text())\n"
        )
    )
    binary.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            "RELEASE_TAG": tag,
            "GITHUB_REPOSITORY": "release-test/repo",
            "PATH": f"{binary.parent}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
