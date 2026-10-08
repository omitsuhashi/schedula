# 履歴を含む指定区間の目標偏差の検証

2026-10-08、[Issue #79](https://github.com/omitsuhashi/schedula/issues/79)の契約0.10を検証した。
開始commitは `36925c320a5fd38d4f2fea588387d613690b62fe`。
条件と公開入口は[利用文書](../io-contract-duty-continuity.md)を参照する。
架空の入力を使い、新しい依存は追加しない。成功・失敗・未確定の結果を以下に記録する。

## 環境と再実行

macOS / Apple Silicon、CPython 3.14.8、OR-Tools 9.15.6755、jsonschema 4.26.0。
配布版は未公開の0.1.5、依存は既存 `uv.lock` を使う。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat python scripts/evaluate.py examples/continuity_duty_balance.json docs/evaluations/inputs/continuity-duty-partial.json docs/evaluations/inputs/continuity-duty-conflict.json docs/evaluations/inputs/continuity-duty-invalid.json docs/evaluations/inputs/continuity-duty-timeout.json --repeat 3 --source-ref b50edc8bfaa527d429e7d959722fc3b749c7af89 --output test-results/continuity-duty-balance.json
git diff --check
```

Chromiumは既存 `tests/playground-browser.cjs` のJSON入力経路を使い、0.10の実計算と失敗応答を確認する。
隔離wheel・sdist・mypy consumerは既存の全体pytestへ含める。

## 確認する意味

| 対象 | 期待値・確認 |
| --- | --- |
| 過去Alice240分・Bob0分、残り240分 | Bobを選び偏差0。Aliceだけなら480 |
| 履歴欠落・未確認・C外・精度・粒度 | 入力拒否。確認済み勤務なしだけ0分 |
| 月末夜勤・休憩・分割 | 原区間を一度集計。420=120+300、費用756000=216000+540000 |
| DSTとW外の17分 | 287分=過去17+W内270分。休憩30分を除外 |
| 未来の確定勤務・Wを越える候補 | 返却解に重なる事実とW外だけの事実を重複させない |
| 不足・priority・費用・希望 | 6目的順を8枠の全列挙と照合 |
| 固定・上下限・休息・連勤 | 必須状態を保ち、達成不能な目標は偏差として残す |
| 旧版・基準往復・改ざん | 新版の旧基準受理、旧版の新基準拒否、履歴/原segments/集計/目的の改ざん検出 |
| UNKNOWN・未証明段階 | 上位未証明なら下位を探索せず、完成済みの解と証明範囲を保持 |
| 矛盾縮小 | 実績・確定勤務を背景に保持して必須条件グループを縮小 |

初回の追加確認は49件成功・6件失敗。失敗はテスト入力の作成不備3件
（fairness helperが目的を置換、continuityを外しても期間外の上限制約が残存、診断設定の項目違い）と、
待機勤務を許す既存仕様への期待値不足3件だった。入力と期待値の修正後は55件成功、失敗・skip 0。
固定勤務を保ったままBobの待機を追加すると偏差が480から240へ下がる。
変更目的を先に置く場合は待機追加も避け、元計画の偏差480を保つ。


## 最終の実行結果

追加の移動Wとcontinuityなしの確認を含む新機能57件、関連結合284件が成功した。
全体1523件と6 subtestsは506.02秒で成功し、JUnitのfailure・error・skipはすべて0。
隔離wheel、sdistからの独立導入と中核テスト再実行、mypy consumer、全Schema・公開型・CLIを含む。
Chromiumの3シナリオ・JSON入力・100人30日・キーボード・狭い画面・応答失効も成功。
0.10の実計算はBobを選び偏差0、全5失敗状態の集計残存を拒否した。
Ruff hooks、Nodeの構文確認、差分検査も成功した。旧0.1〜0.9のSchema18ファイルの原bytesを維持した。

[生の測定記録](https://github.com/omitsuhashi/schedula/blob/codex/continuity-duty-balance/docs/evaluations/results/2026-10-08-continuity-duty-balance.json)は
実装commit `b50edc8bfaa527d429e7d959722fc3b749c7af89` のgit archiveから測定した。
source・uv.lock・入力のSHA-256、環境と依存版、探索予算、全15試行を保存した。
新規Pythonプロセスを1件ずつ起動し、各入力3回、CP-SATは2 workers。
OSのファイルキャッシュは消去していない。入力不備の拒否とUNKNOWNも測定結果として残した。

| 入力 | 3試行の状態 | 呼び出し総時間の中央値 | ピークRSSの最大 |
| --- | --- | --- | --- |
| 履歴と残り夜勤 | OPTIMAL 3件、独立検証成功 | 0.341秒 | 108.0 MiB |
| 不足・priority・固定・費用・診断 | PARTIAL 3件、不足240人分、偏差0 | 0.341秒 | 106.1 MiB |
| 確定勤務と勤務量上限の衝突 | INFEASIBLE 3件、背景を保持した包含極小集合 | 0.334秒 | 106.4 MiB |
| 履歴未確認 | INVALID_INPUT 3件、INCOMPLETE_HISTORY | 0.071秒 | 36.4 MiB |
| 探索予算1e-9秒 | UNKNOWN 3件、解と最適性の主張なし | 0.315秒 | 102.5 MiB |

成功例の初回は準備0.00094秒・探索0.00922秒・独立検証0.01294秒。
矛盾例の初回は準備0.00089秒・探索0.00127秒、追加診断全体0.05183秒で、
各削除試行の準備・探索・検証も記録に残す。探索予算は総処理期限ではない。
小規模の架空入力と3試行の値であり、実務規模の性能保証には使わない。

履歴入力の真正性、未入力の未来勤務、分割最適化と通し最適化の同値は保証しない。
PyPI公開・タグ作成・productionデプロイは実施していない。
