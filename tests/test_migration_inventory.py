import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "docs/migrations/legacy"
pytestmark = pytest.mark.repository


def test_fixed_legacy_artifacts_keep_original_bytes_and_contracts():
    manifest = json.loads((LEGACY / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        raw = (LEGACY / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"], entry["path"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["path"]
    for version, wheel, latest in (
        ("0.1.6", manifest["engine"]["wheel"], "0.15"),
        ("0.1.5", manifest["app"]["wheel"], "0.10"),
    ):
        with zipfile.ZipFile(LEGACY / wheel) as archive:
            metadata = archive.read(f"shift_schedula-{version}.dist-info/METADATA").decode()
            assert f"Version: {version}\n" in metadata
            schema = json.loads(
                archive.read(f"shift_schedula/schemas/{latest}/request.schema.json")
            )
            assert schema["properties"]["schema_version"] == {"const": latest}
            assert "shift_schedula/py.typed" in archive.namelist()
    vendor = json.loads((LEGACY / "app-0.1.5/vendor-manifest.json").read_text())
    assert vendor == manifest["app"]["engine"]
    assert (
        vendor["sha256"]
        == hashlib.sha256((LEGACY / manifest["app"]["wheel"]).read_bytes()).hexdigest()
    )


def test_synthetic_saved_json_and_database_keep_plans_references_and_evidence():
    document = json.loads((LEGACY / "app-0.1.5/representative.json").read_text())
    assert document["format"] == "schedula-app/1"
    assert [p["result"]["status"] for p in document["plans"]] == ["OPTIMAL", "PARTIAL"]
    assert document["selected"] == document["baseline"] == "plan_partial"
    assert (
        json.loads(document["input"])["baseline"]["source_solution"]
        == document["plans"][1]["result"]["solution"]
    )
    database = LEGACY / "app-0.1.5/representative.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
        assert (
            json.loads(db.execute("SELECT engine FROM metadata").fetchone()[0])
            == document["engine"]
        )
        selected, baseline, edit = db.execute(
            "SELECT selected,baseline,edit FROM sessions"
        ).fetchone()
        assert selected == baseline == document["selected"]
        assert json.loads(edit) == document["edit"]
        rows = db.execute("SELECT id,request,result,evidence FROM plans ORDER BY id").fetchall()
        assert len(rows) == 2
        for plan, (identifier, request, result, evidence) in zip(
            document["plans"], rows, strict=True
        ):
            assert identifier == plan["id"]
            assert json.loads(request) == plan["request"]
            current = json.loads(result)
            original = json.loads(evidence)
            assert current["verification"]["valid"] is True
            assert current["solution"] == plan["result"]["solution"]
            assert current["shortage_summary"]["proven_minimal"] is False
            assert all(not o["proven_optimal"] for o in current["objectives"])
            assert original == {k: v for k, v in plan["result"].items() if k != "solution"}
