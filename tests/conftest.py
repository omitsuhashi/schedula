import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def assignment_request():
    return json.loads(
        (ROOT / "tests/fixtures/contract-015/assignment.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def assignment_request015(assignment_request):
    return assignment_request
