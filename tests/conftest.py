import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def assignment_request():
    return json.loads((ROOT / "examples/assignment.json").read_text(encoding="utf-8"))
