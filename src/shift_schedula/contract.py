import json
import math
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.resources import files
from itertools import islice

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSIONS = ("0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11")


def schema_version_of(value):
    version = value.get("schema_version") if isinstance(value, dict) else None
    return version if version in SCHEMA_VERSIONS else "0.1"


def diagnostic(code, message, pointer="", related_ids=(), **facts):
    return {
        "code": code,
        "message": message[:400],
        "json_pointer": pointer,
        "related_ids": list(related_ids),
        "facts": [{"name": key, "value": value} for key, value in facts.items()],
    }


class InvalidInput(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(diagnostics[0]["message"])


def reject(code, message, pointer="", related_ids=(), **facts):
    raise InvalidInput([diagnostic(code, message, pointer, related_ids, **facts)])


def pointer(parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def check_json(value, path=(), ancestors=None):
    """dict の入口でも JSON の型・有限数・非循環構造を確認する。"""
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            reject("NON_FINITE_NUMBER", "非有限数は受理できません。", pointer(path))
        return
    if not isinstance(value, dict | list):
        reject("NON_JSON_VALUE", "JSON で表現できない値です。", pointer(path))
    ancestors = set() if ancestors is None else ancestors
    if id(value) in ancestors:
        reject("NON_JSON_VALUE", "循環する入力は受理できません。", pointer(path))
    ancestors.add(id(value))
    children = value.items() if isinstance(value, dict) else enumerate(value)
    for key, item in children:
        if isinstance(value, dict) and not isinstance(key, str):
            reject("NON_JSON_VALUE", "JSON のキーは文字列で指定します。", pointer(path))
        check_json(item, (*path, key), ancestors)
    ancestors.remove(id(value))


def load_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                reject("DUPLICATE_JSON_KEY", "JSON キーが重複しています。", related_ids=[key])
            result[key] = value
        return result

    def constant(_):
        reject("NON_FINITE_NUMBER", "非有限数は受理できません。")

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        check_json(result)
        return result
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, InvalidInput):
            raise
        reject("INVALID_JSON", "UTF-8 JSON を読み取れません。")


_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


def parse_datetime(value):
    if not _DATETIME.fullmatch(value) or value.endswith("-00:00"):
        raise ValueError("日時には既知のオフセットが必要です。")
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(UTC)


_FORMATS = FormatChecker()


@_FORMATS.checks("date-time", raises=(ValueError, OverflowError))
def _date_time(value):
    if not isinstance(value, str):
        return True
    parse_datetime(value)
    return True


@_FORMATS.checks("date", raises=ValueError)
def _date(value):
    if not isinstance(value, str):
        return True
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))


