# 実績と確定勤務を引き継ぐ契約0.6

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #74](https://github.com/omitsuhashi/schedula/issues/74)の実装。
0.6は0.5の需要優先度と0.4の勤務条件・未完成の計画・公開検証に、`roster` 専用の `continuity` を加える。
不足総量→priority群ごとの不足→指定目的の順序を維持する。
0.1〜0.5のSchemaと意味は変更しない。`continuity` を省略すれば従来どおり
全従業員の `history` と計画期間内の勤務候補を使う。

## 入力する事実

計画期間をW、文脈期間をCとする。CはWを包含し、同じタイムゾーンの00:00を両端に持つ。
日時は明示オフセット付き、整数分の半開区間。W内の状態遷移は現在の時間粒度に揃え、
W外の実績・勤務・休憩は整数分のまま保持する。

`continuity.context_window` にCの `start` / `end` を指定する。
`continuity.employees` には登録従業員と同じ集合を重複なく指定する。
各行の必須項目は以下のとおり。

| 項目 | 意味 |
| --- | --- |
| `employee_id` | 登録従業員のID |
| `before_context` | C直前の `last_shift_end`、`last_work_day`、`consecutive_work_days_before_window`。勤務なしも明示 |
| `past_complete: true` | C開始からW開始までの実績を確認済みと宣言 |
| `actual_shifts` | C内に開始しW開始までに終わった全実績。勤務なしなら空配列 |
| `commitments_complete: true` | C内の既知の確定勤務をすべて入力したと宣言 |
| `committed_shifts` | W開始より後に終わる確定勤務。開始境界をまたぐ勤務も原区間を一度だけ記録 |

実績・確定勤務は `id` と、既存の1〜4件の `segments` を持つ。
休憩は各区間内にあり、出退勤には接しない。勤務日は最初の区間の開始日から導出する。
実績は現在の技能・勤務可能時間で再認定しない。確定勤務のW開始以降の部分は、
休憩を含む各区間全体が現在の勤務可能時間に収まる必要がある。
勤務可能時間と期間別勤務量の評価区間は、continuity指定時だけCへ広げられる。

`employees[].history` との併記、未確認・欠落、ID重複、事実の勤務日・外側区間の重複、
C外の勤務、実績とアンカーの時間矛盾を拒否する。確認フラグは供給元の宣言であり、
入力されていない勤務の存在や情報の真正性を証明するものではない。

## 候補・集計・必須条件

新規候補はW内に開始し、全区間がCと勤務可能時間内に収まる。W終了後へ続く夜勤も選択できる。
テンプレートはW内の開始だけを展開し、期間・勤務可能時間から外れる候補を除く。
明示候補の同じ不備は入力エラーにする。確定勤務は候補集合と独立した必須状態であり、
候補を削除しても解除されない。確定するのは勤務状態で、担当役割は今回の求解で決める。

勤務分数はUTC上の実経過時間を区間へ投影する。待機を含み、休憩と分割間の非勤務を除く。
`scheduled_minutes`、`max_scheduled_minutes`、公平性、選好はW内だけを集計する。
`scheduled_minutes_bounds.interval` はC内を指定でき、実績・確定勤務・選択勤務を一度ずつ足す。
Cより前の勤務量を履歴要約から推定しない。

1人1勤務日、外側区間の非重複は全勤務列に適用する。
休息は前の最終終了から次の最初の開始まで、連勤は勤務開始日で数える。
C直前のアンカーから未来の確定勤務まで接続し、現在・未来へ続く違反を検査する。
過去だけの休息・連勤を現在のルールで遡及判定しない。
未来の未入力勤務とC終了より先の条件は検証対象外。
需要・担当資格・担当時間・担当切替はW内だけに適用する。

## 結果と検証

`solution.shifts` はWと外側区間が交差する勤務を、休憩を含む全 `segments` のまま返す。
選択勤務は `candidate_id`、確定勤務は `committed_shift_id` を持ち、両者は排他的。
分割の間隔だけがWに重なる場合も原区間を返す。W外だけの確定勤務は解へ複製せず、
Requestから条件を検証する。担当配置・不足はW内だけを返す。

求解結果と `verify` 結果には `continuity_summary` を追加する。
continuityなし、解なし、不正解の場合はnull。有効な計画ではC、Wと各従業員の以下の値を返す。

- `historical_minutes`: C内のW開始前の勤務分数。
- `planned_minutes`: W内の勤務分数。
- `outside_planning_minutes`: W終了後、C終了までの勤務分数。
- `committed_shift_ids`: 参照した確定勤務ID。W外だけの勤務も含む。

3期間の合計と元の勤務分数の合計が一致することを検査する。
独立検証は元JSONと返却 `segments` から再集計し、モデルの候補表・係数を参照しない。
欠落した確定勤務、勤務日・参照・区間・休憩の改ざんを検出する。
`verify` は有効性と不足を確認するが、最適性・不足最小性は認定しない。

| 状況 | 状態 |
| --- | --- |
| 確認・履歴欠落、集計範囲の履歴不足 | `INVALID_INPUT` / `INCOMPLETE_HISTORY` |
| 事実のID・勤務日・外側区間の重複、history併記 | `INVALID_INPUT` / `CONFLICTING_CONTINUITY` |
| アンカー・実績・確定勤務の期間矛盾 | `INVALID_INPUT` / `INVALID_CONTINUITY_INTERVAL` |
| 有効な事実と勤務可能時間・上限・休息・連勤・固定状態の衝突 | `INFEASIBLE` |
| 需要以外を満たし需要だけ不足 | `PARTIAL` |

診断の十分集合では、実績と確定勤務を `ACTUAL_SHIFT_BACKGROUND` / `COMMITTED_SHIFT_BACKGROUND`、
アンカーを `HISTORY_BACKGROUND` として明示する。自動で事実を削除・緩和しない。

## 実行例

[月末夜勤](../examples/continuity_month.json)は全420分を過去120分・W内300分へ分け、
未来の確定勤務60分を別集計する。[週途中](../examples/continuity_week.json)は実績960分と
選択勤務1440分で週上限2400分を守り、不足480人分を `PARTIAL` として返す。
同率解では不足日が異なる場合がある。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/continuity_month.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/continuity_week.json
uv run --locked python -m shift_schedula schema request --schema-version 0.6
```

Pythonの入力型は `Request06`、勤務結果は `ContinuitySolution`。
`make_baseline(request, solution, plan_id)` の引数は変更せず0.6にも対応する。
元のC・実績・確定勤務をコピーして再検証する。同一Wの基準比較・固定状態は使用できる。
0.6は期間不一致を拒否する。重複期間へWを移す比較・固定再計画は
[契約0.7](io-contract-overlap.md)を指定する。
計画から実績への自動変換は追加しない。

検証条件と実行結果は[継続計画の検証記録](evaluations/continuity.md)を参照する。
