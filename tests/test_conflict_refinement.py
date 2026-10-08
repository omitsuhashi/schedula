"""契約0.8の十分性・証拠・内包予算を公開入口と独立な小規模列挙で確認する。"""

import copy
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shift_schedula import (
    InvalidInput,
    cp_sat,
    diagnosis,
    get_schema,
    make_baseline,
    solve,
    validate,
    verify,
)
from shift_schedula.contract import SCHEMA_VERSIONS, schema_errors
from shift_schedula.engine import validate_response
from shift_schedula.model import normalize
from shift_schedula.verify import verify_plan
from tests.roster_support import rule
from tests.support import assert_response
from tests.test_continuity import example as continuous_example

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/conflict_refinement.json").read_text(encoding="utf-8"))


def active_groups(data):
    return {c["group_id"] for c in diagnosis.condition_groups(data)[0]}


def test_minimum_maximum_remove_irrelevant_and_preserve_allowed_change():
    data = example()
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    conflict = detail["conflict"]
    assert detail["status"] == "COMPLETE"
    assert [c["related_ids"][0] for c in conflict["conditions"]] == ["minimum", "maximum"]
    assert conflict["minimality"] == "inclusion_minimal" and conflict["rechecked"]
    assert conflict["minimality_scope"] == "condition_groups_relative_to_background"
    assert not conflict["background_only"]
    assert conflict["conditions"][0]["interval"] == data["constraints"][0]["interval"]
    assert all(c["completed_in_budget"] for c in conflict["checks"])
    child = detail["suggestions"][0]
    assert child["option_id"] == "raise_maximum"
    assert_response(child["response"], "OPTIMAL")
    assert child["response"]["objectives"][0]["value"] == 60
    assert data == saved
    validate_response(result, data)
    for c in conflict["conditions"] + conflict["background_conditions"]:
        value = data
        for part in c["json_pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert value is not None
        assert c["group_id"] == c["json_pointer"]
    # 返却した参照区間を編集しても入力と変更案を共有しない。
    conflict["conditions"][0]["interval"]["start"] = "changed"
    assert data == saved


def test_independent_conflicts_enumerated_and_confirmed_with_separate_model():
    data = example()
    data["diagnosis"]["allowed_changes"] = []
    data["employees"].append({**copy.deepcopy(data["employees"][0]), "id": "bob"})
    data["shift_candidates"].append(
        {**copy.deepcopy(data["shift_candidates"][0]), "id": "bob_morning", "employee_id": "bob"}
    )
    for c in copy.deepcopy(data["constraints"][:2]):
        c.update(id="bob_" + c["id"], employee_ids=["bob"])
        data["constraints"].append(c)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    selected = {c["group_id"] for c in conflict["conditions"]}
    assert selected == {"/constraints/3", "/constraints/4"}
    assert conflict["minimality"] == "inclusion_minimal"
    module, _ = cp_sat.load_backend()

    def independent(groups):
        # 手書きの別モデル。通常モデルの係数・prepareを参照しない。
        model = module.CpModel()
        variables = {e: model.new_bool_var(e) for e in ("alice", "bob")}
        for i, c in enumerate(data["constraints"]):
            if f"/constraints/{i}" not in groups:
                continue
            x = variables[c["employee_ids"][0]]
            if c["id"].endswith("minimum"):
                model.add(60 * x >= 60)
            elif c["id"].endswith("maximum"):
                model.add(60 * x <= 0)
        return module.CpSolver().solve(model)

    def enumerated(groups):
        for bits in itertools.product((0, 1), repeat=2):
            solution = {
                "assignments": [],
                "shifts": [
                    {
                        "candidate_id": c["id"],
                        "employee_id": c["employee_id"],
                        "work_day": "2026-10-07",
                        "segments": c["segments"],
                    }
                    for c, bit in zip(data["shift_candidates"], bits, strict=True)
                    if bit
                ],
            }
            if not verify_plan(normalize(data), solution, active_groups=groups)[0]:
                return True
        return False

    assert independent(selected) == module.INFEASIBLE and not enumerated(selected)
    for group in selected:
        assert independent(selected - {group}) == module.OPTIMAL
        assert enumerated(selected - {group})


def test_all_active_models_match_and_demand_removal_retains_domain():
    data = example()
    data["constraints"] = []
    data["diagnosis"]["allowed_changes"] = []
    data["employees"].append({**copy.deepcopy(data["employees"][0]), "id": "bob"})
    data["shift_candidates"].append(
        {**copy.deepcopy(data["shift_candidates"][0]), "id": "bob_morning", "employee_id": "bob"}
    )
    problem = normalize(data)
    module, _ = cp_sat.load_backend()
    all_groups = active_groups(data)
    normal = cp_sat.prepare(problem, module)
    diagnostic = cp_sat.prepare(problem, module, active_groups=all_groups)
    relaxed = cp_sat.prepare(problem, module, active_groups=set())
    assert set(normal[1]) == set(diagnostic[1]) == set(relaxed[1])
    # 二人×二枠の担当と二勤務を全列挙し、同じ実行可能集合を確認する。
    for bits in itertools.product((0, 1), repeat=len(normal[1]) + len(normal[2])):
        statuses = []
        for model, assignments, shifts, _ in (normal, diagnostic):
            fixed = model.clone()
            variables = [*assignments.values(), *shifts.values()]
            for variable, bit in zip(variables, bits, strict=True):
                fixed.add(fixed.get_bool_var_from_proto_index(variable.index) == bit)
            statuses.append(module.CpSolver().solve(fixed) == module.OPTIMAL)
        assert statuses[0] == statuses[1]
    solution = {
        "assignments": [
            {"employee_id": e, "role_id": "kitchen", "interval": data["demand"][0]["interval"]}
            for e in ("alice", "bob")
        ],
        "shifts": [
            {
                "candidate_id": c["id"],
                "employee_id": c["employee_id"],
                "work_day": "2026-10-07",
                "segments": c["segments"],
            }
            for c in data["shift_candidates"]
        ],
    }
    assert verify(data, solution)["status"] == "INVALID_PLAN"
    assert not verify_plan(problem, solution, active_groups=set())[0]
    # 未指定枠・需要0には元から変数がなく、除去しても配置を許さない。
    data["demand"][0]["required_people"] = 0
    assert verify_plan(normalize(data), solution, active_groups=set())[0]
    assert not cp_sat.prepare(normalize(data), module, active_groups=set())[1]


@pytest.mark.parametrize("unknown_phase", ["initial", "removal", "final"])
def test_unknown_never_supplies_minimality_evidence(monkeypatch, unknown_phase):
    original = cp_sat.check_feasibility
    calls = [0]

    def check(problem, groups, deadline, num_workers):
        calls[0] += 1
        inject = {"initial": 1, "removal": 3, "final": 6}[unknown_phase]
        if calls[0] == inject:
            return cp_sat.SatResult("UNKNOWN", None)
        return original(problem, groups, deadline, num_workers)

    monkeypatch.setattr(cp_sat, "check_feasibility", check)
    data = example()
    data["diagnosis"]["allowed_changes"] = []
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    if unknown_phase == "initial":
        assert detail["conflict"] is None and detail["status"] == "TIME_LIMIT"
    else:
        assert detail["status"] == "COMPLETE"
        assert detail["conflict"]["minimality"] == "not_proven"
        assert detail["conflict"]["infeasibility_proven"]
        assert detail["conflict"]["rechecked"] == (unknown_phase != "final")


def test_sub_budget_includes_preparation_and_allows_remaining_suggestion_time(monkeypatch):
    data = example()
    problem = normalize(data)
    clock = [0.0]
    calls = [0]

    def late(problem, groups, deadline, num_workers):
        calls[0] += 1
        assert deadline == 5
        if calls[0] == 1:
            return cp_sat.SatResult("INFEASIBLE", None)
        clock[0] = 6
        return cp_sat.SatResult("INFEASIBLE", None, preparation_elapsed_seconds=6)

    child_request = copy.deepcopy(data)
    child_request.pop("diagnosis")
    child_request["constraints"][1]["limit_minutes"] = 60
    child = solve(child_request)
    monkeypatch.setattr(diagnosis.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cp_sat, "check_feasibility", late)
    budgets = []

    def suggestion(request):
        budgets.append(request["solver"]["time_limit_seconds"])
        child["request_id"] = request["request_id"]
        return child

    detail = diagnosis.diagnose(data, "INFEASIBLE", suggestion, problem=problem)
    assert detail["status"] == "TIME_LIMIT" and detail["elapsed_seconds"] == 6
    assert detail["conflict"]["conditions"] == diagnosis.condition_groups(data)[0]
    assert not detail["conflict"]["rechecked"]
    assert detail["conflict"]["minimality"] == "not_proven"
    assert not detail["conflict"]["checks"][-1]["completed_in_budget"]
    assert budgets == [4] and len(detail["suggestions"]) == 1


@pytest.mark.parametrize("kind", ["model_mismatch", "invalid_witness", "exception"])
def test_diagnostic_errors_preserve_original_and_completed_proof(monkeypatch, kind):
    original = cp_sat.check_feasibility
    calls = [0]

    def broken(problem, groups, deadline, num_workers):
        calls[0] += 1
        if kind == "model_mismatch" and calls[0] == 1:
            return cp_sat.SatResult("OPTIMAL", {"shifts": [], "assignments": []})
        if calls[0] == 2:
            if kind == "exception":
                raise RuntimeError("injected")
            return cp_sat.SatResult(
                "FEASIBLE",
                {
                    "shifts": [],
                    "assignments": [
                        {
                            "employee_id": "unknown",
                            "role_id": "kitchen",
                            "interval": data["demand"][0]["interval"],
                        }
                    ],
                },
            )
        return original(problem, groups, deadline, num_workers)

    data = example()
    monkeypatch.setattr(cp_sat, "check_feasibility", broken)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    assert result["diagnosis_result"]["status"] == "ERROR"
    assert result["diagnosis_result"]["suggestions"] == []
    conflict = result["diagnosis_result"]["conflict"]
    assert (conflict is None) == (kind == "model_mismatch")
    if conflict:
        assert conflict["minimality"] == "not_proven" and conflict["infeasibility_proven"]


@pytest.mark.parametrize("fixed", ["fixed_parts", "preserve_assigned"])
def test_fixed_group_removed_without_modifying_baseline(fixed):
    data = example()
    data.pop("diagnosis")
    data["constraints"] = []
    result = solve(data)
    data["baseline"] = make_baseline(data, result["solution"], "original")
    if fixed == "fixed_parts":
        data[fixed] = [
            {
                "id": "fixed",
                "employee_id": "alice",
                "interval": data["demand"][0]["interval"],
                "components": ["work", "role"],
            }
        ]
    else:
        data["replan_mode"] = fixed
    data["constraints"] = [rule("max_scheduled_minutes", 0)]
    data["diagnosis"] = example()["diagnosis"]
    data["diagnosis"]["allowed_changes"] = []
    saved = copy.deepcopy(data)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert {c["group_id"] for c in conflict["conditions"]} == {
        "/constraints/0",
        "/fixed_parts/0" if fixed == "fixed_parts" else "/replan_mode",
    }
    assert conflict["minimality"] == "inclusion_minimal"
    assert any(c["json_pointer"] == "/baseline" for c in conflict["background_conditions"])
    assert data == saved


def test_background_only_keeps_committed_original_intervals():
    data = continuous_example()
    data["schema_version"] = "0.8"
    data["employees"][0]["availability"] = []
    data["shift_candidates"] = []
    data["constraints"] = []
    data["diagnosis"] = example()["diagnosis"]
    data["diagnosis"]["allowed_changes"] = []
    assert validate(data)["status"] == "VALID"
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    conflict = result["diagnosis_result"]["conflict"]
    assert conflict["conditions"] == [] and conflict["background_only"]
    assert conflict["minimality"] == "inclusion_minimal" and conflict["rechecked"]
    duty = data["continuity"]["employees"][0]["committed_shifts"][0]
    refs = {c["group_id"]: c for c in conflict["background_conditions"]}
    reference = refs["/continuity/employees/0/committed_shifts/0"]
    assert reference["interval"] == {
        "start": duty["segments"][0]["interval"]["start"],
        "end": duty["segments"][-1]["interval"]["end"],
    }
    assert "/shift_candidates" in refs


@pytest.mark.parametrize(
    "status,reason",
    [
        ("PARTIAL", "ORIGINAL_PARTIAL"),
        ("UNKNOWN", "ORIGINAL_UNKNOWN"),
        ("OPTIMAL", "ORIGINAL_FEASIBLE"),
    ],
)
def test_non_infeasible_results_do_not_refine(monkeypatch, status, reason):
    monkeypatch.setattr(
        cp_sat, "check_feasibility", lambda *_: pytest.fail("Unexpected refinement")
    )
    detail = diagnosis.diagnose(example(), status, lambda _: pytest.fail("Unexpected proposal"))
    assert detail["status"] == "NOT_APPLICABLE" and detail["reason"] == reason
    assert detail["conflict"] is None
    data = example()
    data["constraints"] = []
    data["diagnosis"]["allowed_changes"] = []
    data["demand"][0]["required_people"] = 2
    result = solve(data)
    assert_response(result, "PARTIAL")
    assert result["diagnosis_result"]["conflict"] is None


@pytest.mark.parametrize(
    "field",
    [
        "conditions",
        "background",
        "pointer",
        "interval",
        "minimality",
        "rechecked",
        "check_group",
        "witness",
        "late_proof",
    ],
)
def test_response_rejects_tampered_references_and_proof_records(field):
    data = example()
    result = solve(data)
    c = result["diagnosis_result"]["conflict"]
    if field == "conditions":
        c["conditions"].pop()
    elif field == "background":
        c["background_conditions"].pop()
    elif field == "pointer":
        c["conditions"][0]["json_pointer"] = "/constraints/999"
    elif field == "interval":
        c["conditions"][0]["interval"] = data["demand"][0]["interval"] | {
            "end": "2026-10-07T11:00:00+09:00"
        }
    elif field == "minimality":
        c["checks"] = c["checks"][:-2]
    elif field == "rechecked":
        c["rechecked"] = False
    elif field == "check_group":
        c["checks"][0]["active_groups"].append("/constraints/999")
    elif field == "witness":
        c["checks"][-1]["witness_verified"] = False
    else:
        c["checks"][0]["completed_in_budget"] = False
    with pytest.raises(InvalidInput):
        validate_response(result, data)


@pytest.mark.parametrize("version", [v for v in SCHEMA_VERSIONS if v not in {"0.8", "0.9", "0.10"}])
def test_new_request_and_response_fields_rejected_by_old_versions(version):
    data = example()
    data["schema_version"] = version
    assert_response(solve(data), "INVALID_INPUT")
    response = solve(example())
    response["schema_version"] = version
    assert schema_errors("response", response, version)


@pytest.mark.parametrize(
    "pointer", ["/employees/0/skills", "/shift_candidates/0", "/fixed_parts/0", "/replan_mode"]
)
def test_unpermitted_edits_still_rejected(pointer):
    data = example()
    data["diagnosis"]["allowed_changes"][0]["edits"][0]["json_pointer"] = pointer
    assert_response(solve(data), "INVALID_INPUT")


def test_budget_validation_default_groups_cli_and_new_schemas(tmp_path):
    data = example()
    data["diagnosis"]["conflict_refinement"]["time_limit_seconds"] = 11
    assert validate(data)["diagnostics"][0]["code"] == "INVALID_DIAGNOSIS_BUDGET"
    data = example()
    del data["diagnosis"]["conflict_refinement"]
    result = solve(data)
    c = result["diagnosis_result"]["conflict"]
    assert c["conditions"] == diagnosis.condition_groups(data)[0]
    assert c["minimality"] == "not_proven" and not c["checks"] and not c["rechecked"]
    for kind in ("request", "response", "solution", "verification"):
        process = subprocess.run(
            [sys.executable, "-m", "shift_schedula", "schema", kind, "--schema-version", "0.8"],
            capture_output=True,
            text=True,
        )
        assert process.returncode == 0
        assert json.loads(process.stdout) == get_schema(kind, "0.8")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "shift_schedula",
            "solve",
            str(ROOT / "examples/conflict_refinement.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 2 and not process.stderr
    assert_response(json.loads(process.stdout), "INFEASIBLE")


def test_unclassified_future_condition_is_unsupported():
    data = example()
    data["constraints"][0]["type"] = "future_rule"
    detail = diagnosis.diagnose(data, "INFEASIBLE", lambda _: pytest.fail("Unexpected proposal"))
    assert detail["status"] == "UNSUPPORTED" and detail["conflict"] is None


@pytest.mark.parametrize("stage", ["final_preparation", "witness_verification"])
def test_late_completion_keeps_last_reduced_proof(monkeypatch, stage):
    from importlib import import_module

    verifier = import_module("shift_schedula.verify")
    original_search, original_verify = cp_sat.check_feasibility, verifier.verify_plan
    calls, verifications, clock = [0], [0], [0.0]

    def check(problem, groups, deadline, num_workers):
        calls[0] += 1
        result = original_search(problem, groups, deadline, num_workers)
        if stage == "final_preparation" and calls[0] == 6:
            clock[0] = 6
        return result

    def verify_witness(*args, **kwargs):
        checked = original_verify(*args, **kwargs)
        if kwargs.get("active_groups") is not None:
            verifications[0] += 1
            if stage == "witness_verification" and verifications[0] == 3:
                clock[0] = 6
        return checked

    data = example()
    data["diagnosis"]["allowed_changes"] = []
    monkeypatch.setattr(diagnosis.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cp_sat, "check_feasibility", check)
    monkeypatch.setattr(verifier, "verify_plan", verify_witness)
    result = solve(data)
    assert_response(result, "INFEASIBLE")
    detail = result["diagnosis_result"]
    c = detail["conflict"]
    assert detail["status"] == "TIME_LIMIT"
    assert {g["group_id"] for g in c["conditions"]} == {"/constraints/0", "/constraints/1"}
    assert c["infeasibility_proven"] and c["minimality"] == "not_proven"
    assert c["rechecked"] == (stage == "witness_verification")


def test_witness_verifier_has_no_backend_and_public_verify_keeps_hard_conditions(monkeypatch):
    data = example()
    solution = {"shifts": [], "assignments": []}
    problem = normalize(data)
    monkeypatch.setattr(cp_sat, "load_backend", lambda: pytest.fail("Unexpected solver"))
    assert not verify_plan(problem, solution, active_groups={"/constraints/1"})[0]
    assert verify(data, solution)["status"] == "INVALID_PLAN"
    solution["assignments"] = [
        {"employee_id": "alice", "role_id": "kitchen", "interval": data["demand"][0]["interval"]}
    ]
    assert verify_plan(problem, solution, active_groups=set())[0]


def test_refinement_workers_and_reconfirmed_full_set_use_same_request(monkeypatch):
    module, _ = cp_sat.load_backend()
    original_search = module.CpSolver.solve
    observed = []

    def search(self, model):
        observed.append(self.parameters.num_search_workers)
        return original_search(self, model)

    monkeypatch.setattr(module.CpSolver, "solve", search)
    result = solve(example(), num_workers=1)
    assert_response(result, "INFEASIBLE")
    assert len(observed) >= 7 and set(observed) == {1}
