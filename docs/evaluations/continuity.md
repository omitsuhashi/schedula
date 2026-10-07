# 継続計画の検証記録

対象は[Issue #74](https://github.com/omitsuhashi/schedula/issues/74)と
[契約0.6](../io-contract-continuity.md)。実績・確定勤務の原区間、期間投影、
休息・連勤、独立検証、旧版回帰を確認する。性能値の対象は下記の架空入力2件に限る。

## 環境とコマンド

2026-10-07、macOS ARM64、CPython 3.14.8、uv 0.12.23、
jsonschema 4.26.0、OR-Tools 9.15.6755、pytest 9.1.1、Ruff 0.16.10、mypy 2.4.0。
依存は `uv sync --locked --extra cp-sat` で同期した。

```sh
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat ruff check .
uv run --locked --extra cp-sat ruff format --check .
uv run --locked mypy --strict examples/typed_api.py
bash -n scripts/deploy
git diff --check
```

## 受け入れ試験

`tests/test_continuity.py` の50件が成功した。
最終修正後の入力契約・継続計画の部分検証は134件成功。

| 条件 | 結果 |
| --- | --- |
| 月末夜勤420分と未来60分 | 過去120・W内300・未来60、原区間・休憩を保持、不足0 |
| 週途中の実績960分と上限2400分 | W内1440、不足480人分、PARTIAL |
| 新候補のW終了越え | W内60、W外の整数分の休憩を保持して未来65 |
| 過去・未来との休息、未来固定までの連勤 | 660分を許容、630分・未来へ続く上限違反を選択不可。強制した解も検証失敗 |
| 履歴欠落・重複・アンカー・勤務可能時間 | 入力事実の矛盾と有効な条件の衝突を区別 |
| 分割勤務・間隔だけがWへ重なる勤務・W外だけの確定勤務 | 原区間を保持、非勤務を集計しない、外側区間の交差と勤務量を区別 |
| Europe/BerlinのDST | UTC実経過210分、明示オフセットを保持 |
| 改ざん勤務 | 参照・勤務日・休憩・区間・重複・確定勤務欠落を検出。モデルの候補・事実表を空にしても検出 |
| 全探索・通し/分割 | 12条件の小規模全列挙と不足→勤務量が一致。同じ固定勤務列の勤務量・不足・休息・連勤が一致 |
| 公開境界 | Schema、CLI、make_baselineの同一W往復、固定状態・公平性・選好を検証 |

未来を固定しない別問題の最適解一致は要求しない。移動Wの再計画は#75の対象。
費用・夜勤休日評価は未導入で、この変更では結合を確認していない。

## 全体実行と修正

最終実装 `88d853b` の[CI](https://github.com/omitsuhashi/schedula/actions/runs/37588785276)は全ジョブ成功。
Linux全体1265件と6 subtests、スキップ0、369.41秒。
隔離wheel・sdist単独実行、Ruff hooks、Chromiumが成功し、
Windows/Linuxのbase/extraはそれぞれ89件成功、スキップ0。
旧0.1〜0.5のSchemaが前提commit `89c6746` と同一であることも確認した。

macOSの修正後の全体回帰は1263件と6 subtests成功、スキップ0、207.96秒。
直前に成功した配布2件はこの再実行から除外した。
Ruff check / format、公開consumerのmypy strict、deploy入口の構文、文書リンク、`git diff --check`も成功。
後続の変更は本記録と評価生データのみで、上記の実装ソースは変更していない。

最初の制限環境の全体実行は1125成功・6失敗・58エラー・配布2件対象外、6 subtests成功。
ローカルHTTPのbind禁止58件、uv cacheへの書き込み禁止5件と、新版追加に伴う
既存テストのPARTIAL期待値1件だった。権限を揃え、期待値を新版の意味へ更新した。

次の全体実行は1233成功・1失敗、6 subtests成功、スキップ0。
失敗は作成途中の本記録への相対リンクをsdistで解決できなかったため。本記録を追加して修正した。
#66の契約0.5を統合後は1260成功・1失敗、6 subtests成功、スキップ0。
未知版を拒否する既存の試験データが新たに有効になった0.6を使っていたため、
未対応の0.7へ更新し、入力契約・継続計画の134件を再実行して成功した。
この全体実行の隔離wheelとsdist単独実行は成功した。

## 固定ソースの実行例測定

ソースは `88d853b063151a5519a53208693bc2d0f4f71373`、未公開配布版は0.1.5。
既存評価スクリプトで各例を新規Pythonプロセスから2回、並行数1で実行した。
OSのファイルキャッシュは消去しておらず、別の回帰試験も同じホストで進行していた。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py examples/continuity_month.json examples/continuity_week.json --output docs/evaluations/results/2026-10-07-continuity.json --repeat 2 --mode cold --source-ref 88d853b063151a5519a53208693bc2d0f4f71373
```

[生データ](https://github.com/omitsuhashi/schedula/blob/35e8fae4ddd128b4ccb2a5978f5cfa68b93ca788/docs/evaluations/results/2026-10-07-continuity.json)に入力・ソース・依存lockのSHA-256、環境、応答、独立検証、目的値、時間・RSSを保存した。
全4回で独立検証成功、ワーカー失敗・打切り0。時間は読み込み・準備・求解・検証を含む要求全体で、各工程を個別には測っていない。

| 入力 | 各2回の結果 | 要求全体の中央値 | peak RSS最大 |
| --- | --- | --- | --- |
| 月末夜勤 | OPTIMAL、不足0、過去120・計画内300・未来60分 | 0.383秒 | 107.23 MiB |
| 週途中 | PARTIAL、不足480人分、実績960・計画内1440分 | 0.374秒 | 106.28 MiB |

この2例の測定から大規模入力の処理能力や応答期限は判断しない。
