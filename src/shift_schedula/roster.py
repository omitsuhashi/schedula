import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from itertools import product

from .contract import reject
from .model import ShiftCandidate, minute_datetime, nonoverlapping, reference, unique


def validate_history(request, grid):
    extended = request["schema_version"] in {
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.10",
        "0.11",
        "0.12",
    }
    first_day = grid.start.astimezone(grid.timezone).date().toordinal()
    for index, employee in enumerate(request["employees"]):
        path = f"/employees/{index}/history"
        if "history" not in employee:
            reject("MISSING_HISTORY", "roster は空履歴も明示します。", path, [employee["id"]])
        history = employee["history"]
        count = int(history["consecutive_work_days_before_window"])
        last = history["last_shift_end"]
        if last is None:
            if count or (extended and history["last_work_day"] is not None):
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
            if extended:
                if history["last_work_day"] is None:
                    reject("INVALID_HISTORY", "最終勤務がある場合は勤務日を明示します。", path)
                work_day = date.fromisoformat(history["last_work_day"]).toordinal()
                if work_day >= first_day or work_day > last_day:
                    reject("INVALID_HISTORY", "勤務日は計画前かつ最終終了より前にします。", path)
                last_day = work_day
        except OverflowError:
            reject("INVALID_HISTORY", "最終勤務日を表現できません。", path)
        if (last_day == first_day - 1) != (count > 0) or count >= first_day:
            reject("INVALID_HISTORY", "最終勤務日と直前日までの連勤数が一致しません。", path)


