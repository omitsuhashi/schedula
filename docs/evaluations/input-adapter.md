# 分割入力と実行記録の結合検証

対象は[マイルストーン8](https://github.com/omitsuhashi/schedula/milestone/8)、
実行契約0.1〜0.15、Adapter/manifest/record形式1.0、配布版0.1.6です。
仕様・全フィールドの所有元・省略/確認・I/O境界は[分割入力](../input-adapter.md)を参照します。
エンジン基点は `cd0787c194b1d3f592742f3a975d647aee694202`。
最終コード・CIの識別子は本実装PRに記録します。

## 再実行

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q -ra tests/test_adapter.py
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
PLAYWRIGHT_MODULE_PATH=/path/to/playwright node tests/playground-browser.cjs
uv run --locked --extra cp-sat python -m shift_schedula adapter solve examples/adapter/assignment.manifest.json --output run.json
uv run --locked python -m shift_schedula adapter verify-record run.json
```

既存ファイルの再出力には別の出力名または明示した `--overwrite` を使います。
原入力への上書きは許可しません。通常の測定はtest-resultsへ保存します。

## 代表入力と期待値

| 入力・検査 | 期待する結果 |
| --- | --- |
| assignment.manifest.json / assignment.draft.json | examples/assignment.jsonと構造・配列順が同一、VALID / OPTIMAL |
| roster.draft.json | 元rosterと同一、目的の順序とemployeeのID対応を保持 |
| partial_roster.draft.json | 元需要を保持、PARTIAL、独立検証成功、現在のverifyは不足最小性なし |
| continuity_week.draft.json | 原実績・確定勤務・文脈期間をそのまま保持 |
| partial_replan_preserve_assigned.draft.json | 原baseline/固定状態を保持、make_baselineを既存入口で実行 |
| unconfirmed.draft.json | UNCONFIRMED_SOURCEとUNRESOLVED_INPUT、部分Requestを出力しない |
| tests/test_adapter.pyの所有競合・不正参照・未知項目/版 | 入力元とpointerを持つ拒否診断、入力不変 |
| week-next-stale.draft.json → week-next.draft.json / week-next.request.json | 確認失効/期間不一致を診断、原履歴を移動しない |
| 同テストの構造的に有効な両立不能 | 組み立てVALID、既存solveがINFEASIBLE |
| 同テストの別実行・混在・原本保護 | request_idとは別のrun_id、ハッシュ検査、書込失敗で原本不変 |

組み立ては期待Requestの構造・値・配列順を比較します。業務意味の比較には同一保存Solutionを
両Requestでverifyし、stats以外の状態・診断・不足・評価を照合します。
同率配置や時間切れの二回のsolveの完全一致は要求しません。
旧版回帰は既存テストと全0.1〜0.15の組み立て/保存/再検証で確認します。
ソルバー未導入環境でも組み立て・validate・verifyを配布wheelから実行します。

## 実行結果と制限

2026-10-08、macOS / CPython 3.14.8 / jsonschema 4.26.0 / OR-Tools 9.15.6755 /
tzdata 2026.5で実行しています。初回追加テストは38件成功、スキップ0件でした。
修正後の追加テストは43件成功、スキップ0件。公開型のmypy strictも成功しました。
実ブラウザー（Chromium）は既存シナリオ・旧JSON・100人30日・新Adapterの保存往復まで成功。
保存往復の初回は整数floatのJSON表記変更でハッシュ照合に失敗し、数値正規化で修正しました。
後続の表示テストは閉じたdetailsのinnerTextを読んで失敗し、textContentで内容を照合しました。
初回全体回帰は1881件成功・1件失敗（sdist内部の途中版で数値正規化/未import名の2件失敗）、
スキップ0件でした。修正後のコードを固定して全体/配布物を再確認します。
Standards/Specの独立レビューで保存Request検証・0.1の混在検査・重複元の診断・置換理由保存を
修正し、レビュー側でも修正と再現テストの成功を確認しました。
初回の保存コマンドはtest-resultsディレクトリ未作成で出力に失敗し、元入力は不変でした。
出力先の親は利用者が作成します。同期の--lockedは配布版変更直後にlock不一致を検出し、
uv lockでパッケージ版だけを更新して再同期しました。

実ブラウザーは既存tests/playground-browser.cjsを使います。
実求解の完全/PARTIAL・個別確認・保存往復と、再現しにくいUNKNOWN/内部障害等の
応答サンプルによる表示検査を区別します。応答サンプルを実求解成功の証拠にしません。
表示期間変更は既存描画の投影で、元記録の原区間を切りません。
勤務/不足の根拠は同じ実行のResponse/現在verifyに限り、採用済みを示しません。

100人・30日の架空入力はCLIで組み立て/保存し、準備・求解・保存・表示の時間と出力サイズを分けます。
ローカルCLIは16 MiB/ファイル・64 MiB合計、demoは2 MiB/本文・100人/30日/3000枠です。
出力上限超過は切り詰めずに拒否します。実務性能や商用画面の保証ではありません。
アプリ側の入力保存・採用・Query/SQLite接続は[schedula-app #30](https://github.com/omitsuhashi/schedula-app/issues/30)に引き継ぎます。


## 規模測定

[生データ](results/input-adapter-20261008.json)は全4試行を保持します。
100人・30日の既存架空入力は準備0.137秒、組み立て0.108秒、求解32.279秒、
記録作成/保存1.220秒、再検証/JSON投影1.658秒、出力921713 bytesでした。
探索予算30秒に対し総処理は別計測です。FEASIBLE、需要充足、独立検証成功、
勤務量540000分、最適性未証明です。PARTIAL・継続計画・固定再計画の3試行も
記録保存・独立再検証成功。不足最小性は元Responseの証拠であり、現在verifyには戻しません。
測定は最終レビュー修正時のローカル試行で、合成入力の性能を他環境へ保証しません。
表示は同じ上限の既存100人30日ブラウザー回帰と新Adapterの小規模表示を別に確認しました。
