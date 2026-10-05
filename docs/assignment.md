# 担当配置の利用手順

schedula 0.1.0 は独立した `assignment` を解く。飲食店の架空の例を
[examples/assignment.json](../examples/assignment.json) に用意した。
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

## 対応する条件

| 対象 | schedula 0.1.0 の対応 |
| --- | --- |
| `problem_type` | `assignment` |
| `solver.backend` | `auto` / `min_cost_flow`。実際の選択は `min_cost_flow` |
| 基本条件 | 必要技能・最低レベルすべてを満たす、勤務可能時間内、厳密な需要、二重配置なし |
| `objectives` | 空、または `preference_penalty` 1件 |
| `preferences` | `avoid_role`。同じ対象への複数指定はペナルティを加算。目的の指定が必要 |
| `constraints` / `shift_candidates` | 空のみ |
| `shift_templates` | 省略または空のみ |
| `history` | `assignment` では受理しない |
| `seed` | 契約に保持。現在の最小費用流は ID 順で探索し、seed は探索に使わない |

`roster`、`cp_sat`、時間横断制約、担当切替・勤務量の目的は `INVALID_INPUT`。
Schema は契約0.1全体を表すが、未対応条件を意味検証で拒否する。
必要な条件を捨てたり、需要不足のまま正式な解を返したりしない。
`BACKEND_UNAVAILABLE` / `FEASIBLE` は共通契約に含むが、現在の方式では発生しない。

日時は既知のオフセット付きで指定する。UTC に正規化した実時間で時間枠を作り、
出力は計画の IANA タイムゾーンで表す。入力のオフセットが異なっても同じ時点なら同じ意味になる。
時計変更時も実時間の分数を使う。秒・端数分を丸めず、計画開始からの時間粒度に揃える。
勤務可能時間と同じ役割の需要は重なりを拒否し、終端と開始が接する区間は許可する。

## 結果の判断

- `OPTIMAL`: 独立検証を通過し、指定されたモデルの最適解を得た。
- `INFEASIBLE`: 人数・担当資格の不足または技能の取り合いにより、厳密な需要を満たせない。
- `UNKNOWN`: 探索予算が切れ、完全な解を得られていない。不可能性の証明ではない。
- `INVALID_INPUT`: 構造、参照、日時、上限または対応範囲を修正する必要がある。
- `INTERNAL_ERROR`: ソルバーの障害、壊れた解、評価値・出力契約の不整合。正式な解は返さない。

`INFEASIBLE` 以下の状態は `solution: null`、`objectives: []`。
未検証は `verification.performed: false` / `valid: null`。
解または出力の検証が失敗した場合は `performed: true` / `valid: false` と違反を記録する。

`INSUFFICIENT_QUALIFIED_EMPLOYEES` は単独役割の勤務可能な有資格者不足、
`COMPETING_ROLE_DEMAND` は複数役割を同時に埋められないことを示す。
診断の `facts` に時間枠インデックスと人数を保持する。最低追加人数は推測しない。
ソルバーの正規化テーブルを検証器へ信用させず、元入力と担当区間から
担当資格・勤務可能時間・需要・二重配置と目的値を照合し、Response 全体も検証する。

## 上限と探索時間

従業員250人、役割50、技能100、需要10,000件、時間枠3,000、
従業員 × 時間枠 × 役割1,000,000以下。その他の配列上限は版別 Schema に記録する。
上限内で応答性能を保証するものではない。

`time_limit_seconds` はグラフ構築後に始まる、すべての時間枠に共通の探索予算。
途中で切れた場合、部分的な配置を返さず `UNKNOWN` にする。
空需要は探索を要しない。入力検証・正規化・構築・結果検証・出力を含む総時間は
`stats.elapsed_seconds` に記録する。外部応答期限やプロセス隔離は未導入。

## 検証とビルド

```sh
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra
uv build --wheel
```

既存 CI の `deploy-entrypoint` で、既存テストに加え、全探索比較150件、
壊れた解の検出、厳密な入力・出力、時計変更、時間切れ、CLI、wheel を検証する。
wheel のテストは、ソース checkout を import せず同梱 Schema・ライブラリ・CLI を実行する。
今回の実測と未検証事項は [担当配置の検証記録](evaluations/assignment.md) に残す。
