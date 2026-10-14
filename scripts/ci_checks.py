"""PRの検証範囲を選び、必要なCIジョブの成功を確認する。"""

import json
import os
import subprocess
import sys
from pathlib import Path

CHECKS = ("python", "distribution", "browser")
JOBS = {
    "python-tests": "python",
    "timezone-distribution": "python",
    "distribution": "distribution",
    "browser": "browser",
}


def select_checks(paths):
    selected = set()
    for name in paths:
        path = Path(name)
        if name.startswith(("docs/designs/", "docs/evaluations/inputs/")):
            # 実行用データ・設計断片の検証はsdist内の回帰から除外される。
            selected.update(CHECKS)
        elif (name.startswith("demo/") and path.suffix in {".html", ".css", ".js"}) or (
            name.startswith("tests/") and path.suffix == ".cjs"
        ):
            selected.update(("distribution", "browser"))
        elif name.startswith("docs/") and path.suffix in {".md", ".html", ".json"}:
            selected.update(("distribution", "browser"))
        elif name in {"README.md", "AGENTS.md", "GLOSSARY.md", "THIRD_PARTY_NOTICES.md"}:
            selected.add("distribution")
        elif name == "LICENSE":
            selected.update(("distribution", "browser"))
        else:
            selected.update(CHECKS)
    # 判定対象がない場合も全検証する。
    return {check: check in selected or not paths for check in CHECKS}


def changed_paths(base, head):
    # renameの旧パスと新パス、削除も対象にする。NUL区切りで特殊なファイル名を保持する。
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"]
    )
    return [os.fsdecode(name) for name in output.split(b"\0") if name]


def check_results(results):
    for job in ("changes", "lint"):
        if results[job]["result"] != "success":
            raise ValueError(f"{job} が成功していません")
    outputs = results["changes"]["outputs"]
    for job, check in JOBS.items():
        if outputs[check] not in {"true", "false"}:
            raise ValueError(f"{check} の選択結果が不正です")
        expected = "success" if outputs[check] == "true" else "skipped"
        if results[job]["result"] != expected:
            raise ValueError(f"{job}: {expected} が必要です: {results[job]['result']}")


def main():
    if sys.argv[1] == "check":
        check_results(json.loads(os.environ["CI_RESULTS"]))
        print("必要な検証はすべて成功しました")
        return
    if sys.argv[1] != "select":
        raise ValueError("select または check を指定してください")
    selected = dict.fromkeys(CHECKS, True)
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr = event["pull_request"]
        selected = select_checks(changed_paths(pr["base"]["sha"], pr["head"]["sha"]))
    print(json.dumps(selected))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for check, enabled in selected.items():
            output.write(f"{check}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
