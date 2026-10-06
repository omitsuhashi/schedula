# 担当配置の利用手順

schedula 0.1.3 は独立した配置と、担当時間上限・担当切替を含む `assignment` を解く。
飲食店の架空の例を [examples/assignment.json](../examples/assignment.json) と
[examples/linked_assignment.json](../examples/linked_assignment.json) に用意した。
JSON の意味と版の変更方針は [入出力契約](io-contract.md)、環境の正本は
[Python セットアップ](python-setup.md) を参照する。

## ライブラリと CLI

リポジトリ直下で実行する。最小費用流は標準ライブラリで実装し、OR-Tools を必要としない。

```sh
uv sync --locked
uv run --locked python -m schedula solve examples/assignment.json
uv run --locked python -m schedula solve - < examples/assignment.json
uv run --locked python -m schedula schema request
uv run --locked python -m schedula schema response
```

例は `OPTIMAL`、`preference_penalty: 0`、`verification.valid: true` を返す。
隣接する同じ従業員・役割の担当をまとめ、`solution.shifts` は空になる。
標準出力は JSON のみ。有効な解は終了コード0、その他の結果状態は2。
CLI の使用法エラーは標準エラーに表示し、終了コード2とする。
ファイル読み取り・UTF-8・JSON の不正は JSON の `INVALID_INPUT` として返す。
JSON 内の日本語は Unicode エスケープで出力する。

```python
import json
from pathlib import Path
from schedula import solve

request = json.loads(Path("examples/assignment.json").read_text(encoding="utf-8"))
response = solve(request)
assert response["status"] == "OPTIMAL"
assert response["verification"]["valid"] is True
```

ライブラリに渡す dict は JSON 型・有限数から構成する。重複キーは dict 化した後には
検出できないため、外部 JSON を厳密に読む場合は CLI を使用する。

