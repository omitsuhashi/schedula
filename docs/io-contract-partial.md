# 不足を伴う計画の入出力契約0.3

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

## 対象と導入範囲

契約0.3は `assignment` と `roster` に未完成の計画を追加する。
[契約0.2](io-contract-next.md)の入力、夜勤・分割勤務、履歴、目標勤務量、基準計画、固定部分を継承する。
変更は明示した `schema_version: "0.3"` に限り、0.1・0.2のSchema・需要の意味・結果状態は変えない。
JSON Schemaの正本は `src/shift_schedula/schemas/0.3/` に置く。

契約検証に加え、元入力から不足を再計算する独立検証、最小費用流・CP-SATの不足最小化、
CLI・ローカルデモを実装している。[不足付き担当配置](../examples/partial_assignment.json)と
[不足付き勤務計画](../examples/partial_roster.json)を同じAPI・CLIで実行できる。
実測・合成応答テスト・未確認事項は[検証記録](evaluations/partial-plans.md)で区別する。

```sh
uv run --locked python -m shift_schedula schema request --schema-version 0.3
uv run --locked python -m shift_schedula schema response --schema-version 0.3
```

## 入力と目的順序

Requestのフィールドは0.2と同じで、`schema_version` だけを変更する。
不足を許容する対象は需要人数だけであり、必要人数自体は変更しない。
未指定の時間帯・役割の需要は0、配置人数は需要を超えない。
担当資格、勤務可能時間、二重配置禁止、休憩、勤務ルール、固定部分は従来どおり必須とする。
入力不正、依存不足、内部障害を未完成の計画として扱わない。

探索は不足合計人分を最優先で最小化する。この目的は契約で固定し、Requestの `objectives` に挿入しない。
不足最小値を証明してから固定し、既存の `objectives` を配列順に最小化する。
同率の不足が残る位置に独自の役割優先度を追加しない。既存目的も同率なら配置の一意性を保証しない。
目的配列が空でも不足最小化は行う。全目的で一つの探索予算を共有する。
上位目的が未証明なら後続目的を優先し直さず、検証済みの計画と証明範囲を返す。

## Responseの状態

| `status` | 計画と証明範囲 | `shortage_summary` |
| --- | --- | --- |
| `OPTIMAL` | 完全な計画。全指定目的の最適性を証明 | 合計0、空一覧、`proven_minimal: true` |
| `FEASIBLE` | 完全な計画。指定目的に未証明のものがある | 合計0、空一覧、`proven_minimal: true` |
| `PARTIAL` | 不足以外の必須条件を満たす未完成の計画。不足や指定目的の最適性は別に読む | 正の合計、空でない一覧 |
| `INFEASIBLE` | 需要不足を許容しても他の必須条件を満たせないと証明 | `null` |
| `UNKNOWN` | 計画も不可能性の証明も取得できていない | `null` |
| `INVALID_INPUT` / `BACKEND_UNAVAILABLE` / `INTERNAL_ERROR` | 入力・実行・検証のエラー | `null` |

`OPTIMAL` / `FEASIBLE` / `PARTIAL` では `solution` は既存の担当配置・勤務を含むオブジェクトで、
`verification` は `performed: true` / `valid: true` / `violations: []`。
それ以外では `solution: null` / `objectives: []`、公平性・変更・不足の集計はすべて `null`。
未検証は `performed: false` / `valid: null`。検証失敗は `INTERNAL_ERROR`、
`performed: true` / `valid: false` と空でない `violations` を持つ。

`shortage_summary` は全状態で必須フィールドとし、不要時に省略しない。
`fairness_summary` / `change_summary` は完全・未完成のどちらも返却計画から評価し、対象外なら `null`。
`diagnosis_result` は未要求なら `null`、要求時の扱いは後述する。
CLIはJSONを標準出力に出し、`OPTIMAL` / `FEASIBLE` は終了コード0、それ以外は2とする。
`PARTIAL` では終了コード2でも計画があるため、呼び出し側はJSONの状態を読む。

## 不足集計のフィールド

| フィールド | 意味 |
| --- | --- |
| `shortage_summary.total_person_minutes` | 不足人数×実経過分数の合計。非負整数、人分 |
| `shortage_summary.proven_minimal` | この不足合計が、元入力の他の必須条件を守る範囲で最小と証明されたか |
| `shortage_summary.shortages` | 不足した需要の区間一覧。完全な計画では `[]` |
| 各要素の `demand_id` / `role_id` | 元の需要IDと、その需要の役割ID |
| `interval` | 不足が続く半開区間。計画・需要内で入力の時間粒度に揃える |
| `required_people` | 元の需要人数。1〜250 |
| `assigned_people` | 同じ区間の配置人数。0〜249 |
| `missing_people` | `required_people - assigned_people`。1〜250 |

一覧は元入力の需要の配列順、その需要内では開始時刻順とする。同じ需要内で必要人数・配置人数・不足人数が
等しい隣接区間をまとめる。異なる需要IDは統合しない。重複・未報告の不足を認めない。
区間の始終端は秒・端数分を持たず、実時刻で正の長さとする。時計変更があっても実経過分数で集計する。
最大件数は50役割×3000時間枠の150,000件とし、診断の件数上限で打ち切らない。
全員を配置できない場合も、他の必須条件を満たす検証済み計画なら空の配置と全不足を返せる。
空の配置が固定部分に違反する場合などに、空の計画を代用品として返してはいけない。

次は12:00〜13:00の調理が1人不足した応答の一部である。完全なResponseではない。

