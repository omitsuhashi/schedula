# 必須の最低充足人数を契約0.12へ追加する

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #87](https://github.com/omitsuhashi/schedula/issues/87)に基づき、
契約0.11へ需要ごとの `minimum_people` を追加する。担当配置と勤務計画の両方に対応する。
0.1〜0.11の受理・状態・不足量は維持し、新項目を旧版へ渡すと拒否する。
パッケージ版とは別のJSON契約版であり、Schema取得の既定値は0.1のままとする。

## 入力と意味

`demand[]` の各要素に `minimum_people` を任意で指定する。
0〜`required_people`、最大250の整数で、省略は0。null、bool、負数、整数でない値、
必要人数超過を拒否する。ID・参照・区間・粒度・同じ役割の需要重複は既存どおり検証する。

```json
{
  "id": "hall_peak",
  "role_id": "hall",
  "interval": {"start": "2026-10-05T12:00:00+09:00", "end": "2026-10-05T13:00:00+09:00"},
  "required_people": 3,
  "minimum_people": 1,
  "priority": 10
}
```

上は需要1件の部分例。必要人数3人を保持し、各時間枠の配置人数を1〜3人とする。
最低人数が必要人数と同じなら全人数が必須。0なら従来の不足許容と同じである。
必須と任意を表すために同じ役割・時間の需要行を重複登録しない。

最低人数と他の必須条件を守る解の中で、不足合計人分 → priorityの高い群の不足 →
利用者の目的の順に比較する。priorityは同じ不足総量の計画を比較する順序であり、
必須充足の代用にはならない。最低人数のために不足総量が増える場合もある。
勤務可能時間・技能・固定・確定勤務・日数上下限を自動解除しない。

契約0.12〜0.14で `minimum_people > 0` があれば `auto` はCP-SATを選び、
`solver.selection_reason: MANDATORY_DEMAND` を返す。`min_cost_flow` の明示は
`INVALID_INPUT` と診断 `UNSUPPORTED_BACKEND`。すべて0または省略なら、従来の
最小費用流の適用範囲を維持する。CP-SATが未導入なら `BACKEND_UNAVAILABLE`。
新しいソルバーは追加しない。

契約0.15では、独立したassignmentの全正需要が `minimum_people = required_people` の場合も
`auto` / 明示 `min_cost_flow` で完全充足を求められる。0需要の下限は0であり、空需要も受理する。
明示制約・担当切替目的・非既定priority・診断を含む場合は従来どおりCP-SATとする。
中間下限や、完全充足と不足許容を混在させた需要もCP-SATであり、明示flowは拒否する。
完全充足flowは有資格者不足・役割間競合をINFEASIBLEとし、探索予算切れの途中配置を返さずUNKNOWNとする。
全下限0のflowは従来どおり検証済みPARTIALを返せる。返却解は既存の独立検証を必ず通す。
完全充足flowの自動選択理由は `INDEPENDENT_ADDITIVE_ASSIGNMENTS`、明示時は `EXPLICIT_BACKEND`。

## 状態と検証

| 条件 | 状態 |
| --- | --- |
| 下限を守り、元の必要人数に不足がある | 独立検証済み `PARTIAL` |
| 全需要を充足する | 証明範囲に応じて `OPTIMAL` / `FEASIBLE` |
| 下限と他の必須条件を同時に満たせないことを証明 | `INFEASIBLE`、解なし |
| 探索予算内に有効な解を取得できない | `UNKNOWN`、解なし |
| `verify` に渡した解が最低人数を破る | `INVALID_PLAN` |

不足は元の `required_people - assigned_people` で計算する。0.12の不足一覧には、
省略時の0も含めて `minimum_people` を必ず返す。
不足人数が `required_people - minimum_people` を超える計画は有効としない。
不足合計人分・priority集計の単位と最適性の証明範囲は従来どおりである。

独立検証は元Requestと返却配置から最低人数・不足を再計算し、モデルの係数を正本にしない。
違反 `MINIMUM_DEMAND_VIOLATION` は元の `/demand/<index>` を指し、需要ID・役割IDと
`interval_start` / `interval_end` / `minimum_people` / `assigned_people` を返す。
`verify` はOR-Toolsなしで利用でき、最適性・不足最小性は付与しない。

## 基準と診断

`make_baseline` は最低人数を元版のRequestに保存して解を再検証する。
新しい最低人数と `preserve_assigned` が衝突すれば `INFEASIBLE`。
`rebuild` は同じ業務条件を持つ別入力として解き、固定を勝手に解除しない。

需要1件の下限と上限は同じ条件グループである。診断の削除試行は人数条件だけを外し、
需要行・配置変数・候補・背景を保持する。緩和した証拠を元条件の正式な解にしない。
需要0や未指定の枠に配置変数を追加することもない。

`diagnosis.allowed_changes` に `/demand/<index>/minimum_people` の整数編集を
明示した場合だけ、最低人数を変更できる。省略されていた下限の明示設定も受け付ける。
`required_people` だけを最低人数未満へ下げる案は拒否し、下限を連動変更しない。
両方を変更する場合は同じ選択肢に両方の編集を明示する。
0.12では下限を守る検証済み `PARTIAL` も変更案として返す。
元の結果は `INFEASIBLE` のまま保持し、変更後Request・不足・証明を別に読む。
旧版の変更案は従来どおり完全な計画のみである。

## 実行例

完全な入力は[担当配置](../examples/minimum_assignment.json)・
[勤務計画](../examples/minimum_roster.json)・[診断](../examples/minimum_conflict.json)を使う。
最初の2例は目標3人・最低1人・配置可能2人で `PARTIAL`、不足30人分となる。
診断例は配置可能0人で `INFEASIBLE`。必要人数だけを0にする案を拒否し、
最低人数だけを0へ戻す未完成の案と、両方0にする完全な案を区別する。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/minimum_assignment.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/minimum_roster.json > result.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/minimum_conflict.json
uv run --locked python -m shift_schedula schema request --schema-version 0.12
```

`PARTIAL` / `INFEASIBLE` のCLI終了コードは2。保存した解の独立検証・基準への保存は
[公開API](python-api.md)と[再計画の契約](io-contract-replanning.md)を参照する。
JSON試用入口は0.12を受理し、不足一覧の最低人数と必須条件の確認結果を表示する。
受け入れ条件と再実行は[検証記録](evaluations/minimum-demand.md)、
不足許容に必須下限を加える理由は[ADR](adr/0009-mandatory-demand-minimum.md)に記録する。
