# 再計画・勤務量・希望日時の契約0.4

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #45](https://github.com/omitsuhashi/schedula/issues/45)の既定案を実装した契約である。
[契約0.3](io-contract-partial.md)の不足最優先・状態・証明範囲を継承する。
候補件数の撤廃以外、旧版の業務上の意味は変更しない。
計算、業務検証、JSON契約、CLI、試用デモはschedulaの責務とし、
HTTP公開・認証・画面・保存・CSV・顧客管理は利用アプリの責務とする。

## 版と移行

| 条件 | 0.1 | 0.2 | 0.3 | 0.4 |
| --- | --- | --- | --- | --- |
| 夜勤・分割・公平性・明示固定 | 不可 | 対応 | 対応 | 対応 |
| 元需要を保持した不足付き計画 | 不可 | 不可 | 対応 | 対応 |
| 未完成の基準計画 | 不可 | 不可 | 不可 | 対応 |
| `replan_mode`・期間別上下限・勤務日時の選好 | 不可 | 不可 | 不可 | 対応 |
| 勤務候補・選択済み勤務の件数上限 | なし | なし | なし | なし |
| ソルバー不要の公開検証API | 対応 | 対応 | 対応 | 対応 |

0.3の入力は `schema_version` を `0.4` に変更すれば同じ条件で利用できる。
0.4の新項目を旧版に指定すると拒否する。0.1からは `segments` / `segment_options` と
`history.last_work_day` の[明示移行](io-contract-next.md)が必要である。
旧版に0.4の基準入力を渡すことも拒否する。0.4には旧版の基準入力を指定できるが、
0.1・0.2の基準の需要充足はその版の意味で検証する。

候補件数は切り捨てず、別の固定件数へ置き換えない。
保存済みの旧Request/Response Schemaには5000件の制限が残るため、
公開 `get_schema` またはCLIから同じ版のSchemaを再取得する。
従業員250人・役割50・時間枠3000・従業員×時間枠×役割1,000,000など、
候補件数以外の上限と構造・参照・粒度・休憩の検証は維持する。
上限内の応答時間保証ではない。過去の評価記録は当時の条件を保持する。

## 期間別勤務量

`constraints` に `scheduled_minutes_bounds` を追加する。
`id`・`type`・`employee_ids`・計画内の `interval` は必須。
`min_minutes` / `max_minutes` は少なくとも一方を指定し、整数0〜10,000,000とする。
省略した側は制約なし。nullは不可で、下限が上限より大きい入力は拒否する。

```json
{
  "id": "week_one",
  "type": "scheduled_minutes_bounds",
  "employee_ids": ["alice"],
  "interval": {"start": "2026-10-05T00:00:00+09:00", "end": "2026-10-12T00:00:00+09:00"},
  "min_minutes": 1200,
  "max_minutes": 2400
}
```

対象者ごとに、返却された勤務区間から休憩を除いた時間と評価区間との重なりを数える。
待機は含め、分割間の非勤務は含めない。半開区間・実経過分数・既存の粒度を使う。
夜勤の勤務日へ全量を帰属させない。時計変更にも明示オフセットと実経過時間を使う。
計画端からはみ出す区間は拒否し、計画外実績を推定しない。
週・月などの区間は利用側が具体的な日時へ展開する。短い週の自動按分はしない。

重複する評価区間は、それぞれの上下限を満たす。計画全体の上限、休息、連勤、
固定、選好、目標勤務量も同時適用する。目標勤務量は必須の下限ではない。
下限のために待機を選ぶことはできるが、需要のない担当や過剰配置は許さない。
候補から下限を満たせない場合は `INFEASIBLE` となり、`PARTIAL` で通過しない。

モデルは候補の勤務枠と区間の重なりを選択変数の係数にし、
独立検証器は返却された勤務区間・休憩から勤務枠を再構成する。
境界の一致は許容する。違反は `MIN_SCHEDULED_MINUTES_VIOLATION` /
`MAX_SCHEDULED_MINUTES_VIOLATION` に実分数・閾値・対象ID・条件の位置を返す。

