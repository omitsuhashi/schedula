"""入力元に依存しない実行記録と、明示ファイルだけを扱うローカルI/O。"""

import copy
import os
import stat
import sys
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from .adapter import (
    assemble,
    canonical_json,
    check_adapter,
    content_hash,
    diagnostic_sources,
)
from .contract import InvalidInput, diagnostic, load_json
from .engine import solve, validate, validate_response
from .verify import verify

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 32


def _reject(code, message, path=""):
    raise InvalidInput([diagnostic(code, message, path)])


def read_json_file(path, *, limit=MAX_FILE_BYTES):
    """通常ファイルまたはインライン標準入力を、上限付きで厳密に読む。"""
    if str(path) == "-":
        data = sys.stdin.buffer.read(limit + 1)
    else:
        path = Path(path)
        if path.is_symlink():
            _reject("UNSAFE_PATH", "シンボリックリンクは読み込みません。")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                _reject("UNSAFE_PATH", "通常ファイルだけを読み込みます。")
            data = stream.read(limit + 1)
    if len(data) > limit:
        _reject("FILE_TOO_LARGE", f"入力は{limit} bytes以下にします。")
    return load_json(data.decode("utf-8")), len(data)


def draft_paths(path):
    """出力先の原本保護にも、読み込みと同じ明示参照の境界を使う。"""
    if str(path) == "-":
        return []
    source = Path(path)
    value, _ = read_json_file(source)
    paths = [source.resolve()]
    if isinstance(value, dict) and "manifest_version" in value:
        check_adapter("manifest", value)
        for name in value["files"]:
            relative = Path(name)
            if (
                relative.is_absolute()
                or PureWindowsPath(name).is_absolute()
                or ".." in relative.parts
                or "\\" in name
                or ":" in name
            ):
                _reject("UNSAFE_PATH", "親参照・絶対パスは指定できません。", "/files")
            candidate = source.resolve().parent
            for part in relative.parts:
                candidate /= part
                if candidate.is_symlink():
                    _reject("UNSAFE_PATH", "シンボリックリンクは参照できません。", "/files")
            resolved = candidate.resolve()
            if not resolved.is_relative_to(source.resolve().parent):
                _reject("UNSAFE_PATH", "manifestの親の中だけを参照します。", "/files")
            if resolved in paths:
                _reject("DUPLICATE_FILE", "ファイル参照が重複しています。", "/files")
            paths.append(resolved)
    return paths


def read_draft(path):
    value, size = read_json_file(path)
    if isinstance(value, dict) and "manifest_version" in value:
        if str(path) == "-":
            _reject("STDIN_MANIFEST", "標準入力ではインラインDraftだけを指定します。")
        check_adapter("manifest", value)
        paths = draft_paths(path)
        value = {**value["draft"], "sources": []}
        for source_path in paths[1:]:
            source, count = read_json_file(
                source_path, limit=min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - size)
            )
            size += count
            if size > MAX_TOTAL_BYTES:
                _reject("TOTAL_TOO_LARGE", "入力ファイルの合計上限を超えました。")
            if isinstance(source, dict):
                source["file"] = str(source_path.relative_to(Path(path).resolve().parent))
            value["sources"].append(source)
    check_adapter("draft", value)
    return value


