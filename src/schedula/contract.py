import json
import math
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.resources import files
from itertools import islice

from jsonschema import Draft202012Validator, FormatChecker


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


def get_schema(kind):
    if kind not in {"request", "response"}:
        raise ValueError("request または response を指定します。")
    return json.loads(
        files("schedula").joinpath(f"schemas/0.1/{kind}.schema.json").read_text(encoding="utf-8")
    )


@lru_cache
def _validator(kind):
    schema = get_schema("response" if kind == "solution" else kind)
    if kind == "solution":
        schema = {"$ref": "#/$defs/solution", "$defs": schema["$defs"]}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=_FORMATS)


def schema_errors(kind, value):
    return [
        diagnostic("SCHEMA_VIOLATION", error.message, pointer(error.absolute_path))
        for error in islice(_validator(kind).iter_errors(value), 100)
    ]


def validate_request(request):
    try:
        check_json(request)
    except RecursionError:
        reject("NON_JSON_VALUE", "入力の階層が深すぎます。")
    errors = schema_errors("request", request)
    if errors:
        raise InvalidInput(errors)
