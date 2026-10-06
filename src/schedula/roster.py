import hashlib
import json
from datetime import UTC, datetime, timedelta
from itertools import product

from .contract import reject
from .model import ShiftCandidate, minute_datetime, nonoverlapping, reference, unique

MAX_CANDIDATES = 5000


def validate_history(request, grid):
    first_day = grid.start.astimezone(grid.timezone).date().toordinal()
    for index, employee in enumerate(request["employees"]):
        path = f"/employees/{index}/history"
        if "history" not in employee:
            reject("MISSING_HISTORY", "roster は空履歴も明示します。", path, [employee["id"]])
        history = employee["history"]
        count = int(history["consecutive_work_days_before_window"])
        last = history["last_shift_end"]
        if last is None:
            if count:
                reject("INVALID_HISTORY", "最終勤務なしの連勤数は0にします。", path)
            continue
        last = minute_datetime(last, path + "/last_shift_end")
        if last > grid.start:
            reject("INVALID_HISTORY", "計画前履歴は計画期間に重ねません。", path)
        try:
            # 終端が00:00なら、その直前の日付が最終勤務日になる。
            last_day = (
                (last - timedelta(microseconds=1)).astimezone(grid.timezone).date().toordinal()
            )
        except OverflowError:
            reject("INVALID_HISTORY", "最終勤務日を表現できません。", path)
        if (last_day == first_day - 1) != (count > 0) or count >= first_day:
            reject("INVALID_HISTORY", "最終勤務日と直前日までの連勤数が一致しません。", path)


def local_start(day, clock, grid, path):
    try:
        naive = datetime.fromisoformat(f"{day}T{clock}")
    except ValueError:
        reject("INVALID_TEMPLATE_TIME", "テンプレートの時刻は HH:MM で指定します。", path)
    instants = {
        aware.astimezone(UTC)
        for fold in (0, 1)
        if (aware := naive.replace(tzinfo=grid.timezone, fold=fold))
        .astimezone(UTC)
        .astimezone(grid.timezone)
        .replace(tzinfo=None)
        == naive
    }
    if len(instants) != 1:
        reject(
            "AMBIGUOUS_LOCAL_TIME" if instants else "NONEXISTENT_LOCAL_TIME",
            "テンプレートには一意に存在するローカル時刻を指定します。",
            path,
            local_datetime=naive.isoformat(),
        )
    return instants.pop()


