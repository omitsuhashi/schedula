"""公開する架空教材と編集範囲。"""

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples" / "playground"
PUBLIC_IDS = ("demand", "consecutive_days", "verify")
LESSONS = {
    item["id"]: item
    for item in json.loads((SAMPLES / "lessons.json").read_text(encoding="utf-8"))
    if item["id"] in PUBLIC_IDS
}


def sample(lesson_id):
    return json.loads((SAMPLES / LESSONS[lesson_id]["request_file"]).read_text(encoding="utf-8"))


def same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def validate_public(lesson_id, value):
    """固定条件を維持し、教材画面が編集する値だけを受理する。"""
    expected = sample(lesson_id)
    if lesson_id == "verify":
        solution = json.loads(
            (SAMPLES / LESSONS[lesson_id]["solution_file"]).read_text(encoding="utf-8")
        )
        for employee in ("alice", "bob", None):
            edited = copy.deepcopy(solution)
            kitchen = next(item for item in edited["assignments"] if item["role_id"] == "kitchen")
            edited["assignments"] = [
                item for item in edited["assignments"] if item["role_id"] != "kitchen"
            ]
            if employee:
                kitchen["employee_id"] = employee
                edited["assignments"].insert(0, kitchen)
            if same(value, {"request": expected, "solution": edited}):
                return
        raise ValueError("公開教材の担当変更だけを指定してください。")

    for definition in LESSONS[lesson_id]["editable_fields"]:
        collection, field = definition["collection"], definition["field"]
        for item_id in definition["ids"]:
            index = next(i for i, item in enumerate(expected[collection]) if item["id"] == item_id)
            edited = value[collection][index][field]
            if "min" in definition:
                if type(edited) is not int or not definition["min"] <= edited <= definition["max"]:
                    raise ValueError("公開教材の値域を確認してください。")
            else:
                choices = [expected[collection][index][field]]
                choices += [
                    step["changes"][collection][item_id][field]
                    for step in LESSONS[lesson_id]["steps"]
                    if field in step["changes"].get(collection, {}).get(item_id, {})
                ]
                if not any(same(edited, choice) for choice in choices):
                    raise ValueError("公開教材の選択肢だけを指定してください。")
            expected[collection][index][field] = edited
    if not same(value, expected):
        raise ValueError("公開教材の固定条件は変更できません。")
