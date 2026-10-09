from datetime import datetime, timedelta


def stamp(day=0, minute=0):
    return (datetime(2026, 10, 5) + timedelta(days=day, minutes=minute)).isoformat() + "+09:00"


def interval(day=0, start=600, end=690):
    return {"start": stamp(day, start), "end": stamp(day, end)}


def candidate(employee="alice", day=0, start=600, end=690, breaks=(), identifier=None):
    return {
        "id": identifier or f"shift_{employee}_{day}_{start}_{end}",
        "employee_id": employee,
        "interval": interval(day, start, end),
        "breaks": [interval(day, a, b) for a, b in breaks],
    }


def rule(kind, value, employees=("alice",), identifier="cap"):
    field = {"max_role_switches": "limit_count", "max_consecutive_days": "limit_days"}.get(
        kind, "limit_minutes"
    )
    return {"id": identifier, "type": kind, "employee_ids": list(employees), field: value}


def template(
    employees=("alice",), dates=("2026-10-05",), starts=("10:00",), durations=(90,), breaks=()
):
    return {
        "id": "day_shift",
        "employee_ids": list(employees),
        "dates": list(dates),
        "start_times": list(starts),
        "duration_minutes_options": list(durations),
        "break_options": [{"offset_minutes": a, "duration_minutes": b} for a, b in breaks],
    }


def request(days=1, employees=("alice",)):
    return {
        "schema_version": "0.1",
        "request_id": "roster_test",
        "problem_type": "roster",
        "planning_window": {
            "start": stamp(),
            "end": stamp(days),
            "timezone": "Asia/Tokyo",
            "slot_minutes": 30,
        },
        "skills": [],
        "roles": [{"id": r, "label": r, "required_skills": []} for r in ("kitchen", "hall")],
        "employees": [
            {
                "id": e,
                "label": e,
                "skills": [],
                "availability": [interval(d) for d in range(days)],
                "history": {"last_shift_end": None, "consecutive_work_days_before_window": 0},
            }
            for e in employees
        ],
        "demand": [],
        "shift_candidates": [candidate(e, d) for e in employees for d in range(days)],
        "constraints": [],
        "preferences": [],
        "objectives": [{"id": "work", "metric": "scheduled_minutes"}],
        "solver": {"backend": "auto", "time_limit_seconds": 10, "seed": 0},
    }


def demand(day=0, start=600, end=630, role="kitchen", people=1):
    return {
        "id": f"need_{day}_{start}_{role}",
        "role_id": role,
        "interval": interval(day, start, end),
        "required_people": people,
    }


def request015(days=1, employees=("alice",)):
    data = request(days, employees)
    data["schema_version"] = "0.15"
    for employee in data["employees"]:
        employee["history"]["last_work_day"] = None
    data["shift_candidates"] = [
        {
            "id": c["id"],
            "employee_id": c["employee_id"],
            "segments": [{"interval": c["interval"], "breaks": c["breaks"]}],
        }
        for c in data["shift_candidates"]
    ]
    return data
