"""勤務パターン教材の休日・境界・分類・日群を公開検証で確認する。"""

import copy
import json
from datetime import datetime, timedelta

import pytest

from shift_schedula import solve, verify
from tests.test_playground_scenarios import SAMPLES, scenario_requests

LESSONS = [
    x for x in json.loads((SAMPLES / "lessons.json").read_text()) if x.get("module") == "patterns"
]


def calendar(request, solution):
    start, end = (datetime.fromisoformat(request["planning_window"][k]) for k in ("start", "end"))
    days = []
    while start < end:
        occupied = any(
            datetime.fromisoformat(s["interval"]["start"]) < start + timedelta(days=1)
            and start < datetime.fromisoformat(s["interval"]["end"])
            for shift in solution["shifts"]
            for s in shift["segments"]
        )
        days.append((start.date().isoformat(), occupied))
        start += timedelta(days=1)
    return days


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x["id"])
def test_pattern_lesson_meaning_and_public_verification(lesson):
    baseline = json.loads((SAMPLES / lesson["request_file"]).read_text())
    saved = copy.deepcopy(baseline)
    for step, request in scenario_requests(lesson, baseline):
        before = copy.deepcopy(request)
        result = solve(request, num_workers=1)
        assert request == before
        assert result["status"] == step["expected"]["status"]
        if not result["solution"]:
            assert result["shortage_summary"] is None
            if step["id"] == "margin":
                d = next(d for d in result["diagnostics"] if d["code"] == "INCOMPLETE_HISTORY")
                assert {f["name"] for f in d["facts"]} >= {"required_start", "required_end"}
            continue
        checked = verify(request, result["solution"])
        assert checked["verification"]["valid"]
        assert result["shortage_summary"]["proven_minimal"]
        assert not checked["shortage_summary"]["proven_minimal"]
        assert (
            result["shortage_summary"]["total_person_minutes"]
            == step["expected"]["total_person_minutes"]
        )
        days = calendar(request, result["solution"])
        rule = request["constraints"][0]
        first, last = (rule["evaluation_period"][k][:10] for k in ("start", "end"))
        if lesson["id"] == "consecutive_days_off":
            off = sum(not work for day, work in days if first <= day < last)
            assert off == step["expected"]["off_days"] >= request["constraints"][1]["min_days"]
            runs = []
            for day, work in days:
                if work:
                    continue
                if runs and datetime.fromisoformat(runs[-1][-1]) + timedelta(
                    days=1
                ) == datetime.fromisoformat(day):
                    runs[-1].append(day)
                else:
                    runs.append([day])
            crossing = [r for r in runs if r[0] < last and first <= r[-1]]
            assert all(len(r) >= rule["min_days"] for r in crossing)
            assert (min(map(len, crossing)) if crossing else None) == step["expected"][
                "shortest_run"
            ]
        elif lesson["id"] == "rest_after_shift":
            origin = request["shift_candidates"][0]["segments"][0]
            duration = (
                datetime.fromisoformat(origin["interval"]["end"])
                - datetime.fromisoformat(origin["interval"]["start"])
            ).total_seconds() / 60 - 30
            assert duration == (90 if step["id"] == "midnight" else 450)
            assert (duration >= request["shift_categories"][0]["min_overlap_minutes"]) == bool(
                step["expected"]["classified_candidates"]
            )
            if step["expected"]["earliest_next"]:
                for shift in result["solution"]["shifts"]:
                    if shift["segments"][0]["interval"]["start"] == origin["interval"]["start"]:
                        continue
                    assert datetime.fromisoformat(
                        shift["segments"][0]["interval"]["start"]
                    ) >= datetime.fromisoformat(step["expected"]["earliest_next"])
        elif lesson["id"] == "forbidden_successions":
            forbidden = (
                rule["day_offset"] == 2
                and request["shift_categories"][1]["min_overlap_minutes"] <= 60
            )
            assert int(forbidden) == step["expected"]["candidate_pairs"]
            assert len(result["solution"]["shifts"]) == (2 if forbidden else 3)
            # 中間勤務があっても2日差の早番を採用しない。個人名・配列順は固定しない。
            starts = {
                s["segments"][0]["interval"]["start"][:10] for s in result["solution"]["shifts"]
            }
            assert {"2026-10-05", "2026-10-06"} <= starts
            assert ("2026-10-07" in starts) != forbidden
        else:
            occupied = {day for day, work in days if work}
            touched = [occupied.intersection(g["dates"]) for g in rule["date_groups"]]
            assert (
                sum(bool(g) for g in touched)
                == step["expected"]["worked_groups"]
                <= rule["max_groups"]
            )
            assert sum(map(len, touched)) == step["expected"]["group_days"]
        if step["id"] == "restored":
            assert request == baseline
    assert baseline == saved


def test_overlapping_group_dates_are_rejected_without_normalization():
    request = json.loads((SAMPLES / "worked-date-groups.json").read_text())
    request["constraints"][0]["date_groups"][1]["dates"].append("2026-10-11")
    before = copy.deepcopy(request)
    result = solve(request)
    assert result["status"] == "INVALID_INPUT" and result["solution"] is None
    assert request == before
