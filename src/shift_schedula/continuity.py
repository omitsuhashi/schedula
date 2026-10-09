"""原区間を保持した実績・確定勤務と計画期間への投影。"""

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timedelta

from .contract import InvalidInput, reject
from .model import ShiftCandidate, minute_datetime, nonoverlapping


def context_bounds(request, grid):
    value = request["continuity"]["context_window"]
    start = minute_datetime(value["start"], "/continuity/context_window/start")
    end = minute_datetime(value["end"], "/continuity/context_window/end")
    if not start <= grid.start < grid.end <= end or any(
        d.astimezone(grid.timezone).time().isoformat() != "00:00:00" for d in (start, end)
    ):
        reject("INVALID_CONTINUITY_INTERVAL", "文脈期間は00:00を両端とし計画を包含します。")
    return start, end


def interval(value, grid, bounds, path, *, aligned=True):
    start = minute_datetime(value["start"], path + "/start")
    end = minute_datetime(value["end"], path + "/end")
    if not bounds[0] <= start < end <= bounds[1]:
        reject("INVALID_CONTINUITY_INTERVAL", "区間は文脈期間内の正の半開区間にします。", path)
    step = timedelta(minutes=grid.slot_minutes)
    if aligned and any(
        grid.start <= d <= grid.end and (d - grid.start) % step for d in (start, end)
    ):
        reject("MISALIGNED_INTERVAL", "計画内の状態遷移は時間粒度に揃えます。", path)
    return start, end


def parse_segments(values, grid, bounds, path, *, aligned=True):
    result = []
    for i, value in enumerate(values):
        p = f"{path}/segments/{i}"
        start, end = interval(value["interval"], grid, bounds, p + "/interval", aligned=aligned)
        rests = tuple(
            sorted(
                interval(b, grid, bounds, f"{p}/breaks/{j}", aligned=aligned)
                for j, b in enumerate(value["breaks"])
            )
        )
        if any(not start < a < b < end for a, b in rests):
            reject("INVALID_BREAK", "休憩は始業・終業に接しない勤務内の区間にします。", p)
        nonoverlapping(rests, p + "/breaks")
        if result and start <= result[-1][1]:
            reject("INVALID_SEGMENT_ORDER", "勤務区間は正の間隔を空け時刻順にします。", p)
        result.append((start, end, rests))
    return tuple(result)