def local_start(day, clock, grid, path):
    try:
        naive = datetime.fromisoformat(f"{day}T{clock}")
        instants = {
            aware.astimezone(UTC)
            for fold in (0, 1)
            if (aware := naive.replace(tzinfo=grid.timezone, fold=fold))
            .astimezone(UTC)
            .astimezone(grid.timezone)
            .replace(tzinfo=None)
            == naive
        }
    except ValueError:
        reject("INVALID_TEMPLATE_TIME", "テンプレートの時刻は HH:MM で指定します。", path)
    except OverflowError:
        reject(
            "INVALID_TEMPLATE_TIME", "タイムゾーン変換で日時が表現できる範囲を超えています。", path
        )
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
    extended = request["schema_version"] in {
        "0.2",
        "0.3",
        "0.4",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "0.10",
        "0.11",
        "0.12",
    }
    employees = {e["id"]: e for e in request["employees"]}
    available = (
        {}
        if request.get("continuity")
        else {
            e["id"]: {
                slot
                for index, interval in enumerate(e["availability"])
                for a, b in [grid.interval(interval, f"/employees/{e['id']}/availability/{index}")]
                for slot in range(a, b)
            }
            for e in request["employees"]
        }
    )
    if request.get("continuity"):
        from .continuity import availability, context_bounds

        absolute_available = availability(request, grid)
        bounds = context_bounds(request, grid)
    identifiers = unique(request["shift_candidates"], "id", "/shift_candidates")
    templates = request.get("shift_templates", [])
    unique(templates, "id", "/shift_templates")
    result = []

    def add(identifier, employee, segments, path, generated=False):
        if request.get("continuity"):
            from .continuity import candidate

            value = candidate(
                identifier,
                employee,
                segments,
                grid,
                bounds,
                absolute_available[employee],
                path,
                generated=generated,
            )
            if value is not None:
                result.append(value)
            return
        step = timedelta(minutes=grid.slot_minutes)
        if not 1 <= len(segments) <= 4:
            reject("INVALID_SEGMENTS", "勤務区間数は1〜4件にします。", path + "/segments")
        slots, eligible = [], True
        for index, (start, end, breaks) in enumerate(segments):
            segment_path = f"{path}/segments/{index}" if extended else path
            if start >= end:
                reject("INVALID_INTERVAL", "勤務は正の区間にします。", segment_path + "/interval")
            if (start - grid.start) % step or (end - grid.start) % step:
                reject(
                    "MISALIGNED_INTERVAL",
                    "勤務が時間粒度に揃っていません。",
                    segment_path + "/interval",
                )
            if index and start <= segments[index - 1][1]:
                reject(
                    "INVALID_SEGMENT_ORDER",
                    "勤務区間は時刻順で正の間隔を空けます。",
                    segment_path + "/interval",
                )
            if not extended and (
                start.astimezone(grid.timezone).date()
                != (end - timedelta(microseconds=1)).astimezone(grid.timezone).date()
            ):
                reject("UNSUPPORTED_OVERNIGHT_SHIFT", "日付をまたぐ勤務は未対応です。", path)
            for j, (a, b) in enumerate(breaks):
                break_path = f"{segment_path}/breaks/{j}"
                if not start < a < b < end:
                    reject(
                        "INVALID_BREAK",
                        "休憩は始業・終業に接しない勤務内の区間にします。",
                        break_path,
                    )
                if (a - grid.start) % step or (b - grid.start) % step:
                    reject("MISALIGNED_INTERVAL", "休憩が時間粒度に揃っていません。", break_path)
            nonoverlapping(breaks, segment_path + "/breaks")
            a, b = (start - grid.start) // step, (end - grid.start) // step
            eligible &= (
                grid.start <= start < end <= grid.end and set(range(a, b)) <= available[employee]
            )
            slots.append(
                (
                    a,
                    b,
                    tuple(
                        sorted(
                            ((x - grid.start) // step, (y - grid.start) // step) for x, y in breaks
                        )
                    ),
                )
            )
        if not eligible:
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
                segments[0][0].astimezone(grid.timezone).date(),
                slots[0][0],
                slots[-1][1],
                tuple(interval for _, _, rests in slots for interval in rests),
                tuple(slots) if extended else (),
            )
        )

    for index, candidate in enumerate(request["shift_candidates"]):
        path = f"/shift_candidates/{index}"
        reference(candidate["employee_id"], employees, path + "/employee_id")
        segments = []
        for j, segment in enumerate(candidate["segments"] if extended else [candidate]):
            segment_path = f"{path}/segments/{j}" if extended else path
            segments.append(
                (
                    minute_datetime(segment["interval"]["start"], segment_path + "/interval/start"),
                    minute_datetime(segment["interval"]["end"], segment_path + "/interval/end"),
                    [
                        (
                            minute_datetime(b["start"], f"{segment_path}/breaks/{k}/start"),
                            minute_datetime(b["end"], f"{segment_path}/breaks/{k}/end"),
                        )
                        for k, b in enumerate(segment["breaks"])
                    ],
                )
            )
        add(candidate["id"], candidate["employee_id"], segments, path)
    for index, template in enumerate(templates):
        path = f"/shift_templates/{index}"
        for j, employee in enumerate(template["employee_ids"]):
            reference(employee, employees, f"{path}/employee_ids/{j}")
        if extended:
            shapes = [
                [
                    {
                        **s,
                        "breaks": sorted(
                            s["breaks"], key=lambda b: (b["offset_minutes"], b["duration_minutes"])
                        ),
                    }
                    for s in option
                ]
                for option in template["segment_options"]
            ]
        options = (
            sorted(shapes, key=lambda s: json.dumps(s, sort_keys=True))
            if extended
            else list(
                product(
                    sorted(template["duration_minutes_options"]),
                    sorted(
                        template["break_options"],
                        key=lambda b: (b["offset_minutes"], b["duration_minutes"]),
                    )
                    or [None],
                )
            )
        )
        for employee, day, clock, option in product(
            sorted(template["employee_ids"]),
            sorted(template["dates"]),
            sorted(template["start_times"]),
            options,
        ):
            start = local_start(day, clock, grid, path + "/start_times")
            try:
                if extended:
                    if not option or option[0]["offset_minutes"] != 0:
                        reject(
                            "INVALID_TEMPLATE_SEGMENTS",
                            "最初の勤務区間のオフセットは0にします。",
                            path + "/segment_options",
                        )
                    shape = option
                else:
                    duration, rest = option
                    shape = [
                        {
                            "offset_minutes": 0,
                            "duration_minutes": duration,
                            "breaks": [rest] if rest else [],
                        }
                    ]
                segments = [
                    (
                        a := start + timedelta(minutes=int(s["offset_minutes"])),
                        a + timedelta(minutes=int(s["duration_minutes"])),
                        [
                            (
                                a + timedelta(minutes=int(b["offset_minutes"])),
                                a
                                + timedelta(
                                    minutes=int(b["offset_minutes"] + b["duration_minutes"])
                                ),
                            )
                            for b in s["breaks"]
                        ],
                    )
                    for s in shape
                ]
            except OverflowError:
                reject(
                    "INVALID_INTERVAL", "テンプレートの日時が表現できる範囲を超えています。", path
                )
            # 0.3でも候補の構造は同じ。0.2の識別子を保持して基準計画と照合する。
            key = json.dumps(
                ["0.2", template["id"], employee, day, clock, option]
                if extended
                else [template["id"], employee, day, clock, int(duration), rest],
                sort_keys=True,
            )
            identifier = "tmpl." + hashlib.sha256(key.encode("utf-8")).hexdigest()
            if identifier in identifiers:
                reject("DUPLICATE_ID", "明示・生成候補の ID が重複しています。", path, [identifier])
            identifiers.add(identifier)
            add(identifier, employee, segments, path, generated=True)
    return sorted(result, key=lambda c: (c.employee_id, c.start, c.end, c.id))
