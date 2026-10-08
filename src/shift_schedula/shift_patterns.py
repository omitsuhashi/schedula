"""原勤務の分類と、ローカル暦日に対する勤務パターンの必須条件。"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from .continuity import context_bounds, interval, minutes, output_segments
from .contract import parse_datetime, reject
from .day_counts import occupied_days
from .model import minute_datetime, reference, unique

KINDS = {
    "forbidden_shift_successions",
    "days_off_after_shift",
    "min_consecutive_days_off",
    "worked_date_groups_limit",
}


def rules(request, active_groups=None):
    return [
        (i, rule)
        for i, rule in enumerate(request["constraints"])
        if rule["type"] in KINDS and (active_groups is None or f"/constraints/{i}" in active_groups)
    ]


def midnight(day, zone):
    if not date.min.toordinal() <= day <= date.max.toordinal():
        reject("INVALID_PATTERN_PERIOD", "判定余白は日時の表現範囲内に指定します。")
    return datetime.combine(date.fromordinal(day), datetime.min.time(), zone).astimezone(UTC)


def day_of(instant, grid):
    return instant.astimezone(grid.timezone).date().toordinal()


def category_ranges(request):
    categories = {}
    for category in request.get("shift_categories", []):
        merged = []
        for a, b in sorted(
            (parse_datetime(i["start"]), parse_datetime(i["end"])) for i in category["intervals"]
        ):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(b, merged[-1][1])
            else:
                merged.append([a, b])
        categories[category["id"]] = (merged, category["min_overlap_minutes"])
    return categories


def classify(segments, categories):
    spans = [
        (
            parse_datetime(s["interval"]["start"]),
            parse_datetime(s["interval"]["end"]),
            tuple((parse_datetime(b["start"]), parse_datetime(b["end"])) for b in s["breaks"]),
        )
        for s in segments
    ]
    return {
        identifier
        for identifier, (ranges, minimum) in categories.items()
        if sum(minutes(spans, a, b) for a, b in ranges) >= minimum
    }


def rest_end(end, min_days, grid):
    return midnight(day_of(end - timedelta(microseconds=1), grid) + min_days + 1, grid.timezone)


def model_duties(problem, shifts=None):
    rows = []
    for candidate in problem.candidates:
        rows.append((candidate.output(problem.grid), shifts[candidate.id] if shifts else 1, False))
    for fact in problem.continuity:
        rows.append(
            (
                {
                    "candidate_id": fact["id"],
                    "employee_id": fact["employee_id"],
                    "segments": output_segments(fact["segments"], problem.grid),
                },
                1,
                not fact["committed"],
            )
        )
    return rows


def validate(problem):
    request, grid = problem.request, problem.grid
    categories = request.get("shift_categories", [])
    if categories and request["problem_type"] != "roster":
        reject("UNSUPPORTED_CONDITION", "勤務分類は roster 専用です。", "/shift_categories")
    bounds = context_bounds(request, grid) if request.get("continuity") else (grid.start, grid.end)
    identifiers = unique(categories, "id", "/shift_categories")
    for i, category in enumerate(categories):
        path = f"/shift_categories/{i}"
        if type(category["min_overlap_minutes"]) is not int:
            reject("INVALID_INTEGER", "分類の閾値は整数で指定します。", path)
        for j, value in enumerate(category["intervals"]):
            interval(value, grid, bounds, f"{path}/intervals/{j}")
            step = timedelta(minutes=grid.slot_minutes)
            if any((parse_datetime(value[k]) - grid.start) % step for k in ("start", "end")):
                reject("MISALIGNED_INTERVAL", "分類区間は時間粒度に揃えます。", path)
    selected_rules = rules(request)
    if not selected_rules:
        return
    ranges = category_ranges(request)
    duties = model_duties(problem)
    for i, rule in selected_rules:
        path = f"/constraints/{i}"
        start, end = (
            minute_datetime(rule["evaluation_period"][k], path + "/evaluation_period/" + k)
            for k in ("start", "end")
        )
        if not grid.start <= start < end <= grid.end or any(
            t.astimezone(grid.timezone).time() != datetime.min.time() for t in (start, end)
        ):
            reject("INVALID_PATTERN_PERIOD", "評価期間は計画内の正の00:00同士の区間です。", path)
        first, last = day_of(start, grid), day_of(end, grid)

        def require(a, b, path=path, rule=rule):
            if a < bounds[0] or b > grid.end:
                reject(
                    "INCOMPLETE_HISTORY",
                    "勤務パターンの判定に必要な過去実績または計画内の余白が不足しています。",
                    path,
                    [rule["id"]],
                    required_start=a.astimezone(grid.timezone).isoformat(),
                    required_end=b.astimezone(grid.timezone).isoformat(),
                )

        for field in ("day_offset", "min_days", "max_groups"):
            if field in rule and type(rule[field]) is not int:
                reject("INVALID_INTEGER", "勤務パターンの日数・群数は整数で指定します。", path)
        for field in ("category_id", "from_category_id", "to_category_id"):
            if field in rule:
                reference(rule[field], identifiers, path + "/" + field)
        kind = rule["type"]
        if kind == "forbidden_shift_successions":
            require(
                midnight(first - rule["day_offset"], grid.timezone),
                midnight(last + rule["day_offset"], grid.timezone),
            )
        elif kind == "min_consecutive_days_off":
            require(
                midnight(first - rule["min_days"], grid.timezone),
                midnight(last + rule["min_days"], grid.timezone),
            )
        elif kind == "days_off_after_shift":
            anchors = (
                {r["employee_id"]: r["before_context"] for r in request["continuity"]["employees"]}
                if request.get("continuity")
                else {e["id"]: e["history"] for e in request["employees"]}
            )
            for employee in rule["employee_ids"]:
                anchor = anchors[employee]["last_shift_end"]
                if (
                    anchor is not None
                    and rest_end(parse_datetime(anchor), rule["min_days"], grid) > start
                ):
                    reject(
                        "INCOMPLETE_HISTORY",
                        "前期間の休み義務の分類には原勤務を含む確認済み実績が必要です。",
                        path,
                        [rule["id"], employee],
                        required_start=midnight(
                            date.fromisoformat(anchors[employee]["last_work_day"]).toordinal(),
                            grid.timezone,
                        ).isoformat(),
                        required_end=end.astimezone(grid.timezone).isoformat(),
                    )
            for duty, _, _ in duties:
                if duty["employee_id"] not in rule["employee_ids"]:
                    continue
                a = parse_datetime(duty["segments"][0]["interval"]["start"])
                b = parse_datetime(duty["segments"][-1]["interval"]["end"])
                until = rest_end(b, rule["min_days"], grid)
                if (
                    a < end
                    and until > start
                    and (a >= start or b < end)
                    and rule["category_id"] in classify(duty["segments"], ranges)
                ):
                    require(bounds[0], until)
        else:
            unique(rule["date_groups"], "id", path + "/date_groups")
            seen = set()
            for j, group in enumerate(rule["date_groups"]):
                for value in group["dates"]:
                    day = date.fromisoformat(value).toordinal()
                    if day in seen or not first <= day < last:
                        reject(
                            "INVALID_DATE_GROUP",
                            "群の日付は評価期間内で、群間も重複させません。",
                            f"{path}/date_groups/{j}",
                        )
                    seen.add(day)


def prepare(model, problem, shifts, active_groups=None):
    selected_rules = rules(problem.request, active_groups)
    if not selected_rules:
        return
    grid = problem.grid
    categories = category_ranges(problem.request)
    by_employee = defaultdict(list)
    for duty, variable, actual in model_duties(problem, shifts):
        a = parse_datetime(duty["segments"][0]["interval"]["start"])
        b = parse_datetime(duty["segments"][-1]["interval"]["end"])
        by_employee[duty["employee_id"]].append(
            (duty, variable, actual, a, b, classify(duty["segments"], categories))
        )
    for i, rule in selected_rules:
        start, end = (parse_datetime(rule["evaluation_period"][k]) for k in ("start", "end"))
        first, last = day_of(start, grid), day_of(end, grid)
        for employee in rule["employee_ids"]:
            duties = by_employee[employee]
            kind = rule["type"]
            if kind in {"forbidden_shift_successions", "days_off_after_shift"}:
                # ponytail: 候補対を走査する。準備時間を支配したら日付索引へ置き換える。
                for duty, chosen, actual, a, b, matches in duties:
                    category = rule.get("category_id", rule.get("from_category_id"))
                    if category not in matches or a >= end:
                        continue
                    target = day_of(a, grid) + rule.get("day_offset", 0)
                    until = rest_end(b, rule.get("min_days", 1), grid)
                    if a < start and (
                        not first <= target < last
                        if kind == "forbidden_shift_successions"
                        else b >= end or until <= start
                    ):
                        continue
                    for other, selected, past, x, _y, other_matches in duties:
                        if other is duty or (actual and past):
                            continue
                        conflict = (
                            day_of(x, grid) == target and rule["to_category_id"] in other_matches
                            if kind == "forbidden_shift_successions"
                            else any(
                                parse_datetime(s["interval"]["start"]) < until
                                and b < parse_datetime(s["interval"]["end"])
                                for s in other["segments"]
                            )
                        )
                        if conflict:
                            model.add(chosen + selected <= 1)
                continue
            margin = rule.get("min_days", 0)
            left, right = first - margin, last + margin
            occupied = defaultdict(list)
            for duty, variable, _, _, _, _ in duties:
                for day in occupied_days(
                    duty["segments"],
                    midnight(left, grid.timezone),
                    midnight(right, grid.timezone),
                    grid.timezone,
                ):
                    occupied[day].append(variable)
            days = {}
            for day in range(left, right):
                v = model.new_bool_var(f"pattern_day_{i}_{employee}_{day}")
                model.add_max_equality(v, [0, *occupied[day]])
                days[day] = v
            if kind == "worked_date_groups_limit":
                groups = []
                for group in rule["date_groups"]:
                    v = model.new_bool_var(f"pattern_group_{i}_{employee}_{group['id']}")
                    model.add_max_equality(
                        v, [days[date.fromisoformat(d).toordinal()] for d in group["dates"]]
                    )
                    groups.append(v)
                model.add(sum(groups) <= rule["max_groups"])
            else:
                # 休日連続長をmin_daysで飽和させ、評価期間と交差する短い区間だけを禁止する。
                previous = 0
                for day, occupied in days.items():
                    if day > first:
                        enough = model.new_bool_var(f"pattern_enough_{i}_{employee}_{day}")
                        model.add(previous == margin).only_enforce_if(enough)
                        model.add(previous <= max(0, day - last)).only_enforce_if(
                            [occupied, enough.Not()]
                        )
                    increment = model.new_int_var(
                        0, margin, f"pattern_increment_{i}_{employee}_{day}"
                    )
                    model.add_min_equality(increment, [previous + 1, margin])
                    run = model.new_int_var(0, margin, f"pattern_run_{i}_{employee}_{day}")
                    model.add(run == 0).only_enforce_if(occupied)
                    model.add(run == increment).only_enforce_if(occupied.Not())
                    previous = run


def evaluate(request, grid, solution, fail, active_groups=None):
    # 元JSONの実績と返却原区間を読む。候補係数・モデル変数は参照しない。
    selected_rules = rules(request, active_groups)
    if not selected_rules:
        return
    duties = defaultdict(list)
    categories = category_ranges(request)
    returned = {s["committed_shift_id"] for s in solution["shifts"] if "committed_shift_id" in s}
    rows = [(s, False) for s in solution["shifts"]]
    for row in request.get("continuity", {}).get("employees", []):
        rows.extend(({**d, "employee_id": row["employee_id"]}, True) for d in row["actual_shifts"])
        rows.extend(
            ({**d, "employee_id": row["employee_id"]}, False)
            for d in row["committed_shifts"]
            if d["id"] not in returned
        )
    for duty, actual in rows:
        segments = duty["segments"]
        duties[duty["employee_id"]].append(
            (
                duty,
                actual,
                parse_datetime(segments[0]["interval"]["start"]),
                parse_datetime(segments[-1]["interval"]["end"]),
                classify(segments, categories),
            )
        )
    for i, rule in selected_rules:
        start, end = (parse_datetime(rule["evaluation_period"][k]) for k in ("start", "end"))
        first, last = day_of(start, grid), day_of(end, grid)
        for employee in rule["employee_ids"]:
            rows = duties[employee]

            def violation(i=i, rule=rule, employee=employee, **facts):
                related = [rule["id"], employee]
                related.extend(
                    d.get("candidate_id", d.get("committed_shift_id", d.get("id")))
                    for d in facts.pop("shifts", [])
                )
                blocked = facts.pop("forbidden_interval", None)
                if blocked:
                    facts.update(forbidden_start=blocked["start"], forbidden_end=blocked["end"])
                groups = facts.pop("date_groups", None)
                if groups:
                    facts["date_group_ids"] = ",".join(g["id"] for g in groups)
                fail(
                    "SHIFT_PATTERN_VIOLATION",
                    "勤務パターンの必須条件に違反しています。",
                    f"/constraints/{i}",
                    related,
                    pattern_type=rule["type"],
                    **facts,
                )

            kind = rule["type"]
            if kind in {"forbidden_shift_successions", "days_off_after_shift"}:
                for duty, actual, a, b, matches in rows:
                    category = rule.get("category_id", rule.get("from_category_id"))
                    if category not in matches or a >= end:
                        continue
                    origin = day_of(a, grid)
                    target = origin + rule.get("day_offset", 0)
                    until = rest_end(b, rule.get("min_days", 1), grid)
                    if a < start and (
                        not first <= target < last
                        if kind == "forbidden_shift_successions"
                        else b >= end or until <= start
                    ):
                        continue
                    for other, past, x, _y, other_matches in rows:
                        if other is duty or (actual and past):
                            continue
                        if kind == "forbidden_shift_successions":
                            conflict = (
                                day_of(x, grid) == target
                                and rule["to_category_id"] in other_matches
                            )
                            blocked = {
                                "start": midnight(target, grid.timezone).isoformat(),
                                "end": midnight(target + 1, grid.timezone).isoformat(),
                            }
                        else:
                            conflict = any(
                                parse_datetime(s["interval"]["start"]) < until
                                and b < parse_datetime(s["interval"]["end"])
                                for s in other["segments"]
                            )
                            blocked = {
                                "start": b.astimezone(grid.timezone).isoformat(),
                                "end": until.astimezone(grid.timezone).isoformat(),
                            }
                        if conflict:
                            violation(
                                origin_day=date.fromordinal(origin).isoformat(),
                                forbidden_interval=blocked,
                                shifts=[duty, other],
                            )
                continue
            margin = rule.get("min_days", 0)
            left, right = first - margin, last + margin
            occupied = set().union(
                *(
                    occupied_days(
                        d["segments"],
                        midnight(left, grid.timezone),
                        midnight(right, grid.timezone),
                        grid.timezone,
                    )
                    for d, *_ in rows
                )
            )
            if kind == "worked_date_groups_limit":
                groups = [
                    g
                    for g in rule["date_groups"]
                    if occupied.intersection(date.fromisoformat(d).toordinal() for d in g["dates"])
                ]
                if len(groups) > rule["max_groups"]:
                    group_days = {
                        date.fromisoformat(d).toordinal() for g in groups for d in g["dates"]
                    }
                    violation(
                        date_groups=groups,
                        actual_groups=len(groups),
                        max_groups=rule["max_groups"],
                        shifts=[
                            d
                            for d, *_ in rows
                            if occupied_days(d["segments"], start, end, grid.timezone) & group_days
                        ],
                    )
            else:
                run = left
                for day in range(left, right + 1):
                    if day in occupied or day == right:
                        if run < last and day > first and 0 < day - run < margin:
                            boundary_start = midnight(run - 1, grid.timezone)
                            boundary_end = midnight(day + 1, grid.timezone)
                            violation(
                                origin_day=date.fromordinal(run).isoformat(),
                                days_off=day - run,
                                min_days=margin,
                                forbidden_interval={
                                    "start": midnight(run, grid.timezone).isoformat(),
                                    "end": midnight(day, grid.timezone).isoformat(),
                                },
                                shifts=[
                                    d
                                    for d, *_ in rows
                                    if occupied_days(
                                        d["segments"], boundary_start, boundary_end, grid.timezone
                                    )
                                ],
                            )
                        run = day + 1
