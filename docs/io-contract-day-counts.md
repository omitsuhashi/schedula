# 契約0.11の勤務日数と完全休日数

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #86](https://github.com/omitsuhashi/schedula/issues/86)に基づき、契約0.10を継承して
勤務分数から独立した日数の必須条件を追加する。`schema_version: "0.11"` を指定する。
0.1〜0.10のSchemaと日数・勤務量・不足の意味は変更しない。パッケージ版は0.1.5のままである。

## 入力

`roster.constraints` に `work_days_bounds` または `days_off_bounds` を指定する。
各条件は `id`、`type`、一意で空でない `employee_ids`、`interval` と、
`min_days` / `max_days` の少なくとも一方を持つ。対象者ごとに同じ上下限を適用する。
日数は0〜10,000,000の整数。省略した側は無制約、null・bool・浮動小数・
未知項目・不明参照・重複ID・下限が上限を超える入力は拒否する。
実際の日数や候補集合で達成できない下限は入力不正にせず、求解時に `INFEASIBLE` とする。

```json
{
  "id": "weekly_days",
  "type": "work_days_bounds",
  "employee_ids": ["alice"],
  "interval": {
    "start": "2026-10-05T00:00:00+09:00",
    "end": "2026-10-12T00:00:00+09:00"
  },
  "min_days": 3,
  "max_days": 4
}
```

これは条件1件の部分例。実行には[7日間の完全な架空入力](../examples/day_counts.json)を使う。
月8日以上の完全休日は、月初から翌月初までの `days_off_bounds` と `min_days: 8` で指定する。
固定の希望休は既存の勤務可能時間、分数上下限は `scheduled_minutes_bounds` を使う。

評価期間の両端は `planning_window.timezone` のローカル00:00とし、正の半開区間にする。
通常は計画期間内。確認済み `continuity` があれば文脈期間の開始から計画期間の終了まで使える。
必要な過去が未確認または文脈開始より前なら `INCOMPLETE_HISTORY`。
計画終了より後の評価は、文脈期間に含まれていても `INVALID_DAY_COUNT_INTERVAL`。
未来の未確定日を完全休日として推定せず、必要な未来日は計画期間へ含める。

## 数え方

| 指標 | 定義 |
| --- | --- |
| `work_days` | 原勤務の最初の区間が開始したローカル日付のうち、評価期間内にある日数 |
| `occupied_days` | 評価期間の各暦日のどこかに原勤務区間が正の時間重なる日数 |
| `days_off` | 評価期間のローカル暦日数から `occupied_days` を引いた完全休日数 |

分割勤務も勤務日は1日。夜勤が翌日に触れても勤務日は開始日の1日である。
休憩も原勤務区間内なので、その日の全勤務時間が休憩でも完全休日にはしない。
分割間の非勤務には勤務区間がなく、丸1日の空白があれば完全休日にできる。
終端00:00は翌日を占有しない。複数の勤務が同じ暦日に触れても占有は1日である。
DSTの23/25時間の日も暦日数は1とし、実経過時間を24時間で割らない。

確認済み過去実績・既知の確定勤務・選択勤務を原区間で一度だけ数える。
評価開始より前に開始して評価期間へ伸びる夜勤は勤務日を加算せず、占有日を加算する。
履歴要約の連勤数・最終勤務時刻から過去の勤務日数は補完しない。

## 求解と独立検証

勤務候補と担当配置は同じCP-SATモデルで決める。勤務日数は既存の候補選択と
1人1勤務日の条件を用い、暦日占有は選択勤務のORと確定事実から求める。
不足総量 → priority群の不足 → 利用者の目的の順は維持する。
日数条件のために待機だけの勤務を選ぶこともある。抑制する場合は勤務量・費用の目的を指定する。

日数違反は `PARTIAL` として許容しない。基準固定と確定勤務を自動解除しない。
条件グループは日数ルール1件につき1件で、診断の削除試行でも実績・確定勤務は背景に残す。
`diagnosis.allowed_changes` の `min_days` / `max_days` 編集は未対応として拒否する。
診断中に条件を除いて得た証拠を元条件の正式な解へ置き換えない。

有効な応答と `verify` は、条件順の `day_count_summary` を返す。
各要素は `constraint_id`、`type`、`interval`、`min_days`、`max_days`、`employees` を持つ。
省略した上下限は出力でnull、各従業員に `employee_id` / `work_days` / `occupied_days` /
`days_off` を載せる。常に `occupied_days + days_off` は評価期間のローカル暦日数と一致する。
日数条件なし・解なし・不正解では集計全体をnullにする。

`verify` は元入力と返却 `segments` から再構成し、ソルバーの候補係数・事実表を参照しない。
違反は `WORK_DAYS_BOUNDS_VIOLATION` または `DAYS_OFF_BOUNDS_VIOLATION` とし、
条件pointer・条件ID・従業員ID・`actual_value`・適用上下限を返す。
最適性・不足最小性の証明は付与しない。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/day_counts.json
uv run --locked python -m shift_schedula schema request --schema-version 0.11
uv run --locked python -m shift_schedula schema verification --schema-version 0.11
```

架空入力は週3勤務日・3占有日・4完全休日、勤務270分、不足0を返す。
返却 `solution` を `solution.json` に保存して独立検証する。

```sh
uv run --locked python -m shift_schedula verify examples/day_counts.json solution.json
```

公開型は `DayCountBounds`、`Request011`、`Response011Success`、`Response011Failure`。
`make_baseline` は新条件を保持し、元版で基準を再検証する。旧版の基準は受理し、
旧版から0.11の基準を参照する入力は拒否する。JSON試用入口でも0.11を受理し、日数を表示する。
検証結果は[受け入れ記録](evaluations/day-counts.md)に記す。
