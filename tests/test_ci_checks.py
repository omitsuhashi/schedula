import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_checks import CHECKS, JOBS, changed_paths, check_results, select_checks

pytestmark = pytest.mark.repository
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_checks.py"


@pytest.mark.parametrize(
    ("paths", "enabled"),
    [
        ([], CHECKS),
        (["demo/app.js"], ("distribution", "browser")),
        (["demo/style.css", "demo/index.html"], ("distribution", "browser")),
        (["tests/playground-browser.cjs"], ("distribution", "browser")),
        (["docs/python-api.md"], ("distribution", "browser")),
        (["docs/adr/0010-single-current-contract.md"], ("distribution", "browser")),
        (["docs/designs/scheduled-cost.md"], CHECKS),
        (["docs/evaluations/inputs/assignment-week.json"], CHECKS),
        (["docs/designs/old.md", "docs/notes/new.md"], CHECKS),
        (["README.md", "GLOSSARY.md"], ("distribution",)),
        (["LICENSE"], ("distribution", "browser")),
        *[
            ([name], CHECKS)
            for name in (
                "src/shift_schedula/solver.py",
                "src/shift_schedula/schemas/0.15/request.schema.json",
                "demo/server.py",
                "tests/conftest.py",
                "tests/fixtures/contract-015/assignment.json",
                "examples/playground/lunch.json",
                "scripts/ci_checks.py",
                "docs/designs/check_numbers.py",
                "pyproject.toml",
                "uv.lock",
                "MANIFEST.in",
                ".python-version",
                ".pre-commit-config.yaml",
                ".github/workflows/ci.yml",
                "unknown/new-file.txt",
            )
        ],
        (["demo/style.css", "src/shift_schedula/solver.py"], CHECKS),
        (["demo/new\nfile.js"] * 400, ("distribution", "browser")),
    ],
)
def test_selection_keeps_shared_and_unknown_changes_fully_verified(paths, enabled):
    assert select_checks(paths) == {check: check in enabled for check in CHECKS}


def successful_results(enabled):
    outputs = {check: str(check in enabled).lower() for check in CHECKS}
    return {
        "changes": {"result": "success", "outputs": outputs},
        "lint": {"result": "success"},
        **{
            job: {"result": "success" if check in enabled else "skipped"}
            for job, check in JOBS.items()
        },
    }


@pytest.mark.parametrize("enabled", [CHECKS, ("distribution", "browser"), ("distribution",)])
def test_selected_success_and_intentional_skips_are_accepted(enabled):
    check_results(successful_results(enabled))


@pytest.mark.parametrize("job", ["changes", "lint", *JOBS])
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_failures_cancellations_and_required_skips_are_rejected(job, result):
    results = successful_results(CHECKS)
    results[job]["result"] = result
    with pytest.raises(ValueError):
        check_results(results)


@pytest.mark.parametrize("value", ["", "TRUE", "unknown", None])
def test_invalid_selection_is_rejected(value):
    results = successful_results(CHECKS)
    results["changes"]["outputs"]["python"] = value
    with pytest.raises(ValueError):
        check_results(results)


def test_missing_job_or_selection_is_rejected():
    results = successful_results(CHECKS)
    del results["browser"]
    with pytest.raises(KeyError):
        check_results(results)
    results = successful_results(CHECKS)
    del results["changes"]["outputs"]["python"]
    with pytest.raises(KeyError):
        check_results(results)


@pytest.mark.parametrize("success", [True, False])
def test_aggregate_command_exits_unsuccessfully_on_cancelled_required_job(success):
    results = successful_results(("distribution", "browser"))
    if not success:
        results["browser"]["result"] = "cancelled"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        env={**os.environ, "CI_RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr


def test_unavailable_diff_cannot_be_treated_as_empty_changes(tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        changed_paths("missing-base", "missing-head")


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_event_selection_uses_merge_base_and_preserves_deleted_and_renamed_paths(
    tmp_path, monkeypatch, event
):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "CI test")
    git("config", "user.email", "ci@example.invalid")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo/old.js").write_text("content")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "pr")
    (tmp_path / "demo/old.js").rename(tmp_path / "demo/new\nname.js")
    git("add", ".")
    git("commit", "-m", "rename")
    head = git("rev-parse", "HEAD")
    git("checkout", "main")
    (tmp_path / "main-only.py").write_text("pass")
    git("add", ".")
    git("commit", "-m", "advance base")
    base = git("rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    assert set(changed_paths(base, head)) == {"demo/old.js", "demo/new\nname.js"}
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"base": {"sha": base}, "head": {"sha": head}}})
    )
    output = tmp_path / "output"
    subprocess.run(
        [sys.executable, str(SCRIPT), "select"],
        check=True,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": event,
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_OUTPUT": str(output),
        },
    )
    enabled = CHECKS if event == "push" else ("distribution", "browser")
    assert output.read_text().splitlines() == [
        f"{check}={str(check in enabled).lower()}" for check in CHECKS
    ]
