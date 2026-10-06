# 目標勤務量と基準計画からの再計画

契約0.2の `roster` では、需要・担当資格・勤務可能時間・勤務ルールを守ったうえで、
明示した目標勤務量との偏差と、基準計画からの変更を目的順序で最小化する。
契約0.1の受理構造と意味は変更しない。

```sh
uv run --locked --extra cp-sat python -m schedula solve examples/fairness.json
uv run --locked --extra cp-sat python -m schedula solve examples/replan.json
```

`fairness.json` は1役割の12時間分の需要を、Alice4時間・Bob8時間へ配置する例である。
目標はそれぞれ240分・480分、目的順序は `fairness_deviation_minutes` → `scheduled_minutes`。
探索を完了したときの値は `[0, 720]`。`fairness_summary.employees` から各人の目標・
実際の勤務量・絶対偏差を確認できる。待機を勤務量に含み、休憩と分割間の非勤務は含まない。

目標0は勤務禁止にせず、目標の粒度一致や達成可能性も必須にしない。
対象外の従業員の目標を補完せず、目標と勤務量の差の絶対値だけを合計する。
評価期間は計画期間と同じ実時刻の区間とする。比率による正規化、給与・過去実績の集計は行わない。

`replan.json` はAliceの6日20:00〜22:00と7日02:00〜04:00の分割勤務を基準にする。
前半の勤務・担当を固定し、後半の勤務可能時間がなくなったAliceの担当をBobへ移す。
旧入力と旧解が有効であることを確認し、新条件に合わなくなった部分だけを再計画する。
目的順序は `plan_changes` → `fairness_deviation_minutes` → `scheduled_minutes`、
探索を完了したときの値は `[16, 0, 240]` となる。

変更量は各従業員・各時間枠の勤務状態（`off` / `work` / `break`）と担当状態を比較する。
この例は後半4枠で、AliceとBobの勤務・担当の2成分ずつが変わるため16単位である。
候補IDや表示名だけが変わっても変更0。追加・削除された従業員も比較対象に含め、
変更件数や変更分数へ換算しない。内訳は `change_summary` に返す。

`baseline` には照合用 `plan_id` と、旧契約0.1または0.2の完結した `source_request`・
検証済みの `source_solution` を指定する。旧入力に `baseline`・`diagnosis` を入れず、
新旧の計画期間・タイムゾーン・粒度を一致させる。不正な旧入力・旧解は `INVALID_INPUT`。
固定部分は旧入力に存在する従業員の `work` / `role` 成分を必須条件として保持する。
非勤務・未担当・休憩も固定でき、目的から `plan_changes` を外しても固定は適用する。
有効な旧状態を新条件で再現できなければ `INFEASIBLE` とし、固定を自動解除しない。

返す解の勤務量・変更量・固定状態は、候補の選択変数から独立して検証する。
探索予算内に全目的を証明できなければ検証済み `FEASIBLE`、解がなければ `UNKNOWN`。
状態と目的ごとの `proven_optimal` を確認し、未証明の解を最適な計画とは説明しない。
