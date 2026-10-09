"""一時的なアプリ移行の条件・元記録・確認と読取専用DB境界を検証する。"""

import copy
import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from scripts.migrate_app import main, migrate_document, read_session
from shift_schedula import create_record, import_request, solve, verify
from shift_schedula.adapter import confirmation_state
from tests.test_contract_migration import read_case

SOURCE = {"version": "0.1.6", "schema_version": "0.10", "commit": "old", "sha256": "old"}
TARGET = {**SOURCE, "schema_version": "0.15", "commit": "new", "sha256": "new"}


def document(name="partial_roster", record=False):
    request = read_case(name, "legacy")
    response = solve(request)
    plan = {"id": "original", "label": "原計画", "request": request, "result": response}
    draft = import_request(request)
    if record:
        from shift_schedula import assemble

        assembled = assemble(draft)
        plan["record"] = create_record(
            request, response, assembled["provenance"], draft["sources"], draft=draft
        )
    return {
        "format": "schedula-app/2" if record else "schedula-app/1",
        "engine": SOURCE,
        "input": "unfinished {",
        "plans": [plan],
        "selected": "original",
        "baseline": "original",
        "edit": {"request": request, "solution": response["solution"]},
        **({"request_draft": draft} if record else {}),
    }


@pytest.mark.parametrize("name", ["partial_roster", "continuity_replan", "roster"])
@pytest.mark.parametrize("record", [False, True])
def test_app_conversion_preserves_conditions_original_evidence_and_unfinished_edits(name, record):
    original = document(name, record)
    saved = copy.deepcopy(original)
    calls = []

    def restore(value, engine):
        # 実アプリのrestoreを呼ぶ前後の引数。実保存往復は候補アプリで別途検証する。
        assert value["engine"] == engine
        calls.append(copy.deepcopy(value))
        for plan in value["plans"]:
            assert verify(plan["request"], plan["result"]["solution"])["verification"]["valid"]
        return value

    target = migrate_document(original, SOURCE, TARGET, restore)
    assert calls[0] == saved and calls[1] == target and original == saved
    assert target["engine"] == TARGET
    assert target["input"] == saved["input"]
    assert target["selected"] == target["baseline"] == "original"
    plan = target["plans"][0]
    assert plan["evidence"]["migration"]["original_plan"] == saved["plans"][0]
    assert plan["request"]["planning_window"] == saved["plans"][0]["request"]["planning_window"]
    assert plan["request"]["schema_version"] == "0.15"
    assert "record" not in plan
    assert target["edit"]["solution"] == saved["edit"]["solution"]
    assert target["edit"]["request"]["schema_version"] == "0.15"
    assert all(not o["proven_optimal"] for o in plan["current_verification"]["objectives"])
    assert not plan["current_verification"]["shortage_summary"]["proven_minimal"]
    if record:
        assert target["request_draft"]["schema_version"] == "0.15"
        assert all(s["state"] != "confirmed" for s in confirmation_state(target["request_draft"]))


def test_failed_app_boundary_does_not_modify_source():
    original = document()
    saved = copy.deepcopy(original)

    def refuse(value, engine):
        value["input"] = "mutated validator copy"
        raise ValueError("pin mismatch")

    with pytest.raises(ValueError, match="pin mismatch"):
        migrate_document(original, SOURCE, TARGET, refuse)
    assert original == saved


def test_cli_new_output_only_and_pin_failure_preserve_original(tmp_path, monkeypatch, capsys):
    original = document()
    source = tmp_path / "source.json"
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "new.json"
    source.write_text(json.dumps(original))
    manifest.write_text(json.dumps(SOURCE))
    raw = source.read_bytes()

    def restore(value, engine):
        if value["engine"] != engine:
            raise ValueError("pin mismatch")
        return value

    monkeypatch.setitem(
        sys.modules, "server", SimpleNamespace(MAX_BODY_BYTES=8 * 1024**2, runtime=lambda: TARGET)
    )
    monkeypatch.setitem(sys.modules, "workflow", SimpleNamespace(restore=restore))
    args = [
        str(source),
        "--source-manifest",
        str(manifest),
        "--app-source",
        str(tmp_path),
        "--output",
    ]
    assert main([*args, str(output)]) == 0
    result = output.read_bytes()
    assert main([*args, str(output)]) == 2
    assert main([*args, str(source)]) == 2
    manifest.write_text(json.dumps({**SOURCE, "sha256": "wrong"}))
    assert main([*args, str(tmp_path / "bad.json")]) == 2
    assert not (tmp_path / "bad.json").exists()
    assert source.read_bytes() == raw and output.read_bytes() == result
    captured = capsys.readouterr()
    assert "unfinished" not in captured.out + captured.err


@pytest.mark.parametrize("version", [1, 2])
def test_sqlite_export_is_read_only_and_matches_json_boundary(tmp_path, version):
    original = document(record=version == 2)
    path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={version}")
        db.execute("CREATE TABLE metadata(engine TEXT)")
        db.execute("INSERT INTO metadata VALUES (?)", (json.dumps(SOURCE),))
        columns = "id,input,selected,baseline,edit" + (",request_draft" if version == 2 else "")
        db.execute(f"CREATE TABLE sessions({columns})")
        row = [
            "session",
            original["input"],
            original["selected"],
            original["baseline"],
            json.dumps(original["edit"]),
        ]
        if version == 2:
            row += [json.dumps(original["request_draft"])]
        db.execute(f"INSERT INTO sessions VALUES ({','.join('?' for _ in row)})", row)
        names = ["id", "label", "request", "result", "evidence"]
        if version == 2:
            names += ["record", "current_verification"]
        db.execute(f"CREATE TABLE plans(session_id,{','.join(names)})")
        plan = original["plans"][0]
        values = ["session"] + [
            plan.get(n) if n in ("id", "label") else json.dumps(plan[n]) if n in plan else None
            for n in names
        ]
        db.execute(f"INSERT INTO plans VALUES ({','.join('?' for _ in values)})", values)
    raw = path.read_bytes()
    assert read_session(path, "session") == original
    with pytest.raises(ValueError, match="セッション"):
        read_session(path, "missing")
    assert path.read_bytes() == raw
