# 参照実装の評価とエンジン導入方針

評価日: 2026-10-05（Asia/Tokyo）。対象: [Issue #5](https://github.com/omitsuhashi/schedula/issues/5)。

## 導入判断

SkillShift Starter 0.1 の ZIP を取得し、保存済みの契約・例との一致と、OR-Tools 導入下での
実行を確認した。未変更の参照テストの再実行は **223 passed / 1 skipped**。
`assignment`、`linked_assignment`、`roster` は検証済みの `OPTIMAL` を返した。
ただし初回実行の失敗と、障害注入で検出した結果検証の不足を後述する。

参照 README は「ライセンスはまだ選定していません」と明記し、ZIP に LICENSE はない。
したがって、参照コード・テストの取り込みは保留する。既存の参照スナップショットは保持し、
schedula のコード・テスト・実行用 Schema は、採用済みの業務仕様と公式 API を基準に独自実装する。
参照コードの利用許諾を後から確認できても、採用可否は改めて判断する。
許諾待ちを [Issue #6](https://github.com/omitsuhashi/schedula/issues/6) のブロッカーにしない。

## 入手と原本の照合

[出典](../sources.md)の元チャットは ZIP の `sandbox:/mnt/data/skillshift-starter-0.1.zip` を示す。
今回、ローカルの Codex 添付保存領域にある次のファイルを取得元として確認した。
このパスは当該端末の入手記録であり、他の環境で取得できる公開 URL ではない。

```text
/Users/omitsuhashi/.codex/attachments/e5245fdb-4618-4194-964b-f00dc33b66dc/skillshift-starter-0.1.zip
SHA-256: dd45f15862f866a0b28762b3314b2fb07c0f2d4942630b6a299106023c9879d6
```

[manifest](../reference/skillshift-starter-0.1/manifest.json)のアーカイブ SHA-256 と一致した。
ZIP は22ファイル。保存済み原本8件について、ZIP 内の元パス、バイト数、SHA-256、
保存ファイルとのバイト列一致を確認した。原本の変更はない。

評価先は `/private/tmp/schedula-issue5-reference-20261005/skillshift-starter`。
参照ソースを変更せず、uv が作成する環境、lock file、ビルド情報だけを隔離先に追加した。
ZIP 自体と参照の Python コード・テストは schedula の配布物へ追加していない。

## 評価環境と依存

| 対象 | 実測値 |
| --- | --- |
| OS / CPU | macOS 26.7.1 / ARM64 |
| Python | CPython 3.14.8、Clang 22.1.3 |
| uv | 0.12.23 |
| 参照パッケージ | `skillshift-starter` 0.1.0、editable install |
| jsonschema / OR-Tools | 4.26.0 / 9.15.6755 |
| pytest | 9.1.1 |
| numpy / pandas / protobuf | 2.5.3 / 3.0.6 / 6.33.6 |
| rpds-py | 参照隔離環境は 2026.9.1、schedula の lock 環境は 2026.6.3 |

参照は Python `>=3.11`、jsonschema `>=4.23,<5`、OR-Tools `==9.15.6755`、
pytest `>=8,<10` を宣言している。現在の schedula の Python と直接依存で実行できた。
参照の `dev` は extra なので、schedula の `dependency-groups.dev` と区別して指定した。
隔離環境で解決した全依存・wheel のハッシュは
[評価用 uv.lock](engine-introduction-20261005/uv.lock)、実際の版は
[environment.json](engine-introduction-20261005/environment.json)に保存する。
schedula 直下の依存定義と lock file は変更していない。

インストール済み metadata / LICENSE と公式原本で、
[OR-Tools 9.15 の Apache-2.0](https://github.com/google/or-tools/blob/v9.15/LICENSE)と
[jsonschema 4.26.0 の MIT](https://github.com/python-jsonschema/jsonschema/blob/v4.26.0/COPYING)を確認した。
これは直接依存の確認であり、参照 ZIP や schedula 本体の利用許諾を示さない。
推移依存・同梱物の表示、本体ライセンスとセキュリティ窓口は配布前に揃える。

## 実行結果

| 実行 | 成功 | 失敗 | スキップ | 結果 |
| --- | --- | --- | --- | --- |
| 参照 pytest 初回 | 222 | 1 | 1 | 27.31秒。`test_cp_examples[assignment]` が `UNKNOWN` |
| 未変更の参照 pytest 再実行 | 223 | 0 | 1 | 1.16秒 |
| 再実行の CP-SAT 対象 | 28 | 0 | 0 | 例4件、最小費用流との比較20件、勤務ルール・目的順序・時間切れ4件 |
| schedula の CP-SAT 基本確認 | 2 | 0 | 0 | 整数最小化の `OPTIMAL` / 値7、矛盾追加後の `INFEASIBLE` |

1件のスキップは `test_unavailable_backend_is_explicit`。
OR-Tools がない環境専用のテストで、今回の依存導入環境では意図どおりスキップされた。
依存未導入時の実行検証は今回行っていない。
150件の小規模担当配置と全探索の比較は、今回も参照テスト内で成功した。
集計と失敗の詳細は [test-results.json](engine-introduction-20261005/test-results.json)に保存する。
schedula の基本確認は [schedula-cpsat-smoke.json](engine-introduction-20261005/schedula-cpsat-smoke.json)に記録する。
ZIP 作成時の `196 passed / 28 skipped` は過去の結果であり、今回の実測とは別である。

CLI の各例は、入力を変更せず、新しいプロセスで順に実行した。
全出力が参照 Response Schema に適合し、標準エラーは空だった。

| 入力 | backend / status | 評価値 | 解・終了コード | エンジン時間 |
| --- | --- | --- | --- | --- |
| `assignment.json` | `min_cost_flow` / `OPTIMAL` | `preference_penalty: 0` | 担当区間3件、勤務0件、検証成功、0 | 0.002603秒 |
| `linked_assignment.json` | `cp_sat` / `OPTIMAL` | `preference_penalty: 0` | 担当区間3件、勤務0件、検証成功、0 | 0.215135秒 |
| `roster.json` | `cp_sat` / `OPTIMAL` | `preference_penalty: 60` → `scheduled_minutes: 2640` → `role_switches: 0` | 候補32件から勤務8件、担当区間24件、検証成功、0 | 0.302508秒 |
| `infeasible.json` | `min_cost_flow` / `INFEASIBLE` | なし | `solution: null`、未検証、2 | 0.002328秒 |

成功した目的はすべて `proven_optimal: true`、`verification.valid: true`。
今回の出力 JSON は [評価結果ディレクトリ](engine-introduction-20261005/)に保存した。
参照同梱の `assignment.result.json` は更新していない。
時間は単発測定で、実務規模の性能保証や外部応答期限ではない。

## 後続実装で修正する差分

### 探索予算より前にバックエンドを準備する

初回は参照テストと CLI 評価を並行実行した。テストの最初の CP-SAT 例は20秒予算で
`UNKNOWN`、CLI の最初の `linked_assignment` は10秒予算で、エンジン時間27.004294秒、
`UNKNOWN` / `TIME_LIMIT` / `solution: null` になった。後者は例の評価を中断した。
再実行時に直接測った CP-SAT import は0.217521秒で、テストと全例は成功した。
初回の import 単体の時間や、並行実行・OS の初回ロードの寄与は直接計測していない。

参照 `engine.py` は期限を設定してから依存とアダプターを読み込み、`cpsat.py` は
`cp_model` の import とモデル構築の後に残り時間を確認する。
[再現プローブ](../../scripts/probe-reference.py)で import に20msの人工遅延を入れ、
探索予算10msの入力が探索前に `UNKNOWN` / `TIME_LIMIT` になることを確認した。
参照ソースを変更せず、プロセス内だけで障害を注入している。

CP-SAT を導入する Issue では、依存読み込み・モデル構築を探索予算の前に完了させ、
目的ごとの `solver.solve` に渡す探索時間を同じ予算から消費する。
入力検証から結果検証までの総時間は別に測る。最小費用流でも入力正規化と探索を分ける。
遅い初期化・上位目的未証明・後段の時間切れのテストを追加し、
探索前の遅延で予算が減らないことと、後段では既存の有効解を保持することを確認する。

### 構造検証を有効な解の返却条件にする

参照 `verify.py` は構造検証を呼び出し側に求めるが、`engine.py` は Response Schema を
検証せずに意味検証だけで解を返す。
`make_solution` が未知プロパティ `unexpected` を加える障害注入では、
参照 API は `OPTIMAL` / `verification.valid: true` の解を返し、外部の Schema 検証は拒否した。
通常の例で発生した不正ではなく、壊れた内部結果を遮断する処理の不足を確認したものである。

Issue #6 では、共通の解の構造検証、独立した意味検証、出力からの目的値再計算、
Response 全体の構造・状態整合を確認してから解を返す。
いずれかに失敗したら `INTERNAL_ERROR` / `solution: null` とし、検証失敗を診断に残す。
未知項目・欠落項目・型不正の解を注入したテストも追加する。
両プローブの実測は [boundary-probes.json](engine-introduction-20261005/boundary-probes.json)に保存する。

## 採用する構造と独自実装の範囲

| 対象 | 導入方針 |
| --- | --- |
| JSON 契約・例 | 保存済み原本を照合基準にする。schedula 用 Schema と例は業務仕様から作成する |
| `model.py` / `templates.py` | ID、時間枠、担当資格、需要、候補展開の責任分担を採用し、意味検証を独自実装する |
| `flow.py` | 標準ライブラリによる整数費用の最小費用流を独自実装する。技能の取り合いと全探索比較を検証する |
| `cpsat.py` | OR-Tools の公式 API で担当配置と勤務候補を同時にモデル化する。予算管理と状態を独自実装する |
| `verify.py` / `engine.py` | ソルバーから独立した結果検証と再計算を実装し、上記の構造検証不足を修正する |
| `__main__.py` / パッケージ設定 | schedula の入口を独自実装する。重複 JSON キーと非有限数を読み取り時に拒否する |
| 参照テスト | 試験条件と評価値を照合基準にする。テストコードをコピーせず、schedula の受け入れ条件で書く |

独立検証器は OR-Tools に依存させない。`auto` の単一バックエンド選択、厳密な需要、
候補内の最適性、未知条件の拒否は既存の ADR・設計方針を維持する。
CP-SAT の状態と API は [公式資料](https://developers.google.com/optimization/cp/cp_solver)を確認した。
確認したコードと正常例の範囲では採用済みの業務仕様との矛盾は見つからなかったが、
勤務計画の全探索比較、大規模性能、全境界条件の検証を完了したという意味ではない。

## 契約と公開入口の決定

実行契約はパッケージ同梱の
`src/schedula/schemas/0.1/request.schema.json` と
`src/schedula/schemas/0.1/response.schema.json` に置き、
`$id` は `urn:schedula:request:0.1` / `urn:schedula:response:0.1`、
`$schema` は `https://json-schema.org/draft/2020-12/schema`、`schema_version` は `"0.1"` とする。
参照用 `urn:skillshift:*` は変更しない。
版の変更・移行と公開入口の詳細は [入出力契約](../io-contract.md)を正本とする。

Issue #6 で `src/schedula/` を作り、`from schedula import solve` と
`solve(request: dict) -> dict`、`python -m schedula solve <入力ファイル>` を実装する。
Schema の取得は `python -m schedula schema request` / `response` とする。
`setuptools.build_meta` でパッケージをビルドし、版別 Schema を wheel に同梱する。
インストールした wheel から API・CLI・Schema を利用できることを同 Issue で確認する。
現時点では入口を確定しただけで、schedula の実行パッケージや外部配布はまだない。

## 再実行の手順

リポジトリ直下で次のように原本を照合し、隔離先に展開する。
`archive_path` は手元で取得できた同じ SHA-256 の ZIP に置き換える。

```sh
repo_root="$(pwd)"
archive_path="/path/to/skillshift-starter-0.1.zip"
reference_dir="$(mktemp -d)"
uv run --locked --extra cp-sat python - "$archive_path" "$reference_dir" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

snapshot = Path("docs/reference/skillshift-starter-0.1")
manifest = json.loads((snapshot / "manifest.json").read_text())
archive_path, reference_dir = map(Path, sys.argv[1:])
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == manifest["archive_sha256"]
with ZipFile(archive_path) as archive:
    for entry in manifest["files"]:
        raw = archive.read(entry["archive_path"])
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert raw == (snapshot / entry["path"]).read_bytes()
    archive.extractall(reference_dir)
PY
cp docs/evaluations/engine-introduction-20261005/uv.lock "$reference_dir/skillshift-starter/uv.lock"
cd "$reference_dir/skillshift-starter"
uv sync --locked --python 3.14.8 --extra dev --extra cp-sat
uv run --locked --extra dev --extra cp-sat pytest -q -ra
uv run --locked --extra dev --extra cp-sat python -m skillshift solve examples/assignment.json
uv run --locked --extra dev --extra cp-sat python -m skillshift solve examples/linked_assignment.json
uv run --locked --extra dev --extra cp-sat python -m skillshift solve examples/roster.json
uv run --locked --extra dev --extra cp-sat python -m skillshift solve examples/infeasible.json
uv run --locked --extra dev --extra cp-sat python "$repo_root/scripts/probe-reference.py"
```

今回の初回同期は lock file 生成のため `uv sync --python 3.14.8 --extra dev --extra cp-sat`。
再同期では保存した評価用 lock を使う。人数不足例の終了コード2は期待値である。
プローブは既知の不足を再現したときに終了コード0となり、修正を検証するテストではない。

## 後続の着手条件と未検証事項

Issue #6 は、確定した API・CLI・版別 Schema、独自実装方針、構造検証の修正条件から着手できる。
まず独立した `assignment`、目的は空または `preference_penalty` に限定し、
`roster`・時間横断制約・未対応 backend を明示的に拒否する。
既存 CI で担当配置の全探索比較、壊れた解の検出、Response の整合、wheel の入口を検証する。
CP-SAT の導入時には探索予算の差分と目的順序の状態検証を含める。

今回の評価は参照実装と依存環境の確認である。schedula エンジンの実装、
Linux での参照テスト、勤務計画の全探索比較、実務規模の性能、依存なしの経路、
Web・API・LLM・実運用デプロイ・外部配布は未検証である。
本 Issue の PR の CI 成功を、これらの完了に置き換えない。
