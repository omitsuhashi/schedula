"""旧契約を受理するcheckoutで、Draft・manifest・実行記録を別出力へ明示移行する。"""

import argparse
import copy
import json
from importlib.metadata import version
from uuid import uuid4

if __package__:
    from .migrate_contract import migrate, migrate_request
else:
    from migrate_contract import migrate, migrate_request

from shift_schedula.adapter import (
    _confirmation_digest,
    assemble,
    check_adapter,
    confirm_source,
    confirmation_state,
    content_hash,
    diagnostic_sources,
)
from shift_schedula.contract import InvalidInput, diagnostic, reject
from shift_schedula.records import (
    _dependency_versions,
    check_record,
    draft_paths,
    read_draft,
    read_json_file,
    save_json,
)


def _candidate(draft):
    # 確認の代行ではなく、移行する値と所有元を検査する一時コピー。
    candidate = copy.deepcopy(draft)
    candidate["unresolved"] = []
    for source in candidate["sources"]:
        candidate = confirm_source(candidate, source["id"])
    result = assemble(candidate)
    if result["request"] is None:
        raise InvalidInput(result["diagnostics"])
    return result


def migrate_draft(draft, *, history_confirmations=None):
    """所有元を維持して値を変換し、同じ値・依存・改訂の確認だけを引き継ぐ。"""
    check_adapter("draft", draft)
    before = _candidate(draft)
    request = migrate_request(before["request"], history_confirmations=history_confirmations)
    target = copy.deepcopy(draft)
    target["schema_version"] = "0.15"
    sources = {s["id"]: s for s in target["sources"]}
    migration_provenance = {}

    def replace(path, value, *, remove=False):
        locations = diagnostic_sources(
            diagnostic("MIGRATION_FIELD", "", path), before["provenance"]
        )["sources"]
        if len(locations) != 1:
            reject("MIGRATION_OWNER_MISMATCH", "変更項目の所有元を一意に指定します。", path)
        migration_provenance[path] = copy.deepcopy(locations)
        if path == "/shift_candidates" and before["request"].get("shift_templates"):
            migration_provenance[path].extend(before["provenance"]["/shift_templates"])
        location = locations[0]
        parts = location["json_pointer"].split("/")[1:]
        parent = sources[location["source_id"]]
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if remove:
            parent.pop(parts[-1])
        else:
            parent[parts[-1]] = copy.deepcopy(value)

    old = before["request"]
    for key in old.keys() | request.keys():
        if key in {"schema_version", "employees"}:
            continue
        if key not in request or old.get(key) != request[key]:
            replace("/" + key, request.get(key), remove=key not in request)
    for i, (previous, employee) in enumerate(
        zip(old["employees"], request["employees"], strict=True)
    ):
        for key in previous.keys() | employee.keys():
            if previous.get(key) != employee.get(key):
                replace(f"/employees/{i}/{key}", employee.get(key), remove=key not in employee)
    for source, previous in zip(target["sources"], draft["sources"], strict=True):
        if source["section"] == "imported":
            source["data"]["schema_version"] = "0.15"
        if source["data"] != previous["data"]:
            source["revision"] = content_hash(
                {"previous_revision": previous["revision"], "data": source["data"]}
            )

    transferred = []
    for source, state in zip(target["sources"], confirmation_state(draft), strict=True):
        same = _confirmation_digest({**target, "schema_version": draft["schema_version"]}, source)
        if state["state"] == "confirmed" and same == state["digest"]:
            source["confirmation"]["digest"] = _confirmation_digest(target, source)
            transferred.append(source["id"])
        elif state["state"] == "stale" and source["confirmation"]["digest"] == _confirmation_digest(
            target, source
        ):
            source["confirmation"] = None

    checked = _candidate(target)
    if checked["request"] != request:
        reject("MIGRATION_OWNER_MISMATCH", "移行した入力元とRequestが一致しません。")
    return {
        "migration_version": "1.0",
        "migration_id": str(uuid4()),
        "kind": "draft",
        "source_schema_version": draft["schema_version"],
        "target_schema_version": "0.15",
        "source_draft_hash": content_hash(draft),
        "target_draft_hash": content_hash(target),
        "history_confirmations": copy.deepcopy(history_confirmations or {}),
        "original_draft": copy.deepcopy(draft),
        "draft": target,
        "request": request,
        "provenance": checked["provenance"],
        "migration_provenance": migration_provenance,
        "confirmations_before": confirmation_state(draft),
        "confirmations_after": confirmation_state(target),
        "transferred_confirmations": transferred,
        "migration_engine": {
            "version": version("shift-schedula"),
            "dependencies": _dependency_versions(),
        },
    }


