import logging
import time
from importlib.metadata import version

from . import cp_sat, flow
from .contract import (
    InvalidInput,
    check_json,
    diagnostic,
    schema_errors,
    schema_version_of,
)
from .model import TimezoneDataError, flow_requires_complete_demand, minute_datetime, normalize
from .verify import priority_summary, verify_plan, verify_solution

logger = logging.getLogger(__name__)


def response(
    request_id,
    status,
    diagnostics=(),
    backend="none",
    verification=None,
    selection_reason="NOT_SELECTED",
    library_version=None,
):
    return {
        "schema_version": "0.1",
        "request_id": request_id,
        "status": status,
        "solver": {
            "backend": backend,
            "engine_version": version("shift-schedula"),
            "library_version": library_version,
            "selection_reason": selection_reason,
        },
        "solution": None,
        "objectives": [],
        "diagnostics": list(diagnostics),
        "verification": verification or {"performed": False, "valid": None, "violations": []},
        "stats": {"elapsed_seconds": 0.0},
    }


def validate_response(result, request=None):
    check_json(result)
    errors = schema_errors("response", result)
    if errors:
        raise InvalidInput(errors)
    if request is not None and result["schema_version"] != request["schema_version"]:
        raise InvalidInput(
            [
                diagnostic(
                    "SCHEMA_VERSION_MISMATCH",
                    "応答の契約版が入力と一致しません。",
                    "/schema_version",
                )
            ]
        )
    if request is not None and result["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:
        expected = [
            (item["id"], item["metric"], item.get("duty_id"), item.get("balance_id"))
            for item in request["objectives"]
        ]
        actual = [
            (item["id"], item["metric"], item.get("duty_id"), item.get("balance_id"))
            for item in result["objectives"]
        ]
        if expected != actual:
            errors.append(
                diagnostic(
                    "OBJECTIVE_MISMATCH", "結果の目的が Request と一致しません。", "/objectives"
                )
            )
        if request["schema_version"] in {
            "0.2",
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            from .extensions import evaluate

            problem = normalize(request)
            violations, values, shortage = verify_plan(problem, result["solution"])
            errors.extend(violations)
            if request["schema_version"] in {
                "0.3",
                "0.4",
                "0.5",
                "0.6",
                "0.7",
                "0.8",
                "0.9",
                "0.10",
                "0.11",
                "0.12",
                "0.13",
                "0.14",
                "0.15",
            } and shortage != {
                k: v for k, v in result["shortage_summary"].items() if k != "proven_minimal"
            }:
                errors.append(
                    diagnostic(
                        "SHORTAGE_MISMATCH",
                        "不足集計が元入力と返却解に一致しません。",
                        "/shortage_summary",
                    )
                )
            if request["schema_version"] in {
                "0.5",
                "0.6",
                "0.7",
                "0.8",
                "0.9",
                "0.10",
                "0.11",
                "0.12",
                "0.13",
                "0.14",
                "0.15",
            }:
                expected_priority = priority_summary(request, shortage)
                actual_priority = {
                    "groups": [
                        {**group, "proven_minimal": False}
                        for group in result["priority_summary"]["groups"]
                    ]
                }
                if actual_priority != expected_priority:
                    errors.append(
                        diagnostic(
                            "PRIORITY_SHORTAGE_MISMATCH",
                            "priority別不足が元需要と返却解に一致しません。",
                            "/priority_summary",
                        )
                    )
            if values != tuple(item["value"] for item in result["objectives"]):
                errors.append(
                    diagnostic(
                        "OBJECTIVE_VALUE_MISMATCH", "返却解の評価値が一致しません。", "/objectives"
                    )
                )
            _, _, summaries = evaluate(problem, result["solution"])
            for name, value in summaries.items():
                if result[name] != value:
                    errors.append(
                        diagnostic(
                            "SUMMARY_MISMATCH", "結果の集計が返却解と一致しません。", "/" + name
                        )
                    )
    if result["status"] in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:
        proofs = [item["proven_optimal"] for item in result["objectives"]]
        if result["schema_version"] in {
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            groups = result["priority_summary"]["groups"]
            levels = [g["priority"] for g in groups]
            if (
                levels != sorted(set(levels), reverse=True)
                or sum(g["total_person_minutes"] for g in groups)
                != result["shortage_summary"]["total_person_minutes"]
            ):
                errors.append(
                    diagnostic(
                        "PRIORITY_SHORTAGE_MISMATCH",
                        "priority別不足の順序または合計が不正です。",
                        "/priority_summary",
                    )
                )
            proofs = [
                result["shortage_summary"]["proven_minimal"],
                *(g["proven_minimal"] for g in groups),
                *proofs,
            ]
        if proofs != sorted(proofs, reverse=True) or (
            result["status"] == "FEASIBLE"
            and (
                proofs
                or result["schema_version"]
                in {
                    "0.3",
                    "0.4",
                    "0.5",
                    "0.6",
                    "0.7",
                    "0.8",
                    "0.9",
                    "0.10",
                    "0.11",
                    "0.12",
                    "0.13",
                    "0.14",
                    "0.15",
                }
            )
            and all(proofs)
        ):
            errors.append(
                diagnostic(
                    "OPTIMALITY_MISMATCH",
                    "最適性の証明範囲が目的順序または結果状態と一致しません。",
                    "/objectives",
                )
            )
    if (
        result["schema_version"]
        in {
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }
        and result["shortage_summary"] is not None
    ):
        summary = result["shortage_summary"]
        total = 0
        for index, item in enumerate(summary["shortages"]):
            path = f"/shortage_summary/shortages/{index}"
            duration = minute_datetime(
                item["interval"]["end"], path + "/interval/end"
            ) - minute_datetime(item["interval"]["start"], path + "/interval/start")
            seconds = duration.total_seconds()
            if (
                seconds <= 0
                or seconds % 60
                or item["required_people"] - item["assigned_people"] != item["missing_people"]
                or (
                    result["schema_version"] in {"0.12", "0.13", "0.14", "0.15"}
                    and not 0 <= item["minimum_people"] <= item["assigned_people"]
                )
            ):
                errors.append(
                    diagnostic(
                        "SHORTAGE_MISMATCH",
                        "不足人数または区間が不足集計の契約と一致しません。",
                        f"/shortage_summary/shortages/{index}",
                    )
                )
            total += seconds // 60 * item["missing_people"]
        if total != summary["total_person_minutes"]:
            errors.append(
                diagnostic(
                    "SHORTAGE_MISMATCH",
                    "不足合計人分が不足一覧と一致しません。",
                    "/shortage_summary/total_person_minutes",
                )
            )
    if request is not None and request["schema_version"] in {
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.10",
        "0.11",
        "0.12",
        "0.13",
        "0.14",
        "0.15",
    }:
        from .diagnosis import validate_result

        errors.extend(validate_result(request, result))
    if errors:
        raise InvalidInput(errors)


def validate(request: object) -> dict:
    """探索せず、構造・参照・時刻・候補・基準計画の意味を検証する。"""
    start = time.perf_counter()
    result = {
        "schema_version": schema_version_of(request),
        "request_id": request.get("request_id")
        if isinstance(request, dict) and isinstance(request.get("request_id"), str)
        else None,
        "status": "VALID",
        "diagnostics": [],
        "stats": {"elapsed_seconds": 0.0},
    }
    try:
        normalize(request)
    except InvalidInput as error:
        result.update(status="INVALID_INPUT", diagnostics=error.diagnostics)
    except TimezoneDataError:
        logger.debug("入力検証で時刻データを読み取れませんでした。", exc_info=True)
        result.update(
            status="INTERNAL_ERROR",
            diagnostics=[
                diagnostic("TIMEZONE_DATA_UNAVAILABLE", "OSのTZDBまたはtzdataの導入を確認します。")
            ],
        )
    except Exception:
        logger.debug("入力検証で内部例外が発生しました。", exc_info=True)
        result.update(
            status="INTERNAL_ERROR",
            diagnostics=[diagnostic("INTERNAL_ERROR", "入力検証の処理に失敗しました。")],
        )
    result["stats"]["elapsed_seconds"] = time.perf_counter() - start
    return result


def choose_backend(request):
    if request["solver"]["backend"] != "auto":
        return request["solver"]["backend"], "EXPLICIT_BACKEND"
    if any(d.get("minimum_people", 0) for d in request["demand"]) and not (
        flow_requires_complete_demand(request)
        and request["problem_type"] == "assignment"
        and not request["constraints"]
        and not request.get("diagnosis")
        and not any(d.get("priority", 0) for d in request["demand"])
        and not any(o["metric"] == "role_switches" for o in request["objectives"])
    ):
        return "cp_sat", "MANDATORY_DEMAND"
    if any(d.get("priority", 0) for d in request["demand"]):
        return "cp_sat", "DEMAND_PRIORITY"
    if request["problem_type"] == "roster":
        return "cp_sat", "JOINT_ROSTER"
    if request.get("diagnosis"):
        return "cp_sat", "INFEASIBILITY_DIAGNOSIS"
    if request["constraints"]:
        return "cp_sat", "ASSIGNMENT_CONSTRAINTS"
    if any(objective["metric"] == "role_switches" for objective in request["objectives"]):
        return "cp_sat", "ROLE_SWITCH_OBJECTIVE"
    return "min_cost_flow", "INDEPENDENT_ADDITIVE_ASSIGNMENTS"


def solve(request: dict, *, num_workers: int = 2) -> dict:
    start = time.perf_counter()
    request_id = request.get("request_id") if isinstance(request, dict) else None
    if not isinstance(request_id, str):
        request_id = None
    backend = "none"
    selection_reason = "NOT_SELECTED"
    library_version = None
    verification = None
    schema_version = schema_version_of(request)

    def extend(result):
        result["schema_version"] = schema_version
        if schema_version in {
            "0.2",
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            result.update(fairness_summary=None, change_summary=None, diagnosis_result=None)
        if schema_version in {
            "0.3",
            "0.4",
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            result["shortage_summary"] = None
        if schema_version in {
            "0.5",
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            result["priority_summary"] = None
        if schema_version in {
            "0.6",
            "0.7",
            "0.8",
            "0.9",
            "0.10",
            "0.11",
            "0.12",
            "0.13",
            "0.14",
            "0.15",
        }:
            result["continuity_summary"] = None
        if schema_version in {"0.9", "0.10", "0.11", "0.12", "0.13", "0.14", "0.15"}:
            result.update(cost_summary=None, duty_balance_summary=None)
        if schema_version in {"0.11", "0.12", "0.13", "0.14", "0.15"}:
            result["day_count_summary"] = None
        if schema_version == "0.15":
            result["shift_count_balance_summary"] = None
        return result

    try:
        if type(num_workers) is not int or not 1 <= num_workers <= 2**31 - 1:
            raise InvalidInput(
                [
                    diagnostic(
                        "INVALID_EXECUTION_OPTION",
                        "num_workers は1〜2147483647の整数で指定します。boolは受理しません。",
                    )
                ]
            )
        problem = normalize(request)
        normalized_at = time.perf_counter()
        backend, selection_reason = choose_backend(request)
        if backend == "cp_sat":
            module, library_version = cp_sat.load_backend()
            loaded_at = time.perf_counter()
            outcome = cp_sat.run(problem, module, num_workers)
        else:
            loaded_at = time.perf_counter()
            outcome = flow.run(problem)
        solved_at = time.perf_counter()
        if (
            backend == "min_cost_flow"
            and outcome.status == "FEASIBLE"
            and schema_version
            not in {
                "0.3",
                "0.4",
                "0.5",
                "0.6",
                "0.7",
                "0.8",
                "0.9",
                "0.10",
                "0.11",
                "0.12",
                "0.13",
                "0.14",
                "0.15",
            }
        ):
            raise RuntimeError("Unexpected flow outcome")
        result = extend(response(request_id, outcome.status, outcome.diagnostics, backend))
        if outcome.status in {"OPTIMAL", "FEASIBLE"}:
            shortage = None
            if schema_version in {
                "0.3",
                "0.4",
                "0.5",
                "0.6",
                "0.7",
                "0.8",
                "0.9",
                "0.10",
                "0.11",
                "0.12",
                "0.13",
                "0.14",
                "0.15",
            }:
                violations, values, shortage = verify_plan(problem, outcome.solution)
                if (
                    shortage is not None
                    and shortage["total_person_minutes"] != outcome.shortage_person_minutes
                ):
                    violations.append(
                        diagnostic(
                            "SHORTAGE_MISMATCH",
                            "ソルバーの不足量が返却解と一致しません。",
                            "/shortage_summary",
                        )
                    )
            else:
                violations, values = verify_solution(problem, outcome.solution)
            priorities = None
            if shortage is not None and schema_version in {
                "0.5",
                "0.6",
                "0.7",
                "0.8",
                "0.9",
                "0.10",
                "0.11",
                "0.12",
                "0.13",
                "0.14",
                "0.15",
            }:
                priorities = priority_summary(request, shortage)
                if backend == "cp_sat" and cp_sat.priority_stages(request):
                    if (
                        tuple(g["total_person_minutes"] for g in priorities["groups"])
                        != outcome.priority_values
                    ):
                        violations.append(
                            diagnostic(
                                "PRIORITY_SHORTAGE_MISMATCH",
                                "ソルバーのpriority別不足が返却解と一致しません。",
                                "/priority_summary",
                            )
                        )
                    for group, proof in zip(
                        priorities["groups"], outcome.priority_proven_minimal, strict=True
                    ):
                        group["proven_minimal"] = proof
                else:
                    for group in priorities["groups"]:
                        group["proven_minimal"] = (
                            outcome.shortage_proven_minimal or shortage["total_person_minutes"] == 0
                        )
            if not violations and values != outcome.values:
                if len(values) != len(outcome.values):
                    violations = [
                        diagnostic(
                            "OBJECTIVE_VALUE_MISMATCH",
                            "ソルバーの目的値の件数が Request と一致しません。",
                            "/objectives",
                        )
                    ]
                else:
                    violations = [
                        diagnostic(
                            "OBJECTIVE_VALUE_MISMATCH",
                            "再計算した評価値がソルバーの値と一致しません。",
                            f"/objectives/{index}",
                            [request["objectives"][index]["id"]],
                            recomputed_value=value,
                            solver_value=solver_value,
                        )
                        for index, (value, solver_value) in enumerate(
                            zip(values, outcome.values, strict=True)
                        )
                        if value != solver_value
                    ]
            verification = {"performed": True, "valid": not violations, "violations": violations}
            if violations:
                result = extend(
                    response(request_id, "INTERNAL_ERROR", violations, backend, verification)
                )
            else:
                result["solution"] = outcome.solution
                if priorities is not None:
                    result["priority_summary"] = priorities
                if schema_version in {
                    "0.3",
                    "0.4",
                    "0.5",
                    "0.6",
                    "0.7",
                    "0.8",
                    "0.9",
                    "0.10",
                    "0.11",
                    "0.12",
                    "0.13",
                    "0.14",
                    "0.15",
                }:
                    minimal = (
                        shortage["total_person_minutes"] == 0 or outcome.shortage_proven_minimal
                    )
                    result["shortage_summary"] = {**shortage, "proven_minimal": minimal}
                    result["status"] = (
                        "PARTIAL"
                        if shortage["total_person_minutes"]
                        else "OPTIMAL"
                        if (
                            all(outcome.proven_optimal)
                            and (
                                priorities is None
                                or all(g["proven_minimal"] for g in priorities["groups"])
                            )
                        )
                        else "FEASIBLE"
                    )
                if schema_version in {
                    "0.2",
                    "0.3",
                    "0.4",
                    "0.5",
                    "0.6",
                    "0.7",
                    "0.8",
                    "0.9",
                    "0.10",
                    "0.11",
                    "0.12",
                    "0.13",
                    "0.14",
                    "0.15",
                }:
                    from .extensions import evaluate

                    _, _, summaries = evaluate(problem, outcome.solution)
                    result.update(summaries)
                result["verification"] = verification
                result["objectives"] = [
                    {
                        **objective,
                        "value": value,
                        "proven_optimal": proven,
                    }
                    for objective, value, proven in zip(
                        request["objectives"], values, outcome.proven_optimal, strict=True
                    )
                ]
        elif outcome.status not in {"INFEASIBLE", "UNKNOWN"} or outcome.solution is not None:
            raise RuntimeError("Unexpected solver outcome")
        verified_at = time.perf_counter()
        result["diagnostics"].append(
            diagnostic(
                "SEARCH_STATS",
                "探索予算・探索開始後の所要時間は呼び出し全体の所要時間と区別します。",
                "/solver/time_limit_seconds",
                time_limit_seconds=request["solver"]["time_limit_seconds"],
                search_elapsed_seconds=outcome.search_elapsed_seconds,
                num_workers=num_workers if backend == "cp_sat" else None,
                workers_applied=backend == "cp_sat",
                normalization_elapsed_seconds=normalized_at - start,
                backend_loading_elapsed_seconds=loaded_at - normalized_at,
                preparation_elapsed_seconds=outcome.preparation_elapsed_seconds,
                verification_elapsed_seconds=verified_at - solved_at,
                **problem.normalization_stats,
            )
        )
        if backend == "cp_sat" and result["solution"] is not None:
            for index, bound in enumerate(outcome.priority_bounds):
                if bound is not None:
                    result["diagnostics"].append(
                        diagnostic(
                            "PRIORITY_SHORTAGE_BOUND",
                            "上位段階を固定したpriority群の不足下限です。",
                            f"/priority_summary/groups/{index}",
                            best_bound=bound,
                        )
                    )
            if (
                schema_version
                in {
                    "0.3",
                    "0.4",
                    "0.5",
                    "0.6",
                    "0.7",
                    "0.8",
                    "0.9",
                    "0.10",
                    "0.11",
                    "0.12",
                    "0.13",
                    "0.14",
                    "0.15",
                }
                and outcome.shortage_bound is not None
            ):
                result["diagnostics"].append(
                    diagnostic(
                        "SHORTAGE_BOUND",
                        "不足合計人分の探索下限です。",
                        "/shortage_summary",
                        best_bound=outcome.shortage_bound,
                    )
                )
            for index, bound in enumerate(outcome.objective_bounds):
                if bound is not None:
                    result["diagnostics"].append(
                        diagnostic(
                            "OBJECTIVE_BOUND",
                            "この目的の下限です。上位目的を固定した探索だけに適用します。",
                            f"/objectives/{index}",
                            [request["objectives"][index]["id"]],
                            objective_index=index,
                            best_bound=bound,
                        )
                    )
        result["solver"]["selection_reason"] = selection_reason
        result["solver"]["library_version"] = library_version
        validated = False
        if request.get("diagnosis") and result["status"] in {
            "OPTIMAL",
            "FEASIBLE",
            "PARTIAL",
            "INFEASIBLE",
            "UNKNOWN",
        }:
            from .diagnosis import diagnose

            diagnosis_start = time.perf_counter()
            try:
                result["diagnosis_result"] = diagnose(
                    request,
                    result["status"],
                    lambda value: solve(value, num_workers=num_workers),
                    problem=problem,
                    num_workers=num_workers,
                )
                validate_response(result, request)
                detail = result["diagnosis_result"]
                detail["elapsed_seconds"] = time.perf_counter() - diagnosis_start
                if (
                    detail["status"] == "COMPLETE"
                    and detail["elapsed_seconds"] > detail["time_limit_seconds"]
                ):
                    detail["status"] = "TIME_LIMIT"
                validated = True
            except Exception:
                logger.debug("追加診断の結果検証で内部例外が発生しました。", exc_info=True)
                result["diagnosis_result"] = {
                    "status": "ERROR",
                    "reason": None,
                    "conflict": None,
                    "suggestions": [],
                    "suggestion_minimality": "not_proven",
                    "time_limit_seconds": request["diagnosis"]["time_limit_seconds"],
                    "elapsed_seconds": time.perf_counter() - diagnosis_start,
                    "diagnostics": [
                        diagnostic("DIAGNOSIS_ERROR", "追加診断の出力検証に失敗しました。")
                    ],
                }
        if not validated:
            validate_response(result, request)
        result["stats"]["elapsed_seconds"] = time.perf_counter() - start
        return result
    except TimezoneDataError:
        logger.debug("求解で時刻データを読み取れませんでした。", exc_info=True)
        result = response(
            request_id,
            "INTERNAL_ERROR",
            [diagnostic("TIMEZONE_DATA_UNAVAILABLE", "OSのTZDBまたはtzdataの導入を確認します。")],
            backend,
        )
    except cp_sat.BackendUnavailable:
        result = response(
            request_id,
            "BACKEND_UNAVAILABLE",
            [
                diagnostic(
                    "BACKEND_UNAVAILABLE",
                    "CP-SAT には cp-sat extra の導入が必要です。",
                    "/solver/backend",
                )
            ],
            backend,
        )
    except InvalidInput as error:
        if backend == "none":
            result = response(request_id, "INVALID_INPUT", error.diagnostics)
        else:
            logger.debug("求解結果の検証に失敗しました。", exc_info=True)
            verification = {"performed": True, "valid": False, "violations": error.diagnostics}
            result = response(
                request_id, "INTERNAL_ERROR", error.diagnostics, backend, verification
            )
    except Exception:
        logger.debug("求解で内部例外が発生しました。", exc_info=True)
        # 内部例外や壊れた出力は正式な解として公開しない。
        result = response(
            request_id,
            "INTERNAL_ERROR",
            [diagnostic("INTERNAL_ERROR", "エンジン内部の処理に失敗しました。")],
            backend,
        )
    extend(result)
    result["solver"]["selection_reason"] = selection_reason
    result["solver"]["library_version"] = library_version
    validate_response(result)
    result["stats"]["elapsed_seconds"] = time.perf_counter() - start
    return result
