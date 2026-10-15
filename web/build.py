"""許可した教材と技術文書だけを、公開prefixの静的成果物へ出力する。"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from web.lessons import LESSONS, PUBLIC_IDS, ROOT, SAMPLES

BASE = "/products/schedula/"
DOCS = ("python-setup", "python-api", "io-contract-current", "distribution")


def build(destination):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("空の出力先を指定してください。")
    product = destination / BASE.strip("/")
    (product / "assets").mkdir(parents=True, exist_ok=True)
    (product / "demo" / "samples").mkdir(parents=True)
    (product / "docs").mkdir()

    html = (ROOT / "demo" / "index.html").read_text(encoding="utf-8")
    html = html.replace('<html lang="ja">', '<html lang="ja" data-public-demo="true">')
    start, end = html.index('  <details id="adapter-demo"'), html.index("</main>")
    html = html[:start] + html[end:]
    html = re.sub(r'  <script src="/demo/adapter.js" defer></script>\n', "", html)
    html = re.sub(r'<a href="#shift_count_balance">.*?</a>', "", html)
    html = html.replace("ローカルデモ", "公開デモ").replace(
        "全44主題の展開と利用者評価は進行中です。",
        "公開対象は必要人数・連勤・手修正検証の3教材です。",
    )
    guide = (ROOT / "demo" / "guide.html").read_text(encoding="utf-8")

    def urls(text):
        def replace(match):
            attribute, path = match.groups()
            if path.startswith(BASE.lstrip("/")):
                return match.group(0)
            if path == "docs.html":
                path = "docs/"
            return f'{attribute}="{BASE}{path}"'

        return re.sub(r'\b(href|src)="/([^\"]*)"', replace, text)

    # scriptはimportせずdefer順で共有する。ファイル内容ごとのhashを参照する。
    for path in (ROOT / "demo").iterdir():
        if path.suffix not in {".js", ".css"} or path.name == "adapter.js":
            continue
        content = path.read_text(encoding="utf-8").replace("/demo/", BASE + "demo/")
        filename = f"{path.stem}.{hashlib.sha256(content.encode()).hexdigest()[:16]}{path.suffix}"
        (product / "assets" / filename).write_text(content, encoding="utf-8")
        original = "/landing.css" if path.name == "landing.css" else f"/demo/{path.name}"
        html = html.replace(original, BASE + "assets/" + filename)
        guide = guide.replace(original, BASE + "assets/" + filename)
    html, guide = urls(html), urls(guide)
    for text, name in ((html, "demo/index.html"), (guide, "docs/index.html")):
        text = text.replace(
            "</head>",
            f'  <link rel="canonical" href="https://the3.co.jp{BASE}{name.split("/")[0]}/">\n</head>',
        )
        (product / name).write_text(text, encoding="utf-8")
    catalog = json.loads((SAMPLES / "catalog.json").read_text(encoding="utf-8"))
    catalog["topics"] = [item for item in catalog["topics"] if item["id"] in PUBLIC_IDS]
    catalog["templates"] = []
    sample_dir = product / "demo" / "samples"
    for filename, value in (("catalog.json", catalog), ("lessons.json", list(LESSONS.values()))):
        (sample_dir / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    for lesson in LESSONS.values():
        for key in ("request_file", "solution_file"):
            if key in lesson:
                (sample_dir / lesson[key]).write_bytes((SAMPLES / lesson[key]).read_bytes())

    def document_link(match):
        label, link = match.groups()
        target = urlsplit(link)
        if target.scheme or target.netloc or not target.path:
            return match.group(0)
        if target.path in {f"{name}.md" for name in DOCS}:
            return match.group(0)
        if target.path == "../LICENSE":
            return f"[{label}]({link.replace('../LICENSE', '../license.txt', 1)})"
        return f"{label}（ソース配布内の `{link}`）"

    for name in DOCS:
        content = (ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")
        content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", document_link, content)
        note = "> 公開版の対象外のファイルは、ソース配布内の参照として記載しています。\n\n"
        (product / "docs" / f"{name}.md").write_text(note + content, encoding="utf-8")
    (product / "license.txt").write_bytes((ROOT / "LICENSE").read_bytes())
    return product


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