def migrate_record(record, *, history_confirmations=None):
    """元実行を保存し、移行後の解と現在検証を別欄に持つ。新しい実行は作らない。"""
    original = check_record(record)
    result = migrate(
        original["request"],
        response=original["response"],
        history_confirmations=history_confirmations,
    )
    if original["draft_metadata"] is not None:
        draft = {
            **original["draft_metadata"],
            "sources": [i["source"] for i in original["sources"]],
        }
        adapter = migrate_draft(draft, history_confirmations=history_confirmations)
        if adapter["request"] != result["request"]:
            reject("RECORD_MISMATCH", "移行したDraftと保存Requestが一致しません。")
        result.update(adapter)
    else:
        if original["sources"]:
            reject("UNTRACKED_SOURCES", "Draftの対応がない入力元は、所有元を確認してください。")
        result.update({"migration_id": str(uuid4()), "draft": None})
    result.update(
        {
            "kind": "record",
            "source_record_hash": content_hash(original),
            "source_run_id": original["run_id"],
            "original_record": original,
            "execution": copy.deepcopy(original["execution"]),
            "migration_engine": {
                "version": result["engine_version"],
                "dependencies": _dependency_versions(),
            },
        }
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["draft", "record"])
    parser.add_argument("input_file")
    parser.add_argument("--history-confirmations")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.input_file == args.history_confirmations == "-":
            reject("INVALID_MIGRATION_INPUT", "標準入力は一つの入力だけに指定します。")
        protected = draft_paths(args.input_file)
        input_value = (
            read_draft(args.input_file)
            if args.kind == "draft"
            else read_json_file(args.input_file)[0]
        )
        inputs = {}
        for path in protected:
            raw, _ = read_json_file(path)
            inputs[str(path)] = {"content_hash": content_hash(raw)}
        if args.input_file == "-":
            inputs["-"] = {"content_hash": content_hash(input_value)}
        confirmations = None
        if args.history_confirmations is not None:
            confirmations, _ = read_json_file(args.history_confirmations)
            if not isinstance(confirmations, dict):
                reject("INVALID_CONFIRMATIONS", "履歴確認はpointerと勤務日のobjectで指定します。")
            if args.history_confirmations != "-":
                protected.append(args.history_confirmations)
            inputs[args.history_confirmations] = {"content_hash": content_hash(confirmations)}
        if args.kind == "draft":
            result = migrate_draft(input_value, history_confirmations=confirmations)
        else:
            result = migrate_record(input_value, history_confirmations=confirmations)
        result["inputs"] = inputs
        save_json(args.output, result, protected=protected)
        print(json.dumps({"status": "MIGRATED", "output": str(args.output)}))
        return 0
    except (InvalidInput, OSError, UnicodeError, RecursionError) as error:
        diagnostics = (
            error.diagnostics
            if isinstance(error, InvalidInput)
            else [diagnostic("MIGRATION_IO_ERROR", "入力読取または新規出力の保存に失敗しました。")]
        )
        status = (
            "NEEDS_CONFIRMATION"
            if any(
                d["code"]
                in {
                    "HISTORY_CONFIRMATION_REQUIRED",
                    "HISTORY_SEMANTICS_CHANGED",
                    "STALE_APPLICABILITY",
                    "UNTRACKED_SOURCES",
                }
                for d in diagnostics
            )
            else "INVALID_INPUT"
        )
        print(json.dumps({"status": status, "diagnostics": diagnostics}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
