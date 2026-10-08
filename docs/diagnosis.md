# 不可能性の診断と許可された変更案

契約0.2の `diagnosis` は、元条件の結果を維持して追加の説明と変更案を返す。
`auto` は追加診断を要求した `assignment`・`roster` に CP-SAT を選ぶ。
明示的な `min_cost_flow` への追加診断は `INVALID_INPUT`。未要求の最小費用流の不足診断は継続する。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/diagnosis.json
```

この例は有資格者Alice一人に2人の需要を要求するため、元結果は `INFEASIBLE`、
`solution: null`、CLI終了コード2となる。利用者が許可した `/demand/0/required_people` を
1人に変更する案だけが、別の `modified_request` と検証済み `response` に返される。
変更しない2人の案は検証済み解を取得できず、掲載しない理由を記録する。
元入力の従業員・技能・勤務可能時間・候補・固定部分は変更しない。

`conflict.conditions` は、需要、資格、勤務可能時間、候補集合、勤務ルール、固定と
二重配置禁止を入力の JSON pointer・ID・該当時間へ追跡する十分集合である。
最初の実装は全必須条件を含め、元の CP-SAT の不可能性証明を使用する。
`infeasibility_proven: true`、`minimality: "not_proven"` であり、唯一の原因や最小原因を主張しない。
複数役割の同時需要を一人が担えない場合も、個別の技能人数不足と決めつけない。

`allowed_changes` は一つの選択肢に1〜10件の整数編集をまとめる。
編集対象は存在する需要人数と、既存必須ルールの数値上限だけである。
同じ選択肢での重複編集、未知項目、技能追加、固定解除、契約上限外の値を拒否する。
異なる選択肢を自動で組み合わせず、変更案の最小性も `not_proven` とする。
案が空でも、許可範囲に有効な変更が存在しないという証明にはしない。

追加の `time_limit_seconds` は0超〜300秒で、抽出・入力検証・探索・独立検証に使う。
変更後の通常探索には残り以下の予算を設定し、`diagnosis` を除いて再帰提案を止める。
実際の短縮予算と元予算を `OPTION_BUDGET`、変更後入力へ記録する。
これはプロセスを強制終了する外部応答期限ではない。
予算切れは `TIME_LIMIT` と完了済みの証明・検証済み案だけを返し、
追加処理・出力検証の失敗は `ERROR` として元の不可能性を保持する。

元が `UNKNOWN` なら `NOT_APPLICABLE` / `ORIGINAL_UNKNOWN`、正常なら
`NOT_APPLICABLE` / `ORIGINAL_FEASIBLE` とし、証明集合も変更案探索も行わない。
独立検証は変更後の入力と解・全目的値・公平性/変更集計を照合する。
元と変更後の入力の差も許可編集・予算短縮・診断無効化だけであることを確認する。

## 契約0.3の不足と診断

[不足付き勤務計画の例](../examples/partial_roster.json)は元需要を保った `PARTIAL` と不足30人分を返す。
`diagnosis_result` は `NOT_APPLICABLE` / `ORIGINAL_PARTIAL`、`conflict: null`、`suggestions: []`。
不足最小性の証明有無によらず、元の完全充足問題の解なしとして条件変更案を探索しない。
0.3の `INFEASIBLE` では需要不足を許容しても成立しない必須条件の十分集合を返し、
基本条件コードは `DEMAND_LIMIT_AND_SINGLE_ASSIGNMENT` とする。
条件変更案の成功は変更後の完全な `OPTIMAL` / `FEASIBLE` だけに限定する。
詳細は[契約0.3](io-contract-partial.md)と[検証記録](evaluations/partial-plans.md)を参照する。

## 契約0.8の条件グループ縮小

契約0.8は0.7の機能を継承し、`diagnosis.conflict_refinement` を追加する。
旧0.1〜0.7はこの新項目を拒否し、既存の診断形式を維持する。

```json
{
  "time_limit_seconds": 10,
  "max_suggestions": 1,
  "allowed_changes": [],
  "conflict_refinement": {"time_limit_seconds": 5}
}
```

これは `diagnosis` の値の例である。縮小予算は0超かつ診断全体の予算以下に指定する。
省略時は全条件グループと背景条件を返し、包含極小性は証明しない。
縮小は元結果が `INFEASIBLE` の場合だけ実行する。`PARTIAL`、`UNKNOWN`、正常解は起点にしない。

| 分類 | 単位と保持する意味 |
| --- | --- |
| 条件グループ | 需要1件、`constraints` 1件、`fixed_parts` 1件、`preserve_assigned` 全体 |
| 背景条件 | 資格、技能、勤務可能時間、元の候補集合、二重配置禁止、勤務と担当の結合、1人1勤務日、勤務外側区間の非重複、時刻・ID、実績・確定勤務、元基準の検証 |
| 必須条件ではない項目 | 選好、目標、目的。診断モデルの実行可能性判定には使わず、元入力と正式な再求解には保持する |

元入力を一度正規化した変数領域を保持し、除去対象の条件の構築だけを省略する。
需要行を削除して再正規化する操作とは異なる。契約0.8の需要は人数上限であり、
需要不足を許した上でも成立しない必須条件を調べる。未指定需要0と元から変数のない枠を保持する。

全条件を新しい診断モデルで再確認し、`group_id` の昇順に一度ずつ削除を試す。
`INFEASIBLE` だけを除去の根拠にする。実行可能なら元JSONから勤務・担当・残す条件を
独立検証して除去証拠を保存し、`UNKNOWN` は未確定のまま条件を残す。
最後に新しいモデルで十分性を再確認し、以前の実行可能証拠を最終集合で再検証する。

| `conflict` の項目 | 読み方 |
| --- | --- |
| `conditions` / `background_conditions` | 条件グループの十分集合と、保持した背景条件の参照一覧 |
| `group_id` | 元のJSON pointerと同じ決定的なID。配列を並べ替えた入力では作り直す |
| `code` / `json_pointer` / `related_ids` / `interval` | 元条件への参照。期間上下限は指定区間、全体ルールは計画期間、候補・実績・確定勤務は原区間を保持する |
| `infeasibility_proven` | 予算内に不可能性を証明した集合だけでtrue |
| `minimality` | `inclusion_minimal` は各要素の除去後の実行可能証拠がすべて独立検証済み。欠ければ `not_proven` |
| `minimality_scope` | `condition_groups_relative_to_background`。背景を保持した、このグループ単位に限定した証明 |
| `background_only` | 集合が空で背景だけが矛盾する場合にtrue。「原因がない」という意味ではない |
| `rechecked` | 最終集合を新規モデルで予算内に再確認できたか |
| `checks` | 初回・削除・最終・証拠再検証の記録。試したグループ、対象、状態、証拠検証、予算内完了、構築・探索・検証・全体時間 |

`inclusion_minimal` は要素数最少、唯一の原因、全原因の列挙を保証しない。
実行可能証拠は内部だけで保持し、緩和解を正式な `solution` や変更案に載せない。
不可能性は別モデルのCP-SATで再確認する。ソルバーを呼ばない独立検証器が確認するのは
除去後の実行可能証拠であり、不可能性の証明ではない。公開 `verify` の条件は弱めない。

縮小予算は診断全体予算に内包する。構築・探索・証拠検証・最終確認に共通の残り時間を使い、
期限後に完成した証拠は採用しない。縮小が時間切れでも、既に証明した集合と元結果を保持し、
診断全体の残り予算があれば既存 `allowed_changes` の案を評価する。
強制中断は[外部の総期限・取消](python-api.md#cpu数総期限取消)で管理する。

`TIME_LIMIT` と十分集合を同時に返せる。全試行を終えてUNKNOWNが残る場合は
`COMPLETE` と `not_proven` の組もある。全条件の初回再確認が未証明なら `conflict: null`。
モデル不一致・無効な証拠・例外は診断だけを `ERROR` にし、既に証明した集合を保持する。
新しい必須条件の分類に未対応の場合は `UNSUPPORTED` とし、無断で条件を外さない。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/conflict_refinement.json
uv run --locked --extra cp-sat python -m shift_schedula schema response --schema-version 0.8
```

[架空入力](../examples/conflict_refinement.json)はAliceの勤務量下限60分と上限0分が矛盾する。
無関係な担当上限120分と需要を除き、二条件の包含極小な十分集合を返す。
元結果は `INFEASIBLE` / `solution: null` / 終了コード2のまま、許可された上限60分への変更案は
別の検証済み `OPTIMAL` として返す。
再実行には元Request、エンジン・OR-Tools版、solver設定、グループIDを保存する。
`checks` は監査記録であり、保存・外部入力の記録だけで証明を再認定しない。
[検証記録](evaluations/conflict-refinement.md)に実行条件と結果を残す。
