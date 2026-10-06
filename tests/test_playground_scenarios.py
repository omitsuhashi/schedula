import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from schedula import solve
from schedula.model import normalize
from schedula.verify import verify_solution
from tests.support import assert_response

SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "playground"
BASELINE = json.loads((SAMPLES / "lunch.json").read_text(encoding="utf-8"))
SCENARIOS = json.loads((SAMPLES / "scenarios.json").read_text(encoding="utf-8"))


def scenario_requests(scenario):
    """保存済みの操作を順に適用し、各時点の確定入力を再現する。"""
    request = copy.deepcopy(BASELINE)
    for step in scenario["steps"]:
        if step["restore"]:
            request = copy.deepcopy(BASELINE)
        for collection, changes in step["changes"].items():
            by_id = {item["id"]: item for item in request[collection]}
            for item_id, fields in changes.items():
                by_id[item_id].update(copy.deepcopy(fields))
        yield step, copy.deepcopy(request)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["id"])
def test_playground_scenario(scenario):
    for step, request in scenario_requests(scenario):
        before = copy.deepcopy(request)
        result = solve(request)
        expected = step["expected"]
        assert_response(result, expected["status"])
        assert request == before
        assert result["solver"]["backend"] == "min_cost_flow"
        assert result["objectives"] == []
        if result["solution"] is not None:
            assert verify_solution(normalize(request), result["solution"]) == ([], ())
            slots = sum(
                (
                    datetime.fromisoformat(item["interval"]["end"])
                    - datetime.fromisoformat(item["interval"]["start"])
                ).total_seconds()
                / 1800
                for item in result["solution"]["assignments"]
            )
            assert slots == expected["assigned_slots"]
        else:
            diagnostic = expected["diagnostic"]
            assert any(
                all(item[key] == value for key, value in diagnostic.items())
                for item in result["diagnostics"]
            )
            # 人数総数は足りるが、調理の担当資格が足りない受け入れ例。
            problem = normalize(request)
            slot = next(fact["value"] for fact in diagnostic["facts"] if fact["name"] == "slot")
            assert sum(slot in slots for slots in problem.available.values()) == sum(
                problem.demand[slot].values()
            )
        if scenario["id"] == "absence" and step["id"] == "repaired":
            assert request["employees"][0]["availability"] == []
            assert all(item["employee_id"] != "aoi" for item in result["solution"]["assignments"])
        if step["id"] == "initial" or step["restore"]:
            assert request == BASELINE
