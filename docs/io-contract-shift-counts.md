# 勤務回数の明示目標の契約0.15

[Issue #90](https://github.com/omitsuhashi/schedula/issues/90)の仕様として、0.14の必須条件と目的順を継承する。
勤務分類は[契約0.13](io-contract-shift-patterns.md)、実績と確定勤務は既存のcontinuityを使う。
有限候補と担当配置の同時最適化・原区間保持・独立検証を維持し、既存ADRの判断は変更しない。
0.1〜0.14へ新項目を渡すと拒否する。パッケージ版0.1.5とJSON契約版0.15は別の識別子である。

## 入力と目的

rosterに任意の`shift_count_balance`を1〜20件指定する。一意の`id`、`label`、
`evaluation_period`、空でない重複なしの`employee_targets`を必須とする。
各目標には既知の`employee_id`と整数0〜10,000,000の`target_count`を指定する。
未指定従業員は評価対象外、明示0は0回を望む目標である。到達不能な目標も有効なソフト目標である。

任意の`category_id`は既存の勤務分類を参照する。省略は全勤務、nullや未知参照は拒否する。
定義と`metric=shift_count_deviation`の目的を`balance_id`で1対1に対応させる。
他の指標に`balance_id`を付けない。指標の一意性は`(metric, balance_id)`であり、
既存の`duty_deviation_minutes`は`duty_id`のままとする。
0.15だけ目的数上限を46件へ広げる（通常6指標・分数評価20定義・回数評価20定義）。

完全な入力例は[履歴付き夜勤回数](../examples/shift_count_balance.json)、
全5機能の結合は[休憩交代の例](../examples/combined_conditions.json)を参照する。

## 原勤務1件を1回とする

原勤務の最初の開始日時が評価期間に入り、指定分類に該当すれば1回と数える。
分割勤務の区間数、勤務分数、夜勤明けが触れた日数、表示上の期間切断は回数にしない。
評価期間の両端はローカル00:00で、通常は計画期間W内、continuity指定時は確認済み文脈期間C内とする。
計画外の評価に必要な確認情報がなければ`INCOMPLETE_HISTORY`として拒否する。

分類は評価期間で原勤務を切る前に、元の分類区間と勤務全体から判定する。
分類区間は和集合とし、休憩・分割間の非勤務を除き、待機を含める。
実績・既知の未来確定勤務は定数、新規勤務は選択変数として一度ずつ数える。
解へ返した確定勤務を元入力から重ねて数えない。未入力の未来勤務を予測しない。

10月31日開始・11月1日終了の夜勤は10月に1回、11月に0回となる。
同じ分類と原勤務集合を使う隣接評価期間では回数の合計が保存される。
DSTでも一勤務は1回であり、分数は従来どおり実経過時間で測る。
分類区間の業務上の十分性は利用側が指定し、表示名から夜勤・祝日を補完しない。

## 求解・出力・独立検証

各対象者の`abs(actual_count-target_count)`を足した値を最小化する。
契約比率・自動均等割り・正規化・必須の回数上下限には置き換えない。
必須条件を保持し、不足合計人分→priority群の不足→利用者が指定した目的順に比較する。
上位目的が未証明なら下位目的へ進まない。勤務回数のために不足を増やさない。

`shift_count_balance_summary`は定義順で`id`、`label`、`evaluation_period`、
指定時の`category_id`、`unit=shifts`、`scale=absolute_deviation`、`normalized=false`、
`total_deviation_count`、対象者ごとの`target_count`・`actual_count`・`deviation_count`を返す。
0回の人も省略しない。対象外、解なし、不正解ではnullとなる。目的にも`balance_id`を返す。

公開`verify`は元Requestと返却原勤務から再計算し、ソルバーの候補係数や目的値を使わない。
探索も最適性認定も行わず、`proven_optimal`と不足最小性はfalseとなる。
Responseの改ざん検査でも回数集計・目的参照・評価値の不一致を拒否する。
`make_baseline`は元の分類と目標を保持し、次回の分類・目標変更を勤務状態の変更量へ加算しない。
診断ではソフト目標を不可能性の条件グループに含めず、必須条件・実績・確定勤務を保持する。

需要のない勤務を目標のために選ぶことがある。待機勤務を抑えたい場合は
`scheduled_minutes`を回数目標より前に置く。明示0でも必須需要・固定勤務は優先する。

## 入力から再計画まで

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/shift_count_balance.json
uv run --locked --extra cp-sat python -m shift_schedula schema request --schema-version 0.15
uv run --locked --extra cp-sat python -m shift_schedula schema verification --schema-version 0.15
```

以下のPython例は不足120人分の計画を確認し、担当を消した手修正を検証で拒否した後、
元の有効な計画を基準へ保存して固定再計画する。末尾の`verify`にもOR-Toolsは不要である。

```python
import copy
import json
from pathlib import Path
from shift_schedula import make_baseline, solve, verify

request = json.loads(Path("examples/combined_conditions.json").read_text(encoding="utf-8"))
result = solve(request)
assert result["status"] == "PARTIAL" and result["verification"]["valid"]
print(result["shortage_summary"], result["day_count_summary"], result["shift_count_balance_summary"])
edited = copy.deepcopy(result["solution"])
edited["assignments"] = []
assert verify(request, edited)["status"] == "INVALID_PLAN"
Path("test-results").mkdir(exist_ok=True)
Path("test-results/combined.solution.json").write_text(json.dumps(result["solution"]), encoding="utf-8")
request["baseline"] = make_baseline(request, result["solution"], "confirmed_partial")
request["replan_mode"] = "preserve_assigned"
replanned = solve(request)
assert verify(request, replanned["solution"])["status"] == "PARTIAL"
```

```sh
uv run --locked python -m shift_schedula verify examples/combined_conditions.json test-results/combined.solution.json
```

上のCLI検証は有効でも不足が残るため終了コード2となる。
検証結果と制限は[追加勤務条件の結合・規模評価](evaluations/added-conditions.md)に記録する。
