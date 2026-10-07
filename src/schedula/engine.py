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
from .model import minute_datetime, normalize
from .verify import verify_plan, verify_solution


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
            "engine_version": version("schedula"),
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
        expected = [(item["id"], item["metric"]) for item in request["objectives"]]
        actual = [(item["id"], item["metric"]) for item in result["objectives"]]
        if expected != actual:
            errors.append(
                diagnostic(
                    "OBJECTIVE_MISMATCH", "結果の目的が Request と一致しません。", "/objectives"
                )
            )
        if request["schema_version"] in {"0.2", "0.3"}:
            from .extensions import evaluate

            problem = normalize(request)
            violations, values, shortage = verify_plan(problem, result["solution"])
            errors.extend(violations)
            if request["schema_version"] == "0.3" and shortage != {
                k: v for k, v in result["shortage_summary"].items() if k != "proven_minimal"
            }:
                errors.append(
                    diagnostic(
                        "SHORTAGE_MISMATCH",
                        "不足集計が元入力と返却解に一致しません。",
                        "/shortage_summary",
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
        if proofs != sorted(proofs, reverse=True) or (
            result["status"] == "FEASIBLE"
            and (proofs or result["schema_version"] == "0.3")
            and all(proofs)
        ):
            errors.append(
                diagnostic(
                    "OPTIMALITY_MISMATCH",
                    "最適性の証明範囲が目的順序または結果状態と一致しません。",
                    "/objectives",
                )
            )
    if result["schema_version"] == "0.3" and result["shortage_summary"] is not None:
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
    if request is not None and request["schema_version"] in {"0.2", "0.3"}:
        from .diagnosis import validate_result

        errors.extend(validate_result(request, result))
    if errors:
        raise InvalidInput(errors)


def choose_backend(request):
    if request["solver"]["backend"] != "auto":
        return request["solver"]["backend"], "EXPLICIT_BACKEND"
    if request["problem_type"] == "roster":
        return "cp_sat", "JOINT_ROSTER"
    if request.get("diagnosis"):
        return "cp_sat", "INFEASIBILITY_DIAGNOSIS"
    if request["constraints"]:
        return "cp_sat", "ASSIGNMENT_CONSTRAINTS"
    if any(objective["metric"] == "role_switches" for objective in request["objectives"]):
        return "cp_sat", "ROLE_SWITCH_OBJECTIVE"
    return "min_cost_flow", "INDEPENDENT_ADDITIVE_ASSIGNMENTS"


def solve(request: dict) -> dict:
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
        if schema_version in {"0.2", "0.3"}:
            result.update(fairness_summary=None, change_summary=None, diagnosis_result=None)
        if schema_version == "0.3":
            result["shortage_summary"] = None
        return result

    try:
        problem = normalize(request)
        normalized_at = time.perf_counter()
        backend, selection_reason = choose_backend(request)
        if backend == "cp_sat":
            module, library_version = cp_sat.load_backend()
            loaded_at = time.perf_counter()
            outcome = cp_sat.run(problem, module)
        else:
            loaded_at = time.perf_counter()
            outcome = flow.run(problem)
        solved_at = time.perf_counter()
        if backend == "min_cost_flow" and outcome.status == "FEASIBLE" and schema_version != "0.3":
            raise RuntimeError("Unexpected flow outcome")
        result = extend(response(request_id, outcome.status, outcome.diagnostics, backend))
        if outcome.status in {"OPTIMAL", "FEASIBLE"}:
            shortage = None
            if schema_version == "0.3":
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
                if schema_version == "0.3":
                    minimal = (
                        shortage["total_person_minutes"] == 0 or outcome.shortage_proven_minimal
                    )
                    result["shortage_summary"] = {**shortage, "proven_minimal": minimal}
                    result["status"] = (
                        "PARTIAL"
                        if shortage["total_person_minutes"]
                        else "OPTIMAL"
                        if all(outcome.proven_optimal)
                        else "FEASIBLE"
                    )
                if schema_version in {"0.2", "0.3"}:
                    from .extensions import evaluate

                    _, _, summaries = evaluate(problem, outcome.solution)
                    result.update(summaries)
                result["verification"] = verification
                result["objectives"] = [
                    {
                        "id": objective["id"],
                        "metric": objective["metric"],
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
                normalization_elapsed_seconds=normalized_at - start,
                backend_loading_elapsed_seconds=loaded_at - normalized_at,
                preparation_elapsed_seconds=outcome.preparation_elapsed_seconds,
                verification_elapsed_seconds=verified_at - solved_at,
            )
        )
        if backend == "cp_sat" and result["solution"] is not None:
            if schema_version == "0.3" and outcome.shortage_bound is not None:
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
                result["diagnosis_result"] = diagnose(request, result["status"], solve)
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
            verification = {"performed": True, "valid": False, "violations": error.diagnostics}
            result = response(
                request_id, "INTERNAL_ERROR", error.diagnostics, backend, verification
            )
    except Exception:
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
