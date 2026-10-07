# 不可能性の診断と許可された変更案

契約0.2の `diagnosis` は、元条件の結果を維持して追加の説明と変更案を返す。
`auto` は追加診断を要求した `assignment`・`roster` に CP-SAT を選ぶ。
明示的な `min_cost_flow` への追加診断は `INVALID_INPUT`。未要求の最小費用流の不足診断は継続する。

```sh
uv run --locked --extra cp-sat python -m schedula solve examples/diagnosis.json
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