def expand_candidates(request, grid):
    """元入力から有限候補を生成する。ソルバー用のテーブルは参照しない。"""
    employees = {e["id"]: e for e in request["employees"]}
    available = {
        e["id"]: {
            slot
            for index, interval in enumerate(e["availability"])
            for a, b in [grid.interval(interval, f"/employees/{e['id']}/availability/{index}")]
            for slot in range(a, b)
        }
        for e in request["employees"]
    }
    identifiers = unique(request["shift_candidates"], "id", "/shift_candidates")
    templates = request.get("shift_templates", [])
    unique(templates, "id", "/shift_templates")
    # 除外後の件数だけでなく、展開前の組合せ数も制限する。
    attempts = len(request["shift_candidates"])
    for index, template in enumerate(templates):
        attempts += (
            len(template["employee_ids"])
            * len(template["dates"])
            * len(template["start_times"])
            * len(template["duration_minutes_options"])
            * max(1, len(template["break_options"]))
        )
        if attempts > MAX_CANDIDATES:
            reject(
                "INPUT_LIMIT",
                "勤務候補の展開数が5000件を超えています。",
                f"/shift_templates/{index}",
            )
    result = []

    def add(identifier, employee, start, end, breaks, path, generated=False):
        step = timedelta(minutes=grid.slot_minutes)
        if start >= end:
            reject("INVALID_INTERVAL", "勤務は正の区間にします。", path + "/interval")
        if (start - grid.start) % step or (end - grid.start) % step:
            reject("MISALIGNED_INTERVAL", "勤務が時間粒度に揃っていません。", path + "/interval")
        if (
            start.astimezone(grid.timezone).date()
            != (end - timedelta(microseconds=1)).astimezone(grid.timezone).date()
        ):
            reject("UNSUPPORTED_OVERNIGHT_SHIFT", "日付をまたぐ勤務は未対応です。", path)
        for index, (a, b) in enumerate(breaks):
            if not start < a < b < end:
                reject(
                    "INVALID_BREAK",
                    "休憩は始業・終業に接しない勤務内の区間にします。",
                    f"{path}/breaks/{index}",
                )
            if (a - grid.start) % step or (b - grid.start) % step:
                reject(
                    "MISALIGNED_INTERVAL",
                    "休憩が時間粒度に揃っていません。",
                    f"{path}/breaks/{index}",
                )
        nonoverlapping(breaks, path + "/breaks")
        a, b = (start - grid.start) // step, (end - grid.start) // step
        if not grid.start <= start < end <= grid.end or not set(range(a, b)) <= available[employee]:
            if generated:
                return
            reject(
                "INVALID_CANDIDATE_AVAILABILITY",
                "勤務全体が計画期間・勤務可能時間に収まっていません。",
                path,
            )
        result.append(
            ShiftCandidate(
                identifier,
                employee,
                start.astimezone(grid.timezone).date(),
                a,
                b,
                tuple(
                    sorted(
                        ((left - grid.start) // step, (right - grid.start) // step)
                        for left, right in breaks
                    )
                ),
            )
        )

    for index, candidate in enumerate(request["shift_candidates"]):
        path = f"/shift_candidates/{index}"
        reference(candidate["employee_id"], employees, path + "/employee_id")
        start = minute_datetime(candidate["interval"]["start"], path + "/interval/start")
        end = minute_datetime(candidate["interval"]["end"], path + "/interval/end")
        breaks = [
            (
                minute_datetime(i["start"], f"{path}/breaks/{j}/start"),
                minute_datetime(i["end"], f"{path}/breaks/{j}/end"),
            )
            for j, i in enumerate(candidate["breaks"])
        ]
        add(candidate["id"], candidate["employee_id"], start, end, breaks, path)
    for index, template in enumerate(templates):
        path = f"/shift_templates/{index}"
        for j, employee in enumerate(template["employee_ids"]):
            reference(employee, employees, f"{path}/employee_ids/{j}")
        for employee, day, clock, duration, option in product(
            sorted(template["employee_ids"]),
            sorted(template["dates"]),
            sorted(template["start_times"]),
            sorted(template["duration_minutes_options"]),
            sorted(
                template["break_options"],
                key=lambda b: (b["offset_minutes"], b["duration_minutes"]),
            )
            or [None],
        ):
            start = local_start(day, clock, grid, path + "/start_times")
            try:
                end = start + timedelta(minutes=int(duration))
                breaks = (
                    []
                    if option is None
                    else [
                        (
                            start + timedelta(minutes=int(option["offset_minutes"])),
                            start
                            + timedelta(
                                minutes=int(option["offset_minutes"] + option["duration_minutes"])
                            ),
                        )
                    ]
                )
            except OverflowError:
                reject(
                    "INVALID_INTERVAL", "テンプレートの日時が表現できる範囲を超えています。", path
                )
            key = json.dumps(
                [template["id"], employee, day, clock, int(duration), option], sort_keys=True
            )
            identifier = "tmpl." + hashlib.sha256(key.encode("utf-8")).hexdigest()
            if identifier in identifiers:
                reject("DUPLICATE_ID", "明示・生成候補の ID が重複しています。", path, [identifier])
            identifiers.add(identifier)
            add(identifier, employee, start, end, breaks, path, generated=True)
    return sorted(result, key=lambda c: (c.employee_id, c.start, c.end, c.id))
