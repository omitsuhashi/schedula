import json
import logging
from pathlib import Path

from shift_schedula import diagnosis, engine, model, solve, validate, verify

ROOT = Path(__file__).resolve().parents[1]


def test_internal_exception_logging_is_opt_in_and_recorded_once(
    assignment_request, monkeypatch, caplog, capsys
):
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    assignment_request["employees"][0]["label"] = "PRIVATE_EMPLOYEE_SENTINEL"

    def fail(*args):
        raise RuntimeError("injected internal failure")

    with monkeypatch.context() as patch:
        patch.setattr(engine.flow, "run", fail)
        assert solve(assignment_request)["status"] == "INTERNAL_ERROR"
        assert caplog.records == []
        assert capsys.readouterr() == ("", "")
        with caplog.at_level(logging.DEBUG, logger="shift_schedula"):
            assert solve(assignment_request)["status"] == "INTERNAL_ERROR"
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.exc_info and record.exc_info[0] is RuntimeError
        assert "injected internal failure" in caplog.text
        assert "PRIVATE_EMPLOYEE_SENTINEL" not in caplog.text

    with caplog.at_level(logging.DEBUG, logger="shift_schedula"):
        for operation in (
            lambda: validate(assignment_request),
            lambda: verify(assignment_request, {"assignments": [], "shifts": []}),
        ):
            caplog.clear()
            with monkeypatch.context() as patch:
                patch.setattr(model, "normalize", fail)
                patch.setattr(engine, "normalize", fail)
                assert operation()["status"] == "INTERNAL_ERROR"
            assert len(caplog.records) == 1 and caplog.records[0].exc_info
        caplog.clear()
        request = json.loads((ROOT / "examples/diagnosis.json").read_text(encoding="utf-8"))
        with monkeypatch.context() as patch:
            patch.setattr(diagnosis, "conditions", fail)
            result = solve(request)
        assert result["status"] == "INFEASIBLE"
        assert result["diagnosis_result"]["status"] == "ERROR"
        assert len(caplog.records) == 1 and caplog.records[0].name.endswith("diagnosis")
        caplog.clear()
        assert solve({})["status"] == "INVALID_INPUT"
        assignment_request["employees"][0]["availability"] = []
        assert solve(assignment_request)["status"] == "INFEASIBLE"
        assert caplog.records == []
    assert root.handlers == handlers and root.level == level