## 勤務日時の選好

`preferences` の `prefer_work` / `avoid_work` はrosterのみ。
`id`・`type`・`employee_ids`・計画内の `interval`・`penalty_per_minute` を必須とする。
ペナルティは1〜10,000の整数。勤務禁止は引き続き `availability` で表す。
選好を指定したら `preference_penalty` 目的も指定する。

- `prefer_work`: 区間全体の分数から、その区間に重なる勤務分数を引いて単価を掛ける。
- `avoid_work`: 区間に重なる勤務分数へ単価を掛ける。
- 対象者・複数希望のすべてを合算し、従来の `avoid_role` の値へ加える。

休憩・非勤務・待機の扱いは勤務量と同じ。希望勤務の定数項も含める。
例えば90分の候補に30分休憩があり、全90分を希望して単価2なら、担当がなくても
勤務60分・未達30分・ペナルティ60となる。勤務60分を避ける単価3なら180を加算する。
矛盾する複数希望も独立して加算し、勝手に優先度を付けない。
不足最小化を常に先に実行するため、希望を満たす目的で需要不足を増やさない。
技能・休息・上下限・固定の違反も許さない。

## 再計画2方式

`replan_mode` はrosterの任意項目。nullは不可。
省略すれば既存の `baseline` / `fixed_parts` / `plan_changes` を明示利用できる。

- `preserve_assigned`: 基準の非空担当枠の従業員・役割・時間帯と、その枠の勤務状態を必須固定する。
  基準が必要。未担当・休憩・待機・非勤務は自動固定しない。
  追加の明示固定には従来の `fixed_parts` を使う。自動固定はこの配列へ展開せず、1000件上限に依存しない。
- `rebuild`: 通常の求解へ接続する。基準は比較指標の集計にのみ使える。
  非空 `fixed_parts` または `plan_changes` 目的は `REBUILD_CONFLICT` として拒否する。

基準の `source_request` と `source_solution` を再検証し、外部の検証フラグ・評価値は受け取らない。
0.4の基準には需要不足以外の違反がない未完成の計画も使える。
従業員が消えた、勤務不可になった、技能や新しい上下限が固定と矛盾した場合は
固定案を `INFEASIBLE` とし、自動解除しない。全体再計画は別入力として呼び出す。
新しい需要が基準の空欄を埋められる場合は、その枠へ追加配置できる。

2案は同じ新需要・業務必須条件・候補・共通目的順序で、`solve` を各1回呼ぶ。
不足、目的値、`change_summary`、探索予算、状態、証明を別々に保存する。
変更量を全体再計画の目的へ暗黙追加しない。明示的な変更最小化を固定案へ加えた場合は、
共通目的での比較とその追加目的を分けて読む。
両案が同じ共通目的の最適性を証明した場合、固定のない案の評価は固定案より悪くならない。
探索打切り時の観測値の優劣から、その保証や最適性を主張しない。

## 基準スナップショット

公開 `make_baseline(request, solution, plan_id)` は契約0.4のrosterを再検証し、
次の `baseline` として保存可能なJSONを返す。不正な入力・解では `ValueError` を送出する。
元入力と解は呼び出し側が別に保存し、書き換えない。

結果の `source_request` から比較専用の `baseline`、`replan_mode`、`fixed_parts`、
`plan_changes` 目的と追加診断を取り除く。需要、技能、勤務可能時間、候補、履歴、
勤務ルール、期間別上下限、選好、目標勤務量は保持する。
実行時の自動・明示固定は基準の絶対状態へ解決して `source_fixed_states` に保存する。
これは元計画の検証条件であり、次の求解を無条件で固定する指示ではない。
そのため比較元の無限ネストを避けても、元計画を検証する必須条件は失わない。
`source_solution` は別コピー。`snapshot_origin` の `request_id`、`baseline_plan_id`、
`replan_mode` で実行時原入力・結果との対応を追跡する。