```json
{
  "schema_version": "0.3",
  "status": "PARTIAL",
  "shortage_summary": {
    "total_person_minutes": 60,
    "proven_minimal": false,
    "shortages": [{
      "demand_id": "lunch",
      "role_id": "kitchen",
      "interval": {"start": "2026-10-05T12:00:00+09:00", "end": "2026-10-05T13:00:00+09:00"},
      "required_people": 2,
      "assigned_people": 1,
      "missing_people": 1
    }]
  }
}
```

## 証明と検証の境界

不足は非負なので、検証済みの不足0はそれだけで最小性を証明できる。
指定目的が空で不足0なら `OPTIMAL` とする。正の不足では `proven_minimal` が真でも状態は `PARTIAL`。
偽なら「この計画では不足している」という範囲であり、「必ず不足する」「最低1人追加が必要」とは説明しない。
正の最小不足が証明されても、どの区間を空けるかが一意であることや、追加従業員数は証明しない。

既存目的の `id`・`metric`・順序はRequestと一致させ、値は返却計画から計算する。
`proven_optimal` が真の目的は先頭から連続し、偽の後に真を置けない。
`proven_minimal: false` なら全指定目的が `proven_optimal: false`。
真なら、既存の辞書式最適化と同様に証明済みの接頭部分だけ真にできる。
検証器が配置の正しさを確認したことだけで最適性を真にしない。正の不足の最小性や目的の最適性は
ソルバーの証明に基づき、応答の意味検証はその主張の順序・整合性を確認する。

Schemaはフィールド・型・状態によるnull/空配列・不足の正負・証明の前提を検証する。
`validate_response(result)` はさらに不足一覧内の算術と区間長、合計、目的の証明順序を検証する。
入力との照合なしでは、需要IDや配置の正しさ、元の需要をすべて網羅したかは確認できない。
`verify_plan(problem, solution)` は元入力と返却配置から、違反・目的値・不足一覧と合計を返す。
`verify_solution(problem, solution)` は同じ検証経路から従来どおり違反・目的値を返す。
`validate_response(result, request)` は再計算した不足・目的値・公平性/変更集計を応答と照合する。
基準計画の検証には `require_complete=True` を指定し、0.3でも需要不足を違反として拒否する。
ソルバーの不足量と再計算値が一致しない場合も `INTERNAL_ERROR` にして計画を公開しない。

最小費用流は時間枠ごとに最大流を求め、その流量の範囲で費用を最小化する。
不足する時間枠で打ち切らず、巨大な罰金や架空の従業員を使わない。
CP-SATは各需要枠に非負の不足変数を置き、配置人数＋不足人数＝必要人数とする。
既存の辞書式探索の先頭に不足人分を置き、証明済みの値だけ固定する。
両方式とも全目的で一つの探索予算を共有し、別予算で完全充足の再探索は行わない。
時間切れの最小費用流も、それまでの配置と残りの不足を独立検証して返す。
CP-SATが計画を取得できていない場合は `UNKNOWN` を維持し、空の配置を代用しない。

## 基準計画と診断

0.3の基準計画は0.1・0.2・0.3の入力と、その入力の需要を含む全必須条件を満たす計画に限定する。
元の需要に不足がある基準計画は `INVALID_INPUT`。0.2の基準入力は従来どおり0.1・0.2に限る。
再計画の固定部分は未完成の出力でも解除しない。勤務候補の構造は0.2と同じなので、
テンプレート生成IDも0.2と同じ方式を使い、版だけの変更で候補IDを変えない。

0.3の `PARTIAL` に `diagnosis` が指定されていれば、`diagnosis_result.status: "NOT_APPLICABLE"`、
`reason: "ORIGINAL_PARTIAL"`、`conflict: null`、`suggestions: []` とする。
不足最小性の証明有無によらず追加の条件変更案を探索しない。診断結果を省略したり、
`ORIGINAL_FEASIBLE` / `ORIGINAL_UNKNOWN` に読み替えたりしない。
要求の予算と経過時間は従来どおり記録し、`suggestion_minimality: "not_proven"` を維持する。

完全な計画は `ORIGINAL_FEASIBLE`、`UNKNOWN` は `ORIGINAL_UNKNOWN` として追加診断しない。
入力不正・依存不足・内部障害では追加診断を実行せず `diagnosis_result: null` とする。
0.3の `INFEASIBLE` は需要不足を許容したモデルの証明であり、条件集合の基本条件コードは
`DEMAND_LIMIT_AND_SINGLE_ASSIGNMENT` とする。0.2の `EXACT_DEMAND_AND_SINGLE_ASSIGNMENT` は変更しない。
許可編集の範囲、固定解除の禁止、別入力と元結果の区別を維持する。
変更案として掲載するのは変更後の完全な `OPTIMAL` / `FEASIBLE` の計画だけとし、
未完成の計画を変更案の成功として掲載しない。

## 再実行

```sh
uv run --locked --extra cp-sat pytest -q tests/test_partial_contract.py tests/test_partial_plans.py tests/test_schema_encoding.py
```

テストは全状態の合成応答、状態・数値・証明の矛盾、旧版境界、拡張入力の継承、完全な基準計画のみの受理、
不足の改ざん、必須条件違反、小規模全探索、両方式の共通評価値、制御した時間切れ、PARTIAL時の診断非適用を確認する。
Schemaと両方式の実装をwheelにも同梱し、OR-Toolsなしの最小費用流と依存不足も隔離環境で検証する。
