"""更新単位を持つJSON入力候補を、一つの既存Requestへ組み立てる。"""

import copy
import hashlib
import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from .contract import InvalidInput, check_json, diagnostic, get_schema, pointer
from .engine import validate

SECTIONS = {
    "basic": {"skills", "roles", "employees"},
    "common": {"constraints"},
    "period": {
        "request_id",
        "problem_type",
        "planning_window",
        "employees",
        "demand",
        "shift_candidates",
        "shift_templates",
        "constraints",
        "preferences",
        "shift_categories",
    },
    "history": {"employees", "continuity"},
    "replanning": {"baseline", "fixed_parts", "replan_mode"},
    "execution": {
        "objectives",
        "solver",
        "fairness",
        "costs",
        "duty_balance",
        "shift_count_balance",
        "diagnosis",
    },
}
EMPLOYEE_FIELDS = {
    "basic": {"id", "label", "skills"},
    "period": {"id", "availability"},
    "history": {"id", "history"},
}


def canonical_json(value):
    check_json(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def get_adapter_schema(kind):
    if kind not in {"draft", "manifest", "record"}:
        raise ValueError("draft、manifest、recordを指定します。")
    return json.loads(
        files("shift_schedula")
        .joinpath(f"schemas/adapter/{kind}.schema.json")
        .read_text(encoding="utf-8")
    )


def check_adapter(kind, value):
    check_json(value)
    errors = list(
        Draft202012Validator(get_adapter_schema(kind), format_checker=FormatChecker()).iter_errors(
            value
        )
    )
    if errors:
        raise InvalidInput(
            [
                diagnostic("ADAPTER_SCHEMA_VIOLATION", e.message, pointer(e.absolute_path))
                for e in errors[:100]
            ]
        )


def dated(value):
    if isinstance(value, dict):
        return any(
            k in {"start", "end", "dates", "date_groups", "evaluation_period", "interval"}
            or dated(v)
            for k, v in value.items()
        )
    return isinstance(value, list) and any(dated(v) for v in value)


def _window(draft):
    return next(
        (s["data"]["planning_window"] for s in draft["sources"] if "planning_window" in s["data"]),
        None,
    )


def _applicability(draft, source):
    section = source["section"]
    if section == "history":
        continuity = next(
            (s["data"].get("continuity") for s in draft["sources"] if s["data"].get("continuity")),
            None,
        )
        return continuity.get("context_window") if continuity else _window(draft)
    if section in {"period", "replanning", "imported"} or (
        section == "execution" and dated(source["data"])
    ):
        return _window(draft)
    return None


def _items(value):
    return value if isinstance(value, list) else []


def _dependencies(draft, source):
    references = set()
    names = {
        "employee_id": "employees",
        "employee_ids": "employees",
        "coworker_ids": "employees",
        "skill_id": "skills",
        "role_id": "roles",
        "category_id": "shift_categories",
        "from_category_id": "shift_categories",
        "to_category_id": "shift_categories",
    }

    def scan(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in names:
                    for item in v if isinstance(v, list) else [v]:
                        if isinstance(item, str):
                            references.add((names[k], item))
                scan(v)
        elif isinstance(value, list):
            for item in value:
                scan(item)

    scan(source["data"])
    references.update(
        ("employees", e["id"])
        for e in _items(source["data"].get("employees", []))
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    )
    result = []
    for collection, item_id in sorted(references):
        owners = []
        for other in draft["sources"]:
            for item in _items(other["data"].get(collection, [])):
                if not isinstance(item, dict) or item.get("id") != item_id:
                    continue
                if collection == "employees":
                    if other["section"] not in {"basic", "imported"}:
                        continue
                    keys = (
                        {"id", "skills"} if source["section"] in {"period", "imported"} else {"id"}
                    )
                elif collection == "roles":
                    keys = {"id", "required_skills"}
                elif collection == "skills":
                    keys = {"id"}
                else:
                    keys = item.keys()
                owners.append(
                    {"source_id": other["id"], "value": {k: item[k] for k in keys if k in item}}
                )
        result.append({"collection": collection, "id": item_id, "owners": owners})
    return result


def _confirmation_digest(draft, source):
    return content_hash(
        {
            "schema_version": draft["schema_version"],
            "source": {k: v for k, v in source.items() if k != "confirmation"},
            "applicability": _applicability(draft, source),
            "dependencies": _dependencies(draft, source),
            "overrides": [
                v
                for v in draft["overrides"]
                if source["id"] in {v["source_id"], v["target_source_id"]}
            ],
            "order": draft["order"] if "constraints" in source["data"] else {},
        }
    )


def confirmation_state(draft):
    check_adapter("draft", draft)
    return [
        {
            "source_id": s["id"],
            "digest": _confirmation_digest(draft, s),
            "saved_digest": s["confirmation"]["digest"] if s["confirmation"] else None,
            "state": "unconfirmed"
            if s["confirmation"] is None
            else "confirmed"
            if s["confirmation"]["digest"] == _confirmation_digest(draft, s)
            else "stale",
        }
        for s in draft["sources"]
    ]


def confirm_source(draft, source_id):
    check_adapter("draft", draft)
    result = copy.deepcopy(draft)
    matches = [s for s in result["sources"] if s["id"] == source_id]
    if len(matches) != 1:
        raise InvalidInput(
            [diagnostic("UNKNOWN_SOURCE", "確認対象を一意に指定します。", related_ids=[source_id])]
        )
    source = matches[0]
    source["confirmation"] = {
        "digest": _confirmation_digest(result, source),
        "provenance": "declared",
    }
    return result


def _blank(version):
    return {
        "adapter_version": "1.0",
        "schema_version": version,
        "sources": [],
        "unresolved": [],
        "assumptions": [],
        "overrides": [],
        "order": {},
    }


def _source(section, data, origin="declared"):
    return {
        "id": section,
        "revision": "1",
        "section": section,
        "origin": origin,
        "data": data,
        "references": [],
        "applies_to": None,
        "confirmation": None,
    }


def import_request(request):
    checked = validate(request)
    if checked["status"] != "VALID":
        raise InvalidInput(checked["diagnostics"])
    draft = _blank(request["schema_version"])
    draft["sources"] = [_source("imported", copy.deepcopy(request), "unknown")]
    source = draft["sources"][0]
    source["applies_to"] = copy.deepcopy(request["planning_window"])
    source["confirmation"] = {
        "digest": _confirmation_digest(draft, source),
        "provenance": "unknown",
    }
    return draft


def split_request(request):
    import_request(request)  # 同じ既存validateを使い、原入力を変更しない。
    draft = _blank(request["schema_version"])
    parts = {section: {} for section in SECTIONS}
    for key, value in request.items():
        if key == "schema_version":
            continue
        if key == "employees":
            for section, fields in EMPLOYEE_FIELDS.items():
                records = [
                    {k: copy.deepcopy(v) for k, v in e.items() if k in fields} for e in value
                ]
                if any(len(e) > 1 for e in records):
                    parts[section][key] = records
        elif key == "constraints":
            for section, temporal in (("common", False), ("period", True)):
                records = [copy.deepcopy(c) for c in value if dated(c) == temporal]
                if records or (not value and section == "common"):
                    parts[section][key] = records
            draft["order"]["constraints"] = [c["id"] for c in value]
        else:
            section = next(s for s, keys in SECTIONS.items() if key in keys)
            parts[section][key] = copy.deepcopy(value)
    draft["sources"] = [_source(s, data) for s, data in parts.items() if data]
    for source in draft["sources"]:
        source["applies_to"] = copy.deepcopy(_applicability(draft, source))
    return draft


def _locations(source, path):
    return {
        "source_id": source["id"],
        "revision": source["revision"],
        "section": source["section"],
        "json_pointer": "/data" + path,
    }


def diagnostic_sources(item, provenance):
    path = item["json_pointer"]
    locations = []
    while True:
        locations = provenance.get(path, [])
        if locations or not path:
            break
        path = path.rsplit("/", 1)[0]
    suffix = item["json_pointer"][len(path) :]
    return {
        **item,
        "sources": [{**loc, "json_pointer": loc["json_pointer"] + suffix} for loc in locations],
    }


def assemble(draft):
    result = {
        "status": "INVALID_INPUT",
        "request": None,
        "provenance": {},
        "diagnostics": [],
        "confirmations": [],
    }
    try:
        check_adapter("draft", draft)
        result["confirmations"] = confirmation_state(draft)
        errors = result["diagnostics"]
        provenance = result["provenance"]
        request = {"schema_version": draft["schema_version"]}
        ids = set()
        employees, employee_origins, rules, rule_origins = {}, {}, [], []
        fields = get_schema("request", draft["schema_version"])["properties"]

        def fail(code, message, path, locations=(), related=()):
            errors.append({**diagnostic(code, message, path, related), "sources": list(locations)})

        def own(path, value, location, target, key):
            if path in provenance:
                fail(
                    "OWNERSHIP_CONFLICT",
                    "項目の所有元が競合しています。",
                    path,
                    [*provenance[path], location],
                )
            else:
                target[key] = copy.deepcopy(value)
                provenance[path] = [location]

        for source, state in zip(draft["sources"], result["confirmations"], strict=True):
            if source["id"] in ids:
                fail("DUPLICATE_SOURCE", "入力元IDが重複しています。", "", related=[source["id"]])
            ids.add(source["id"])
            if state["state"] != "confirmed":
                fail(
                    "UNCONFIRMED_SOURCE",
                    "値・改訂・期間・参照情報の確認が必要です。",
                    "",
                    [_locations(source, "")],
                    [source["id"]],
                )
            expected = _applicability(draft, source)
            if expected != source["applies_to"]:
                fail(
                    "STALE_APPLICABILITY",
                    "適用期間を明示更新して確認します。",
                    "",
                    [_locations(source, "")],
                    [source["id"]],
                )
            section = source["section"]
            allowed = fields if section == "imported" else SECTIONS[section]
            for key, value in source["data"].items():
                path = pointer([key])
                location = _locations(source, path)
                if key not in allowed or key not in fields:
                    fail(
                        "FIELD_OWNER_MISMATCH",
                        "この入力元では項目を所有できません。",
                        path,
                        [location],
                    )
                    continue
                if key == "schema_version":
                    if value != draft["schema_version"]:
                        fail(
                            "SCHEMA_VERSION_MISMATCH",
                            "実行契約版が一致しません。",
                            path,
                            [location],
                        )
                elif key == "employees" and section != "imported":
                    if not isinstance(value, list):
                        fail("INVALID_EMPLOYEES", "従業員は配列で指定します。", path, [location])
                        continue
                    seen = set()
                    for index, employee in enumerate(value):
                        ep = f"{path}/{index}"
                        loc = _locations(source, ep)
                        if not isinstance(employee, dict) or not isinstance(
                            employee.get("id"), str
                        ):
                            fail("INVALID_EMPLOYEE", "従業員IDが必要です。", ep, [loc])
                            continue
                        eid = employee["id"]
                        if eid in seen:
                            fail(
                                "DUPLICATE_ID",
                                "入力元内の従業員IDが重複しています。",
                                ep,
                                [loc],
                                [eid],
                            )
                        seen.add(eid)
                        if section == "basic":
                            if eid in employees:
                                fail(
                                    "DUPLICATE_ID",
                                    "基本情報の従業員IDが重複しています。",
                                    ep,
                                    [employee_origins[eid], loc],
                                    [eid],
                                )
                            else:
                                employees[eid] = {"id": eid}
                                employee_origins[eid] = loc
                        for field in employee:
                            if field not in EMPLOYEE_FIELDS[section]:
                                fail(
                                    "FIELD_OWNER_MISMATCH",
                                    "従業員項目の所有区分を確認します。",
                                    ep + "/" + field,
                                    [loc],
                                )
                elif key == "constraints" and section != "imported":
                    if not isinstance(value, list):
                        fail("INVALID_CONSTRAINTS", "ルールは配列で指定します。", path, [location])
                        continue
                    for index, rule in enumerate(value):
                        loc = _locations(source, f"/constraints/{index}")
                        if section == "common" and dated(rule):
                            fail(
                                "DATED_COMMON_RULE",
                                "日付付きルールは今回の条件に置きます。",
                                path,
                                [loc],
                            )
                        rules.append(copy.deepcopy(rule))
                        rule_origins.append((source, loc))
                else:
                    own(path, value, location, request, key)
        # 基本情報の順序でID結合し、入力元順や社員配列の並べ替えに依存しない。
        for source in draft["sources"]:
            if source["section"] not in EMPLOYEE_FIELDS:
                continue
            for index, e in enumerate(_items(source["data"].get("employees", []))):
                if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                    continue
                eid = e["id"]
                if eid not in employees:
                    fail(
                        "UNKNOWN_REFERENCE",
                        "基本情報に従業員がありません。",
                        "/employees",
                        [_locations(source, f"/employees/{index}")],
                        [eid],
                    )
                    continue
                position = list(employees).index(eid)
                ep = f"/employees/{position}"
                provenance.setdefault(ep, []).append(_locations(source, f"/employees/{index}"))
                for key, value in e.items():
                    if key != "id":
                        own(
                            ep + "/" + key,
                            value,
                            _locations(source, f"/employees/{index}/{key}"),
                            employees[eid],
                            key,
                        )
        if employees:
            own(
                "/employees",
                list(employees.values()),
                employee_origins[next(iter(employees))],
                request,
                "employees",
            )
        if rules or any(
            "constraints" in s["data"] and s["section"] != "imported" for s in draft["sources"]
        ):
            for change in draft["overrides"]:
                positions = [
                    i
                    for i, r in enumerate(rules)
                    if isinstance(r, dict) and r.get("id") == change["constraint_id"]
                ]
                old = [
                    i
                    for i in positions
                    if rule_origins[i][0]["id"] == change["target_source_id"]
                    and rule_origins[i][0]["section"] == "common"
                ]
                new = [
                    i
                    for i in positions
                    if rule_origins[i][0]["id"] == change["source_id"]
                    and rule_origins[i][0]["section"] == "period"
                ]
                if len(old) != 1 or len(new) != 1 or rules[old[0]] != change["before"]:
                    fail(
                        "INVALID_OVERRIDE",
                        "置換元・変更前・変更後を一意に照合できません。",
                        "/constraints",
                        [rule_origins[i][1] for i in positions],
                    )
                else:
                    rules.pop(old[0])
                    rule_origins.pop(old[0])
            order = draft["order"].get("constraints")
            if order is not None:
                rule_ids = [r.get("id") if isinstance(r, dict) else None for r in rules]
                if len(rule_ids) != len(order) or set(rule_ids) != set(order):
                    fail("ARRAY_ORDER_MISMATCH", "ルールの全IDを順序に明示します。", "/constraints")
                else:
                    combined = {r["id"]: (r, o) for r, o in zip(rules, rule_origins, strict=True)}
                    rules = [combined[i][0] for i in order]
                    rule_origins = [combined[i][1] for i in order]
            own(
                "/constraints",
                rules,
                {
                    "source_id": "draft",
                    "revision": "1",
                    "section": "common",
                    "json_pointer": "/order/constraints",
                },
                request,
                "constraints",
            )
            for i, (_, loc) in enumerate(rule_origins):
                provenance[f"/constraints/{i}"] = [loc]
        elif draft["overrides"]:
            fail("INVALID_OVERRIDE", "置換対象のルールがありません。", "/constraints")
        for unresolved in draft["unresolved"]:
            fail(
                "UNRESOLVED_INPUT",
                unresolved["message"],
                unresolved["json_pointer"],
                related=[unresolved["source_id"]],
            )
        if errors:
            return result
        checked = validate(request)
        result["status"] = checked["status"]
        result["diagnostics"] = [diagnostic_sources(d, provenance) for d in checked["diagnostics"]]
        if checked["status"] == "VALID":
            result["request"] = request
    except InvalidInput as error:
        result["diagnostics"] = error.diagnostics
    except TypeError, ValueError, KeyError, RecursionError:
        result["diagnostics"] = [
            diagnostic("ADAPTER_INVALID_DATA", "入力元の型と参照を確認します。")
        ]
    return result
