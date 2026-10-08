"""元条件の不可能性と、入力者が許可した変更後の解を分けて返す。"""

import logging
import re
import time
from copy import deepcopy

from .contract import diagnostic, parse_datetime, reject

logger = logging.getLogger(__name__)


def validate_options(request):
    from .model import unique

    options = request.get("diagnosis", {}).get("allowed_changes", [])
    config = request.get("diagnosis", {})
    refinement = config.get("conflict_refinement")
    if refinement and refinement["time_limit_seconds"] > config["time_limit_seconds"]:
        reject(
            "INVALID_DIAGNOSIS_BUDGET",
            "縮小予算は診断全体の予算以下にします。",
            "/diagnosis/conflict_refinement/time_limit_seconds",
        )
    unique(options, "id", "/diagnosis/allowed_changes")
    for index, option in enumerate(options):
        seen = set()
        for j, edit in enumerate(option["edits"]):
            path = f"/diagnosis/allowed_changes/{index}/edits/{j}"
            target = edit["json_pointer"]
            match = re.fullmatch(
                r"/(demand|constraints)/(0|[1-9][0-9]*)/(required_people|limit_minutes|limit_days|limit_count|min_minutes|max_minutes)",
                target,
            )
            if match is None or target in seen:
                reject(
                    "UNSUPPORTED_DIAGNOSIS_EDIT",
                    "存在する需要人数・必須ルールの上限だけを重複なしで編集します。",
                    path,
                )
            name, number, field = match.groups()
            number = int(number)
            if (
                number >= len(request[name])
                or field not in request[name][number]
                or (name == "demand") != (field == "required_people")
            ):
                reject(
                    "UNSUPPORTED_DIAGNOSIS_EDIT", "編集先が対応済みの入力項目ではありません。", path
                )
            maximum = 250 if name == "demand" else 10000000
            if not 0 <= edit["value"] <= maximum:
                reject(
                    "INVALID_DIAGNOSIS_VALUE",
                    "編集値が対象項目の契約上限を超えています。",
                    path + "/value",
                )
            seen.add(target)


