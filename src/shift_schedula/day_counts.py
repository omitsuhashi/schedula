"""勤務開始日と、原勤務区間が占有するローカル暦日を別々に数える。"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta

from .contract import parse_datetime, reject
from .model import minute_datetime

KINDS = {"work_days_bounds", "days_off_bounds"}


def rules(request, active_groups=None):
    return [
        (i, rule)
        for i, rule in enumerate(request["constraints"])
        if rule["type"] in KINDS and (active_groups is None or f"/constraints/{i}" in active_groups)
    ]


def period(rule, grid):
    start, end = (parse_datetime(rule["interval"][key]) for key in ("start", "end"))
    return (
        start,
        end,
        range(
            start.astimezone(grid.timezone).date().toordinal(),
            end.astimezone(grid.timezone).date().toordinal(),
        ),
    )


def validate(request, grid):
    for i, rule in rules(request):
        path = f"/constraints/{i}"
        for field in ("min_days", "max_days"):
            if field in rule and type(rule[field]) is not int:
                reject("INVALID_INTEGER", "日数は整数で指定します。", path + "/" + field)
        if rule.get("min_days", 0) > rule.get("max_days", 10000000):
            reject("INVALID_DAYS_BOUNDS", "日数の下限が上限を超えています。", path)
        start, end = (
            minute_datetime(rule["interval"][key], path + "/interval/" + key)
            for key in ("start", "end")
        )
        if start >= end or any(
            instant.astimezone(grid.timezone).time() != datetime.min.time()
            for instant in (start, end)
        ):
            reject("INVALID_DAY_COUNT_INTERVAL", "評価期間は正の00:00同士の区間にします。", path)
        if end > grid.end:
            reject("INVALID_DAY_COUNT_INTERVAL", "評価期間は計画終了より後へ延ばせません。", path)
        earliest = grid.start
        if request.get("continuity"):
            from .continuity import context_bounds

            earliest = context_bounds(request, grid)[0]
        if start < earliest:
            reject("INCOMPLETE_HISTORY", "評価期間の過去には確認済み実績が必要です。", path)


def occupied_days(segments, start, end, zone):
    # 休憩も原勤務区間に含める。分割間の非勤務は占有しない。
    occupied = set()
    for segment in segments:
        a = max(start, parse_datetime(segment["interval"]["start"]))
        b = min(end, parse_datetime(segment["interval"]["end"]))
        if a < b:
            occupied.update(
                range(
                    a.astimezone(zone).date().toordinal(),
                    (b - timedelta(microseconds=1)).astimezone(zone).date().toordinal() + 1,
                )
            )
    return occupied


def prepare(model, problem, shifts, active_groups=None):
    from .continuity import output_segments

    grid = problem.grid
    candidates = defaultdict(list)
    facts = defaultdict(list)
    for candidate in problem.candidates:
        candidates[candidate.employee_id].append(candidate)
    for fact in problem.continuity:
        facts[fact["employee_id"]].append(fact)
    for i, rule in rules(problem.request, active_groups):
        start, end, days = period(rule, grid)
        for employee in rule["employee_ids"]:
            if rule["type"] == "work_days_bounds":
                # 1人1勤務日の背景条件により、候補選択の和が勤務日数になる。
                value = sum(
                    shifts[c.id] for c in candidates[employee] if c.day.toordinal() in days
                ) + len({d["day"] for d in facts[employee] if d["day"] in days})
            else:
                fixed = set().union(
                    *(
                        occupied_days(
                            output_segments(d["segments"], grid), start, end, grid.timezone
                        )
                        for d in facts[employee]
                    )
                )
                by_day = defaultdict(list)
                for c in candidates[employee]:
                    for day in occupied_days(c.output(grid)["segments"], start, end, grid.timezone):
                        if day not in fixed:
                            by_day[day].append(shifts[c.id])
                occupied = []
                for day, variables in by_day.items():
                    variable = model.new_bool_var(f"occupied_{i}_{employee}_{day}")
                    model.add_max_equality(variable, variables)
                    occupied.append(variable)
                value = len(days) - len(fixed) - sum(occupied)
            if "min_days" in rule:
                model.add(value >= rule["min_days"])
            if "max_days" in rule:
                model.add(value <= rule["max_days"])


def evaluate(request, grid, solution, fail=None, active_groups=None):
    selected_rules = rules(request, active_groups)
    if not selected_rules:
        return None
    # 生入力の実績・解に出ない確定勤務を補い、解の原segmentsを一度だけ数える。
    duties = defaultdict(list)
    returned = {s["committed_shift_id"] for s in solution["shifts"] if "committed_shift_id" in s}
    for shift in solution["shifts"]:
        duties[shift["employee_id"]].append(shift["segments"])
    for row in request.get("continuity", {}).get("employees", []):
        duties[row["employee_id"]].extend(
            d["segments"]
            for d in row["actual_shifts"] + row["committed_shifts"]
            if d["id"] not in returned
        )
    summaries = []
    for i, rule in selected_rules:
        start, end, days = period(rule, grid)
        employees = []
        for employee in rule["employee_ids"]:
            work = {
                parse_datetime(segments[0]["interval"]["start"])
                .astimezone(grid.timezone)
                .date()
                .toordinal()
                for segments in duties[employee]
            }
            occupied = set().union(
                *(occupied_days(s, start, end, grid.timezone) for s in duties[employee])
            )
            counts = {
                "work_days": len(work.intersection(days)),
                "occupied_days": len(occupied),
                "days_off": len(days) - len(occupied),
            }
            employees.append({"employee_id": employee, **counts})
            value = counts["work_days" if rule["type"] == "work_days_bounds" else "days_off"]
            if fail is not None and (
                value < rule.get("min_days", 0) or value > rule.get("max_days", 10000000)
            ):
                fail(
                    "WORK_DAYS_BOUNDS_VIOLATION"
                    if rule["type"] == "work_days_bounds"
                    else "DAYS_OFF_BOUNDS_VIOLATION",
                    "評価期間の日数が必須の上下限に違反しています。",
                    f"/constraints/{i}",
                    [rule["id"], employee],
                    actual_value=value,
                    min_days=rule.get("min_days"),
                    max_days=rule.get("max_days"),
                )
        summaries.append(
            {
                "constraint_id": rule["id"],
                "type": rule["type"],
                "interval": deepcopy(rule["interval"]),
                "min_days": rule.get("min_days"),
                "max_days": rule.get("max_days"),
                "employees": employees,
            }
        )
    return summaries
