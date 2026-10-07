import errno
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contract import parse_datetime, reject, validate_request


def minute_datetime(value, pointer):
    try:
        result = parse_datetime(value)
    except ValueError, OverflowError:
        reject("INVALID_DATETIME", "オフセット付きの日時を指定します。", pointer)
    # fromisoformat による7桁目以降の切り捨てを受理しない。
    fraction = value.split(".", 1)[1] if "." in value else ""
    fraction = fraction.split("+", 1)[0].split("-", 1)[0].rstrip("Zz")
    if result.second or result.microsecond or any(char != "0" for char in fraction):
        reject("INVALID_TIME_PRECISION", "秒・端数分は指定できません。", pointer)
    return result


@dataclass(frozen=True)
class TimeGrid:
    start: datetime
    end: datetime
    timezone: ZoneInfo
    slot_minutes: int
    slots: int

    def interval(self, value, pointer):
        start = minute_datetime(value["start"], pointer + "/start")
        end = minute_datetime(value["end"], pointer + "/end")
        if not self.start <= start < end <= self.end:
            reject("INVALID_INTERVAL", "区間は計画内の正の半開区間にします。", pointer)
        step = timedelta(minutes=self.slot_minutes)
        if (start - self.start) % step or (end - self.start) % step:
            reject("MISALIGNED_INTERVAL", "区間が計画開始からの時間粒度に揃っていません。", pointer)
        return (start - self.start) // step, (end - self.start) // step

    def output_interval(self, start, end):
        return {
            "start": (self.start + timedelta(minutes=start * self.slot_minutes))
            .astimezone(self.timezone)
            .isoformat(),
            "end": (self.start + timedelta(minutes=end * self.slot_minutes))
            .astimezone(self.timezone)
            .isoformat(),
        }


@dataclass
class ShiftCandidate:
    id: str
    employee_id: str
    day: date
    start: int
    end: int
    breaks: tuple[tuple[int, int], ...]
    segments: tuple = ()

    @property
    def work_slots(self):
        return (
            {slot for a, b, _ in self.segments for slot in range(a, b)}
            - {slot for start, end in self.breaks for slot in range(start, end)}
            if self.segments
            else set(range(self.start, self.end))
            - {slot for start, end in self.breaks for slot in range(start, end)}
        )

    def output(self, grid):
        if self.segments:
            return {
                "candidate_id": self.id,
                "employee_id": self.employee_id,
                "work_day": self.day.isoformat(),
                "segments": [
                    {
                        "interval": grid.output_interval(a, b),
                        "breaks": [grid.output_interval(x, y) for x, y in rests],
                    }
                    for a, b, rests in self.segments
                ],
            }
        return {
            "candidate_id": self.id,
            "employee_id": self.employee_id,
            "interval": grid.output_interval(self.start, self.end),
            "breaks": [grid.output_interval(start, end) for start, end in self.breaks],
        }


@dataclass
class Problem:
    request: dict
    grid: TimeGrid
    available: dict[str, set[int]]
    qualified: dict[str, set[str]]
    demand: list[dict[str, int]]
    costs: dict[tuple[str, str], int]
    candidates: list[ShiftCandidate] = field(default_factory=list)
    baseline: dict | None = None


def unique(items, field, path):
    seen = set()
    for index, item in enumerate(items):
        identifier = item[field]
        if identifier in seen:
            reject("DUPLICATE_ID", "ID が重複しています。", f"{path}/{index}/{field}", [identifier])
        seen.add(identifier)
    return seen


def reference(identifier, identifiers, path):
    if identifier not in identifiers:
        reject("UNKNOWN_REFERENCE", "参照先の ID がありません。", path, [identifier])


def nonoverlapping(intervals, path):
    ordered = sorted((start, end, index) for index, (start, end) in enumerate(intervals))
    for (_, previous_end, _), (start, _, index) in zip(ordered, ordered[1:], strict=False):
        if start < previous_end:
            reject("OVERLAPPING_INTERVALS", "同じ対象の区間が重複しています。", f"{path}/{index}")


