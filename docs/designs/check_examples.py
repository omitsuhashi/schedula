"""設計例の検算。新しいschedulaの機能を実装・検証するものではない。"""

import argparse
from datetime import datetime
from itertools import product


def minutes(start, end):
    return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60)


def check_numbers():
    before = minutes("2026-10-31T22:00:00+09:00", "2026-11-01T00:00:00+09:00")
    after = minutes("2026-11-01T00:00:00+09:00", "2026-11-01T06:00:00+09:00") - 60
    assert (before, after, before + after) == (120, 300, 420)
    assert minutes("2026-11-01T06:00:00+09:00", "2026-11-01T17:00:00+09:00") == 660
    assert minutes("2026-11-01T21:00:00+09:00", "2026-11-02T08:00:00+09:00") == 660
    assert minutes("2026-11-01T21:30:00+09:00", "2026-11-02T08:00:00+09:00") == 630
    assert minutes("2026-10-25T01:00:00+02:00", "2026-10-25T04:00:00+01:00") - 30 == 210
    assert 2 * 480 + 3 * 480 == 2400
    assert 4 * 480 - (2400 - 2 * 480) == 480
    assert (120 * 1800, 300 * 1800, 420 * 1800) == (216000, 540000, 756000)
    assert (1800 * 60, 2400 * 60) == (108000, 144000)
    assert 1800 * 17 == 30600 and 30600 // 60 == 510
    # 1枠の交代は旧・新の2人、それぞれ勤務・役割の2成分が変わる。
    assert 1 * 2 * 2 == 4 and 2 * 2 * 2 == 8
    # 1分を1要素とする独立な集合で、重複区間の二重計上を検査する。
    assert len(set(range(240)) | set(range(120, 360))) == 360
    # 2日、各人1日1勤務。1はAlice夜、0はBob夜。残りの人が昼を担当。
    plans = []
    for nights in product((0, 1), repeat=2):
        alice = 240 * sum(nights)
        bob = 480 - alice
        deviation = abs(alice - 240) + abs(bob - 240)
        plans.append((deviation, nights))
    assert dict((n, d) for d, n in plans)[(1, 1)] == 480
    assert {n for d, n in plans if d == min(v[0] for v in plans)} == {(0, 1), (1, 0)}
    # 7日のAlice夜を固定し、8日の昼を避ける。
    choices = [(d, 240 * (1 - n[1]), n) for d, n in plans if n[0] == 1]
    assert min(choices) == (0, 240, (1, 0))
    assert min(choices, key=lambda row: (row[1], row[0])) == (480, 0, (1, 1))
    assert abs(240 - 240) + abs(240 - 240) == 0
    assert abs(480 - 240) + abs(0 - 240) == 480


GROUPS = ("alice_min", "alice_max", "bob_min", "bob_max", "irrelevant")


def satisfied(group, x, y):
    return {
        "alice_min": x == 1,
        "alice_max": x == 0,
        "bob_min": y == 1,
        "bob_max": y == 0,
        "irrelevant": x + y <= 2,
    }[group]


def feasible(groups):
    return any(all(satisfied(g, x, y) for g in groups) for x, y in product((0, 1), repeat=2))


def shrink(groups, query):
    current = list(groups)
    witnesses = set()
    for group in groups:
        trial = [g for g in current if g != group]
        status = query(trial)
        if status == "INFEASIBLE":
            current = trial
        elif status == "FEASIBLE":
            witnesses.add(group)
        else:
            assert status == "UNKNOWN"
    return current, all(g in witnesses for g in current)


def check_conflicts():
    def query(groups):
        return "FEASIBLE" if feasible(groups) else "INFEASIBLE"

    core, minimal = shrink(GROUPS, query)
    assert core == ["bob_min", "bob_max"] and minimal
    assert not feasible(core) and all(
        feasible([g for g in core if g != removed]) for removed in core
    )
    reverse, minimal = shrink(tuple(reversed(GROUPS)), query)
    assert set(reverse) == {"alice_min", "alice_max"} and minimal
    core, minimal = shrink(
        ("alice_min", "alice_max", "irrelevant"),
        lambda groups: "UNKNOWN" if groups == ["alice_min", "irrelevant"] else query(groups),
    )
    assert core == ["alice_min", "alice_max"] and not minimal


def check_cp_sat():
    from ortools import __version__
    from ortools.sat.python import cp_model

    def build(groups, assumptions=False):
        model = cp_model.CpModel()
        x, y = model.new_bool_var("alice"), model.new_bool_var("bob")
        expressions = (x == 1, x == 0, y == 1, y == 0, x + y <= 2)
        labels = {}
        for group, expression in zip(GROUPS, expressions, strict=True):
            if group not in groups:
                continue
            condition = model.add(expression)
            if assumptions:
                flag = model.new_bool_var(group)
                condition.only_enforce_if(flag)
                model.add_assumption(flag)
                labels[flag.index] = group
        return model, labels, x, y

    def solve_model(model):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        return solver, solver.solve(model)

    def query(groups):
        model, _, x, y = build(groups)
        solver, status = solve_model(model)
        if status == cp_model.INFEASIBLE:
            assert not feasible(groups)
            return "INFEASIBLE"
        if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            assert all(satisfied(g, solver.value(x), solver.value(y)) for g in groups)
            return "FEASIBLE"
        raise AssertionError(f"検算が未完了: {solver.status_name(status)}")

    model, labels, _, _ = build(GROUPS, assumptions=True)
    solver, status = solve_model(model)
    assert status == cp_model.INFEASIBLE
    assumed = [labels[i] for i in solver.sufficient_assumptions_for_infeasibility()]
    assert not feasible(assumed)
    deleted, minimal = shrink(GROUPS, query)
    assert minimal and not feasible(deleted)
    assert query(deleted) == "INFEASIBLE"
    # 固定版ではno_overlapの仮定も使える。無効化時の解も確認する。
    overlap = cp_model.CpModel()
    first = overlap.new_fixed_size_interval_var(0, 60, "first")
    second = overlap.new_fixed_size_interval_var(30, 60, "second")
    flag = overlap.new_bool_var("rest")
    overlap.add_no_overlap([first, second]).only_enforce_if(flag)
    assert not overlap.validate()
    overlap.add_assumption(flag)
    _, status = solve_model(overlap)
    assert status == cp_model.INFEASIBLE
    overlap.clear_assumptions()
    overlap.add(flag == 0)
    _, status = solve_model(overlap)
    assert status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    print(f"OR-Tools {__version__}: 仮定の十分集合={assumed}, 削除の包含極小集合={deleted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cp-sat", action="store_true")
    args = parser.parse_args()
    check_numbers()
    check_conflicts()
    if args.cp_sat:
        check_cp_sat()
    print("設計例の検算に成功しました。新機能の動作検証ではありません。")
