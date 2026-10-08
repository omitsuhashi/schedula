# 必須の最低充足人数の受け入れ記録

対象は[Issue #87](https://github.com/omitsuhashi/schedula/issues/87)、契約0.12。
基点はmain `b536cdd79f92af2a70af030a5af518ca32d80196`、パッケージ版0.1.5。
2026-10-08にApple Silicon macOS、CPython 3.14.8、OR-Tools 9.15.6755と
`uv.lock` の固定依存で検証する。#88〜#91の機能の受け入れ結果は含めない。

## 再実行

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q tests/test_minimum_demand.py
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
node --check demo/app.js
node tests/playground-browser.cjs
```

ブラウザー検証は既存のPlaywright導入と `PLAYWRIGHT_MODULE_PATH` を使う。
通常のテストログは `test-results/` とActions artifactへ保存する。

## 受け入れ条件

| ケース | 確認内容 |
| --- | --- |
| 30分・目標3人・最低1人・配置可能2人 | 担当配置/勤務計画ともPARTIAL、配置2人、不足30人分 |
| 配置可能0人 | INFEASIBLE。空のPARTIALを返さない |
| 必須30分と通常60分の同日勤務二択 | 必須枠を選び、不足60人分。最低0へ戻すと通常枠と不足30人分 |
| 固定再計画と新しい最低人数の衝突 | preserve_assignedはINFEASIBLE、rebuildは別入力で必須枠を充足 |
| 全人数が必須・需要0 | 下限=必要人数で完全充足、0=0で配置なし |
| 技能の不足と担当資格の取り合い | 有効入力のINFEASIBLE。資格・二重配置禁止を解除しない |
| 確定勤務と日数上限の矛盾 | INFEASIBLE。診断の背景に確定勤務の原区間を保持 |
| 独立検証と改ざん | 元需要から下限を再計算。担当削除・不足一覧の最低人数改ざんを拒否 |
| 条件グループの削除試行 | 下限と上限を同時に外し、配置変数・背景を保持。小さな全ビット列と照合 |
| 許可編集 | 上限だけを下限未満へ下げる案を拒否。明示した下限編集だけを適用 |
| 全探索 | 担当配置の全配置と勤務候補の全部分集合から、上下限・不足・priority・目的順を照合 |
| 時間切れ | UNKNOWN、未証明の不足/目的、途中の有効な解を区別。共有探索予算を段階ごとに確認 |
| 互換性・公開境界 | 旧0.1〜0.11で新項目を拒否。Schema4種、CLI、型、wheel/sdist、JSON試用入口を確認 |

通常の2入力と診断例は架空データ。実店舗の性能保証、給与計算、法令判定には使わない。
最小不足と最適性は探索の証明範囲であり、公開verifyはどちらも認定しない。

## 実行結果

新機能55件と、修正後の公開API・CLI・wheel検証102件が成功した。
OR-Toolsを導入しない隔離wheelでも下限の公開verifyはPARTIAL/INVALID_PLANを区別し、
求解はBACKEND_UNAVAILABLEとなった。mypy consumerでRequest012と不足一覧の型を確認した。

初回の全体実行は1652成功・1失敗・6 subtests成功、547.89秒、error/skip 0だった。
失敗は既存の公開verifyテストの不足許容版一覧に0.12を追加していなかったためで、
期待するPARTIALの実際の応答に対してINVALID_PLANを期待していた。
一覧を修正し、上記102件の再検証で当該ケースも成功した。
sdist由来の隔離導入と中核テスト再実行も初回全体実行で成功している。
最終commitの全体実行はPRのGitHub CIを正本とし、実行URLと件数をPRに記録する。

Chromiumで担当配置/勤務計画の0.12実計算、最低人数・不足の表示、下限違反と不足一覧の改ざん拒否を確認した。
既存3シナリオ・100人30日・キーボード・狭い画面・応答失効も成功した。
ブラウザーの改ざん検出テストでは初回にフォームの時刻境界を使用して別の違反を検出したため、
JSON入力の境界を明示して修正・再実行した。最終ブラウザー実行は成功、page error 0。
通常のローカルログは `test-results/pytest.xml` / `public-api.xml` / `playground-browser.json` に残す。

旧0.1〜0.11の22 Schemaファイルは基点commitの原bytesと一致した。
新版Request/Response/solution/verification Schemaは構造検証に成功した。
Ruff hooks・Node構文確認・`bash -n scripts/deploy`・`git diff --check` は成功した。

## 固定ソースの反復評価

[生の評価結果](results/2026-10-08-minimum-demand.json)は、実装commit
`4b9a7501c457fa49801a3a80d1900458daf9a759` のGit archiveを読み込んで取得した。
ソースはdirty=false、ソースツリーSHA-256は
`34b3f65380b09009d9724f9fe8f682a5dab2cfe5e6013b4e5a2aae8591ee7868`。
入力・評価スクリプト・lockのSHA-256、依存版、探索結果と診断結果を同じJSONへ保存した。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py \
  examples/minimum_assignment.json examples/minimum_roster.json examples/minimum_conflict.json \
  --source-ref 4b9a7501c457fa49801a3a80d1900458daf9a759 \
  --repeat 3 --mode warm --backend auto \
  --output docs/evaluations/results/2026-10-08-minimum-demand.json
```

| 入力 | 3回の結果 | 確認内容 |
| --- | --- | --- |
| minimum_assignment.json | PARTIAL 3回 | 独立検証成功、不足30人分 |
| minimum_roster.json | PARTIAL 3回 | 独立検証成功、不足30人分、勤務180分を最適性証明 |
| minimum_conflict.json | INFEASIBLE 3回 | 需要グループの矛盾を再検証、上限のみの編集を拒否 |

診断例では毎回、下限のみを0へ下げる案が独立検証済みPARTIAL、
下限と上限をともに0へ下げる案が独立検証済みOPTIMALとなった。
各入力は別プロセス内で3回連続実行し、初回のimport等を含む呼び出し時間は0.335〜0.367秒、
継続呼び出しは0.004〜0.024秒だった。小さな架空例の観測値であり、
#91の規模評価や実データの所要時間の保証を代替しない。
