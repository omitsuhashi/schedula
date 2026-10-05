from dataclasses import dataclass
from datetime import datetime, timedelta
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
class Problem:
    request: dict
    grid: TimeGrid
    available: dict[str, set[int]]
    qualified: dict[str, set[str]]
    demand: list[dict[str, int]]
    costs: dict[tuple[str, str], int]


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
    if request["problem_type"] != "assignment":
        reject("UNSUPPORTED_CONDITION", "roster は未対応です。", "/problem_type")
    for field in ("shift_candidates", "shift_templates", "constraints"):
        if request.get(field):
            reject(
                "UNSUPPORTED_CONDITION",
                "勤務候補・勤務テンプレート・明示制約は未対応です。",
                "/" + field,
            )
    if request["solver"]["backend"] == "cp_sat":
        reject("UNSUPPORTED_BACKEND", "cp_sat は未導入です。", "/solver/backend")
    for index, employee in enumerate(request["employees"]):
        if "history" in employee:
            reject(
                "UNSUPPORTED_CONDITION",
                "assignment は計画前履歴を扱いません。",
                f"/employees/{index}/history",
            )

    ids = {
        field: unique(request[field], "id", "/" + field)
        for field in ("skills", "roles", "employees", "demand", "preferences", "objectives")
    }
    metrics = unique(request["objectives"], "metric", "/objectives")
    for index, objective in enumerate(request["objectives"]):
        if objective["metric"] != "preference_penalty":
            reject(
                "UNSUPPORTED_CONDITION",
                "対応目的は preference_penalty のみです。",
                f"/objectives/{index}/metric",
            )
    if request["preferences"] and "preference_penalty" not in metrics:
        reject(
            "MISSING_PREFERENCE_OBJECTIVE",
            "選好には preference_penalty 目的が必要です。",
            "/objectives",
        )

    window = request["planning_window"]
    try:
        zone = ZoneInfo(window["timezone"])
    except ZoneInfoNotFoundError, ValueError:
        reject("INVALID_TIMEZONE", "IANA タイムゾーンを指定します。", "/planning_window/timezone")
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
    return Problem(request, grid, available, qualified, demand, costs)
