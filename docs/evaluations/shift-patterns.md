# 勤務パターンの受け入れ記録

対象は[Issue #88](https://github.com/omitsuhashi/schedula/issues/88)、契約0.13。
基点はmain `ad1c7c6`。2026-10-08、Apple Silicon macOS、CPython 3.14.8、
OR-Tools 9.15.6755と`uv.lock`の依存で確認する。#89〜#91の機能・規模評価は含めない。

## 再実行

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q tests/test_shift_patterns.py
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
node tests/playground-browser.cjs
```

ブラウザーは既存のPlaywrightと`PLAYWRIGHT_MODULE_PATH`を使う。
全テストはwheel・sdistの隔離導入、OR-Toolsなしのverify、公開型、CLI、版別Schemaを含む。

## 受け入れ内容

| ケース | 確認する結果 |
| --- | --- |
| 勤務・休・勤務、勤務・休・休・勤務 | 1日だけの完全休日を拒否、2日を受理。休日なし・全休日も受理 |
| 月曜夜勤の翌06:00 / 翌00:00終了 | min_days=2で金曜 / 木曜00:00から次勤務を許可。直前30分からの勤務を拒否 |
| 遅番→早番 | 開始日のday_offsetで禁止。別従業員・無関係な分類へ波及させない |
| 二つの週末群 | 同じ週末の土日勤務は一群、別週末の一日ずつは二群。夜勤明け・休憩は占有し、分割間の空白は占有しない |
| 分類の閾値・区間和集合 | 休憩を除く60分は閾値60で該当、61で非該当。重複区間を二重計上せず、複数分類・未参照分類を保持 |
| 前期間の実績と未来確定 | 実績が起点の禁止・休み義務を適用し、確定勤務を解除せずINFEASIBLE。診断は分類・原勤務を背景に保持 |
| 不完全な範囲 | 左右の余白不足・分類できない履歴要約・W外の未来休日をINCOMPLETE_HISTORYで拒否し必要範囲を返す |
| 7日間の全候補部分集合 | 128通り×休日数3設定。独立した最大休日区間計算とverifyを照合し、不足→勤務量の最適値を求解と照合 |
| 基準保存・固定・再構築 | 元分類・ルールを保持し、次Requestで明示された業務条件を適用。明示固定の休日と矛盾する案はINFEASIBLE |
| 旧版・公開境界 | 0.1〜0.12で新項目を拒否。0.13のSchema4種・型・CLI・共有探索予算を確認 |
| DST | 春・秋の23/25時間の日をローカル暦日で判定。時間の重なりを実経過分数で扱う |

入力例はPARTIAL、不足30人分・勤務780分・独立検証成功。
commit `93e327335f458de09ac70aa8527671a12590767f`のgit archiveを使った同一プロセス3回の
反復でも同じ値を返し、不足最小・勤務量最適の証明と独立検証が全回成功した。
初回Requestは0.502秒、継続2回の中央値は0.0221秒、最大RSSは109.80 MiBだった。
原結果は`docs/evaluations/results/shift-patterns-20261008-warm.json`に保存する。
3回の架空入力であり、cold比較や統計的な性能保証ではない。
分類・勤務パターンは法令判定や自動カレンダー生成ではない。
候補対の走査は同一人物の候補数に対して二乗で、準備時間を支配する場合は日付索引へ変更する。
本記録は架空入力の機能検証であり、実店舗や100人30日の性能保証ではない。

## 実行結果

新規の機能テスト64件は成功した。384通りの休日区間と、他3ルール各16通りの
候補部分集合を独立した期待値・公開verify・必須需要で固定した求解と照合した。
公開API・wheel consumerの3件、関連回帰249件、契約0.4と新規機能142件も成功した。
OR-Toolsなしの隔離wheelで0.13のPARTIAL・改ざんしたINVALID_PLAN・基準保存を確認し、
求解はBACKEND_UNAVAILABLEになった。mypy consumerでRequest013を確認した。

初回全体実行は1709成功・6失敗・6 subtests成功、543.70秒だった。
失敗は継承済み機能を拒否する旧版一覧、PARTIALを許す版一覧、公開型の一覧の更新漏れ5件と、
同じ5件を含むsdist内の中核テスト再実行。期待値を更新し、最終全体実行で再確認した。
実装側の結果は、0.13で継承するINFEASIBLE・OPTIMAL・PARTIALだった。

Chromium 151.0.7922.34で4ルールのJSONサンプル実計算、必須最低人数・不足表示、
余白不足の必要区間表示を確認した。既存3シナリオ、100人30日、キーボード、狭い画面、
応答失効も成功し、page errorは0。初回は必要区間が折りたたみ詳細にしか表示されなかったため、
診断欄へ直接表示するよう修正して再実行した。

旧0.1〜0.12の24 Schemaファイルは基点commitの原bytesと一致した。
uv.lockのSHA-256は`b848a99532d8d329e6b18c35257ec158ff829b111fe0b98a3381904cb7703cd7`。
Ruff hooks、Node構文確認、bash構文確認、git diff --checkは成功。
最終全体実行は1723件・6 subtestsが成功、557.17秒。skipは0だった。
配布用sdistから再構築したwheelの中核テストも成功した。
その実行中に変更した診断参照先の絞り込みは、新規機能64件を再実行して成功した。

PR #94のcommit `d938ac8300f98aa3031ce13dc29a8a6f98866507`に対するGitHub CIは、
全体1724件・6 subtestsが成功、526.35秒、skip 0だった。
Ubuntu/Windowsと通常/CP-SAT依存の4ジョブも各89件成功した。
[初回CI](https://github.com/omitsuhashi/schedula/actions/runs/37740030346)は
Chromium確認中にジョブの10分上限で中断した。全体回帰・配布物・ブラウザー確認を
完走できるよう当該ジョブの上限を15分へ調整し、再実行する。
