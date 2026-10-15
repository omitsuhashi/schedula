import base64
import copy
import hashlib
import json
import re
import subprocess
from urllib.parse import urljoin, urlsplit

import pytest

from web import handler
from web.build import BASE, DOCS, build
from web.lessons import LESSONS, PUBLIC_IDS, SAMPLES, sample, validate_public


def event(lesson_id="demand", value=None):
    value = sample(lesson_id) if value is None else value
    body = json.dumps(value, ensure_ascii=False)
    host = "example.lambda-url.ap-northeast-1.on.aws"
    return {
        "rawPath": handler.PREFIX + ("verify-json" if lesson_id == "verify" else "solve-json"),
        "requestContext": {"http": {"method": "POST"}, "domainName": host},
        "headers": {
            "host": host,
            "origin": "https://the3.co.jp",
            "content-type": "application/json",
            "x-demo-lesson": lesson_id,
            "x-amz-content-sha256": hashlib.sha256(body.encode()).hexdigest(),
        },
        "body": body,
    }


def invoke(lesson_id, value):
    result = handler.lambda_handler(event(lesson_id, value), None)
    assert result["statusCode"] == 200, result
    assert result["headers"]["Cache-Control"] == "no-store"
    return json.loads(result["body"])


def verify_input(employee="alice"):
    solution = json.loads((SAMPLES / "manual-verify.solution.json").read_text())
    kitchen = solution["assignments"].pop(0)
    assert kitchen["role_id"] == "kitchen"
    if employee:
        kitchen["employee_id"] = employee
        solution["assignments"].insert(0, kitchen)
    return {"request": sample("verify"), "solution": solution}


def test_public_lessons_execute_and_keep_shortages_and_verification():
    request = sample("demand")
    assert invoke("demand", request)["status"] == "OPTIMAL"
    for item in request["demand"]:
        if item["id"] in {"hall_2", "hall_3"}:
            item["required_people"] = 4
    result = invoke("demand", request)
    assert result["status"] == "PARTIAL"
    assert result["shortage_summary"]["total_person_minutes"] == 60
    assert result["verification"]["valid"]
    request = sample("consecutive_days")
    request["constraints"][0]["limit_days"] = 3
    assert invoke("consecutive_days", request)["verification"]["valid"]
    for employee, status in (("alice", "VALID"), ("bob", "INVALID_PLAN"), (None, "PARTIAL")):
        assert invoke("verify", verify_input(employee))["status"] == status


def test_registered_edits_accept_bounds_but_reject_fixed_values():
    for limit in (1, 7):
        request = sample("consecutive_days")
        request["constraints"][0]["limit_days"] = limit
        for step in LESSONS["consecutive_days"]["steps"]:
            for collection, changes in step["changes"].items():
                if collection == "employees":
                    for item in request[collection]:
                        item.update(copy.deepcopy(changes.get(item["id"], {})))
        validate_public("consecutive_days", request)
    for value in (-1, 7, True, "4"):
        request = sample("demand")
        next(item for item in request["demand"] if item["id"] == "hall_2")["required_people"] = (
            value
        )
        with pytest.raises(ValueError):
            validate_public("demand", request)
    for field, value in (("schema_version", "0.1"), ("solver", {"time_limit_seconds": 600})):
        request = sample("demand")
        request[field] = value
        with pytest.raises(ValueError):
            validate_public("demand", request)
    value = verify_input()
    value["solution"]["shifts"] = []
    with pytest.raises(ValueError):
        validate_public("verify", value)


@pytest.mark.parametrize(
    ("target", "key", "value", "status"),
    [
        ("event", "rawPath", "/products/schedula/api/adapter/run", 404),
        ("http", "method", "GET", 405),
        ("headers", "origin", "https://schedula.the3.co.jp", 403),
        ("headers", "host", "the3.co.jp", 403),
        ("headers", "content-type", "text/plain", 415),
        ("headers", "x-demo-lesson", "large", 400),
        ("headers", "x-amz-content-sha256", "invalid", 400),
    ],
)
def test_boundary_rejects_without_spawning(monkeypatch, target, key, value, status):
    def forbidden(*args, **kwargs):
        pytest.fail("拒否した入力を実行してはいけない")

    monkeypatch.setattr(subprocess, "run", forbidden)
    incoming = event()
    selected = {"event": incoming, "http": incoming["requestContext"]["http"]}
    selected["headers"] = incoming["headers"]
    selected[target][key] = value
    assert handler.lambda_handler(incoming, None)["statusCode"] == status


