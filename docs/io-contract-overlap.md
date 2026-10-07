# 重複期間の基準比較と固定再計画の契約0.7

[Issue #75](https://github.com/omitsuhashi/schedula/issues/75)の実装。
契約0.6の実績・確定勤務・原区間と、不足総量→需要priority群→指定目的の順序を維持し、
`roster` の基準比較を新旧計画の重複期間へ限定する。0.1〜0.6のSchemaと同一期間要求は変更しない。
0.7ではcontinuityを省略した勤務計画や、旧契約の基準計画も元の契約の意味で再検証する。

## 比較と固定

旧計画期間を旧W、新しい計画期間を新Wとし、重複区間Oを比較対象にする。
同じIANAタイムゾーン名・時間粒度・枠の境界を必須とする。
重複なし、タイムゾーン変更、粒度変更は `INVALID_INPUT` / `BASELINE_WINDOW_MISMATCH`。
保存済み `baseline.source_request` と `source_solution` を新Wへ切り詰めたり書き換えたりしない。
基準の履歴・原区間・業務条件・解・`source_fixed_states` は旧W全体で再検証する。
新Wから外れた固定状態の改ざんも拒否する。

`fixed_parts[].interval` はO内のみ指定できる。
`preserve_assigned` はO内の旧非空担当枠の勤務状態と担当役割だけを固定する。
旧Wの過去部分や新しく加わる日へ固定を延長しない。
固定対象者・役割の削除、技能・勤務可能時間との衝突は `INFEASIBLE` とし、自動解除しない。
非勤務・未担当を明示固定した従業員の削除も成立不能となる。

`plan_changes` はO内の従業員ID和集合について、各枠の勤務状態
（`off` / `break` / `work`）と役割状態（役割ID / null）の差を各1と数える。
候補IDの変更、旧Wから消えた日、新Wだけに加わった日は変更に数えない。
削除・追加された従業員の非固定部分も比較する。

有効な基準付き結果の `change_summary` は既存の `slot_components` と内訳に加え、
`comparison_interval`（Oの `start` / `end`）と `slot_minutes` を必ず返す。
基準なし・解なしは従来どおりnull。
`verify` も元JSONと解から再計算し、最適性・不足最小性は認定しない。

## 事実と再計画

`rebuild` は比較用固定と変更最小化を外すが、`continuity.committed_shifts` は保持する。
新旧の実績・確定勤務に同じIDがある場合、従業員・原区間・休憩の矛盾は
`INVALID_INPUT` / `CONFLICTING_CONTINUITY`。実績へ移った同一勤務も同じ原区間で照合する。
別の有効な確定勤務と基準固定の衝突は `INFEASIBLE` と区別する。
実績の入力は利用側の確認が必要で、基準解から自動生成しない。

`make_baseline(request, solution, plan_id)` の引数は維持する。
0.7の入力・解を再検証し、W・C・実績・確定勤務・候補・業務条件をコピーする。
比較専用の入力と `plan_changes` 目的を除き、今回の固定を `source_fixed_states` へ保存する。
ネストを増やさず何度でも保存でき、次回は保存したWとの重複期間を比較する。

## 実行例

[1日スライドの入力](../examples/continuity_replan.json)は旧Wが10月5〜8日、新Wが6〜9日。
Aliceの5日の勤務60分を確認済み実績として渡し、6・7日の担当4枠を固定する。
8日の需要もAliceが担当し、新W勤務180分、過去60分、日間休息1380分、4連勤、変更量0となる。
休息・連勤の値は架空の試験条件で、就業規則の推奨値ではない。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/continuity_replan.json
uv run --locked python -m shift_schedula schema request --schema-version 0.7
```

公開変換・求解・独立検証・保存は次の順で使用する。

```python
from shift_schedula import load_json, make_baseline, solve, verify

request = load_json(open("examples/continuity_replan.json", encoding="utf-8").read())
result = solve(request)
assert result["status"] == "OPTIMAL"
checked = verify(request, result["solution"])
assert checked["status"] == "VALID"
assert checked["change_summary"]["total_changes"] == 0
baseline = make_baseline(request, result["solution"], "saved")
# 次回のRequestへbaselineを指定し、実績と確定勤務は利用側で確認して入力する。
```

30分1枠をAliceからBobへ勤務ごと交代すると、勤務変更2・役割変更2で合計4。
2枠の交代は勤務変更4・役割変更4で合計8。独立検証も同じ値を返す。
公開型は `Request07`、`Response07Success` / `Response07Failure`。
検証のコマンド・実行結果は[検証記録](evaluations/overlap-replanning.md)を参照する。
