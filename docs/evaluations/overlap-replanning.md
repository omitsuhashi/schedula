# 重複期間の基準比較と固定再計画の検証

## 対象と合格条件

[Issue #75](https://github.com/omitsuhashi/schedula/issues/75)の契約0.7について、
公開変換→求解→独立検証→再保存を実行する。基準は原期間で保存・検証し、
比較・固定は重複期間だけに限定する。旧0.1〜0.6のSchemaと意味を維持する。

| 検証 | 実測・期待値 |
| --- | --- |
| 1日スライド | Aliceの新W勤務180分、過去60分、日間休息1380分、4連勤、変更量0 |
| 30分1枠・2枠のAlice→Bob交代 | 勤務変更2/4、役割変更2/4、合計4/8。期間から消えた日と新規日は含めない |
| off / break / work、role / null | 休憩から勤務への変更1と担当変更3、勤務・休憩からoffへの変更3と担当変更2を別々に検出 |
| 固定衝突 | 従業員・役割の削除、技能・勤務可能時間の衝突はINFEASIBLE。空状態の固定対象者の削除も拒否 |
| rebuild | 比較固定を外して求解し、確定勤務は原区間のまま保持 |
| 記録の矛盾 | 同じ勤務IDの従業員・原区間・休憩の矛盾はINVALID_INPUT。有効な別勤務と比較固定の衝突はINFEASIBLE |
| 保存・独立検証 | W・C・実績・確定勤務・業務条件を保持。範囲外のsource_fixed_statesも再検証し、ネストを増やさない |
| 変更範囲 | 前方・後方へのスライド、従業員ID和集合、重複外の固定拒否、重複なし・粒度/タイムゾーン変更の拒否 |
| 公開境界 | Request07のmypy consumer、4種類のCLI Schema、solve/verify、旧版の同一期間要求 |

## 環境とコマンド

実行日は2026-10-07（Asia/Tokyo）。macOS 26.7.1 / arm64、CPython 3.14.8、
uv 0.12.23、OR-Tools 9.15.6755、jsonschema 4.26.0、pytest 9.1.1、Ruff 0.16.10。
依存は既存uv.lockを使用した。追加依存なし。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q tests/test_overlap_replanning.py
uv run --locked --extra cp-sat pytest -q tests/test_demand_priority.py tests/test_overlap_replanning.py tests/test_input_contract.py
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
PLAYWRIGHT_MODULE_PATH=/private/tmp/schedula-revert-browser/node_modules/playwright node tests/playground-browser.cjs
uv run --locked --extra cp-sat python scripts/evaluate.py examples/continuity_replan.json --output test-results/overlap-replanning.json
git diff --check
```

最終の手元全体テストは1316件と6 subtestsが成功、失敗・スキップ0。隔離wheel導入、sdist単独の中核テスト再実行、
公開typing consumer、全Schemaの取得、Chromium、pre-commit、bash構文、diff確認が成功した。
契約0.7を追加した不足総量優先・段階別の時間切れを含む関連145件も成功した。

追加テスト38件が成功、失敗・スキップ0。小規模の担当者列挙とソルバーの不足・目的値を比較した。
独立検証ではCP-SATの呼び出しを禁止し、評価値の再計算に最適性証明が付かないことも確認した。

初回の全版向け検証では、0.7がPARTIALを返す正しい結果に対し、既存テストの版一覧が
未更新で1件失敗した。0.7を追加して回帰対象に含めた。
新テスト作成中には、期待日時の文字列置換がUTCオフセットも置換した誤り、
再保存時に新規担当も固定対象となる件数の誤り、rebuildの不足/完全状態の期待値誤りを修正した。
これらは検証コードの誤りであり、失敗を機能成功の証拠には使わない。
初回の全体実行は1313成功・2失敗・6 subtests成功・スキップ0。未対応版の試験値が0.7だったため99.0へ変更し、
sdistから除外する生データへの相対リンクを保存先の説明へ直した。Request07の型consumerは既存の隔離wheel検証へ統合した。

## 架空入力の実行測定

[実行入力](../../examples/continuity_replan.json)は2人・1役割・3日・30分粒度・5候補。
旧Wは10月5〜8日、新Wは6〜9日、比較Oは6〜8日。
生データ `docs/evaluations/results/2026-10-07-overlap-replanning.json` には入力SHA、source tree SHA、
uv.lock SHA、依存・目的値・証明・検証・時間・RSSを保存する。測定の生データはGitに保存し、sdistには含めない。

冷起動1回でOPTIMAL、不足0、独立検証成功、目的値0/180、各目的の最適性証明あり。
求解全体0.397秒、importを含むRequest処理0.453秒、ピークRSS107.6MiBだった。
単一の架空小規模入力の測定であり、大規模性能・応答時間の保証や改善比較には使用しない。
新規実績の自動生成・粒度/タイムゾーン変換・費用・夜勤休日評価は対象外。
パッケージ公開・タグ・productionデプロイは実施しない。

実装commitは `6a78bbd2b929548a99da5696f4739ecd18d58ef7`、[PR #81](https://github.com/omitsuhashi/schedula/pull/81)。
Linux・Windowsの最終CI結果はPRとIssue #75・#58へ記録する。