def test_strict_json_size_and_base64(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("不正JSONを実行しない"))
    for body in ('{"duplicate":1,"duplicate":2}', '{"number":NaN}', '{"array":['):
        incoming = event()
        incoming["body"] = body
        incoming["headers"]["x-amz-content-sha256"] = hashlib.sha256(body.encode()).hexdigest()
        assert handler.lambda_handler(incoming, None)["statusCode"] == 400
    incoming = event()
    incoming["body"] = "a" * (handler.MAX_BODY + 1)
    assert handler.lambda_handler(incoming, None)["statusCode"] == 413
    incoming["isBase64Encoded"] = True
    incoming["body"] = "!!!"
    assert handler.lambda_handler(incoming, None)["statusCode"] == 400


def test_base64_and_deadline_do_not_poison_next_call(monkeypatch):
    incoming = event()
    incoming["body"] = base64.b64encode(incoming["body"].encode()).decode()
    incoming["isBase64Encoded"] = True
    with monkeypatch.context() as patch:
        patch.setattr(handler, "WORKER_TIMEOUT", 0.000001)
        result = handler.lambda_handler(incoming, None)
        assert result["statusCode"] == 504
        assert json.loads(result["body"])["error"]["code"] == "DEADLINE_EXCEEDED"
    assert handler.lambda_handler(incoming, None)["statusCode"] == 200


def test_public_build_is_allowlisted_and_prefixes_all_links(tmp_path):
    product = build(tmp_path)
    files = {p.relative_to(product).as_posix() for p in product.rglob("*") if p.is_file()}
    assert {"demo/index.html", "docs/index.html", "license.txt"} <= files
    assert not any("reference" in f or "100-30" in f or "adapter" in f for f in files)
    lessons = json.loads((product / "demo/samples/lessons.json").read_text())
    assert {item["id"] for item in lessons} == set(PUBLIC_IDS)
    html = (product / "demo/index.html").read_text()
    assert 'data-public-demo="true"' in html
    for removed in ("adapter-demo", "json-demo", 'id="editor"', "#shift_count_balance"):
        assert removed not in html
    from tests.test_landing_page import PageLinks

    for name in ("demo/index.html", "docs/index.html"):
        content = (product / name).read_text()
        for link in PageLinks(content).links:
            if link.startswith("/"):
                assert link.startswith(BASE), link
                target = link.split("#")[0]
                if target == BASE:
                    continue  # 紹介ページは会社の成果物が所有する。
                path = tmp_path / target.lstrip("/")
                assert (path / "index.html").is_file() if target.endswith("/") else path.is_file()
    with pytest.raises(ValueError):
        build(tmp_path)


def test_public_documents_link_only_to_emitted_files(tmp_path):
    product = build(tmp_path)
    for name in DOCS:
        document = product / "docs" / f"{name}.md"
        content = document.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", content):
            target = urlsplit(urljoin(f"{BASE}docs/{name}.md", link))
            if target.scheme or target.netloc:
                continue
            assert target.path.startswith(BASE), (name, link)
            assert (tmp_path / target.path.lstrip("/")).is_file(), (name, link)

    setup = (product / "docs/python-setup.md").read_text(encoding="utf-8")
    api = (product / "docs/python-api.md").read_text(encoding="utf-8")
    distribution = (product / "docs/distribution.md").read_text(encoding="utf-8")
    assert "[現行契約](io-contract-current.md)" in api
    assert "[LICENSE](../license.txt)" in distribution
    assert "担当配置の手順（ソース配布内の `assignment.md`）" in setup
    assert "README（ソース配布内の `../README.md`）" in setup
    assert "実行例（ソース配布内の `../examples/typed_api.py`）" in api
