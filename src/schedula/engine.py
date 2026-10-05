import time
from importlib.metadata import version

from . import cp_sat, flow
from .contract import InvalidInput, check_json, diagnostic, schema_errors
from .model import normalize
from .verify import verify_solution


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
    if request is not None and result["status"] in {"OPTIMAL", "FEASIBLE"}:
        expected = [(item["id"], item["metric"]) for item in request["objectives"]]
        actual = [(item["id"], item["metric"]) for item in result["objectives"]]
        if expected != actual:
            errors.append(
                diagnostic(
                    "OBJECTIVE_MISMATCH", "結果の目的が Request と一致しません。", "/objectives"
                )
            )
    if errors:
        raise InvalidInput(errors)


def choose_backend(request):
    if request["solver"]["backend"] != "auto":
        return request["solver"]["backend"], "EXPLICIT_BACKEND"
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
    try:
        problem = normalize(request)
        backend, selection_reason = choose_backend(request)
        if backend == "cp_sat":
            module, library_version = cp_sat.load_backend()
            outcome = cp_sat.run(problem, module)
        else:
            outcome = flow.run(problem)
        if backend == "min_cost_flow" and outcome.status == "FEASIBLE":
            raise RuntimeError("Unexpected flow outcome")
        result = response(request_id, outcome.status, outcome.diagnostics, backend)
        if outcome.status in {"OPTIMAL", "FEASIBLE"}:
            violations, value = verify_solution(problem, outcome.solution)
            if not violations and value != outcome.cost:
                violations = [
                    diagnostic(
                        "OBJECTIVE_VALUE_MISMATCH",
                        "再計算した評価値がソルバーの値と一致しません。",
                        "/objectives",
                        recomputed_value=value,
                        solver_value=outcome.cost,
                    )
                ]
            verification = {"performed": True, "valid": not violations, "violations": violations}
            if violations:
                result = response(request_id, "INTERNAL_ERROR", violations, backend, verification)
            else:
                result["solution"] = outcome.solution
                result["verification"] = verification
                result["objectives"] = [
                    {
                        "id": objective["id"],
                        "metric": objective["metric"],
                        "value": value,
                        "proven_optimal": outcome.status == "OPTIMAL",
                    }
                    for objective in request["objectives"]
                ]
        elif outcome.status not in {"INFEASIBLE", "UNKNOWN"} or outcome.solution is not None:
            raise RuntimeError("Unexpected solver outcome")
        result["solver"]["selection_reason"] = selection_reason
        result["solver"]["library_version"] = library_version
        result["stats"]["elapsed_seconds"] = time.perf_counter() - start
        validate_response(result, request)
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
    result["solver"]["selection_reason"] = selection_reason
    result["solver"]["library_version"] = library_version
    result["stats"]["elapsed_seconds"] = time.perf_counter() - start
    validate_response(result)
    return result