`source_fixed_states` は配列。各要素は `employee_id`、計画内の `interval` と
`work: off | work | break` / `role: 役割ID | null` の少なくとも一方を持つ。
従業員IDは `source_request` の登録者を参照する。
同じ状態が続く枠は区間へまとめる。件数制限はない。
基準の検証時に `source_solution` の勤務・担当状態と照合し、不一致なら拒否する。
新規の基準ではこれらの項目は省略可能。自作の投影で業務条件を落とさず、この公開変換を使う。
原入力・元ソルバー結果の保管や来歴の真正性の保証は利用側の責務である。

## ソルバーなしの公開検証

```python
from shift_schedula import solve, verify, make_baseline, get_schema

result = solve(request)
checked = verify(request, result["solution"])
request_schema = get_schema("request", "0.4")
solution_schema = get_schema("solution", "0.4")
verification_schema = get_schema("verification", "0.4")
```

`verify(request, solution)` はJSON型のRequestとSolutionを受ける。
Response全体や持ち込まれた評価値・検証フラグをSolutionとして指定すると拒否する。
RequestのSchema・意味・参照・候補を再検証し、全必須条件を元入力から確認する。
OR-Toolsの読み込みや探索は不要。内部モジュールのimportやSchemaの複製は必要ない。
未知版・不正型・非有限数・循環・壊れた入力を有効としない。
`dict` の前段の重複JSONキー検出はCLIを使う。

| 検証 `status` | 意味 | CLI終了コード |
| --- | --- | --- |
| `VALID` | 有効で需要も充足。最適性は認定しない | 0 |
| `PARTIAL` | 0.3・0.4の不足以外が有効な計画 | 2 |
| `INVALID_INPUT` | RequestまたはJSON読み取りが不正。計画検証は未実施 | 2 |
| `INVALID_PLAN` | Solutionの構造や必須条件が不正。違反位置・IDを返す | 2 |
| `INTERNAL_ERROR` | 検証処理が完了しない。採用不可 | 2 |

有効な結果の `verification.valid` はtrueで、`demand_satisfied` は完全/不足を分ける。
`objectives`・不足・公平性・変更量を再計算する。全 `proven_optimal` と
`shortage_summary.proven_minimal` はfalseで、保存済みソルバーの証明を引き継がない。
不正結果は `demand_satisfied: null`、目的・集計を空またはnullとし、
検証できなかった値を有効な評価値として返さない。応答の `schema_version` はRequestの版。
公開 `get_schema("verification", 版)` で版別の検証結果Schemaを取得できる。
0.1・0.2の需要不足は `INVALID_PLAN` で、旧版の完全充足の意味を維持する。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/roster_conditions.json
uv run --locked python -m shift_schedula verify examples/roster_conditions.json examples/roster_conditions.solution.json
uv run --locked python -m shift_schedula schema verification --schema-version 0.4
uv run --locked --extra cp-sat python -m shift_schedula solve examples/partial_replan_preserve_assigned.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/partial_replan_rebuild.json
```

上下限・希望例は目的 `[0, 180]`、固定案は不足30人分の `PARTIAL`、
全体案は不足0の `OPTIMAL`。固定案の終了コード2は意図した結果である。
再計画例ではaliceだけがホール技能を持ち、基準の調理担当を固定するとホールが埋まらない。
全体案はaliceをホール、bobを調理へ移す。両案の `change_summary` と目的の証明を読める。
上下限矛盾は `INVALID_MINUTES_BOUNDS`、未知参照は `UNKNOWN_REFERENCE`、
固定と勤務不可の衝突は `INFEASIBLE`、目標未達は必須違反ではなく公平性集計に現れる。
勤務条件の検証と合成規模の実測は[結合・規模評価](evaluations/roster-conditions.md)を参照する。