def normalize(request):
    validate_request(request)
    roster = request["problem_type"] == "roster"
    if not roster:
        for name in ("shift_candidates", "shift_templates"):
            if request.get(name):
                reject("UNSUPPORTED_CONDITION", "assignment は勤務候補を扱いません。", "/" + name)
        for index, employee in enumerate(request["employees"]):
            if "history" in employee:
                reject(
                    "UNSUPPORTED_CONDITION",
                    "assignment は計画前履歴を扱いません。",
                    f"/employees/{index}/history",
                )

    ids = {
        field: unique(request[field], "id", "/" + field)
        for field in (
            "skills",
            "roles",
            "employees",
            "demand",
            "constraints",
            "preferences",
            "objectives",
        )
    }
    metrics = unique(request["objectives"], "metric", "/objectives")
    for index, objective in enumerate(request["objectives"]):
        if not roster and objective["metric"] not in {"preference_penalty", "role_switches"}:
            reject(
                "UNSUPPORTED_CONDITION",
                "assignment の対応目的は preference_penalty または role_switches です。",
                f"/objectives/{index}/metric",
            )
    if request["preferences"] and "preference_penalty" not in metrics:
        reject(
            "MISSING_PREFERENCE_OBJECTIVE",
            "選好には preference_penalty 目的が必要です。",
            "/objectives",
        )
    for index, constraint in enumerate(request["constraints"]):
        path = f"/constraints/{index}"
        if not roster and constraint["type"] not in {"max_assigned_minutes", "max_role_switches"}:
            reject("UNSUPPORTED_CONDITION", "assignment では未対応の制約です。", path + "/type")
        for employee_index, identifier in enumerate(constraint["employee_ids"]):
            reference(identifier, ids["employees"], f"{path}/employee_ids/{employee_index}")
    if request["solver"]["backend"] == "min_cost_flow" and (
        roster or request["constraints"] or "role_switches" in metrics or request.get("diagnosis")
    ):
        reject(
            "UNSUPPORTED_BACKEND",
            "min_cost_flow は roster・明示制約・role_switches 目的を扱えません。",
            "/solver/backend",
        )

    window = request["planning_window"]
    try:
        zone = ZoneInfo(window["timezone"])
    except ZoneInfoNotFoundError, ValueError:
        reject("INVALID_TIMEZONE", "IANA タイムゾーンを指定します。", "/planning_window/timezone")
    except OSError as error:
        if error.errno == errno.ENAMETOOLONG:
            reject("INVALID_TIMEZONE", "timezone 名が長すぎます。", "/planning_window/timezone")
        raise
    start = minute_datetime(window["start"], "/planning_window/start")
    end = minute_datetime(window["end"], "/planning_window/end")
    step = timedelta(minutes=int(window["slot_minutes"]))
    if end <= start or (end - start) % step:
        reject(
            "INVALID_PLANNING_WINDOW",
            "計画期間は正の区間で時間粒度に揃える必要があります。",
            "/planning_window",
        )
    slots = (end - start) // step
    if slots > 3000 or slots * len(ids["roles"]) * len(ids["employees"]) > 1000000:
        reject(
            "INPUT_LIMIT",
            "時間枠数または従業員 × 時間枠 × 役割が上限を超えています。",
            "/planning_window",
            slots=slots,
        )
    grid = TimeGrid(start, end, zone, int(window["slot_minutes"]), slots)
    if roster and any(
        value.astimezone(zone).time() != datetime.min.time() for value in (start, end)
    ):
        reject(
            "INVALID_ROSTER_WINDOW",
            "roster の計画期間の両端はローカル日付の00:00にします。",
            "/planning_window",
        )

    for index, role in enumerate(request["roles"]):
        path = f"/roles/{index}/required_skills"
        unique(role["required_skills"], "skill_id", path)
        for skill_index, skill in enumerate(role["required_skills"]):
            reference(skill["skill_id"], ids["skills"], f"{path}/{skill_index}/skill_id")
    available, qualified = {}, {}
    for index, employee in enumerate(request["employees"]):
        path = f"/employees/{index}"
        unique(employee["skills"], "skill_id", path + "/skills")
        levels = {}
        for skill_index, skill in enumerate(employee["skills"]):
            reference(skill["skill_id"], ids["skills"], f"{path}/skills/{skill_index}/skill_id")
            levels[skill["skill_id"]] = skill["level"]
        intervals = [
            grid.interval(value, f"{path}/availability/{i}")
            for i, value in enumerate(employee["availability"])
        ]
        nonoverlapping(intervals, path + "/availability")
        available[employee["id"]] = {slot for a, b in intervals for slot in range(a, b)}
        qualified[employee["id"]] = {
            role["id"]
            for role in request["roles"]
            if all(
                skill["skill_id"] in levels and levels[skill["skill_id"]] >= skill["min_level"]
                for skill in role["required_skills"]
            )
        }
    demand = [{} for _ in range(slots)]
    for index, item in enumerate(request["demand"]):
        path = f"/demand/{index}"
        reference(item["role_id"], ids["roles"], path + "/role_id")
        a, b = grid.interval(item["interval"], path + "/interval")
        for slot in range(a, b):
            if item["role_id"] in demand[slot]:
                reject(
                    "OVERLAPPING_DEMAND",
                    "同じ役割の需要区間が重複しています。",
                    path + "/interval",
                    [item["id"], item["role_id"]],
                )
            demand[slot][item["role_id"]] = int(item["required_people"])
    costs = {}
    for index, item in enumerate(request["preferences"]):
        path = f"/preferences/{index}"
        reference(item["role_id"], ids["roles"], path + "/role_id")
        for employee_index, identifier in enumerate(item["employee_ids"]):
            reference(identifier, ids["employees"], f"{path}/employee_ids/{employee_index}")
            key = identifier, item["role_id"]
            costs[key] = costs.get(key, 0) + int(item["penalty_per_minute"]) * grid.slot_minutes
    problem = Problem(request, grid, available, qualified, demand, costs)
    if roster:
        from .roster import expand_candidates, validate_history

        validate_history(request, grid)
        problem.candidates = expand_candidates(request, grid)
    if request["schema_version"] in {"0.2", "0.3"}:
        from .diagnosis import validate_options
        from .extensions import validate

        validate(problem)
        validate_options(request)
        bounds = [
            slots * len(ids["employees"]) * max(costs.values(), default=0),
            sum(len(c.work_slots) * grid.slot_minutes for c in problem.candidates),
            slots * len(ids["employees"]),
            sum(
                max(slots * grid.slot_minutes, t["target_minutes"])
                for t in request.get("fairness", {}).get("employee_targets", [])
            ),
            2 * slots * 500,
        ]
        if max(bounds) > 2**60 - 1:
            reject("INTEGER_EXPRESSION_LIMIT", "整数式の保守的な上界を超えています。")
    return problem
