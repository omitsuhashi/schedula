"""隔離した参照実装で、導入時に修正する2つの境界を再現する。"""

import builtins
import json
from pathlib import Path
from time import sleep
from unittest.mock import patch

from jsonschema import Draft202012Validator
from skillshift import engine, solve
from skillshift.model import schema


def probe_import_budget(request):
    request["solver"].update(backend="cp_sat", time_limit_seconds=0.01)
    original_import = builtins.__import__

    def delayed_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ortools.sat.python":
            sleep(0.02)
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=delayed_import):
        result = solve(request)
    assert result["status"] == "UNKNOWN", result
    assert result["diagnostics"][0]["code"] == "TIME_LIMIT", result
    assert result["solution"] is None, result
    return {
        "injected_import_delay_seconds": 0.02,
        "search_budget_seconds": 0.01,
        "response": result,
    }


def probe_output_structure(request):
    original = engine.make_solution

    def malformed_solution(*args):
        output = original(*args)
        output["unexpected"] = True
        return output

    with patch.object(engine, "make_solution", side_effect=malformed_solution):
        result = solve(request)
    errors = list(Draft202012Validator(schema("response")).iter_errors(result))
    assert result["status"] == "OPTIMAL", result
    assert result["verification"]["valid"] is True, result
    assert errors, result
    return {
        "injected_solution_property": "unexpected",
        "status": result["status"],
        "verification": result["verification"],
        "response_schema_errors": [error.message for error in errors],
    }


if __name__ == "__main__":
    # 参照 ZIP の pyproject.toml があるディレクトリで実行する。
    text = Path("examples/assignment.json").read_text(encoding="utf-8")
    print(
        json.dumps(
            {
                "import_budget": probe_import_budget(json.loads(text)),
                "output_structure": probe_output_structure(json.loads(text)),
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )
