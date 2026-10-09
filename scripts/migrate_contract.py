"""旧契約を受理するcheckoutで、一回限りの明示移行と独立再検証を行う。"""

import argparse
import copy
import json
from datetime import timedelta
from importlib.metadata import version

from shift_schedula import InvalidInput, validate, verify
from shift_schedula.adapter import content_hash
from shift_schedula.contract import check_json, diagnostic, parse_datetime, reject
from shift_schedula.model import normalize
from shift_schedula.records import _check_pair, read_json_file, save_json


def _valid(result):
    if result["status"] not in {"VALID", "PARTIAL"}:
        raise InvalidInput(result["diagnostics"])
    return result


def migrate_request(request, *, history_confirmations=None):
    """条件を保って0.15へコピーする。追加の履歴事実はpointerで明示確認する。"""
    _valid(validate(request))
    confirmations = {} if history_confirmations is None else history_confirmations
    check_json(confirmations)
    if not isinstance(confirmations, dict):
        reject("INVALID_CONFIRMATIONS", "履歴確認はpointerと勤務日のobjectで指定します。")
    used = set()

    def convert(source, prefix=""):
        old = normalize(source)
        target = copy.deepcopy(source)
        source_version = source["schema_version"]
        target["schema_version"] = "0.15"
        if source_version in {"0.1", "0.2"}:
            for demand in target["demand"]:
                demand["minimum_people"] = demand["required_people"]
            for option in target.get("diagnosis", {}).get("allowed_changes", []):
                # 旧完全充足の人数編集にだけ同じ下限編集を結び付ける。
                option["edits"].extend(
                    {
                        **edit,
                        "json_pointer": edit["json_pointer"].replace(
                            "/required_people", "/minimum_people"
                        ),
                    }
                    for edit in list(option["edits"])
                    if edit["json_pointer"].startswith("/demand/")
                    and edit["json_pointer"].endswith("/required_people")
                )
        if source_version == "0.1":
            for i, employee in enumerate(target["employees"]):
                history = employee.get("history")
                if history is None:
                    continue
                path = f"{prefix}/employees/{i}/history/last_work_day"
                if history["last_shift_end"] is None:
                    history["last_work_day"] = None
                    continue
                if path not in confirmations:
                    reject(
                        "HISTORY_CONFIRMATION_REQUIRED",
                        "最終勤務日を確認してください。",
                        path,
                        [employee["id"]],
                    )
                confirmed = confirmations[path]
                last_day = (
                    (parse_datetime(history["last_shift_end"]) - timedelta(microseconds=1))
                    .astimezone(old.grid.timezone)
                    .date()
                    .isoformat()
                )
                if confirmed != last_day:
                    reject(
                        "HISTORY_SEMANTICS_CHANGED",
                        "旧版の連勤判定と異なる勤務日は自動移行できません。",
                        path,
                        [employee["id"]],
                    )
                history["last_work_day"] = confirmed
                used.add(path)
            if source["problem_type"] == "roster":
                target["shift_candidates"] = [
                    {
                        "id": c["id"],
                        "employee_id": c["employee_id"],
                        "segments": [{"interval": c["interval"], "breaks": c["breaks"]}],
                    }
                    for c in target["shift_candidates"]
                ]
                explicit = {c["id"] for c in target["shift_candidates"]}
                # 0.15のテンプレート式は旧IDを再現しないため、旧展開結果を固定する。
                target["shift_candidates"].extend(
                    {
                        "id": c.id,
                        "employee_id": c.employee_id,
                        "segments": [
                            {
                                "interval": old.grid.output_interval(c.start, c.end),
                                "breaks": [old.grid.output_interval(a, b) for a, b in c.breaks],
                            }
                        ],
                    }
                    for c in old.candidates
                    if c.id not in explicit
                )
                target.pop("shift_templates", None)
        if target.get("baseline"):
            baseline = target["baseline"]
            original = source["baseline"]["source_request"]
            baseline["source_request"] = convert(original, prefix + "/baseline/source_request")
            baseline["source_solution"] = migrate_solution(
                original, baseline["source_request"], baseline["source_solution"]
            )[0]
        _valid(validate(target))
        return target

    target = convert(request)
    if set(confirmations) != used:
        reject("UNUSED_CONFIRMATION", "対象外または不要な履歴確認が含まれています。")
    return target


