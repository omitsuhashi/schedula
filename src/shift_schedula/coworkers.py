"""休憩・分割間の非勤務を除く勤務状態に、従業員間の必須条件を適用する。"""

from .contract import reject
from .model import reference

KINDS = {"required_coworkers", "incompatible_employees"}


def rules(request, active_groups=None):
    return [
        (i, rule)
        for i, rule in enumerate(request["constraints"])
        if rule["type"] in KINDS and (active_groups is None or f"/constraints/{i}" in active_groups)
    ]


def validate(request, grid):
    employees = {e["id"] for e in request["employees"]}
    for i, rule in rules(request):
        path = f"/constraints/{i}"
        grid.interval(rule["interval"], path + "/interval")
        if rule["type"] == "required_coworkers":
            for j, employee in enumerate(rule["coworker_ids"]):
                reference(employee, employees, f"{path}/coworker_ids/{j}")
            overlap = set(rule["employee_ids"]) & set(rule["coworker_ids"])
            if overlap:
                reject(
                    "OVERLAPPING_EMPLOYEE_SETS",
                    "対象者と同僚の集合を交差させません。",
                    path + "/coworker_ids",
                    sorted(overlap),
                )
            if type(rule["minimum_people"]) is not int:
                reject("INVALID_INTEGER", "最低人数は整数で指定します。", path + "/minimum_people")
            if rule["minimum_people"] > len(rule["coworker_ids"]):
                reject(
                    "INVALID_COWORKER_MINIMUM",
                    "最低人数は同僚集合の人数以下にします。",
                    path + "/minimum_people",
                )


def prepare(model, problem, coverage, active_groups=None):
    # 選択候補と確定勤務の既存coverageを使う。背景の重複禁止により各人は0/1になる。
    for i, rule in rules(problem.request, active_groups):
        start, end = problem.grid.interval(rule["interval"], f"/constraints/{i}/interval")
        for slot in range(start, end):
            if rule["type"] == "required_coworkers":
                coworkers = sum(sum(coverage.get((e, slot), [])) for e in rule["coworker_ids"])
                for employee in rule["employee_ids"]:
                    model.add(
                        coworkers
                        >= rule["minimum_people"] * sum(coverage.get((employee, slot), []))
                    )
            else:
                model.add(sum(sum(coverage.get((e, slot), [])) for e in rule["employee_ids"]) <= 1)


def evaluate(request, grid, coverage, fail, active_groups=None):
    # verify_shiftsが元入力と返却原区間から再構成した勤務状態。ソルバー係数は読まない。
    for i, rule in rules(request, active_groups):
        start, end = grid.interval(rule["interval"], f"/constraints/{i}/interval")
        for slot in range(start, end):
            working = [e for e in rule["employee_ids"] if slot in coverage.get(e, set())]
            if rule["type"] == "required_coworkers":
                coworkers = [e for e in rule["coworker_ids"] if slot in coverage.get(e, set())]
                if len(coworkers) >= rule["minimum_people"]:
                    continue
                for employee in working:
                    span = grid.output_interval(slot, slot + 1)
                    fail(
                        "REQUIRED_COWORKERS_VIOLATION",
                        "勤務中の対象者に必要な同僚人数が不足しています。",
                        f"/constraints/{i}",
                        [rule["id"], employee, *rule["coworker_ids"]],
                        interval_start=span["start"],
                        interval_end=span["end"],
                        actual_people=len(coworkers),
                        minimum_people=rule["minimum_people"],
                    )
            elif len(working) > 1:
                span = grid.output_interval(slot, slot + 1)
                fail(
                    "INCOMPATIBLE_EMPLOYEES_VIOLATION",
                    "同時勤務を禁止した従業員が同じ時間枠に勤務しています。",
                    f"/constraints/{i}",
                    [rule["id"], *working],
                    interval_start=span["start"],
                    interval_end=span["end"],
                    actual_people=len(working),
                    maximum_people=1,
                )