def minutes(segments, start, end):
    def overlap(a, b):
        return max(0, (min(end, b) - max(start, a)) // timedelta(minutes=1))

    return sum(overlap(a, b) - sum(overlap(x, y) for x, y in rests) for a, b, rests in segments)


def covered_slots(segments, grid, *, breaks=False):
    step = timedelta(minutes=grid.slot_minutes)
    spans = (
        [(x, y) for _, _, rests in segments for x, y in rests]
        if breaks
        else [(a, b) for a, b, _ in segments]
    )
    result = {
        slot
        for a, b in spans
        for slot in range(
            max(0, (a - grid.start) // step), min(grid.slots, (b - grid.start) // step)
        )
    }
    return result if breaks else result - covered_slots(segments, grid, breaks=True)


def availability(request, grid):
    bounds = context_bounds(request, grid)
    result = {}
    for i, employee in enumerate(request["employees"]):
        p = f"/employees/{i}/availability"
        intervals = [
            interval(value, grid, bounds, f"{p}/{j}")
            for j, value in enumerate(employee["availability"])
        ]
        nonoverlapping(intervals, p)
        merged = []
        for start, end in sorted(intervals):
            if merged and merged[-1][1] == start:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        result[employee["id"]] = merged
    return result


def facts(request, grid):
    """入力事実の矛盾のみを拒否する。現在の必須条件は求解・解検証で扱う。"""
    from .roster import validate_history

    start, end = context_bounds(request, grid)
    rows = request["continuity"]["employees"]
    employees = {e["id"] for e in request["employees"]}
    if len({r["employee_id"] for r in rows}) != len(rows):
        reject("CONFLICTING_CONTINUITY", "従業員の文脈が重複しています。", "/continuity/employees")
    if len(rows) != len(employees) or {r["employee_id"] for r in rows} != employees:
        reject(
            "INCOMPLETE_HISTORY", "全従業員の文脈を重複なく指定します。", "/continuity/employees"
        )
    if any("history" in e for e in request["employees"]):
        reject("CONFLICTING_CONTINUITY", "continuity と history は併記できません。", "/employees")
    seen, result = set(), []
    for i, row in enumerate(rows):
        path = f"/continuity/employees/{i}"
        anchor = row["before_context"]
        try:
            validate_history(
                {
                    "schema_version": "0.15",
                    "employees": [{"id": row["employee_id"], "history": anchor}],
                },
                replace(grid, start=start, end=end),
            )
        except InvalidInput as error:
            reject(
                "INVALID_CONTINUITY_INTERVAL",
                error.diagnostics[0]["message"],
                path + "/before_context",
            )
        duties = []
        for name in ("actual_shifts", "committed_shifts"):
            for j, value in enumerate(row[name]):
                p = f"{path}/{name}/{j}"
                if value["id"] in seen:
                    reject("CONFLICTING_CONTINUITY", "実績・確定勤務のIDが重複しています。", p)
                seen.add(value["id"])
                segments = parse_segments(
                    value["segments"], grid, (start, end), p, aligned=name != "actual_shifts"
                )
                a, b = segments[0][0], segments[-1][1]
                if (
                    (name == "actual_shifts" and b > grid.start)
                    or (name == "committed_shifts" and b <= grid.start)
                    or (
                        anchor["last_shift_end"] is not None
                        and a < minute_datetime(anchor["last_shift_end"], p)
                    )
                ):
                    reject(
                        "INVALID_CONTINUITY_INTERVAL",
                        "実績・確定勤務・アンカーの期間が矛盾しています。",
                        p,
                    )
                duty = {
                    "id": value["id"],
                    "employee_id": row["employee_id"],
                    "segments": segments,
                    "day": a.astimezone(grid.timezone).date().toordinal(),
                    "committed": name == "committed_shifts",
                }
                duties.append(duty)
        ordered = sorted(duties, key=lambda d: d["segments"][0][0])
        if len({d["day"] for d in duties}) != len(duties) or any(
            a["segments"][-1][1] > b["segments"][0][0]
            for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            reject(
                "CONFLICTING_CONTINUITY", "同一人物の事実の勤務日・外側区間が重複しています。", path
            )
        result.extend(duties)
    return result


def candidate(identifier, employee, segments, grid, bounds, available, path, *, generated=False):
    if not grid.start <= segments[0][0] < grid.end or any(
        not bounds[0] <= a < b <= bounds[1] for a, b, _ in segments
    ):
        if generated:
            return None
        reject(
            "INVALID_CANDIDATE_AVAILABILITY", "候補は計画内に開始し文脈期間内に終わります。", path
        )
    # 明示候補と生成候補で同じ区間・休憩検証を使う。
    values = output_segments(segments, grid)
    segments = parse_segments(values, grid, bounds, path)
    if any(not any(x <= a and b <= y for x, y in available) for a, b, _ in segments):
        if generated:
            return None
        reject("INVALID_CANDIDATE_AVAILABILITY", "勤務全体が勤務可能時間に収まりません。", path)
    step = timedelta(minutes=grid.slot_minutes)
    slots = tuple(
        (
            max(0, (a - grid.start) // step),
            min(grid.slots, (b - grid.start) // step),
            tuple(
                (max(0, (x - grid.start) // step), min(grid.slots, (y - grid.start) // step))
                for x, y in rests
            ),
        )
        for a, b, rests in segments
    )
    return ShiftCandidate(
        identifier,
        employee,
        segments[0][0].astimezone(grid.timezone).date(),
        slots[0][0],
        slots[-1][1],
        tuple(r for _, _, rests in slots for r in rests),
        slots,
        absolute_segments=segments,
    )


def output_segments(segments, grid):
    def value(a, b):
        return {
            "start": a.astimezone(grid.timezone).isoformat(),
            "end": b.astimezone(grid.timezone).isoformat(),
        }

    return [
        {"interval": value(a, b), "breaks": [value(x, y) for x, y in rests]}
        for a, b, rests in segments
    ]


def committed_outputs(request, grid):
    return [
        {
            "committed_shift_id": d["id"],
            "employee_id": d["employee_id"],
            "work_day": d["segments"][0][0].astimezone(grid.timezone).date().isoformat(),
            "segments": output_segments(d["segments"], grid),
        }
        for d in facts(request, grid)
        if d["committed"] and d["segments"][0][0] < grid.end and grid.start < d["segments"][-1][1]
    ]


def prepare(model, problem, active_groups=None):
    request, grid = problem.request, problem.grid
    duties = list(problem.continuity)
    shifts = {c.id: model.new_bool_var(f"shift_{c.id}") for c in problem.candidates}
    for c in problem.candidates:
        duties.append(
            {
                "id": c.id,
                "employee_id": c.employee_id,
                "segments": c.absolute_segments,
                "day": c.day.toordinal(),
                "variable": shifts[c.id],
            }
        )
    by_employee, coverage, scheduled = defaultdict(list), defaultdict(list), {}
    available = availability(request, grid)
    for duty in duties:
        e, seg, var = duty["employee_id"], duty["segments"], duty.get("variable", 1)
        by_employee[e].append(duty)
        for slot in covered_slots(seg, grid):
            coverage[e, slot].append(var)
        if duty.get("committed") and any(
            not any(x <= max(a, grid.start) and b <= y for x, y in available[e])
            for a, b, _ in seg
            if b > grid.start
        ):
            model.add(False)
    rows = {r["employee_id"]: r for r in request["continuity"]["employees"]}
    h, f = context_bounds(request, grid)
    for e, row in rows.items():
        employee_duties = by_employee[e]
        by_day = defaultdict(list)
        intervals = []
        for d in employee_duties:
            by_day[d["day"]].append(d.get("variable", 1))
            a, b = d["segments"][0][0], d["segments"][-1][1]
            intervals.append(
                model.new_optional_fixed_size_interval_var(
                    (a - h) // timedelta(minutes=1),
                    (b - a) // timedelta(minutes=1),
                    d.get("variable", 1),
                    f"span_{e}_{d['id']}",
                )
            )
        for values in by_day.values():
            model.add(sum(values) <= 1)
        model.add_no_overlap(intervals)
        scheduled[e] = sum(
            minutes(d["segments"], grid.start, grid.end) * d.get("variable", 1)
            for d in employee_duties
        )
        for i, rule in enumerate(request["constraints"]):
            if active_groups is not None and f"/constraints/{i}" not in active_groups:
                continue
            if e not in rule["employee_ids"]:
                continue
            kind = rule["type"]
            if kind == "max_scheduled_minutes":
                model.add(scheduled[e] <= rule["limit_minutes"])
            elif kind == "scheduled_minutes_bounds":
                a, b = interval(rule["interval"], grid, (h, f), f"/constraints/{i}/interval")
                value = sum(
                    minutes(d["segments"], a, b) * d.get("variable", 1) for d in employee_duties
                )
                if "min_minutes" in rule:
                    model.add(value >= rule["min_minutes"])
                if "max_minutes" in rule:
                    model.add(value <= rule["max_minutes"])
            elif kind == "min_rest_minutes":
                # 過去だけの休息は遡及判定しない。直近実績と以後の勤務へ接続する。
                past = [d for d in employee_duties if d["segments"][-1][1] <= grid.start]
                recent = [d for d in employee_duties if d["segments"][-1][1] > grid.start]
                last = max((d["segments"][-1][1] for d in past), default=None)
                if last is None and row["before_context"]["last_shift_end"] is not None:
                    last = minute_datetime(row["before_context"]["last_shift_end"], "/continuity")
                for d in recent:
                    if last is not None and d["segments"][0][0] - last < timedelta(
                        minutes=rule["limit_minutes"]
                    ):
                        model.add(d.get("variable", 1) == 0)
                model.add_no_overlap(
                    [
                        model.new_optional_fixed_size_interval_var(
                            (d["segments"][0][0] - h) // timedelta(minutes=1),
                            (d["segments"][-1][1] - d["segments"][0][0]) // timedelta(minutes=1)
                            + rule["limit_minutes"],
                            d.get("variable", 1),
                            f"rest_{i}_{e}_{d['id']}",
                        )
                        for d in recent
                    ]
                )
            elif kind == "max_consecutive_days":
                previous = row["before_context"]["consecutive_work_days_before_window"]
                max_run = previous + len(employee_duties)
                previous_day = h.astimezone(grid.timezone).date().toordinal() - 1
                future_days = {
                    d["day"] for d in employee_duties if d["segments"][-1][1] > grid.start
                }
                for day in sorted(by_day):
                    if day > previous_day + 1:
                        previous = 0
                    previous_day = day
                    work = model.new_bool_var(f"day_{i}_{e}_{day}")
                    model.add(work == sum(by_day[day]))
                    count = model.new_int_var(0, max_run, f"run_{i}_{e}_{day}")
                    model.add(count == previous + 1).only_enforce_if(work)
                    model.add(count == 0).only_enforce_if(work.Not())
                    if day in future_days:
                        model.add(count <= rule["limit_days"])
                    previous = count
            elif kind == "min_split_gap_minutes":
                for d in employee_duties:
                    if d["segments"][-1][1] > grid.start and any(
                        (b[0] - a[1]) // timedelta(minutes=1) < rule["limit_minutes"]
                        for a, b in zip(d["segments"], d["segments"][1:], strict=False)
                    ):
                        model.add(d.get("variable", 1) == 0)
    return shifts, coverage, scheduled


def verify_shifts(request, grid, shifts, fail, active_groups=None):
    from .roster import expand_candidates

    # 生JSONと返却segmentsから再計算し、Problemの候補・係数・事実表は読まない。
    duties = facts(request, grid)
    candidates = {c.id: c for c in expand_candidates(request, grid)}
    expected = {s["committed_shift_id"]: s for s in committed_outputs(request, grid)}
    bounds = context_bounds(request, grid)
    seen = set()
    for i, shift in enumerate(shifts):
        path = f"/shifts/{i}"
        committed = "committed_shift_id" in shift
        identifier = shift["committed_shift_id" if committed else "candidate_id"]
        key = committed, identifier
        if key in seen:
            fail("DUPLICATE_SHIFT", "同じ勤務を複数回返しています。", path)
            continue
        seen.add(key)
        try:
            seg = parse_segments(shift["segments"], grid, bounds, path)
        except InvalidInput as error:
            for d in error.diagnostics:
                fail(d["code"], d["message"], d["json_pointer"])
            continue
        if committed:
            source = expected.get(identifier)
            match = (
                source is not None
                and shift["employee_id"] == source["employee_id"]
                and seg == parse_segments(source["segments"], grid, bounds, path)
            )
        else:
            source = candidates.get(identifier)
            match = (
                source is not None
                and source.employee_id == shift["employee_id"]
                and seg == source.absolute_segments
            )
        if not match or shift["work_day"] != seg[0][0].astimezone(grid.timezone).date().isoformat():
            fail(
                "CANDIDATE_MISMATCH", "勤務参照・勤務日・原区間・休憩が元入力と一致しません。", path
            )
            continue
        if not committed:
            duties.append(
                {
                    "id": identifier,
                    "employee_id": shift["employee_id"],
                    "segments": seg,
                    "day": seg[0][0].astimezone(grid.timezone).date().toordinal(),
                }
            )
    for identifier in expected:
        if (True, identifier) not in seen:
            fail(
                "MISSING_COMMITTED_SHIFT",
                "計画に重なる確定勤務が欠落しています。",
                "/shifts",
                [identifier],
            )
    coverage, breaks, scheduled = defaultdict(set), defaultdict(set), Counter()
    available = availability(request, grid)
    rows = {r["employee_id"]: r for r in request["continuity"]["employees"]}
    for e, row in rows.items():
        selected = sorted(
            (d for d in duties if d["employee_id"] == e), key=lambda d: d["segments"][0][0]
        )
        if len({d["day"] for d in selected}) != len(selected):
            fail("MULTIPLE_DAILY_SHIFTS", "1人・勤務日につき最大1勤務です。", "/shifts", [e])
        if any(
            a["segments"][-1][1] > b["segments"][0][0]
            for a, b in zip(selected, selected[1:], strict=False)
        ):
            fail("OVERLAPPING_SHIFTS", "勤務の外側区間が重複しています。", "/shifts", [e])
        for d in selected:
            seg = d["segments"]
            coverage[e].update(covered_slots(seg, grid))
            breaks[e].update(covered_slots(seg, grid, breaks=True))
            scheduled[e] += minutes(seg, grid.start, grid.end)
            if seg[-1][1] > grid.start and any(
                not any(x <= max(a, grid.start) and b <= y for x, y in available[e])
                for a, b, _ in seg
                if b > grid.start
            ):
                fail(
                    "AVAILABILITY_VIOLATION",
                    "確定勤務が現在の勤務可能時間と矛盾しています。",
                    "/shifts",
                    [e],
                )
        for i, rule in enumerate(request["constraints"]):
            if active_groups is not None and f"/constraints/{i}" not in active_groups:
                continue
            if e not in rule["employee_ids"]:
                continue
            path, kind = f"/constraints/{i}", rule["type"]
            if kind in {"max_scheduled_minutes", "scheduled_minutes_bounds"}:
                value = scheduled[e]
                if kind == "scheduled_minutes_bounds":
                    a, b = interval(rule["interval"], grid, bounds, path + "/interval")
                    value = sum(minutes(d["segments"], a, b) for d in selected)
                if value > rule.get("max_minutes", rule.get("limit_minutes", 2**60)):
                    fail(
                        "MAX_SCHEDULED_MINUTES_VIOLATION",
                        "期間勤務量の上限違反です。",
                        path,
                        [e],
                        actual_value=value,
                    )
                if value < rule.get("min_minutes", 0):
                    fail(
                        "MIN_SCHEDULED_MINUTES_VIOLATION",
                        "期間勤務量の下限違反です。",
                        path,
                        [e],
                        actual_value=value,
                    )
            elif kind == "min_rest_minutes":
                last = row["before_context"]["last_shift_end"]
                last = minute_datetime(last, path) if last is not None else None
                for d in selected:
                    a, b = d["segments"][0][0], d["segments"][-1][1]
                    if (
                        b > grid.start
                        and last is not None
                        and a - last < timedelta(minutes=rule["limit_minutes"])
                    ):
                        fail(
                            "MIN_REST_MINUTES_VIOLATION",
                            "勤務間の休息が不足しています。",
                            path,
                            [e],
                        )
                    last = b
            elif kind == "max_consecutive_days":
                count = row["before_context"]["consecutive_work_days_before_window"]
                working = {d["day"] for d in selected}
                current = {d["day"] for d in selected if d["segments"][-1][1] > grid.start}
                previous_day = bounds[0].astimezone(grid.timezone).date().toordinal() - 1
                for day in sorted(working):
                    count = count + 1 if day == previous_day + 1 else 1
                    previous_day = day
                    if day in current and count > rule["limit_days"]:
                        fail(
                            "MAX_CONSECUTIVE_DAYS_VIOLATION",
                            "連勤上限に違反しています。",
                            path,
                            [e],
                        )
            elif kind == "min_split_gap_minutes":
                for d in selected:
                    if d["segments"][-1][1] > grid.start and any(
                        (b[0] - a[1]) // timedelta(minutes=1) < rule["limit_minutes"]
                        for a, b in zip(d["segments"], d["segments"][1:], strict=False)
                    ):
                        fail(
                            "MIN_SPLIT_GAP_VIOLATION", "分割勤務の間隔が不足しています。", path, [e]
                        )
    return coverage, breaks, scheduled


def summary(request, grid, solution):
    duties = facts(request, grid)
    bounds = context_bounds(request, grid)
    duties.extend(
        {
            "employee_id": s["employee_id"],
            "segments": parse_segments(s["segments"], grid, bounds, "/shifts"),
        }
        for s in solution["shifts"]
        if "candidate_id" in s
    )
    employees = []
    for employee in request["employees"]:
        selected = [d for d in duties if d["employee_id"] == employee["id"]]
        values = [
            sum(minutes(d["segments"], a, b) for d in selected)
            for a, b in ((bounds[0], grid.start), (grid.start, grid.end), (grid.end, bounds[1]))
        ]
        if sum(values) != sum(minutes(d["segments"], *bounds) for d in selected):
            raise RuntimeError("Continuity projection changed total minutes")
        employees.append(
            {
                "employee_id": employee["id"],
                "historical_minutes": values[0],
                "planned_minutes": values[1],
                "outside_planning_minutes": values[2],
                "committed_shift_ids": sorted(d["id"] for d in selected if d.get("committed")),
            }
        )
    return {
        "context_window": request["continuity"]["context_window"],
        "planning_window": {k: request["planning_window"][k] for k in ("start", "end")},
        "employees": employees,
    }