def conditions(request):
    result = []

    def add(code, path, ids=(), interval=None):
        result.append(
            {
                "code": code,
                "json_pointer": path,
                "related_ids": list(ids),
                "interval": deepcopy(interval),
            }
        )

    window = {k: request["planning_window"][k] for k in ("start", "end")}
    add("PLANNING_GRID", "/planning_window", interval=window)
    add(
        "DEMAND_LIMIT_AND_SINGLE_ASSIGNMENT"
        if request["schema_version"]
        in {"0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}
        else "EXACT_DEMAND_AND_SINGLE_ASSIGNMENT",
        "/problem_type",
    )
    for i, demand in enumerate(request["demand"]):
        add("DEMAND", f"/demand/{i}", [demand["id"], demand["role_id"]], demand["interval"])
    for i, role in enumerate(request["roles"]):
        add("REQUIRED_SKILLS", f"/roles/{i}/required_skills", [role["id"]])
    for i, employee in enumerate(request["employees"]):
        add("EMPLOYEE_SKILLS", f"/employees/{i}/skills", [employee["id"]])
        add("AVAILABILITY", f"/employees/{i}/availability", [employee["id"]], window)
        if "history" in employee:
            add("HISTORY", f"/employees/{i}/history", [employee["id"]])
    if request.get("continuity"):
        add("CONTINUITY_BACKGROUND", "/continuity/context_window")
        for i, row in enumerate(request["continuity"]["employees"]):
            add(
                "HISTORY_BACKGROUND",
                f"/continuity/employees/{i}/before_context",
                [row["employee_id"]],
            )
            for name in ("actual_shifts", "committed_shifts"):
                for j, duty in enumerate(row[name]):
                    add(
                        "ACTUAL_SHIFT_BACKGROUND"
                        if name == "actual_shifts"
                        else "COMMITTED_SHIFT_BACKGROUND",
                        f"/continuity/employees/{i}/{name}/{j}",
                        [row["employee_id"], duty["id"]],
                    )
    for i, candidate in enumerate(request["shift_candidates"]):
        segments = candidate["segments"]
        add(
            "SHIFT_CANDIDATE",
            f"/shift_candidates/{i}",
            [candidate["id"], candidate["employee_id"]],
            {"start": segments[0]["interval"]["start"], "end": segments[-1]["interval"]["end"]},
        )
    # 空の候補集合も必須条件として追跡する。
    add("CANDIDATE_SET", "/shift_candidates")
    for name, code in [
        ("shift_templates", "SHIFT_TEMPLATES"),
        ("constraints", "CONSTRAINT"),
        ("fixed_parts", "FIXED_PART"),
    ]:
        for i, item in enumerate(request.get(name, [])):
            add(code, f"/{name}/{i}", [item["id"]], item.get("interval"))
    if request.get("baseline"):
        add("BASELINE_STATES", "/baseline", [request["baseline"]["plan_id"]])
    if request.get("replan_mode") == "preserve_assigned":
        add("PRESERVE_ASSIGNED", "/replan_mode", [request["baseline"]["plan_id"]])
    return result


def condition_groups(request):
    """元pointerをグループIDにし、対応済みの必須条件を背景と削除対象へ分ける。"""
    supported_fields = {
        "schema_version",
        "request_id",
        "problem_type",
        "planning_window",
        "skills",
        "roles",
        "employees",
        "demand",
        "shift_candidates",
        "shift_templates",
        "constraints",
        "preferences",
        "objectives",
        "solver",
        "fairness",
        "costs",
        "duty_balance",
        "baseline",
        "fixed_parts",
        "replan_mode",
        "continuity",
        "diagnosis",
    }
    supported_rules = {
        "max_assigned_minutes",
        "max_role_switches",
        "max_scheduled_minutes",
        "min_rest_minutes",
        "max_consecutive_days",
        "min_split_gap_minutes",
        "scheduled_minutes_bounds",
        "work_days_bounds",
        "days_off_bounds",
    }
    if request.keys() - supported_fields or any(
        rule["type"] not in supported_rules for rule in request["constraints"]
    ):
        raise NotImplementedError("Unclassified hard condition")
    groups, background = [], []
    window = {k: request["planning_window"][k] for k in ("start", "end")}
    for condition in conditions(request):
        item = {**condition, "group_id": condition["json_pointer"]}
        path, code = item["json_pointer"], item["code"]
        if code in {"DEMAND", "CONSTRAINT", "FIXED_PART", "PRESERVE_ASSIGNED"}:
            if code == "CONSTRAINT":
                rule = request["constraints"][int(path.rsplit("/", 1)[1])]
                item["related_ids"] = [rule["id"], *rule["employee_ids"]]
                item["interval"] = deepcopy(rule.get("interval", window))
            elif code == "FIXED_PART":
                part = request["fixed_parts"][int(path.rsplit("/", 1)[1])]
                item["related_ids"] = [part["id"], part["employee_id"]]
            elif code == "PRESERVE_ASSIGNED":
                source = request["baseline"]["source_request"]["planning_window"]
                item["interval"] = {
                    "start": max((window["start"], source["start"]), key=parse_datetime),
                    "end": min((window["end"], source["end"]), key=parse_datetime),
                }
            groups.append(item)
        else:
            if path == "/problem_type":
                item["code"] = (
                    "BASIC_ROSTER_RULES"
                    if request["problem_type"] == "roster"
                    else "BASIC_ASSIGNMENT_RULES"
                )
                item["interval"] = deepcopy(window)
            elif code == "CONTINUITY_BACKGROUND":
                item["interval"] = deepcopy(request["continuity"]["context_window"])
            elif code in {"ACTUAL_SHIFT_BACKGROUND", "COMMITTED_SHIFT_BACKGROUND"}:
                value = request
                for part in path.split("/")[1:]:
                    value = value[int(part)] if isinstance(value, list) else value[part]
                item["interval"] = {
                    "start": value["segments"][0]["interval"]["start"],
                    "end": value["segments"][-1]["interval"]["end"],
                }
            elif code == "SHIFT_TEMPLATES":
                item["interval"] = deepcopy(window)
            background.append(item)
    return sorted(groups, key=lambda c: c["group_id"]), sorted(
        background, key=lambda c: c["group_id"]
    )


def group_conflict(groups, background):
    return {
        "conditions": deepcopy(groups),
        "background_conditions": deepcopy(background),
        "infeasibility_proven": True,
        "minimality": "not_proven",
        "minimality_scope": "condition_groups_relative_to_background",
        "background_only": not groups,
        "rechecked": False,
        "checks": [],
    }


def refine(request, result, groups, background, overall_deadline, problem, num_workers, start):
    from .cp_sat import check_feasibility
    from .model import normalize
    from .verify import verify_plan

    deadline = min(
        overall_deadline,
        start + request["diagnosis"]["conflict_refinement"]["time_limit_seconds"],
    )
    if problem is None:
        problem = normalize(request)
    active = {item["group_id"] for item in groups}
    conflict = group_conflict(groups, background)
    witnesses = {}

    def check(selected, phase, removed=None, witness=None):
        started = time.monotonic()
        if started >= deadline:
            result["status"] = "TIME_LIMIT"
            return None
        outcome = (
            check_feasibility(problem, selected, deadline, num_workers)
            if witness is None
            else witness
        )
        verified = None
        verification_start = time.monotonic()
        if outcome.solution is not None and verification_start < deadline:
            verified = not verify_plan(problem, outcome.solution, active_groups=selected)[0]
        finished = time.monotonic()
        completed = finished < deadline
        record = {
            "phase": phase,
            "active_groups": sorted(selected),
            "removed_group_id": removed,
            "status": outcome.status,
            "witness_verified": verified,
            "completed_in_budget": completed,
            "elapsed_seconds": finished - started,
            "preparation_elapsed_seconds": outcome.preparation_elapsed_seconds
            if witness is None
            else 0.0,
            "search_elapsed_seconds": outcome.search_elapsed_seconds if witness is None else 0.0,
            "verification_elapsed_seconds": finished - verification_start,
        }
        conflict["checks"].append(record)
        if not completed:
            result["status"] = "TIME_LIMIT"
            return None
        if outcome.status in {"FEASIBLE", "OPTIMAL"} and verified is not True:
            raise RuntimeError("Invalid relaxation witness")
        if outcome.status not in {"INFEASIBLE", "FEASIBLE", "OPTIMAL", "UNKNOWN"}:
            raise RuntimeError("Unexpected refinement status")
        return outcome

    initial = check(active, "initial")
    if initial is None or initial.status == "UNKNOWN":
        result["status"] = "TIME_LIMIT"
        result["diagnostics"].append(
            diagnostic("REFINEMENT_UNPROVEN", "全条件の再確認を追加予算内に証明できませんでした。")
        )
        return
    if initial.status != "INFEASIBLE":
        raise RuntimeError("Diagnostic model differs from original model")
    result["conflict"] = conflict
    for identifier in sorted(active):
        trial = check(active - {identifier}, "removal", identifier)
        if trial is None:
            break
        if trial.status == "INFEASIBLE":
            active.remove(identifier)
            conflict["conditions"] = [c for c in groups if c["group_id"] in active]
            conflict["background_only"] = not active
        elif trial.status in {"FEASIBLE", "OPTIMAL"}:
            witnesses[identifier] = trial
    final = check(active, "final")
    if final is None or final.status == "UNKNOWN":
        return
    if final.status != "INFEASIBLE":
        raise RuntimeError("Final conflict is feasible")
    conflict["rechecked"] = True
    for identifier in sorted(active):
        if identifier not in witnesses:
            return
        # 以前の大きな集合の証拠を、返す集合の各要素を除いた条件で再検証する。
        if (
            check(active - {identifier}, "witness_recheck", identifier, witnesses[identifier])
            is None
        ):
            return
    conflict["minimality"] = "inclusion_minimal"


def valid_group_conflict(request, conflict, *, failed=False):
    """参照と探索記録の整合を検査する。保存された記録だけで証明を再認定しない。"""
    groups, background = condition_groups(request)
    expected = {c["group_id"]: c for c in groups}
    ids = [c["group_id"] for c in conflict["conditions"]]
    if (
        ids != sorted(set(ids))
        or any(expected.get(c["group_id"]) != c for c in conflict["conditions"])
        or conflict["background_conditions"] != background
        or conflict["background_only"] != (not ids)
    ):
        return False
    if not request["diagnosis"].get("conflict_refinement"):
        return (
            conflict["conditions"] == groups
            and not conflict["checks"]
            and conflict["minimality"] == "not_proven"
            and not conflict["rechecked"]
        )
    active = set(expected)
    initialized, rechecked, final_seen = False, False, False
    removed, feasible, witnesses = set(), set(), set()
    for index, record in enumerate(conflict["checks"]):
        selected, target = record["active_groups"], record["removed_group_id"]
        status, phase = record["status"], record["phase"]
        completed = record["completed_in_budget"]
        verified = record["witness_verified"]
        if selected != sorted(set(selected)) or not set(selected) <= expected.keys():
            return False
        if status in {"INFEASIBLE", "UNKNOWN"} and verified is not None:
            return False
        if completed and status in {"FEASIBLE", "OPTIMAL"} and verified is not True and not failed:
            return False
        if phase == "initial":
            if index != 0 or target is not None or set(selected) != active:
                return False
            initialized = completed and status == "INFEASIBLE"
        elif phase == "removal":
            if (
                not initialized
                or final_seen
                or target not in active
                or target in removed
                or set(selected) != active - {target}
            ):
                return False
            removed.add(target)
            if completed and status == "INFEASIBLE":
                active.remove(target)
            elif completed and verified and status in {"FEASIBLE", "OPTIMAL"}:
                feasible.add(target)
        elif phase == "final":
            if not initialized or final_seen or target is not None or set(selected) != active:
                return False
            final_seen = True
            rechecked = completed and status == "INFEASIBLE"
        elif phase == "witness_recheck":
            if (
                not rechecked
                or target not in active
                or target not in feasible
                or target in witnesses
                or set(selected) != active - {target}
                or status not in {"FEASIBLE", "OPTIMAL"}
            ):
                return False
            if completed and verified:
                witnesses.add(target)
    return (
        initialized
        and set(ids) == active
        and conflict["rechecked"] == rechecked
        and (conflict["minimality"] == "not_proven" or (rechecked and witnesses == active))
    )


def diagnose(request, status, solve, *, problem=None, num_workers=2):
    from .engine import validate_response

    start = time.monotonic()
    config = request["diagnosis"]
    deadline = start + config["time_limit_seconds"]
    result = {
        "status": "COMPLETE",
        "reason": None,
        "conflict": None,
        "suggestions": [],
        "suggestion_minimality": "not_proven",
        "time_limit_seconds": config["time_limit_seconds"],
        "elapsed_seconds": 0.0,
        "diagnostics": [],
    }
    if status != "INFEASIBLE":
        result.update(
            status="NOT_APPLICABLE",
            reason={"UNKNOWN": "ORIGINAL_UNKNOWN", "PARTIAL": "ORIGINAL_PARTIAL"}.get(
                status, "ORIGINAL_FEASIBLE"
            ),
        )
        result["elapsed_seconds"] = time.monotonic() - start
        return result
    try:
        if time.monotonic() >= deadline:
            result["status"] = "TIME_LIMIT"
        else:
            if request["schema_version"] in {"0.8", "0.9", "0.10", "0.11"}:
                groups, background = condition_groups(request)
                if config.get("conflict_refinement"):
                    refine(
                        request, result, groups, background, deadline, problem, num_workers, start
                    )
                else:
                    conflict = group_conflict(groups, background)
                    if time.monotonic() < deadline:
                        result["conflict"] = conflict
                    else:
                        result["status"] = "TIME_LIMIT"
            else:
                # 旧版の全必須条件の十分集合と証明範囲は維持する。
                conflict = {
                    "conditions": conditions(request),
                    "infeasibility_proven": True,
                    "minimality": "not_proven",
                }
                if time.monotonic() < deadline:
                    result["conflict"] = conflict
                else:
                    result["status"] = "TIME_LIMIT"
        for option in config["allowed_changes"]:
            if (result["status"] == "TIME_LIMIT" and not config.get("conflict_refinement")) or len(
                result["suggestions"]
            ) >= config["max_suggestions"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["status"] = "TIME_LIMIT"
                break
            modified = deepcopy(request)
            modified.pop("diagnosis")
            for edit in option["edits"]:
                _, name, number, field = edit["json_pointer"].split("/")
                modified[name][int(number)][field] = edit["value"]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["status"] = "TIME_LIMIT"
                break
            modified["solver"]["time_limit_seconds"] = min(
                modified["solver"]["time_limit_seconds"], remaining
            )
            response = solve(modified)
            if time.monotonic() > deadline:
                result["status"] = "TIME_LIMIT"
                result["diagnostics"].append(
                    diagnostic(
                        "OPTION_TIME_LIMIT",
                        "追加予算内に変更案の検証を完了できませんでした。",
                        related_ids=[option["id"]],
                    )
                )
                break
            if response["status"] in {"OPTIMAL", "FEASIBLE"} and response["verification"]["valid"]:
                validate_response(response, modified)
                if time.monotonic() > deadline:
                    result["status"] = "TIME_LIMIT"
                    result["diagnostics"].append(
                        diagnostic(
                            "OPTION_TIME_LIMIT",
                            "変更案の追加検証が予算内に完了しませんでした。",
                            related_ids=[option["id"]],
                        )
                    )
                    break
                result["suggestions"].append(
                    {"option_id": option["id"], "modified_request": modified, "response": response}
                )
                result["diagnostics"].append(
                    diagnostic(
                        "OPTION_BUDGET",
                        "許可編集を適用し、診断を無効にして残り予算で検証しました。",
                        "/solver/time_limit_seconds",
                        [option["id"]],
                        original_budget=request["solver"]["time_limit_seconds"],
                        applied_budget=modified["solver"]["time_limit_seconds"],
                    )
                )
            else:
                result["diagnostics"].append(
                    diagnostic(
                        "OPTION_REJECTED",
                        "変更後入力の検証済み解を取得できませんでした。",
                        related_ids=[option["id"]],
                        status=response["status"],
                    )
                )
    except NotImplementedError:
        result["status"] = "UNSUPPORTED"
        result["diagnostics"].append(
            diagnostic("UNCLASSIFIED_CONDITION", "診断の分類に未対応の必須条件があります。")
        )
    except Exception:
        logger.debug("追加診断で内部例外が発生しました。", exc_info=True)
        result["status"] = "ERROR"
        result["diagnostics"].append(
            diagnostic("DIAGNOSIS_ERROR", "追加診断の処理に失敗しました。")
        )
    result["elapsed_seconds"] = time.monotonic() - start
    return result


def validate_result(request, response):
    from .engine import validate_response

    result = response["diagnosis_result"]
    config = request.get("diagnosis")
    errors = []

    def fail():
        errors.append(
            diagnostic(
                "DIAGNOSIS_MISMATCH",
                "診断結果が元入力・証明範囲・許可編集と一致しません。",
                "/diagnosis_result",
            )
        )

    if not config:
        if result is not None:
            fail()
        return errors
    if result is None:
        if response["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL", "INFEASIBLE", "UNKNOWN"}:
            fail()
        return errors
    if result["time_limit_seconds"] != config["time_limit_seconds"]:
        fail()
    if response["status"] != "INFEASIBLE":
        if (
            response["status"] != "PARTIAL"
            and result["status"] == "ERROR"
            and result["conflict"] is None
            and not result["suggestions"]
        ):
            return errors
        reason = {"UNKNOWN": "ORIGINAL_UNKNOWN", "PARTIAL": "ORIGINAL_PARTIAL"}.get(
            response["status"], "ORIGINAL_FEASIBLE"
        )
        if (
            result["status"] != "NOT_APPLICABLE"
            or result["reason"] != reason
            or result["conflict"] is not None
            or result["suggestions"]
        ):
            fail()
        return errors
    if result["conflict"] is not None:
        if request["schema_version"] in {"0.8", "0.9", "0.10", "0.11"}:
            if not valid_group_conflict(
                request, result["conflict"], failed=result["status"] == "ERROR"
            ):
                fail()
        elif result["conflict"]["conditions"] != conditions(request):
            fail()
    if result["status"] == "COMPLETE" and result["conflict"] is None:
        fail()
    options = {option["id"]: option for option in config["allowed_changes"]}
    seen = set()
    if len(result["suggestions"]) > config["max_suggestions"]:
        fail()
    for suggestion in result["suggestions"]:
        identifier = suggestion["option_id"]
        if identifier not in options or identifier in seen:
            fail()
            continue
        seen.add(identifier)
        modified = suggestion["modified_request"]
        expected = deepcopy(request)
        expected.pop("diagnosis")
        for edit in options[identifier]["edits"]:
            _, name, number, field = edit["json_pointer"].split("/")
            expected[name][int(number)][field] = edit["value"]
        budget = modified.get("solver", {}).get("time_limit_seconds", 0)
        if (
            not 0
            < budget
            <= min(config["time_limit_seconds"], request["solver"]["time_limit_seconds"])
        ):
            fail()
        expected["solver"]["time_limit_seconds"] = budget
        if modified != expected:
            fail()
            continue
        validate_response(suggestion["response"], modified)
    return errors
