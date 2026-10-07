# 条件グループ縮小の検証記録

対象は[Issue #76](https://github.com/omitsuhashi/schedula/issues/76)の契約0.8。
[利用文書](../diagnosis.md#契約08の条件グループ縮小)と[架空入力](../../examples/conflict_refinement.json)を再実行する。
既存0.1〜0.7のSchemaは変更せず、診断以外の機能と公開 `verify` の意味を継承する。

## 合格基準と対象

- Aliceの下限60分と上限0分から無関係な上限120分を除き、二条件の十分性と各除去後の実行可能性を確認する。
- Bobにも独立した矛盾がある場合は、一つの十分集合を全列挙と手書きの別CP-SATモデルで再確認する。
- 全条件有効時の実行可能集合を通常モデルと全列挙で比較する。需要除去でも元の変数領域、未指定需要0、背景条件を保持する。
- UNKNOWN・構築/検証/最終確認の時間切れ・例外では未証明の極小性を主張せず、元の不可能性と完成済み証明を保持する。
- 明示固定・自動固定はグループとして扱い、実績・確定勤務・原区間・空候補集合は背景へ保持する。緩和解を正式な結果へ載せない。
- 参照・グループ・背景・証明記録の改ざん、許可外編集、旧版への新項目、外部期限・取消、配布と型情報を検証する。

## 実行環境とコマンド

2026-10-08、macOS 26.7.1 arm64、CPython 3.14.8、OR-Tools 9.15.6755、jsonschema 4.26.0、pytest 9.1.1、Ruff 0.16.10。
実行依存は `uv.lock` で固定する。入力・lock・sourceと採用測定の生データは
`docs/evaluations/results/2026-10-08-conflict-refinement.json` に保存し、sdistには含めない。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat python -m shift_schedula solve examples/conflict_refinement.json
bash -n scripts/deploy
```

## 実測と確認範囲

初回の全体実行は1365成功・2失敗・6 subtests成功、スキップ0（473.88秒）。
既存の版別期待値が0.8の正しいPARTIALを含まず、同じ期待値を同梱したsdistの再実行も失敗した。
期待値を更新した関連78件は成功、失敗・スキップ0。配布の再検証と最終CIの結果を追記する。
追加の診断検証は42件で、未知の版の拒否・UNKNOWN・期限・背景矛盾・許可変更案を含む。
テスト作成時には、削除した制約を参照する許可編集と、mockの参照変数の誤りを修正した。
これらの失敗を機能成功の証拠には使わない。

Chromiumの3シナリオ、JSON入力、100人30日の勤務計画、キーボード、狭い画面、応答失効は成功した。
Ruff、bash構文、旧Schema14ファイルの原bytes維持、32種類のSchema、公開入れ子型とSchemaの照合を確認した。

## 架空入力の実行測定

1人・1役割・1日・30分粒度・60分候補1件、削除対象4グループ、背景8件。
冷起動1回で元のINFEASIBLEを保持し、2グループの包含極小な十分集合と最終再確認を返した。
削除4回のうち2回はINFEASIBLE、2回は独立検証済みOPTIMAL。UNKNOWNは0。
初回・最終の再確認2回と、最後の証拠再検証2回を合わせ、checksは8件。
構築0.00139秒、探索0.00445秒、証拠検証0.00874秒（checksの合計）。
診断全体0.0655秒、求解全体0.334秒、importを含むRequest処理0.388秒、ピークRSS108.6MiB。
許可された上限60分の変更案はOPTIMAL、勤務量60分、独立検証成功。
全体回帰の実行中の単一測定であり、性能比較・実務規模の時間保証には使わない。
入力・source・lockのSHA、状態・全checks・許可案は生データに保持する。
小規模の包含極小性は要素数最少・唯一の原因・全原因列挙を意味しない。
実務規模の処理時間保証、仮定方式による高速化、並列削除探索、パッケージ公開・タグ・productionデプロイは確認範囲に含めない。
