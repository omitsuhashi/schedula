"""Web公開タグとmain CIを確認する。AWS認証前に実行する。"""

import json
import os
import re
import subprocess


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def check(tag, repository):
    if not re.fullmatch(r"web-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Webタグはweb-vMAJOR.MINOR.PATCHに限定します。")
    if repository != "the3-inc/schedula":
        raise ValueError("公開元リポジトリが一致しません。")
    sha = command("git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], check=True)
    runs = json.loads(
        command(
            "gh",
            "api",
            f"repos/{repository}/actions/runs?head_sha={sha}&event=push&branch=main&per_page=100",
        )
    )["workflow_runs"]
    matches = [run for run in runs if run["path"] == ".github/workflows/ci.yml"]
    if not matches or max(matches, key=lambda run: run["id"])["conclusion"] != "success":
        raise ValueError("対象commitの最新main CIが成功していません。")
    return sha


if __name__ == "__main__":
    if (
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ["GITHUB_REF"] != "refs/heads/main"
    ):
        raise ValueError("手動公開はmainのworkflowから実行します。")
    sha = check(os.environ["RELEASE_TAG"], os.environ["GITHUB_REPOSITORY"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"sha={sha}\n")
