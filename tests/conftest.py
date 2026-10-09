import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def assignment_request(request):
    name = "legacy" if getattr(request, "param", "0.15") == "0.1" else "015"
    return json.loads(
        (ROOT / f"tests/fixtures/contract-migration/assignment.{name}.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def legacy_assignment_request():
    return json.loads(
        (ROOT / "tests/fixtures/contract-migration/assignment.legacy.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def assignment_request015():
    return json.loads(
        (ROOT / "tests/fixtures/contract-migration/assignment.015.json").read_text(encoding="utf-8")
    )
