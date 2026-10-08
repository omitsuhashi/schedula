# 勤務費用と指定区間の目標偏差の検証

2026-10-08、[Issue #77](https://github.com/omitsuhashi/schedula/issues/77)と
[Issue #78](https://github.com/omitsuhashi/schedula/issues/78)の契約0.9を検証した。
開始commitは `c4c2c65e19ed17a8052bb7fce4f835d2c9ea0d96`。
利用条件は[契約0.9](../io-contract-roster-metrics.md)、入力は架空の従業員・需要である。

## 環境とコマンド

macOS / Apple Silicon、CPython 3.14.8、OR-Tools 9.15.6755、jsonschema 4.26.0。
既存の `uv.lock` と配布版0.1.5を使い、新しい依存は追加していない。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat ruff check .
uv run --locked --extra cp-sat ruff format --check .
uv run --locked --extra cp-sat python scripts/evaluate.py examples/scheduled_cost.json examples/duty_balance.json --output test-results/roster-metrics.json
git diff --check
```

Chromium結合は既存の `tests/playground-browser.cjs` を使う。
`PLAYWRIGHT_MODULE_PATH` に既存のPlaywrightを指定し、`node tests/playground-browser.cjs` を実行する。
隔離wheel・sdist・mypy consumerは全体pytestのdistributionテストに含まれる。

## 受け入れと実測

| 確認 | 結果 |
| --- | --- |
| 費用→選好 / 選好→費用 | Alice・108000・選好60 / Bob・144000・選好0。全候補列挙と一致 |
| 17分・単価1800 / 1分・単価1001 | 30600 / 1001費用単位。倍率60で1001/60を丸めない |
| 費用・偏差・希望の全優先順 | 6通りを小規模候補の全列挙と照合 |
| 昼夜の交代・既存fairness・費用 | 各人480分。夜勤交代は偏差0、同じ人が両夜なら480。費用は同じ2016000 |
| 7日Alice夜固定・8日昼回避 | 偏差優先は0/選好240、希望優先は480/選好0。固定を保持 |
| preserve_assigned / 変更優先 / rebuild | 前二者は偏差480を保持、rebuildは交代して0 |
| 22:00〜02:00と00:00〜04:00 | 和集合360分、重複・再掲・入力順を独立集計で照合 |
| 休憩・分割・待機・目標0・対象外・未達 | 休憩と非勤務を除外、待機を含む。対象者と明示目標だけを集計 |
| BerlinのDST | 01:00+02:00〜04:00+01:00は240分、休憩30分なら210分 |
| 境界夜勤と費用 | 420分を10月120分・216000、11月300分・540000へ投影。通し756000と一致 |
| 不足とpriority | 安価な無勤務へ逃げず、総不足を固定して高priorityの需要を優先 |
| 上位未証明・期限 | 後続を探索せず、費用・偏差の最適性をfalseに保持 |
| 入力拒否 | 単価欠落・未知・重複・混在項目・不正整数・費用上界超過、評価と目的の不一致・区間・目標・上限を拒否 |
| 公開集計と改ざん | 元segments・休憩・単価・区間から再計算。集計・目的値・duty_id・勤務の改ざんを拒否 |
| 基準と単価変更 | 元Requestの単価を保持。新単価2000で同じ120分勤務なら費用240000・変更0 |
| 旧契約・公開境界 | 新項目は旧0.1〜0.8で拒否。CLI、全Schema、型、独立verify、make_baselineを検証 |

[測定記録](https://github.com/omitsuhashi/schedula/blob/codex/scheduled-cost-duty-balance/docs/evaluations/results/2026-10-08-roster-metrics.json)は
未コミットの実装をコピーしたsnapshotのsource SHA、入力SHA、環境、全2試行、探索・準備・検証時間を持つ。
両入力とも `OPTIMAL`、独立検証成功。費用例の目的は `[108000, 60]`、
夜勤例は `[0, 240, 2016000]`。探索はそれぞれ約0.0044秒・0.0091秒。
この小規模測定は実務規模の応答時間を保証しない。

初回の追加75件、機能追加後の関連回帰310件は成功、スキップ0。
初回全体実行は1458件と6 subtests成功・1件失敗。
失敗は評価文書の作成前にsdistをビルドし、利用文書からのリンク先が未作成だったため。
評価文書を追加した後、全体1461件と6 subtestsが498.26秒で成功し、失敗・スキップ0。
隔離wheel、sdistからの独立ビルドと中核テスト再実行、mypy consumerも含む。
最終レビューで追加した費用・偏差と矛盾縮小の結合を含め、
`tests/test_roster_metrics.py tests/test_conflict_refinement.py tests/test_evaluation.py`
の137件も11.25秒で成功した。新機能テストは最終86件。

途中の追加確認は93件成功・1件失敗で、既存の旧package評価がsandboxからuv cacheを読めなかった。
通常のcacheアクセスを許可した上記137件では同じ評価も成功し、失敗・スキップ0。
Chromiumの3シナリオ・JSON入力・100人30日・キーボード・狭い画面・応答失効、
Ruff hooks、差分検査が成功した。旧0.1〜0.8のSchemaの原bytesを維持した。

履歴を含む夜勤休日評価は#79へ残し、0.9ではW外を受理しない。
PyPI公開・タグ作成・productionデプロイは実施していない。

## JSON画面の契約版処理の修正

PR #83のレビュー指摘を受け、JSON画面が0.9入力を0.1として応答照合していた問題を修正した。
0.6〜0.9をそのまま照合し、不足・priority集計と証明の検証を同じ版まで適用する。
目的の照合には `duty_id` も含める。READMEの0.1〜0.9対応という記載を維持する。

既存Chromium結合に、0.9の費用・夜勤例の貼り付け実行と、0.6〜0.9のPARTIAL表示を追加した。
費用108000/2016000、夜勤偏差0、不足60人分を確認し、
不足合計・priority・矛盾する証明・解なし集計・duty_idの改ざんを拒否した。
修正前の追加テストは版不一致で失敗し、修正後は既存操作も含めて成功した。
途中で目的のないPARTIALの未証明priorityを不正と期待したテストが1件失敗したため、
総不足未証明なのにpriority証明済みという矛盾した応答へ修正した。

`uv run --locked --extra cp-sat pytest -q -ra tests/test_playground_server.py tests/test_playground_scenarios.py`
は61件成功、失敗・skip 0。最初のsandbox実行は3件成功・HTTP bind権限不足で58件の準備エラー、
ローカルHTTPを許可した環境で再実行して成功した。Chromiumのコマンドは上記と同じ。
Nodeの構文検査、Ruff、差分検査も成功した。エンジン・旧Schema・依存は変更していない。

続くレビュー指摘に対応し、0.9の失敗応答では早期return前に
`cost_summary` と `duty_balance_summary` が両方nullであることを確認する。
全5失敗状態について、各集計を個別に残す応答の拒否と両方nullの受理の計15ケースを
既存Chromium結合へ追加し、既存操作も含めて成功した。Nodeの構文検査・差分検査も成功した。
