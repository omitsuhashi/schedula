"""明示移行の意味保持、再検証、原本と成功済み出力の保護。"""

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.migrate_contract import main, migrate, migrate_request
from shift_schedula import InvalidInput, load_json, make_baseline, solve, validate, verify
from shift_schedula.adapter import content_hash
from shift_schedula.model import normalize
from tests.roster_support import demand, interval, stamp
from tests.roster_support import legacy_request as request
from tests.roster_support import legacy_template as template
from tests.test_extended_roster import legacy_extended_request as extended_request

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/contract-migration"
CASES = tuple(row["name"] for row in load_json((FIXTURES / "cases.json").read_text())["cases"])


def read_case(name, kind):
    return load_json((FIXTURES / f"{name}.{kind}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CASES)
def test_every_legacy_version_migrates_to_the_fixed_regression_case(name):
    source = read_case(name, "legacy")
    saved = copy.deepcopy(source)
    target = migrate_request(source)
    expected = read_case(name, "015")
    if name == "roster":
        # 移行元の明示順は保ち、比較台帳とは候補IDで照合する。
        target["shift_candidates"].sort(key=lambda c: c["id"])
        expected["shift_candidates"].sort(key=lambda c: c["id"])
    assert target == expected
    assert source == saved


@pytest.mark.parametrize("name", CASES)
def test_saved_plans_are_reverified_and_original_proofs_remain_historical(name):
    source = read_case(name, "legacy")
    response = solve(source)
    saved = copy.deepcopy((source, response))
    result = migrate(source, response=response)
    assert result["original_response"] == response
    assert result["source_request_hash"] == content_hash(source)
    assert result["target_request_hash"] == content_hash(result["request"])
    current = result["current_verification"]
    if response["solution"] is None:
        assert current is result["solution"] is None
    else:
        assert current["status"] == ("PARTIAL" if response["status"] == "PARTIAL" else "VALID")
        assert current["verification"]["valid"]
        assert all(not o["proven_optimal"] for o in current["objectives"])
        assert not current["shortage_summary"]["proven_minimal"]
        assert all(not g["proven_minimal"] for g in current["priority_summary"]["groups"])
    assert (source, response) == saved


def test_current_015_and_migration_do_not_solve(monkeypatch):
    source = read_case("continuity_replan", "015")
    saved = copy.deepcopy(source)

    def unexpected(*args, **kwargs):
        raise AssertionError("移行処理は求解しない")

    from shift_schedula import cp_sat, flow

    monkeypatch.setattr(cp_sat, "load_backend", unexpected)
    monkeypatch.setattr(flow, "run", unexpected)
    assert migrate_request(source) == saved == source


@pytest.mark.parametrize("start,end,expected", [(600, 690, 90), (600, 660, 60)])
def test_01_explicit_segments_keep_raw_offsets_and_candidate_ids(start, end, expected):
    source = request()
    source["shift_candidates"][0]["interval"] = interval(start=start, end=end)
    source["demand"] = [demand(end=end)]
    response = solve(source)
    result = migrate(source, solution=response["solution"])
    old, new = source["shift_candidates"][0], result["request"]["shift_candidates"][0]
    assert new["id"] == old["id"]
    assert new["segments"] == [{"interval": old["interval"], "breaks": old["breaks"]}]
    assert result["solution"]["shifts"][0]["candidate_id"] == old["id"]
    assert result["current_verification"]["objectives"][0]["value"] == expected


def test_01_template_cartesian_product_keeps_ids_breaks_and_filtering():
    source = request()
    source["shift_candidates"] = []
    source["shift_templates"] = [
        template(starts=("10:00", "12:00"), durations=(60, 90), breaks=((30, 30),))
    ]
    # 60分の候補は休憩が終業に接するため、旧版でも不正。
    with pytest.raises(InvalidInput):
        migrate_request(source)
    source["shift_templates"][0]["duration_minutes_options"] = [90, 120]
    source["employees"][0]["availability"] = [interval(end=720)]
    before = normalize(source)
    target = migrate_request(source)
    after = normalize(target)
    assert "shift_templates" not in target
    assert [(c.id, c.day, c.start, c.end, c.breaks, c.work_slots) for c in before.candidates] == [
        (c.id, c.day, c.start, c.end, c.breaks, c.work_slots) for c in after.candidates
    ]
    assert len(after.candidates) == 2


@pytest.mark.parametrize("last", [stamp(-1, 690), stamp(0)])
def test_nonempty_history_requires_matching_explicit_confirmation(last):
    source = request()
    source["employees"][0]["history"] = {
        "last_shift_end": last,
        "consecutive_work_days_before_window": 1,
    }
    path = "/employees/0/history/last_work_day"
    original = copy.deepcopy(source)
    with pytest.raises(InvalidInput) as error:
        migrate_request(source)
    assert error.value.diagnostics[0]["code"] == "HISTORY_CONFIRMATION_REQUIRED"
    assert error.value.diagnostics[0]["json_pointer"] == path
    for value in (None, 0, "2026-10-03"):
        with pytest.raises(InvalidInput) as error:
            migrate_request(source, history_confirmations={path: value})
        assert error.value.diagnostics[0]["code"] == "HISTORY_SEMANTICS_CHANGED"
    target = migrate_request(source, history_confirmations={path: "2026-10-04"})
    assert target["employees"][0]["history"]["last_work_day"] == "2026-10-04"
    assert source == original


def test_empty_unknown_and_unused_history_are_distinct():
    source = request()
    assert migrate_request(source)["employees"][0]["history"]["last_work_day"] is None
    with pytest.raises(InvalidInput) as error:
        migrate_request(source, history_confirmations={"/employees/0/history/last_work_day": None})
    assert error.value.diagnostics[0]["code"] == "UNUSED_CONFIRMATION"
    del source["employees"][0]["history"]
    with pytest.raises(InvalidInput) as error:
        migrate_request(source)
    assert error.value.diagnostics[0]["code"] == "MISSING_HISTORY"


@pytest.mark.parametrize(
    "name", ["replan", "continuity_replan", "partial_replan_preserve_assigned"]
)
def test_baseline_fixed_states_and_original_windows_survive_replanning(name):
    source = read_case(name, "legacy")
    target = migrate_request(source)
    old, new = source["baseline"], target["baseline"]
    assert old["source_request"]["planning_window"] == new["source_request"]["planning_window"]
    for key in ("plan_id", "source_fixed_states", "snapshot_origin"):
        assert old.get(key) == new.get(key)
    assert source.get("fixed_parts") == target.get("fixed_parts")
    assert source.get("replan_mode") == target.get("replan_mode")
    result = solve(target)
    assert result["solution"] is not None
    baseline = make_baseline(target, result["solution"], "next")
    assert verify(baseline["source_request"], baseline["source_solution"])["verification"]["valid"]


def test_legacy_01_baseline_requires_confirmation_at_its_original_pointer():
    source = extended_request()
    old = request()
    old["demand"] = [demand()]
    old["employees"][0]["history"] = {
        "last_shift_end": stamp(-1, 690),
        "consecutive_work_days_before_window": 1,
    }
    source["baseline"] = {
        "plan_id": "old",
        "source_request": old,
        "source_solution": solve(old)["solution"],
    }
    source["fixed_parts"] = []
    path = "/baseline/source_request/employees/0/history/last_work_day"
    with pytest.raises(InvalidInput) as error:
        migrate_request(source)
    assert error.value.diagnostics[0]["json_pointer"] == path
    target = migrate_request(source, history_confirmations={path: "2026-10-04"})
    assert target["baseline"]["source_request"]["schema_version"] == "0.15"
    assert (
        target["baseline"]["source_solution"]["shifts"][0]["candidate_id"]
        == old["shift_candidates"][0]["id"]
    )


def test_complete_diagnosis_couples_only_permitted_edits_and_reverifies_suggestions():
    source = load_json((FIXTURES / "diagnosis.legacy.json").read_text())
    response = solve(source)
    assert response["status"] == "INFEASIBLE"
    result = migrate(source, response=response)
    for old, new in zip(
        source["diagnosis"]["allowed_changes"],
        result["request"]["diagnosis"]["allowed_changes"],
        strict=True,
    ):
        assert new["id"] == old["id"]
        assert new["edits"] == old["edits"] + [
            {"json_pointer": "/demand/0/minimum_people", "value": old["edits"][0]["value"]}
        ]
    assert result["original_response"] == response
    assert [s["option_id"] for s in result["suggestions"]] == ["one_person"]
    new_result = solve(result["request"])
    assert new_result["status"] == "INFEASIBLE"
    assert [s["option_id"] for s in new_result["diagnosis_result"]["suggestions"]] == ["one_person"]
    suggestion = result["suggestions"][0]
    assert suggestion["request"]["demand"][0]["minimum_people"] == 1
    assert suggestion["current_verification"]["status"] == "VALID"
    assert not suggestion["current_verification"]["shortage_summary"]["proven_minimal"]


def test_maximum_ten_legacy_edits_fit_twenty_target_edits_and_overflow_is_rejected():
    source = load_json((FIXTURES / "diagnosis.legacy.json").read_text())
    source["demand"] = [
        {
            **source["demand"][0],
            "id": f"d{i}",
            "interval": interval(start=600 + i * 5, end=605 + i * 5),
        }
        for i in range(10)
    ]
    source["planning_window"]["slot_minutes"] = 5
    source["diagnosis"]["allowed_changes"] = [
        {
            "id": "all",
            "edits": [
                {"json_pointer": f"/demand/{i}/required_people", "value": 1} for i in range(10)
            ],
        }
    ]
    target = migrate_request(source)
    edits = target["diagnosis"]["allowed_changes"][0]["edits"]
    assert len(edits) == 20
    assert validate(target)["status"] == "VALID"
    edits.append({"json_pointer": "/constraints/0/limit_minutes", "value": 1})
    assert validate(target)["status"] == "INVALID_INPUT"
    source["diagnosis"]["allowed_changes"][0]["edits"].append(
        {"json_pointer": "/demand/0/required_people", "value": 1}
    )
    assert validate(source)["status"] == "INVALID_INPUT"


def test_invalid_plan_and_tampered_response_are_rejected(legacy_assignment_request):
    source = legacy_assignment_request
    response = solve(source)
    corrupt = copy.deepcopy(response["solution"])
    corrupt["assignments"].pop()
    with pytest.raises(InvalidInput):
        migrate(source, solution=corrupt)
    response["objectives"][0]["value"] += 1
    with pytest.raises(InvalidInput):
        migrate(source, response=response)


@pytest.mark.parametrize("mutation", ["missing", "unknown", "type", "cycle", "nonfinite"])
def test_invalid_input_is_rejected_without_changing_original(legacy_assignment_request, mutation):
    source = legacy_assignment_request
    if mutation == "missing":
        del source["schema_version"]
    elif mutation == "unknown":
        source["schema_version"] = "9.0"
    elif mutation == "type":
        source["schema_version"] = 15
    elif mutation == "cycle":
        source["cycle"] = source
    else:
        source["solver"]["time_limit_seconds"] = float("inf")
    with pytest.raises(InvalidInput):
        migrate_request(source)


def test_cli_separate_output_reread_repeated_run_and_original_protection(tmp_path, capsys):
    source = tmp_path / "request.json"
    raw = (FIXTURES / "assignment.legacy.json").read_bytes()
    source.write_bytes(raw)
    target = tmp_path / "migration.json"
    args = [str(source), "--output", str(target)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "MIGRATED"
    first = target.read_bytes()
    result = load_json(first.decode())
    assert result["inputs"]["request"]["content_hash"] == content_hash(load_json(raw.decode()))
    assert validate(result["request"])["status"] == "VALID"
    for output in (target, source):
        assert main([str(source), "--output", str(output)]) == 2
        assert source.read_bytes() == raw
        assert target.read_bytes() == first
    assert not list(tmp_path.glob(".schedula-*"))


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_cli_strict_json_failure_leaves_no_output(tmp_path, raw, capsys):
    source, target = tmp_path / "input.json", tmp_path / "output.json"
    source.write_bytes(raw)
    assert main([str(source), "--output", str(target)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID_INPUT"
    assert source.read_bytes() == raw
    assert not target.exists()


@pytest.mark.parametrize("option", ["--solution", "--response", "--history-confirmations"])
def test_cli_multiple_stdin_inputs_return_json_without_creating_output(
    tmp_path, option, monkeypatch
):
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    target = tmp_path / "output.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/migrate_contract.py"),
            "-",
            option,
            "-",
            "--output",
            str(target),
        ],
        input="not JSON",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stderr == ""
    status = json.loads(result.stdout)
    assert status["status"] == "INVALID_INPUT"
    assert status["diagnostics"][0]["code"] == "INVALID_MIGRATION_INPUT"
    assert status["diagnostics"][0]["message"] == "標準入力は一つの入力だけに指定します。"
    assert not target.exists()


@pytest.mark.parametrize("option", ["--solution", "--response", "--history-confirmations"])
@pytest.mark.parametrize("value", [None, [], False])
def test_cli_explicit_invalid_optional_input_is_not_treated_as_absent(tmp_path, option, value):
    source, optional, target = (
        tmp_path / "request.json",
        tmp_path / "value.json",
        tmp_path / "output.json",
    )
    source.write_bytes((FIXTURES / "assignment.legacy.json").read_bytes())
    optional.write_text(json.dumps(value))
    assert main([str(source), option, str(optional), "--output", str(target)]) == 2
    assert not target.exists()


def test_cli_interrupted_save_leaves_no_partial_output_and_can_retry(tmp_path, monkeypatch):
    from shift_schedula import records

    source, target = tmp_path / "input.json", tmp_path / "output.json"
    raw = (FIXTURES / "assignment.legacy.json").read_bytes()
    source.write_bytes(raw)
    with monkeypatch.context() as context:
        context.setattr(records.os, "fsync", lambda fd: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            main([str(source), "--output", str(target)])
    assert source.read_bytes() == raw
    assert not target.exists()
    assert not list(tmp_path.glob(".schedula-*"))
    assert main([str(source), "--output", str(target)]) == 0


def test_script_runs_in_a_fresh_process(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/migrate_contract.py"),
            str(FIXTURES / "roster.legacy.json"),
            "--output",
            str(tmp_path / "migration.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "MIGRATED"


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00"),
        ("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00"),
    ],
)
def test_dst_offsets_keep_raw_intervals_elapsed_time_and_work_day(start, end):
    source = request()
    day = start[:10]
    spring = "03-08" in day
    source["planning_window"].update(
        start=day + "T00:00:00" + ("-05:00" if spring else "-04:00"),
        end=(datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
        + "T00:00:00"
        + ("-04:00" if spring else "-05:00"),
        timezone="America/New_York",
    )
    raw = {"start": start, "end": end}
    source["employees"][0]["availability"] = [raw]
    source["shift_candidates"][0]["interval"] = raw
    source["demand"] = [{**demand(), "interval": raw}]
    result = migrate(source, response=solve(source))
    assert result["solution"]["shifts"][0]["segments"][0]["interval"] == raw
    assert result["solution"]["shifts"][0]["work_day"] == day
    assert result["current_verification"]["objectives"][0]["value"] == 60


@pytest.mark.parametrize(
    "day,clock,code",
    [
        ("2026-03-08", "02:30", "NONEXISTENT_LOCAL_TIME"),
        ("2026-11-01", "01:30", "AMBIGUOUS_LOCAL_TIME"),
    ],
)
def test_dst_ambiguous_and_nonexistent_templates_stay_invalid(day, clock, code):
    source = request()
    spring = "03-08" in day
    start = day + "T00:00:00" + ("-05:00" if spring else "-04:00")
    end = (
        (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
        + "T00:00:00"
        + ("-04:00" if spring else "-05:00")
    )
    source["planning_window"].update(start=start, end=end, timezone="America/New_York")
    source["employees"][0]["availability"] = [{"start": start, "end": end}]
    source["shift_candidates"] = []
    source["shift_templates"] = [template(dates=(day,), starts=(clock,), durations=(60,))]
    with pytest.raises(InvalidInput) as error:
        migrate_request(source)
    assert error.value.diagnostics[0]["code"] == code


def test_cli_needs_confirmation_leaves_no_output(tmp_path, capsys):
    source = request()
    source["employees"][0]["history"] = {
        "last_shift_end": stamp(-1, 690),
        "consecutive_work_days_before_window": 1,
    }
    path, output = tmp_path / "input.json", tmp_path / "output.json"
    raw = json.dumps(source).encode()
    path.write_bytes(raw)
    assert main([str(path), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NEEDS_CONFIRMATION"
    assert path.read_bytes() == raw
    assert not output.exists()


@pytest.mark.parametrize("fail_at", ["read", "save", "size"])
def test_cli_io_failure_protects_original_and_existing_output(tmp_path, monkeypatch, fail_at):
    from shift_schedula import records

    path, output = tmp_path / "input.json", tmp_path / "output.json"
    raw = (FIXTURES / "assignment.legacy.json").read_bytes()
    if fail_at == "size":
        raw += b" " * records.MAX_FILE_BYTES
    path.write_bytes(raw)
    args = [str(path), "--output", str(output)]
    if fail_at == "read":
        # Windows CIでも管理権限を要求せずにリンク拒否を検証する。
        monkeypatch.setattr(records.Path, "is_symlink", lambda self: self == path)
    elif fail_at == "save":
        monkeypatch.setattr(records.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError()))
    assert main(args) == 2
    assert path.read_bytes() == raw
    assert not output.exists()
    assert not list(tmp_path.glob(".schedula-*"))
