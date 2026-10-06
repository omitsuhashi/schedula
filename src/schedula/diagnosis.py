"""元条件の不可能性と、入力者が許可した変更後の解を分けて返す。"""

import re
import time
from copy import deepcopy

from .contract import diagnostic, reject


def validate_options(request):
    from .model import unique

    options = request.get("diagnosis", {}).get("allowed_changes", [])
    unique(options, "id", "/diagnosis/allowed_changes")
    for index, option in enumerate(options):
        seen = set()
        for j, edit in enumerate(option["edits"]):
            path = f"/diagnosis/allowed_changes/{index}/edits/{j}"
            target = edit["json_pointer"]
            match = re.fullmatch(
                r"/(demand|constraints)/(0|[1-9][0-9]*)/(required_people|limit_minutes|limit_days|limit_count)",
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
    add("EXACT_DEMAND_AND_SINGLE_ASSIGNMENT", "/problem_type")
    for i, demand in enumerate(request["demand"]):
        add("DEMAND", f"/demand/{i}", [demand["id"], demand["role_id"]], demand["interval"])
    for i, role in enumerate(request["roles"]):
        add("REQUIRED_SKILLS", f"/roles/{i}/required_skills", [role["id"]])
    for i, employee in enumerate(request["employees"]):
        add("EMPLOYEE_SKILLS", f"/employees/{i}/skills", [employee["id"]])
        add("AVAILABILITY", f"/employees/{i}/availability", [employee["id"]], window)
        if "history" in employee:
            add("HISTORY", f"/employees/{i}/history", [employee["id"]])
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
    return result


def diagnose(request, status, solve):
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
            reason="ORIGINAL_UNKNOWN" if status == "UNKNOWN" else "ORIGINAL_FEASIBLE",
        )
        result["elapsed_seconds"] = time.monotonic() - start
        return result
    try:
        if time.monotonic() >= deadline:
            result["status"] = "TIME_LIMIT"
        else:
            # ponytail: 最初は全必須条件の十分集合。最小集合が必要になれば削除探索を追加する。
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
            if (
                result["status"] == "TIME_LIMIT"
                or len(result["suggestions"]) >= config["max_suggestions"]
            ):
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
    except Exception:
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
        if response["status"] in {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN"}:
            fail()
        return errors
    if result["time_limit_seconds"] != config["time_limit_seconds"]:
        fail()
    if response["status"] != "INFEASIBLE":
        if result["status"] == "ERROR" and result["conflict"] is None and not result["suggestions"]:
            return errors
        reason = "ORIGINAL_UNKNOWN" if response["status"] == "UNKNOWN" else "ORIGINAL_FEASIBLE"
        if (
            result["status"] != "NOT_APPLICABLE"
            or result["reason"] != reason
            or result["conflict"] is not None
            or result["suggestions"]
        ):
            fail()
        return errors
    if result["conflict"] is not None and result["conflict"]["conditions"] != conditions(request):
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
