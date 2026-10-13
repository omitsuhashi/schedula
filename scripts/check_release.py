"""正式タグの版と公開元を検査する。"""

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
print(f"公開対象: {tag} (main に含まれる commit)")
