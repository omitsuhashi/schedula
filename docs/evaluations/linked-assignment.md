# 時間横断条件と CP-SAT の検証記録

検証日: 2026-10-06（Asia/Tokyo）。対象: [Issue #7](https://github.com/omitsuhashi/schedula/issues/7)。
前提の Issue #6 は完了済みであり、main の `144fe8b` から実装した。
[参照 ZIP の評価](engine-introduction.md)、[独立配置の検証](assignment.md)と区別して、
今回の schedula コードを実行した。保存済み参照原本8件のサイズ・SHA-256 は manifest と一致する。

## 実装と契約

`assignment` の CP-SAT モデルに基本条件、`max_assigned_minutes`、`max_role_switches` を導入し、
空目的または `preference_penalty` / `role_switches` のいずれか一つを扱う。
担当切替は、隣接枠で両方とも担当し、役割が異なる場合だけ数える。
独立検証器は元入力と返された担当区間から上限・目的値を計算し、壊れた解を公開しない。

`auto` は従来の設計に沿って一つの方式を選び、明示した最小費用流で扱えない条件は
`INVALID_INPUT`、CP-SAT の依存不足は `BACKEND_UNAVAILABLE` とする。
複数目的、`roster` と勤務ルールは今回受理しない。
Request / Response Schema の構造・意味は既存0.1を維持し、対応機能をパッケージ版0.1.1で記録する。
依存の追加・更新は行わず、`uv.lock` の差分は schedula の版だけである。

## 実行環境

| 対象 | 実測値 |
| --- | --- |
| OS / CPU | macOS 26.7.1 / ARM64 |
| Python / uv | CPython 3.14.8 / uv 0.12.23 |
| schedula / jsonschema | 0.1.1 / 4.26.0 |
| OR-Tools | 9.15.6755 |
| pytest / Ruff / pre-commit | 9.1.1 / 0.16.10 / 4.6.2 |

指定された checkout が存在しなかったため、`/private/tmp/schedula-issue7-20261006` に clone した。
`uv sync --locked --extra cp-sat` で同期し、テスト内の `uv build` も実行できるように
`/Users/omitsuhashi/.local/bin` を PATH に追加した。CP-SAT は1 worker で実行し、入力の seed を渡す。

## コマンドと結果

リポジトリ直下で、正本の uv 手順を使用した。

| 実行 | 成功 | 失敗 | スキップ・理由 |
| --- | --- | --- | --- |
| `uv run --locked --extra cp-sat pytest -q -ra` | 593件、既存 subtest 6件 | 0件 | 0件 |
| `uv run --locked --extra cp-sat pytest tests/test_cp_sat.py -q -ra` | CP-SAT 対象132件 | 0件 | 0件 |
| `uv run --locked --extra cp-sat ruff check .` | 成功 | 0件 | なし |
| `uv run --locked --extra cp-sat ruff format --check .` | 37ファイル成功 | 0件 | なし |
| `uv run --locked --extra cp-sat python -m schedula solve examples/linked_assignment.json` | `OPTIMAL`、ペナルティ0、検証成功、終了コード0 | 0件 | なし |
| `uv build --wheel --out-dir /private/tmp/schedula-issue7-wheel` | 0.1.1 wheel 作成 | 0件 | なし |
| wheel の Schema / API / CLI、OR-Tools 不在の隔離実行 | pytest 内で成功 | 0件 | なし |
| `bash -n scripts/deploy` / `git diff --check` | 成功 | 0件 | なし |
| 参照原本8件の SHA-256 / サイズ | 全件一致 | 0件 | なし |

最終 pytest の実測時間は5.49秒。単発の確認であり、実務規模の性能保証ではない。
例の Response は `backend: cp_sat`、`selection_reason: ASSIGNMENT_CONSTRAINTS`、
`library_version: 9.15.6755`、`engine_version: 0.1.1` を記録した。
GitHub CI の URL と結果は PR に記録する。

## 比較・境界・障害経路

- 共通の小規模入力150件を最小費用流と CP-SAT のそれぞれで実行し、元入力による全探索と
  実行可能性・最適値が一致した。同率解の従業員・役割配置の一致は要求していない。
- 時間横断条件を含む小規模入力80件を別の全探索で照合した。
  2人・2役割・3時間枠で、勤務可能時間、担当時間・切替上限、空目的・選好・切替目的を変えた。
- 担当60分に対する上限0・29・30・59・60・61分、切替回数の上限未満・一致・余裕を確認した。
  各従業員への個別適用、同一従業員への複数条件、空需要・勤務不可・上限0も確認した。
- 同一役割、連続した役割変更、未担当枠を一つまたは複数挟んだ変更を確認した。
  担当切替の目的なしでも必須上限が守られることを検証した。
- 制約の参照・ID・対象者重複、負数・端数・未知項目・未知ルール・未対応勤務ルールを拒否した。
  複数目的、明示した最小費用流と時間横断条件の組合せも、依存読み込みより前に拒否した。
- 方式の呼び出し回数を照合し、`auto` / 明示指定が一つのバックエンドだけを呼ぶことを確認した。
  `selection_reason` と実際に読み込んだ OR-Tools の版を照合した。
- 壊した解の担当時間・切替上限違反と切替目的値の不一致を独立検出し、
  `INTERNAL_ERROR` / `solution: null` とした。ソルバー用の正規化テーブルを空にしても照合できた。
- OR-Tools の import 失敗を注入し、明示指定・制約・切替目的のどの選択でも自動退避しなかった。
  別途、ビルドした wheel を `uv run --no-project --isolated --python <テスト用Python> --with <wheel>
  --with jsonschema==4.26.0` で導入し、`find_spec("ortools") is None` を実測した。
  ソース checkout を import せず、最小費用流は `OPTIMAL`、CP-SAT は `BACKEND_UNAVAILABLE`、
  CP-SAT CLI は JSON のみを返して終了コード2、非対応の最小費用流は `INVALID_INPUT` だった。
- 実際の CP-SAT に探索予算1nsを渡して `UNKNOWN` / `TIME_LIMIT` を確認した。
  import・モデル構築・探索の順序と、探索に渡す予算が入力と同じことも確認した。
- `FEASIBLE` / `MODEL_INVALID` などの状態変換は、ネイティブ境界への状態注入で検証した。
  `FEASIBLE` の変数値は実際の CP-SAT で得た解を使い、独立検証・目的値・`proven_optimal: false`
  を確認した。実行可能性だけの状態でも壊れた解の公開を遮断した。

初回の全件実行は uv が子プロセスの PATH にないため wheel テスト1件が失敗し、
460件・subtest 6件が成功した。PATH を修正して全件を再実行し、未解決の失敗はない。
CP-SAT の対象ファイルは OR-Tools を通常 import し、依存不足での skip に置き換えていない。

CP-SAT の整数モデル・状態は [OR-Tools の公式説明](https://developers.google.com/optimization/cp/cp_solver)、
基本配置は [従業員スケジューリングの公式例](https://developers.google.com/optimization/scheduling/employee_scheduling)
を確認した。参照 ZIP のソースコード・テストはコピーしていない。

## 未検証事項

勤務計画、複数目的の優先順最適化・共有探索予算・後段の時間切れでの解保持は後続 Issue の範囲。
実務規模の性能、自然な探索打ち切りでの `FEASIBLE` 発生、Windows 本体、
HTTP の隔離・応答期限・キャンセル、公開配布とデプロイは未検証。
未入力の業務ルールや現場データの真偽に適合する保証として扱わない。