def migrate_solution(source, target, solution):
    """元期間で旧解を照合し、新しいsummaryだけを独立検証で取得する。"""
    _valid(verify(source, solution))
    plan = copy.deepcopy(solution)
    if source["schema_version"] == "0.1":
        grid = normalize(source).grid
        plan["shifts"] = [
            {
                "candidate_id": s["candidate_id"],
                "employee_id": s["employee_id"],
                "work_day": parse_datetime(s["interval"]["start"])
                .astimezone(grid.timezone)
                .date()
                .isoformat(),
                "segments": [{"interval": s["interval"], "breaks": s["breaks"]}],
            }
            for s in plan["shifts"]
        ]
    return plan, _valid(verify(target, plan))


def migrate(request, *, solution=None, response=None, history_confirmations=None):
    """通常Requestと過去Responseを混同しない移行記録を返す。求解しない。"""
    if solution is not None and response is not None:
        reject("AMBIGUOUS_PLAN", "解またはResponseの一方だけを指定します。")
    target = migrate_request(request, history_confirmations=history_confirmations)
    if response is not None:
        _check_pair(request, response)
        if response["request_id"] != request["request_id"]:
            reject("RESPONSE_MISMATCH", "元RequestとResponseのIDが一致しません。")
        solution = response["solution"]
    plan, checked = (
        (None, None) if solution is None else migrate_solution(request, target, solution)
    )
    suggestions = []
    for item in (
        (response or {}).get("diagnosis_result", {}).get("suggestions", [])
        if (response or {}).get("diagnosis_result")
        else []
    ):
        old = item["modified_request"]
        new = migrate_request(old, history_confirmations=history_confirmations)
        suggestion, verification = migrate_solution(old, new, item["response"]["solution"])
        suggestions.append(
            {
                "option_id": item["option_id"],
                "request": new,
                "solution": suggestion,
                "current_verification": verification,
            }
        )
    return {
        "migration_version": "1.0",
        "engine_version": version("shift-schedula"),
        "source_schema_version": request["schema_version"],
        "target_schema_version": "0.15",
        "source_request_hash": content_hash(request),
        "target_request_hash": content_hash(target),
        "source_solution_hash": content_hash(solution) if solution is not None else None,
        "history_confirmations": copy.deepcopy(history_confirmations or {}),
        "request": target,
        "solution": plan,
        "current_verification": checked,
        "original_response": copy.deepcopy(response),
        "suggestions": suggestions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_file")
    plans = parser.add_mutually_exclusive_group()
    plans.add_argument("--solution")
    plans.add_argument("--response")
    parser.add_argument("--history-confirmations")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    paths = [args.request_file, args.solution, args.response, args.history_confirmations]
    try:
        if paths.count("-") > 1:
            reject("INVALID_MIGRATION_INPUT", "標準入力は一つの入力だけに指定します。")
        inputs = {}
        values = []
        for name, path in zip(
            ("request", "solution", "response", "history_confirmations"), paths, strict=True
        ):
            value = read_json_file(path)[0] if path is not None else None
            if path is not None and not isinstance(value, dict):
                reject("INVALID_MIGRATION_INPUT", "指定した入力はJSON objectにします。", "/" + name)
            values.append(value)
            if path is not None:
                inputs[name] = {"path": str(path), "content_hash": content_hash(value)}
        request, solution, response, confirmations = values
        result = migrate(
            request, solution=solution, response=response, history_confirmations=confirmations
        )
        result["inputs"] = inputs
        save_json(args.output, result, protected=[p for p in paths if p and p != "-"])
        print(json.dumps({"status": "MIGRATED", "output": str(args.output)}))
        return 0
    except (InvalidInput, OSError, UnicodeError) as error:
        diagnostics = (
            error.diagnostics
            if isinstance(error, InvalidInput)
            else [diagnostic("MIGRATION_IO_ERROR", "入力読取または新規出力の保存に失敗しました。")]
        )
        status = (
            "NEEDS_CONFIRMATION"
            if any(
                d["code"] in {"HISTORY_CONFIRMATION_REQUIRED", "HISTORY_SEMANTICS_CHANGED"}
                for d in diagnostics
            )
            else "INVALID_INPUT"
        )
        print(json.dumps({"status": status, "diagnostics": diagnostics}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
