"""正式タグの版と公開元を検査する。"""

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

tag = os.environ["RELEASE_TAG"]
version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None or tag != f"v{version}":
    raise SystemExit(f"正式タグ {tag!r} は project.version={version!r} と一致する必要があります。")
subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], check=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
repository = os.environ["GITHUB_REPOSITORY"]
runs = json.loads(
    subprocess.check_output(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repository}/actions/workflows/ci.yml/runs",
            "-f",
            "branch=main",
            "-f",
            "event=push",
            "-f",
            f"head_sha={commit}",
            "-f",
            "per_page=1",
        ],
        text=True,
    )
)["workflow_runs"]
expected = {
    "head_sha": commit,
    "head_branch": "main",
    "event": "push",
    "path": ".github/workflows/ci.yml",
    "status": "completed",
    "conclusion": "success",
}
if not runs or any(runs[0].get(key) != value for key, value in expected.items()):
    raise SystemExit(
        "対象commitの最新main CIが成功していません。成功後に公開workflowを再実行してください。"
    )
print(f"公開対象: {tag} ({commit})、main CI成功: {runs[0]['html_url']}")
