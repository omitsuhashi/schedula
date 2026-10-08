import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import (
    InvalidInput,
    adapter,
    assemble,
    check_record,
    confirm_source,
    confirmation_state,
    get_adapter_schema,
    import_request,
    make_baseline,
    read_draft,
    record_view,
    records,
    reverify_record,
    run_draft,
    save_json,
    solve,
    split_request,
    validate,
    verify,
)
from shift_schedula.contract import SCHEMA_VERSIONS
from tests.support import assert_response

ROOT = Path(__file__).resolve().parents[1]


def request(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))


def confirmed(value):
    draft = split_request(value)
    for source in draft["sources"]:
        draft = confirm_source(draft, source["id"])
    return draft


def source(draft, section):
    return next(s for s in draft["sources"] if s["section"] == section)


def assert_code(draft, code):
    before = copy.deepcopy(draft)
    result = assemble(draft)
    assert result["request"] is None and result["status"] == "INVALID_INPUT"
    assert any(d["code"] == code for d in result["diagnostics"]), result
    assert draft == before
    return result


@pytest.mark.parametrize(
    "name",
    [
        "assignment",
        "roster",
        "partial_roster",
        "partial_assignment",
        "overnight",
        "split_roster",
        "continuity_week",
        "continuity_month",
        "continuity_replan",
        "continuity_duty_balance",
        "partial_replan_preserve_assigned",
        "partial_replan_rebuild",
        "combined_conditions",
        "combined_month",
        "shift_count_balance",
    ],
)
def test_roundtrip_matches_complete_request_and_same_solution(name):
    value = request(name)
    before = copy.deepcopy(value)
    draft = confirmed(value)
    draft_before = copy.deepcopy(draft)
    assembled = assemble(draft)
    assert assembled["status"] == "VALID", assembled["diagnostics"]
    assert assembled["request"] == value
    assert value == before and draft == draft_before
    response = solve(value)
    assert response["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}
    direct = verify(value, response["solution"])
    other = verify(assembled["request"], response["solution"])
    direct.pop("stats")
    other.pop("stats")
    assert direct == other
    assert assembled["provenance"]["/employees/0/availability"][0]["section"] == "period"
    record = run_draft(draft)
    assert_response(record["response"], record["response"]["status"])
    restored = reverify_record(record)
    assert restored["current_verification"]["verification"]["valid"]
    assert all(not o["proven_optimal"] for o in restored["current_verification"]["objectives"])
    assert restored["current_verification"]["shortage_summary"]["proven_minimal"] is False
    assert record == restored["record"]


@pytest.mark.parametrize("version", SCHEMA_VERSIONS)
def test_all_contract_versions_and_ownership_table(version):
    value = request("assignment")
    value["schema_version"] = version
    assert validate(value)["status"] == "VALID"
    draft = confirmed(value)
    assert assemble(draft)["request"] == value
    fields = set(adapter.get_schema("request", version)["properties"]) - {"schema_version"}
    assert fields <= set().union(*adapter.SECTIONS.values())
    record = run_draft(draft)
    assert reverify_record(record)["current_verification"]["status"] == "VALID"


def test_confirmation_changes_only_affected_values_and_references():
    draft = confirmed(request("roster"))
    before = copy.deepcopy(draft)
    period = source(draft, "period")
    period["data"]["employees"][0]["availability"] = []
    states = {s["source_id"]: s["state"] for s in confirmation_state(draft)}
    assert states["period"] == "stale"
    assert all(v == "confirmed" for k, v in states.items() if k != "period")
    draft = confirm_source(draft, "period")
    assert assemble(draft)["status"] == "VALID"
    basic = source(draft, "basic")
    basic["data"]["employees"][0]["skills"] = []
    states = {s["source_id"]: s["state"] for s in confirmation_state(draft)}
    assert states["basic"] == states["period"] == "stale"
    assert states["common"] == "confirmed"
    draft = copy.deepcopy(before)
    source(draft, "basic")["data"]["employees"][0]["label"] = "<script>text</script>"
    states = {s["source_id"]: s["state"] for s in confirmation_state(draft)}
    assert states["basic"] == "stale" and states["period"] == "confirmed"
    source(draft, "basic")["revision"] = "2"
    assert {s["source_id"]: s["state"] for s in confirmation_state(draft)}["common"] == "confirmed"
    # 勤務不可/未入力、0目標/対象外、履歴なし/未確認を補完しない。
    draft = confirmed(request("roster"))
    del source(draft, "period")["data"]["employees"][0]["availability"]
    draft = confirm_source(draft, "period")
    assert_code(draft, "SCHEMA_VIOLATION")
    draft = confirmed(request("roster"))
    source(draft, "history")["confirmation"] = None
    assert_code(draft, "UNCONFIRMED_SOURCE")
    assert assemble(confirmed(request("assignment")))["status"] == "VALID"


def test_import_unknown_provenance_and_no_solver_in_assembly(monkeypatch):
    value = request("roster")
    draft = import_request(value)
    assert draft["sources"][0]["origin"] == "unknown"
    assert draft["sources"][0]["confirmation"]["provenance"] == "unknown"
    assert assemble(draft)["request"] == value
    draft["sources"][0]["data"]["employees"][0]["availability"] = []
    assert_code(draft, "UNCONFIRMED_SOURCE")
    draft = confirm_source(draft, "imported")
    assert assemble(draft)["status"] == "VALID"
    assert draft["sources"][0]["origin"] == "unknown"

    def unexpected(*args, **kwargs):
        raise AssertionError("assembly must not call a solver")

    monkeypatch.setattr("shift_schedula.cp_sat.load_backend", unexpected)
    monkeypatch.setattr("shift_schedula.flow.run", unexpected)
    assert assemble(confirmed(value))["status"] == "VALID"


def test_conflict_invalid_reference_and_feasibility_are_distinct():
    draft = confirmed(request("assignment"))
    duplicate = copy.deepcopy(source(draft, "period"))
    duplicate["id"] = "other"
    draft["sources"].append(duplicate)
    draft = confirm_source(draft, "other")
    result = assert_code(draft, "OWNERSHIP_CONFLICT")
    error = next(e for e in result["diagnostics"] if e["code"] == "OWNERSHIP_CONFLICT")
    assert {s["source_id"] for s in error["sources"]} == {"period", "other"}
    draft = confirmed(request("assignment"))
    source(draft, "period")["data"]["employees"].reverse()
    source(draft, "period")["data"]["employees"][0]["availability"][0]["start"] = "bad"
    draft = confirm_source(draft, "period")
    result = assert_code(draft, "SCHEMA_VIOLATION")
    e = next(e for e in result["diagnostics"] if e["json_pointer"].endswith("/start"))
    assert e["sources"][0]["json_pointer"] == "/data/employees/0/availability/0/start"
    draft = confirmed(request("assignment"))
    source(draft, "period")["data"]["employees"][0]["id"] = "unknown"
    draft = confirm_source(draft, "period")
    assert_code(draft, "UNKNOWN_REFERENCE")
    value = request("assignment")
    for e in value["employees"]:
        e["skills"] = []
    draft = confirmed(value)
    assert assemble(draft)["status"] == "VALID"
    assert run_draft(draft)["response"]["status"] == "INFEASIBLE"
    view = record_view(run_draft(draft))
    assert view["current_status"] == "NOT_PERFORMED" and view["solution"] is None
    for key in ("schema_version", "solver"):
        broken = copy.deepcopy(draft)
        if key == "schema_version":
            broken[key] = "9.9"
        else:
            source(broken, "execution")["data"]["extra"] = True
        if key != "schema_version":
            broken = confirm_source(broken, "execution")
        assert assemble(broken)["request"] is None


def test_week_change_dates_explicit_and_original_history_kept():
    value = request("roster")
    draft = confirmed(value)
    period = source(draft, "period")
    original_history = copy.deepcopy(source(draft, "history")["data"])
    period["data"]["planning_window"]["start"] = "2026-10-12T00:00:00+09:00"
    period["data"]["planning_window"]["end"] = "2026-10-19T00:00:00+09:00"
    assert_code(draft, "STALE_APPLICABILITY")
    assert source(draft, "history")["data"] == original_history
    period["applies_to"] = copy.deepcopy(period["data"]["planning_window"])
    source(draft, "history")["applies_to"] = copy.deepcopy(period["data"]["planning_window"])
    for s in draft["sources"]:
        draft = confirm_source(draft, s["id"])
    # 日付は移動されず、既存validateが古い需要/候補を拒否する。
    assert assemble(draft)["status"] == "INVALID_INPUT"
    assert source(draft, "period")["data"]["shift_templates"] == value["shift_templates"]


def test_explicit_rule_override_and_order():
    value = request("roster")
    draft = confirmed(value)
    common = source(draft, "common")
    old = copy.deepcopy(common["data"]["constraints"][0])
    replacement = {**old, "limit_minutes": old["limit_minutes"] + 30}
    period = source(draft, "period")
    period["data"]["constraints"] = [replacement]
    draft["overrides"] = [
        {
            "source_id": "period",
            "target_source_id": "common",
            "constraint_id": old["id"],
            "before": old,
            "reason": "今回の勤務量上限を明示変更する",
        }
    ]
    draft = confirm_source(confirm_source(draft, "common"), "period")
    assembled = assemble(draft)
    assert assembled["status"] == "VALID", assembled
    assert assembled["request"]["constraints"][0] == replacement
    draft["overrides"][0]["before"]["limit_minutes"] -= 1
    draft = confirm_source(confirm_source(draft, "common"), "period")
    assert_code(draft, "INVALID_OVERRIDE")


def test_save_snapshot_mixups_reverify_and_replanning(tmp_path):
    draft = confirmed(request("partial_replan_preserve_assigned"))
    record = run_draft(draft)
    saved = copy.deepcopy(record)
    path = tmp_path / "run.json"
    save_json(path, record)
    source(draft, "basic")["data"]["employees"][0]["skills"] = []
    restored, _ = records.read_json_file(path)
    checked = reverify_record(restored)
    assert checked["current_verification"]["status"] == "PARTIAL"
    assert record == saved
    baseline = make_baseline(record["request"], record["response"]["solution"], "saved")
    assert baseline["source_request"]
    broken = copy.deepcopy(record["response"]["solution"])
    broken["assignments"] = []
    view = record_view(record, solution=broken)
    assert view["current_status"] in {"PARTIAL", "INVALID_PLAN"}
    assert record == saved
    other = run_draft(confirmed(request("partial_replan_preserve_assigned")))
    assert other["run_id"] != record["run_id"]
    assert other["request"]["request_id"] == record["request"]["request_id"]
    for field, replacement in [
        ("request", other["request"]),
        ("response", other["response"]),
        ("execution", {"num_workers": 1}),
    ]:
        corrupt = copy.deepcopy(record)
        if field == "request":
            replacement = {**replacement, "request_id": "different"}
        corrupt[field] = replacement
        if corrupt == record:
            continue
        with pytest.raises(InvalidInput):
            check_record(corrupt)
    corrupt = copy.deepcopy(record)
    corrupt["content_hash"] = adapter.content_hash(
        {k: v for k, v in corrupt.items() if k != "content_hash"}
    )
    assert check_record(corrupt) == record
    assert adapter.content_hash({"b": 2, "a": [1, 0]}) == adapter.content_hash(
        {"a": [1, 0], "b": 2}
    )
    assert adapter.content_hash([1, 0]) != adapter.content_hash([0, 1])
    assert adapter.content_hash(1) != adapter.content_hash(1.0)
    for bad in ("{", '{"a":1,"a":2}', '{"a":NaN}'):
        path.write_text(bad)
        with pytest.raises(InvalidInput):
            records.read_json_file(path)


def test_file_boundaries_atomic_save_and_input_protection(tmp_path, monkeypatch):
    original = read_draft(ROOT / "examples/adapter/assignment.manifest.json")
    assert assemble(original)["status"] == "VALID"
    files = []
    for s in original["sources"]:
        name = s["id"] + ".json"
        save_json(tmp_path / name, s)
        files.append(name)
    manifest = {
        "manifest_version": "1.0",
        "draft": {k: v for k, v in original.items() if k != "sources"},
        "files": files,
    }
    path = tmp_path / "manifest.json"
    save_json(path, manifest)
    assert read_draft(path) == original
    original_bytes = path.read_bytes()
    with pytest.raises(InvalidInput):
        save_json(path, original, overwrite=True, protected=[path])
    with pytest.raises(FileExistsError):
        save_json(path, original)
    assert path.read_bytes() == original_bytes

    def fail(*args):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        save_json(path, original, overwrite=True)
    assert path.read_bytes() == original_bytes
    assert not list(tmp_path.glob(".schedula-*"))
    for name in ("../outside.json", "/absolute.json", "C:\\absolute.json"):
        altered = copy.deepcopy(manifest)
        altered["files"][0] = name
        path.write_text(json.dumps(altered))
        with pytest.raises(InvalidInput):
            read_draft(path)
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / files[0])
    altered = copy.deepcopy(manifest)
    altered["files"][0] = "link.json"
    path.write_text(json.dumps(altered))
    with pytest.raises(InvalidInput):
        read_draft(path)
    altered = copy.deepcopy(manifest)
    altered["files"] = [files[0]] * 33
    path.write_text(json.dumps(altered))
    with pytest.raises(InvalidInput):
        read_draft(path)
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(records, "MAX_TOTAL_BYTES", len(path.read_bytes()) + 1)
    with pytest.raises(InvalidInput):
        read_draft(path)


def cli(*args, text=None):
    return subprocess.run(
        [sys.executable, "-m", "shift_schedula", "adapter", *map(str, args)],
        input=text,
        capture_output=True,
        text=True,
    )


def test_cli_checkpoints_and_schema(tmp_path):
    for kind in ("draft", "manifest", "record"):
        assert json.loads(cli("schema", kind).stdout) == get_adapter_schema(kind)
    manifest = ROOT / "examples/adapter/assignment.manifest.json"
    assembled = cli("assemble", manifest, "--request-only")
    assert assembled.returncode == 0 and json.loads(assembled.stdout) == request("assignment")
    run = tmp_path / "run.json"
    result = cli("solve", manifest, "--output", run)
    assert result.returncode == 0 and result.stderr == ""
    record = json.loads(result.stdout)
    assert check_record(record) == record
    assert cli("solve", manifest, "--output", run).returncode == 2
    assert json.loads(cli("verify-record", run).stdout)["current_verification"]["status"] == "VALID"
    assert json.loads(cli("view", run).stdout)["current_status"] == "VALID"
    assert cli("assemble", "-", text=manifest.read_text()).returncode == 2
    draft = confirmed(request("assignment"))
    assert cli("assemble", "-", text=json.dumps(draft)).returncode == 0
    assert cli("confirm", "-", "basic", text=json.dumps(draft)).returncode == 0
    bad = json.loads(cli("assemble", "-", text="{").stdout)
    assert bad["status"] == "INVALID_INPUT"
    saved = run.read_bytes()
    assert cli("verify-record", run, "--output", run, "--overwrite").returncode == 2
    assert run.read_bytes() == saved
