# 契約0.9の勤務費用と指定区間の目標偏差

[Issue #77](https://github.com/omitsuhashi/schedula/issues/77)と
[Issue #78](https://github.com/omitsuhashi/schedula/issues/78)を契約 `0.9` にまとめた。
0.8の継続計画・再計画・需要priority・診断を引き継ぎ、`roster` に評価項目を追加する。
既定Schemaは0.1、旧0.1〜0.8の受理項目と意味は維持する。新項目を旧版へ渡すと拒否する。

目的順は、不足合計人分 → priorityの高い需要群の不足 → `objectives` の配列順。
上位の最適性が未証明なら後続を探索せず、費用や偏差の最適性も主張しない。
必須条件・明示固定・`preserve_assigned` の担当済み枠を評価のために解除しない。

## 勤務費用

`costs` と metricが `scheduled_cost` の目的を対にして指定する。

```json
{
  "costs": {
    "currency": "JPY",
    "units_per_currency": 60,
    "employee_rates": [
      {"employee_id": "alice", "units_per_minute": 1800},
      {"employee_id": "bob", "units_per_minute": 2400}
    ]
  },
  "objectives": [{"id": "cost", "metric": "scheduled_cost"}]
}
```

これは部分例。実行には[完全な架空入力](../examples/scheduled_cost.json)を使う。
`currency` は大文字英字3文字、倍率は1〜1,000,000、分単価は0〜1,000,000,000の整数。
候補がない人も含め全登録従業員の単価を要求し、未知・重複・欠落を拒否する。
bool・null・浮動小数・負数は拒否し、明示0単価は受理する。
従業員ごとの通貨・倍率は持たず、未知項目として拒否する。
テンプレート候補にも同じ従業員単価を使う。

費用は `sum(計画内勤務分数 * 従業員の分単価)`。
待機を含み、休憩と分割勤務間の非勤務を除く。継続計画の原区間は保持し、
計画期間Wと交差する分だけを課金する。過去実績・未来部分は計画内費用へ加算しない。
倍率60なら、60分・単価1800は108000費用単位＝1800通貨単位。
17分は30600費用単位、単価1001の1分は正確に1001/60通貨単位となる。
途中の丸めは行わない。0.9以降は1分粒度も受理し、従来の5/10/15/20/30/60分と
時間枠数3000・従業員×枠×役割100万の上限を維持する。

全候補と確定勤務のW内費用をPython整数で足した保守的上界は `2**53-1` 以下。
排他的な候補もすべて足すため、実際の解が小さくても拒否する場合がある。
超過はモデル構築前に `INTEGER_EXPRESSION_LIMIT`、pointer `/costs` で返す。
内部整数式の `2**60-1` も維持する。

`cost_summary` は対象外ならnull。対象なら `currency`、`units_per_currency`、
`evaluation_period`（W）、`total_units`、`employees` を返す。
各人に `employee_id`、`units_per_minute`、`scheduled_minutes`、`cost_units` を載せ、
勤務0の人も省略しない。`scheduled_cost` の値は `total_units` と一致する。

`make_baseline` は旧単価を元Requestとともに保持して旧解を再検証する。
再計画は新単価で評価し、勤務・担当が同じなら単価だけ変えても `plan_changes=0`。
基準だけに残る従業員へ新単価を要求しない。新旧の費用を比較する際は、
利用側が通貨・倍率・期間・単価を揃えて再評価する。
給与・税・為替・有給休憩・日額・期間別単価・段階料金は扱わない。

## 指定区間の勤務分数の偏り

`duty_balance` に1〜20定義を指定する。各定義は `id`、`label`、`evaluation_period`、
1〜1000件の `intervals`、1〜250人の `employee_targets` を持つ。
評価期間はW内の正の半開区間、各区間はその内側で計画開始からの粒度に揃える。
目標 `target_minutes` は0〜10,000,000の整数。未知・重複対象、空の対象集合、
bool・null・浮動小数・負数を拒否する。達成不能な目標は有効なソフト目標として受理する。

同一定義の区間は重複・隣接・再掲を和集合にまとめる。異なる定義同士の重複は許す。
22:00〜02:00と00:00〜04:00は360分として数える。
未指定者は対象外、明示0は勤務0分を望む目標。祝日や夜勤時間帯は自動判定しない。

metricが `duty_deviation_minutes` の目的に `duty_id` を必須指定する。
定義と目的は1対1。未知参照・同一定義の複数目的・他metricの `duty_id` を拒否する。
このmetricだけ `(metric, duty_id)` を一意キーとし、他metricの重複禁止は維持する。
目的数は通常6metricと20定義を収める26件まで。各定義は指定目的の位置で最適化する。

実分数は休憩を除く勤務と区間の和集合の交差、偏差は `abs(実分数 - 目標)`。
対象者の偏差合計を最小化する。待機は含み、分割間の非勤務を除く。
DSTでは時計表示差でなくUTC上の実経過分数を使う。係数・偏差の保守的上界は
モデル構築前に `2**60-1` 以下と確認する。
目標を満たすだけの待機勤務を抑えたい場合は `scheduled_minutes` との優先順を明示する。
総勤務量の公平性 `fairness_deviation_minutes` の意味は変えない。

`duty_balance_summary` は対象外ならnull、対象なら定義順の配列。
各要素に `duty_id`、`label`、`evaluation_period`、併合した `intervals`、
`unit: "minutes"`、`scale: "absolute_deviation"`、`normalized: false`、
`total_deviation_minutes`、対象者の `employee_id` / `target_minutes` / `actual_minutes` /
`deviation_minutes` を返す。Responseの目的にも `duty_id` を保持する。
過去を含む評価は[契約0.10](io-contract-duty-continuity.md)を指定する。0.9はW外の評価を拒否する。

## 実行と独立検証

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/scheduled_cost.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/duty_balance.json
uv run --locked python -m shift_schedula schema request --schema-version 0.9
uv run --locked python -m shift_schedula schema verification --schema-version 0.9
```

費用例はAlice・勤務60分・費用108000・選好60。目的配列を逆にするとBob・選好0・費用144000。
夜勤例は7日Alice夜を固定し、8日は交代して夜勤240/240分・偏差0・選好240。
選好を偏差より先に置くとAlice両夜・偏差480・選好0。
両案の各人勤務量480分と費用2016000は同じ。

公開 `verify(request, solution)` はOR-Toolsを呼ばず、元の勤務・休憩・入力区間・単価から
両集計と目的値を再計算する。モデルの係数や正規化済み区間は参照しない。
集計・目的・勤務の改ざんは元RequestとResponseの照合で検出する。
独立検証は最適性・不足最小性を認定せず、証明フラグをfalseで返す。
実行環境・検証結果は[検証記録](evaluations/roster-metrics.md)を参照する。