def save_json(path, value, *, overwrite=False, protected=()):
    """途中失敗で既存記録を壊さず、新規出力/明示上書きだけを行う。"""
    path = Path(path)
    if path.resolve() in {Path(p).resolve() for p in protected}:
        _reject("PROTECTED_INPUT", "元入力・参照元には出力できません。")
    if path.is_symlink():
        _reject("UNSAFE_PATH", "出力先にシンボリックリンクは指定できません。")
    data = canonical_json(value) + b"\n"
    if len(data) > MAX_FILE_BYTES:
        _reject("FILE_TOO_LARGE", "保存データの上限を超えました。切り詰めません。")
    fd, temporary = tempfile.mkstemp(prefix=".schedula-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # 競合時にも既存ファイルを上書きしない。
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _dependency_versions():
    result = {}
    for name in ("jsonschema", "ortools", "tzdata"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def _check_pair(request, response):
    checked = validate(request)
    if checked["status"] != "VALID":
        raise InvalidInput(checked["diagnostics"])
    validate_response(response, request)
    if response["schema_version"] == "0.1" and response["solution"] is not None:
        checked_plan = verify(request, response["solution"])
        if checked_plan["verification"]["valid"] is not True:
            raise InvalidInput(checked_plan["diagnostics"])
        expected = [(o["id"], o["metric"], o["value"]) for o in checked_plan["objectives"]]
        actual = [(o["id"], o["metric"], o["value"]) for o in response["objectives"]]
        if expected != actual:
            _reject("RECORD_MISMATCH", "保存した目的値がRequest/解と一致しません。")


def _check_draft_pair(record):
    if record["draft_metadata"] is None:
        return
    draft = {**record["draft_metadata"], "sources": [i["source"] for i in record["sources"]]}
    assembled = assemble(draft)
    if assembled["request"] is None:
        raise InvalidInput(assembled["diagnostics"])
    if assembled["request"] != record["request"]:
        _reject("RECORD_MISMATCH", "記録した入力元/確認と確定Requestが一致しません。")


def create_record(request, response, provenance=None, sources=(), *, num_workers=2, draft=None):
    if type(num_workers) is not int or not 1 <= num_workers <= 32:
        _reject("INVALID_EXECUTION", "num_workersは1〜32の整数で指定します。")
    _check_pair(request, response)
    if response["request_id"] != request.get("request_id"):
        _reject("RECORD_MISMATCH", "RequestとResponseのIDが一致しません。")
    record = {
        "draft_metadata": {k: copy.deepcopy(v) for k, v in draft.items() if k != "sources"}
        if draft is not None
        else None,
        "record_version": "1.0",
        "run_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "request": copy.deepcopy(request),
        "response": copy.deepcopy(response),
        "execution": {"num_workers": num_workers},
        "engine": {"version": version("shift-schedula"), "dependencies": _dependency_versions()},
        "sources": [{"source": copy.deepcopy(s), "content_hash": content_hash(s)} for s in sources],
        "provenance": copy.deepcopy(provenance or {}),
    }
    record["content_hash"] = content_hash(record)
    check_adapter("record", record)
    _check_draft_pair(record)
    return record


def check_record(record):
    check_adapter("record", record)
    if (
        content_hash({k: v for k, v in record.items() if k != "content_hash"})
        != record["content_hash"]
    ):
        _reject("RECORD_HASH_MISMATCH", "実行記録の入力・設定・結果の照合に失敗しました。")
    for item in record["sources"]:
        if content_hash(item["source"]) != item["content_hash"]:
            _reject("SOURCE_HASH_MISMATCH", "入力元の内容ハッシュが一致しません。")
    request, response = record["request"], record["response"]
    if response.get("request_id") != request.get("request_id"):
        _reject("RECORD_MISMATCH", "RequestとResponseのIDが一致しません。")
    _check_pair(request, response)
    _check_draft_pair(record)
    return copy.deepcopy(record)


def run_draft(draft, *, num_workers=2):
    assembled = assemble(draft)
    if assembled["request"] is None:
        raise InvalidInput(assembled["diagnostics"])
    if type(num_workers) is not int or not 1 <= num_workers <= 32:
        _reject("INVALID_EXECUTION", "num_workersは1〜32の整数で指定します。")
    result = solve(assembled["request"], num_workers=num_workers)
    return create_record(
        assembled["request"],
        result,
        assembled["provenance"],
        draft["sources"],
        num_workers=num_workers,
        draft=draft,
    )


def reverify_record(record, *, solution=None):
    saved = check_record(record)
    plan = saved["response"]["solution"] if solution is None else solution
    current = verify(saved["request"], plan) if plan is not None else None
    return {
        "record": saved,
        "current_verification": current,
        "current_solution": copy.deepcopy(plan),
    }


def record_view(record, *, solution=None):
    checked = reverify_record(record, solution=solution)
    saved, current = checked["record"], checked["current_verification"]
    valid = current is not None and current["verification"]["valid"] is True
    evidence = saved["response"]
    metrics = {
        k: copy.deepcopy(v)
        for k, v in (current or {}).items()
        if k == "objectives" or k.endswith("_summary")
    }
    return {
        "run_id": saved["run_id"],
        "record_hash": saved["content_hash"],
        "request_id": saved["request"]["request_id"],
        "original_status": evidence["status"],
        "current_status": current["status"] if current else "NOT_PERFORMED",
        "verification": current["verification"] if current else None,
        "demand_satisfied": current["demand_satisfied"] if current else None,
        "planning_window": saved["request"]["planning_window"],
        "solution": checked["current_solution"] if valid else None,
        "metrics": metrics,
        "diagnostics": [
            diagnostic_sources(d, saved["provenance"])
            for d in (current["diagnostics"] if current else evidence["diagnostics"])
        ],
        "original_evidence": copy.deepcopy(evidence),
    }
