import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def assignment_request(request):
    data = json.loads((ROOT / "examples/assignment.json").read_text(encoding="utf-8"))
    if getattr(request, "param", "0.1") == "0.15":
        data["schema_version"] = "0.15"
    return data


@pytest.fixture
def assignment_request015():
    return json.loads(
        (ROOT / "tests/fixtures/contract-migration/assignment.015.json").read_text(encoding="utf-8")
    )