CP-SAT を使う例は `cp-sat` extra を指定する。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python -m schedula solve examples/linked_assignment.json
```

この例は各従業員の担当時間120分以下・担当切替0回を守り、
`preference_penalty: 0` の検証済み `OPTIMAL` を返す。

## 対応する条件

| 対象 | schedula 0.1.3 の担当配置の対応 |
| --- | --- |
| `problem_type` | `assignment` |
| `solver.backend` | `auto` / `min_cost_flow` / `cp_sat` |
| 基本条件 | 必要技能・最低レベルすべてを満たす、勤務可能時間内、厳密な需要、二重配置なし |
| `objectives` | 空、または `preference_penalty` / `role_switches` の順序付き配列。同じ指標は重複不可 |
| `preferences` | `avoid_role`。同じ対象への複数指定はペナルティを加算。目的の指定が必要 |
| `constraints` | `max_assigned_minutes` / `max_role_switches`。対象者ごとに全件を適用 |
| `shift_candidates` | 空のみ |
| `shift_templates` | 省略または空のみ |
| `history` | `assignment` では受理しない |
| `seed` | CP-SAT に渡し、worker 数は1。最小費用流は ID 順で探索し seed を使わない |

`assignment` への勤務量の目的・勤務用ルールは `INVALID_INPUT`。
`roster` は [勤務計画の利用手順](roster.md)で扱う。
Schema は契約0.1全体を表すが、未対応条件を意味検証で拒否する。
必要な条件を捨てたり、需要不足のまま正式な解を返したりしない。
担当時間は担当した枠数 × `slot_minutes`。上限は対象者全員の合計ではなく、一人ずつ適用する。
上限が時間粒度の倍数でなくても受理し、丸めずに比較する。
担当切替は隣接枠で両方とも役割を担当し、その役割が異なる場合に一回と数える。
未担当の枠を挟んだ変更は数えない。`role_switches` 目的は全従業員の回数を最小化する。
同じ従業員に複数の上限が指定された場合はすべて守る。

`preferences` がある場合は `preference_penalty` 目的が必須である。
`role_switches` も併せて指定でき、配列の先頭の目的を優先する。
目的が空の場合は任意の実行可能解を求め、担当切替が最小になるとは保証しない。

## バックエンドと実行情報

| 入力 | 選択 | `selection_reason` |
| --- | --- | --- |
| `auto`、明示制約なし、目的は空または `preference_penalty` | `min_cost_flow` | `INDEPENDENT_ADDITIVE_ASSIGNMENTS` |
| `auto`、明示制約あり | `cp_sat` | `ASSIGNMENT_CONSTRAINTS` |
| `auto`、制約なしで `role_switches` 目的 | `cp_sat` | `ROLE_SWITCH_OBJECTIVE` |
| 明示指定の対応方式 | 指定された方式 | `EXPLICIT_BACKEND` |

一つの Request につき一つの方式を選ぶ。CP-SAT は目的順序に沿って複数回探索できる。
明示した `min_cost_flow` に制約・担当切替目的がある場合は、依存の有無によらず `INVALID_INPUT`。
CP-SAT を選んで OR-Tools またはその import に必要な依存がなければ `BACKEND_UNAVAILABLE`。
条件を捨てた方式へ退避しない。

Response の `solver.library_version` は読み込んだ OR-Tools の実際の版である。
標準ライブラリで実装した最小費用流と、依存を読み込めない CP-SAT は `null`。
`solver.engine_version` は schedula のパッケージ版、`schema_version` は従来の0.1を維持する。
同率解の配置や時間切れ結果の全環境での再現性は seed だけでは保証しない。

IANA タイムゾーン名は128文字以内。名前が長すぎる入力は `INVALID_INPUT` とし、
zoneinfo の読み取りなど実行環境の I/O 障害は `INTERNAL_ERROR` とする。
日時は既知のオフセット付きで指定する。UTC に正規化した実時間で時間枠を作り、
出力は計画の IANA タイムゾーンで表す。入力のオフセットが異なっても同じ時点なら同じ意味になる。
時計変更時も実時間の分数を使う。秒・端数分を丸めず、計画開始からの時間粒度に揃える。
勤務可能時間と同じ役割の需要は重なりを拒否し、終端と開始が接する区間は許可する。

## 結果の判断

- `OPTIMAL`: 独立検証を通過し、指定されたモデルの最適解を得た。
- `FEASIBLE`: 独立検証を通過したが、一部またはすべての目的の最適性が未証明。
- `INFEASIBLE`: 需要・担当資格・勤務可能時間・上限をすべて満たす解がないと証明された。
- `UNKNOWN`: 探索予算が切れ、完全な解を得られていない。不可能性の証明ではない。
- `INVALID_INPUT`: 構造、参照、日時、上限または対応範囲を修正する必要がある。
- `BACKEND_UNAVAILABLE`: CP-SAT の必要な依存がない。`cp-sat` extra を導入する。
- `INTERNAL_ERROR`: ソルバーの障害、壊れた解、評価値・出力契約の不整合。正式な解は返さない。

`INFEASIBLE` 以下の状態は `solution: null`、`objectives: []`。
未検証は `verification.performed: false` / `valid: null`。
解または出力の検証が失敗した場合は `performed: true` / `valid: false` と違反を記録する。

`INSUFFICIENT_QUALIFIED_EMPLOYEES` は単独役割の勤務可能な有資格者不足、
`COMPETING_ROLE_DEMAND` は複数役割を同時に埋められないことを示す。
これらは最小費用流の診断であり、`facts` に時間枠インデックスと人数を保持する。
CP-SAT の `NO_FEASIBLE_PLAN` は全体の不可能性を示す。唯一の原因や最低追加人数は推測しない。
ソルバーの正規化テーブルを検証器へ信用させず、元入力と担当区間から
担当資格・勤務可能時間・需要・二重配置・担当時間上限・担当切替上限と目的値を照合し、
Response 全体も検証する。上限違反は `MAX_ASSIGNED_MINUTES_VIOLATION` /
`MAX_ROLE_SWITCHES_VIOLATION`、目的値の不一致は `OBJECTIVE_VALUE_MISMATCH` として公開を遮断する。
`FEASIBLE` も同じ検証を通し、目的の `proven_optimal` は `false` にする。
隣接した同一担当の結合漏れも `UNMERGED_ASSIGNMENTS` として検出し、解の公開を遮断する。
Schema は UTF-8 を明示して読み取る。

## 上限と探索時間

従業員250人、役割50、技能100、需要10,000件、時間枠3,000、
従業員 × 時間枠 × 役割1,000,000以下。その他の配列上限は版別 Schema に記録する。
上限内で応答性能を保証するものではない。

`time_limit_seconds` は依存読み込み・グラフまたはモデル構築を終えてから始まる探索予算。
最小費用流ではすべての時間枠で共有し、途中で切れた部分配置は返さず `UNKNOWN` にする。
CP-SAT は同じモデルで目的順に探索し、最適性を証明した上位目的の値だけを固定する。
上位目的が `FEASIBLE` なら終了する。段階間の時間切れや後段の `UNKNOWN` では最良の既知解を
保持して `FEASIBLE` とし、解も不可能性の証明もない場合は `UNKNOWN`。
全目的の値を返す解から再計算し、`proven_optimal` は証明済みの先頭部分だけを `true` にする。
`SEARCH_STATS` 診断の `facts` に共有予算と探索開始後の所要時間を記録する。
入力検証・正規化・依存読み込み・構築・結果検証を含む総時間は
`stats.elapsed_seconds` に記録する。外部応答期限やプロセス隔離は未導入。

## 検証とビルド

```sh
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra
uv build --wheel
```

既存 CI の `deploy-entrypoint` で、既存テストに加え、全探索比較150件、
両バックエンドの比較、時間横断条件を含む全探索80件、壊れた解の検出、
厳密な入力・出力、時計変更、時間切れ、CLI、wheel と依存不足を検証する。
wheel のテストは、ソース checkout を import せず同梱 Schema・ライブラリ・CLI を実行する。
独立配置の実測は [担当配置の検証記録](evaluations/assignment.md)、今回の実測と未検証事項は
[時間横断配置の検証記録](evaluations/linked-assignment.md)・
[目的順序・終了状態の検証記録](evaluations/objectives.md) に残す。
クリーンな wheel の隔離導入、CI のスキップ検出、週単位の架空入力の時間・メモリは
[利用入口・CI・実行評価](evaluations/runtime.md)に記録する。