def get_schema(kind, schema_version="0.1"):
    if kind not in {"request", "response", "solution", "verification"}:
        raise ValueError("request、response、solution、verification を指定します。")
    if schema_version not in SCHEMA_VERSIONS:
        raise ValueError("schema_version は 0.1〜0.11 のいずれかを指定します。")
    if kind in {"solution", "verification"}:
        if kind == "solution":
            schema = get_schema("response", schema_version)
            return {
                "$schema": schema["$schema"],
                "$id": f"urn:schedula:solution:{schema_version}",
                "$ref": "#/$defs/solution",
                "$defs": schema["$defs"],
            }
        # 旧版にも同じ検証入口を提供し、配布済みの定義を再利用する。
        schema = get_schema(
            "response",
            schema_version
            if schema_version in {"0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}
            else "0.4",
        )
        properties = {
            name: schema["properties"][name]
            for name in (
                "request_id",
                "objectives",
                "diagnostics",
                "verification",
                "stats",
                "fairness_summary",
                "change_summary",
                "shortage_summary",
            )
        }
        if schema_version in {"0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}:
            properties["continuity_summary"] = schema["properties"]["continuity_summary"]
        if schema_version in {"0.9", "0.10", "0.11"}:
            for name in ("cost_summary", "duty_balance_summary"):
                properties[name] = schema["properties"][name]
        if schema_version == "0.11":
            properties["day_count_summary"] = schema["properties"]["day_count_summary"]
        properties.update(
            schema_version={"const": schema_version},
            status={
                "enum": ["VALID", "PARTIAL", "INVALID_INPUT", "INVALID_PLAN", "INTERNAL_ERROR"]
            },
            demand_satisfied={"type": ["boolean", "null"]},
        )
        if schema_version in {"0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}:
            properties["priority_summary"] = schema["properties"]["priority_summary"]
        properties["objectives"]["items"]["properties"]["proven_optimal"] = {"const": False}
        definitions = {k: v for k, v in schema["$defs"].items() if k != "solution"}
        definitions["shortage_summary"]["properties"]["proven_minimal"] = {"const": False}
        if schema_version in {"0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}:
            definitions["priority_summary"]["properties"]["groups"]["items"]["properties"][
                "proven_minimal"
            ] = {"const": False}
        rules = []
        for statuses, performed, valid, complete in (
            (["VALID"], True, True, True),
            (["PARTIAL"], True, True, False),
            (["INVALID_INPUT", "INTERNAL_ERROR"], False, None, None),
            (["INVALID_PLAN"], True, False, None),
        ):
            expected = {
                "verification": {
                    "properties": {"performed": {"const": performed}, "valid": {"const": valid}}
                },
                "demand_satisfied": {"const": complete},
            }
            if valid:
                expected["shortage_summary"] = {
                    "type": "object",
                    "properties": {
                        "total_person_minutes": {"const": 0} if complete else {"minimum": 1}
                    },
                }
            else:
                expected.update(objectives={"maxItems": 0})
                expected.update(
                    {
                        name: {"type": "null"}
                        for name in ("shortage_summary", "fairness_summary", "change_summary")
                    }
                )
            if schema_version in {"0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}:
                expected["priority_summary"] = {"type": "object" if valid else "null"}
            if schema_version in {"0.6", "0.7", "0.8", "0.9", "0.10", "0.11"} and not valid:
                expected["continuity_summary"] = {"type": "null"}
            if schema_version in {"0.9", "0.10", "0.11"} and not valid:
                expected.update(
                    cost_summary={"type": "null"}, duty_balance_summary={"type": "null"}
                )
            if schema_version == "0.11" and not valid:
                expected["day_count_summary"] = {"type": "null"}
            rules.append(
                {
                    "if": {"properties": {"status": {"enum": statuses}}},
                    "then": {"properties": expected},
                }
            )
        return {
            "$schema": schema["$schema"],
            "$id": f"urn:schedula:verification:{schema_version}",
            "title": f"schedula Verification {schema_version}",
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
            "$defs": definitions,
            "allOf": rules,
        }
    return json.loads(
        files("shift_schedula")
        .joinpath(f"schemas/{schema_version}/{kind}.schema.json")
        .read_text(encoding="utf-8")
    )


@lru_cache
def _validator(kind, schema_version):
    schema = get_schema(kind, schema_version)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=_FORMATS)


def schema_errors(kind, value, schema_version=None):
    if schema_version is None:
        schema_version = schema_version_of(value)
    return [
        diagnostic("SCHEMA_VIOLATION", error.message, pointer(error.absolute_path))
        for error in islice(_validator(kind, schema_version).iter_errors(value), 100)
    ]


def validate_request(request):
    try:
        check_json(request)
    except RecursionError:
        reject("NON_JSON_VALUE", "入力の階層が深すぎます。")
    if (
        isinstance(request, dict)
        and request.get("schema_version") in {"0.6", "0.7", "0.8", "0.9", "0.10", "0.11"}
        and isinstance(request.get("continuity"), dict)
    ):
        value = request["continuity"]
        if "context_window" not in value or "employees" not in value:
            reject("INCOMPLETE_HISTORY", "文脈期間と全従業員の履歴が必要です。", "/continuity")
        if isinstance(value["employees"], list):
            for i, row in enumerate(value["employees"]):
                if isinstance(row, dict) and (
                    not {"before_context", "actual_shifts", "committed_shifts"} <= row.keys()
                    or (
                        isinstance(row.get("before_context"), dict)
                        and not {
                            "last_shift_end",
                            "last_work_day",
                            "consecutive_work_days_before_window",
                        }
                        <= row["before_context"].keys()
                    )
                    or row.get("past_complete") is not True
                    or row.get("commitments_complete") is not True
                ):
                    reject(
                        "INCOMPLETE_HISTORY",
                        "履歴・実績・確定勤務と完全性確認が必要です。",
                        f"/continuity/employees/{i}",
                    )
    errors = schema_errors("request", request)
    if errors:
        raise InvalidInput(errors)
