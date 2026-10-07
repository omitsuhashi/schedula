"""厳密JSON読み取り、探索前のフォーム検証、状態に応じた結果利用の例。"""

import sys
from pathlib import Path
from typing import cast

from shift_schedula import InvalidInput, Request, Response, load_json, solve, validate


def read_form(text: str) -> Request | None:
    try:
        value = load_json(text)
    except InvalidInput as error:
        print(error.diagnostics[0]["code"])
        return None
    checked = validate(value)
    if checked["status"] != "VALID":
        print(checked["status"], checked["diagnostics"])
        return None
    # 静的な型だけでは参照・時刻・baselineの意味を検証できない。
    return cast(Request, value)


def report(request: Request) -> Response:
    result = solve(request, num_workers=1)
    print(result["status"])
    if result["status"] == "PARTIAL":
        print("配置件数", len(result["solution"]["assignments"]))
        print("不足", result["shortage_summary"])
        if result["schema_version"] in {"0.5", "0.6"}:
            print("優先度別不足", result["priority_summary"])
    elif result["status"] == "OPTIMAL" or result["status"] == "FEASIBLE":
        print("配置件数", len(result["solution"]["assignments"]))
    else:
        print(result["diagnostics"])
    if result["schema_version"] == "0.6" and result["continuity_summary"] is not None:
        for employee in result["continuity_summary"]["employees"]:
            print(
                employee["employee_id"], employee["historical_minutes"], employee["planned_minutes"]
            )
    return result


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("examples/partial_assignment.json")
    request = read_form(path.read_text(encoding="utf-8"))
    if request is not None:
        report(request)
