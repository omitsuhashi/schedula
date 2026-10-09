"""Adapter移行の所有元、確認、過去証拠と安全な別出力を検証する。"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.migrate_adapter import main, migrate_draft, migrate_record
from shift_schedula import (
    InvalidInput,
    assemble,
    check_record,
    confirm_source,
    confirmation_state,
    create_record,
    import_request,
    make_baseline,
    read_draft,
    record_view,
    records,
    reverify_record,
    run_draft,
    save_json,
    solve,
    validate,
    verify,
)
from shift_schedula.adapter import EMPLOYEE_FIELDS, SECTIONS, get_schema
from tests.test_adapter import confirmed, source
from tests.test_adapter import request as current_request
from tests.test_contract_migration import CASES, read_case


def request(name):
    return read_case(name, "legacy") if name in CASES else current_request(name)


ROOT = Path(__file__).resolve().parents[1]


def reconfirm(draft):
    for item in confirmation_state(draft):
        if item["state"] != "confirmed":
            draft = confirm_source(draft, item["source_id"])
    return draft


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("split", [True, False])
def test_all_old_versions_keep_owned_fields_and_reconfirm_before_execution(name, split):
    previous = read_case(name, "legacy")
    draft = confirmed(previous) if split else import_request(previous)
    saved = copy.deepcopy(draft)
    result = migrate_draft(draft)
    target = result["draft"]
    assert result["original_draft"] == draft == saved
    assert target["schema_version"] == "0.15" and target["adapter_version"] == "1.0"
    assert validate(result["request"])["status"] == "VALID"
    assert [s["id"] for s in target["sources"]] == [s["id"] for s in draft["sources"]]
    assert assemble(reconfirm(target))["request"] == result["request"]
    response = solve(previous)
    if response["solution"] is not None:
        # 保存解の移行・再検証はrecord経路で行い、元の証明を転記しない。
        migrated = migrate_record(create_record(previous, response))
        assert migrated["current_verification"]["verification"]["valid"]
        assert not migrated["current_verification"]["shortage_summary"]["proven_minimal"]


def test_confirmation_transfer_is_selective_and_keeps_unknown_empty_and_unresolved():
    draft = confirmed(request("assignment"))
    source(draft, "basic")["references"] = ["利用者が確認した技能一覧"]
    draft = confirm_source(draft, "basic")
    source(draft, "common")["confirmation"] = None
    source(draft, "execution")["revision"] = "edited-but-unconfirmed"
    draft["unresolved"] = [
        {"source_id": "period", "json_pointer": "/demand", "message": "担当者確認待ち"}
    ]
    draft["assumptions"] = ["日付は原入力を使う"]
    result = migrate_draft(draft)
    target = result["draft"]
    assert result["transferred_confirmations"] == ["basic"]
    states = {s["source_id"]: s["state"] for s in confirmation_state(target)}
    assert states == {
        "basic": "confirmed",
        "common": "unconfirmed",
        "period": "stale",
        "execution": "stale",
    }
    assert target["unresolved"] == draft["unresolved"]
    assert target["assumptions"] == draft["assumptions"]
    assert source(target, "common")["data"] == {"constraints": []}
    assert source(target, "basic")["references"] == source(draft, "basic")["references"]
    assert source(target, "period")["revision"] != source(draft, "period")["revision"]
    assert assemble(reconfirm(target))["request"] is None
    assert target["unresolved"]


@pytest.mark.parametrize(
    "name", ["continuity_duty_balance", "combined_month", "shift_count_balance"]
)
def test_current_015_has_no_blanket_confirmation_change_or_solver(monkeypatch, name):
    previous = current_request(name)
    draft = confirmed(previous)
    source(draft, "period")["revision"] = "unconfirmed-edit"
    before = copy.deepcopy(draft)

    def unexpected(*args, **kwargs):
        raise AssertionError("移行は求解しない")

    monkeypatch.setattr("shift_schedula.cp_sat.load_backend", unexpected)
    monkeypatch.setattr("shift_schedula.flow.run", unexpected)
    result = migrate_draft(draft)
    assert result["draft"] == draft == before
    assert result["confirmations_after"] == result["confirmations_before"]
    assert result["request"] == previous


def test_ownership_table_covers_all_top_level_and_employee_fields():
    schema = get_schema("request", "0.15")
    assert set(schema["properties"]) - {"schema_version"} <= set().union(*SECTIONS.values())
    employee = schema["properties"]["employees"]["items"]
    assert set(employee["properties"]) <= set().union(*EMPLOYEE_FIELDS.values())


def test_stale_confirmation_cannot_be_resurrected_by_a_matching_target_digest():
    draft = confirmed(request("continuity_week"))
    migrated = migrate_draft(draft)["draft"]
    source(draft, "common")["confirmation"] = source(migrated, "common")["confirmation"]
    assert (
        next(s for s in confirmation_state(draft) if s["source_id"] == "common")["state"] == "stale"
    )
    result = migrate_draft(draft)
    assert source(result["draft"], "common")["confirmation"] is None
    assert source(draft, "common")["confirmation"] is not None


def test_multiple_source_owners_employee_order_overrides_and_dependencies():
    draft = confirmed(request("roster"))
    period = source(draft, "period")
    other = copy.deepcopy(period)
    other["id"] = "candidates"
    other["data"] = {"shift_candidates": period["data"].pop("shift_candidates")}
    common = source(draft, "common")
    old_rule = copy.deepcopy(common["data"]["constraints"][0])
    period["data"]["constraints"] = [{**old_rule, "limit_minutes": old_rule["limit_minutes"] + 30}]
    draft["overrides"] = [
        {
            "source_id": "period",
            "target_source_id": "common",
            "constraint_id": old_rule["id"],
            "before": old_rule,
            "reason": "今回の勤務量上限を明示変更する",
        }
    ]
    # 勤務候補とテンプレートを別所有にし、historyの順をbasicから変える。
    source(draft, "history")["data"]["employees"].reverse()
    draft["sources"].append(other)
    draft = reconfirm(draft)
    result = migrate_draft(draft)
    target = result["draft"]
    expected = result["request"]
    assert "shift_templates" not in source(target, "period")["data"]
    assert expected["shift_candidates"] == next(
        s["data"]["shift_candidates"] for s in target["sources"] if s["id"] == "candidates"
    )
    assert assemble(reconfirm(target))["request"] == expected
    assert target["overrides"] == draft["overrides"]
    assert target["order"] == draft["order"]
    assert {s["source_id"] for s in result["migration_provenance"]["/shift_candidates"]} == {
        "candidates",
        "period",
    }
    assert source(target, "basic")["data"] == source(draft, "basic")["data"]
    assert (
        source(target, "history")["data"]["employees"][0]["id"]
        == source(draft, "history")["data"]["employees"][0]["id"]
    )


@pytest.mark.parametrize("name", ["assignment", "partial_roster", "continuity_replan"])
def test_record_keeps_execution_identity_proofs_and_replans_under_a_new_run_id(name, tmp_path):
    draft = confirmed(read_case(name, "legacy"))
    record = run_draft(draft, num_workers=1)
    original = copy.deepcopy(record)
    result = migrate_record(record)
    assert record == original == result["original_record"]
    assert result["source_run_id"] == record["run_id"] != result["migration_id"]
    assert "run_id" not in result  # 移行だけで新しい求解を実行したとは主張しない。
    assert result["execution"] == {"num_workers": 1}
    assert result["original_response"] == record["response"]
    assert result["original_record"]["engine"] == record["engine"]
    assert result["current_verification"]["verification"]["valid"]
    assert all(not o["proven_optimal"] for o in result["current_verification"]["objectives"])
    assert not result["current_verification"]["shortage_summary"]["proven_minimal"]
    if result["request"]["problem_type"] == "roster":
        baseline = make_baseline(result["request"], result["solution"], "migrated-plan")
        assert baseline["source_request"]["schema_version"] == "0.15"
        replanning = {**result["request"], "baseline": baseline}
        replanned = solve(replanning)
        assert verify(replanning, replanned["solution"])["verification"]["valid"]
    fresh = run_draft(reconfirm(result["draft"]), **result["execution"])
    assert check_record(fresh) == fresh
    assert fresh["run_id"] != record["run_id"]
    assert fresh["request"]["request_id"] == record["request"]["request_id"]
    output = tmp_path / "new-run.json"
    save_json(output, fresh)
    loaded, _ = records.read_json_file(output)
    assert reverify_record(loaded)["current_verification"]["verification"]["valid"]
    assert record_view(loaded)["current_status"] in {"VALID", "PARTIAL"}


@pytest.mark.parametrize("name", ["assignment", "infeasible"])
def test_record_without_draft_keeps_no_solution_and_original_evidence(name):
    previous = request(name)
    record = create_record(previous, solve(previous))
    result = migrate_record(record)
    assert result["original_record"] == record
    assert result["draft"] is None
    assert (result["solution"] is None) == (record["response"]["solution"] is None)
    if result["solution"] is None:
        assert result["current_verification"] is None


def test_cli_manifest_tracks_all_inputs_preserves_originals_and_refuses_overwrite(tmp_path, capsys):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in [
        "assignment.manifest.json",
        "basic.json",
        "common.json",
        "period.json",
        "execution.json",
    ]:
        (source_dir / name).write_bytes(
            (ROOT / "tests/fixtures/contract-migration/adapter" / name).read_bytes()
        )
    originals = {p: p.read_bytes() for p in source_dir.iterdir()}
    manifest = source_dir / "assignment.manifest.json"
    output = tmp_path / "migration.json"
    assert main(["draft", str(manifest), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "MIGRATED"
    result, _ = records.read_json_file(output)
    assert set(result["inputs"]) == {str(p) for p in originals}
    assert result["transferred_confirmations"] == ["basic", "common", "execution"]
    moved = tmp_path / "draft.json"
    save_json(moved, result["draft"])
    target = read_draft(moved)
    target = reconfirm(target)
    assert assemble(target)["request"] == result["request"]
    assert result["provenance"]["/demand"][0]["file"] == "period.json"
    initial = output.read_bytes()
    for protected in [*originals, output]:
        assert main(["draft", str(manifest), "--output", str(protected)]) == 2
        assert output.read_bytes() == initial
        assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert not list(tmp_path.rglob(".schedula-*"))


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"null"])
def test_cli_rejects_invalid_json_without_output(tmp_path, raw):
    source_file, output = tmp_path / "input.json", tmp_path / "output.json"
    source_file.write_bytes(raw)
    assert main(["draft", str(source_file), "--output", str(output)]) == 2
    assert source_file.read_bytes() == raw
    assert not output.exists()


@pytest.mark.parametrize(
    "path",
    [
        "../input.json",
        "/input.json",
        "https://example.com/input.json",
        "C:\\input.json",
        "self.json",
    ],
)
def test_cli_manifest_rejects_unsafe_and_cyclic_paths(tmp_path, path):
    manifest = json.loads(
        (ROOT / "tests/fixtures/contract-migration/adapter/assignment.manifest.json").read_text()
    )
    manifest["files"] = [path]
    source_file, output = tmp_path / "self.json", tmp_path / "output.json"
    source_file.write_text(json.dumps(manifest))
    raw = source_file.read_bytes()
    assert main(["draft", str(source_file), "--output", str(output)]) == 2
    assert source_file.read_bytes() == raw
    assert not output.exists()


@pytest.mark.parametrize("fail_at", ["file_size", "total_size", "symlink", "fsync", "interrupted"])
def test_cli_io_failure_protects_original_and_cleans_partial_output(tmp_path, monkeypatch, fail_at):
    source_file, output = tmp_path / "input.json", tmp_path / "output.json"
    source_file.write_bytes(
        (ROOT / "tests/fixtures/contract-migration/adapter/assignment.draft.json").read_bytes()
    )
    raw = source_file.read_bytes()
    if fail_at == "file_size":
        source_file.write_bytes(raw + b" " * records.MAX_FILE_BYTES)
        raw = source_file.read_bytes()
    elif fail_at == "total_size":
        source_file.write_bytes(
            (
                ROOT / "tests/fixtures/contract-migration/adapter/assignment.manifest.json"
            ).read_bytes()
        )
        raw = source_file.read_bytes()
        monkeypatch.setattr(records, "MAX_TOTAL_BYTES", len(raw))
        for name in ("basic", "common", "period", "execution"):
            (tmp_path / f"{name}.json").write_bytes(
                (ROOT / f"tests/fixtures/contract-migration/adapter/{name}.json").read_bytes()
            )
    elif fail_at == "symlink":
        monkeypatch.setattr(records.Path, "is_symlink", lambda self: self == source_file)
    else:
        error = KeyboardInterrupt if fail_at == "interrupted" else OSError
        monkeypatch.setattr(records.os, "fsync", lambda fd: (_ for _ in ()).throw(error()))
    if fail_at == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            main(["draft", str(source_file), "--output", str(output)])
    else:
        assert main(["draft", str(source_file), "--output", str(output)]) == 2
    assert source_file.read_bytes() == raw
    assert not output.exists()
    assert not list(tmp_path.glob(".schedula-*"))


def test_cli_history_confirmation_and_stdin_are_explicit(tmp_path, capsys):
    previous = request("roster")
    previous["employees"][0]["history"] = {
        "last_shift_end": "2026-10-04T18:00:00+09:00",
        "consecutive_work_days_before_window": 1,
    }
    input_file, output, confirmations = (
        tmp_path / "input.json",
        tmp_path / "output.json",
        tmp_path / "confirm.json",
    )
    save_json(input_file, confirmed(previous))
    args = ["draft", str(input_file), "--output", str(output)]
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NEEDS_CONFIRMATION"
    assert not output.exists()
    save_json(confirmations, {"/employees/0/history/last_work_day": "2026-10-04"})
    assert main([*args, "--history-confirmations", str(confirmations)]) == 0
    assert (
        records.read_json_file(output)[0]["request"]["employees"][0]["history"]["last_work_day"]
        == "2026-10-04"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/migrate_adapter.py"),
            "draft",
            "-",
            "--history-confirmations",
            str(confirmations),
            "--output",
            str(tmp_path / "stdin.json"),
        ],
        input=json.dumps(confirmed(previous)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["status"] == "MIGRATED"


def test_cli_record_fresh_process_keeps_hashes_and_rejects_tampering(tmp_path):
    previous = request("assignment")
    record = create_record(previous, solve(previous))
    input_file, output = tmp_path / "record.json", tmp_path / "migration.json"
    save_json(input_file, record)
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/migrate_adapter.py"),
            "record",
            str(input_file),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert records.read_json_file(output)[0]["original_record"] == record
    record["execution"]["num_workers"] = 3
    with pytest.raises(InvalidInput):
        migrate_record(record)


def test_cli_record_without_source_metadata_requires_confirmation(tmp_path, capsys):
    previous = request("assignment")
    draft = confirmed(previous)
    record = create_record(previous, solve(previous), sources=draft["sources"])
    input_file, output = tmp_path / "record.json", tmp_path / "migration.json"
    save_json(input_file, record)
    raw = input_file.read_bytes()
    assert main(["record", str(input_file), "--output", str(output)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NEEDS_CONFIRMATION"
    assert result["diagnostics"][0]["code"] == "UNTRACKED_SOURCES"
    assert input_file.read_bytes() == raw
    assert not output.exists()
