# 同時勤務条件の受け入れ記録

対象は[Issue #89](https://github.com/omitsuhashi/schedula/issues/89)、契約0.14。
基点はmain `552c3f9`。2026-10-08、Apple Silicon macOS、CPython 3.14.8、
OR-Tools 9.15.6755とuv.lockの依存で確認する。#90の回数目標と#91の全機能結合・規模評価は後続課題。

## 再実行

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pytest -q tests/test_coworkers.py
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
PLAYWRIGHT_MODULE_PATH=/private/tmp/schedula-playwright-20261008/node_modules/playwright node tests/playground-browser.cjs
```

ブラウザーは既存PlaywrightとChromiumを使う。最後のパスはこの実行環境の導入先。
全テストには公開型、CLI、Schema4種、OR-Toolsなしの公開verify、wheel/sdistの隔離導入が含まれる。

## 受け入れ内容

| ケース | 確認する結果 |
| --- | --- |
| 新人2時間、A/Bが1時間ずつ交代 | 同じ相手の終日勤務を要求せず成立。指導者は待機でも数える |
| 全指導者が同時休憩 | 新人が勤務する枠は違反。新人も休憩なら成立。分割間の非勤務も除外 |
| 最低2人・相互条件・共有指導者 | 指導者1人だけの解を拒否。相互条件は両者勤務で成立。同じ指導者が複数人を支えられる |
| 同時勤務禁止 | 境界交代を受理。3人集合のどの2人も重複勤務を拒否。条件区間外は対象外 |
| 入力不備と旧版 | 自己参照・集合交差・重複・未知ID・人数・区間を拒否。0.1〜0.13は新2条件を拒否 |
| 必須需要・休日・基準固定との矛盾 | INFEASIBLE。需要が不足許容なら対象勤務を選ばずPARTIALになり、不足を返す |
| Wをまたぐ確定勤務 | 原区間の計画内勤務状態を同僚として数え、休憩を除外。確定勤務を解除しない |
| 診断の縮小 | ルールを一単位とし、候補・技能・勤務可能時間を背景として保持する |
| 3人の全候補部分集合 | 各条件で8通りを元JSONの独立した時間比較、verify、日数で選択を固定したsolveと照合 |
| 基準往復・独立性・予算 | ルール保持、モデル候補を空にしても違反検出、UNKNOWNと証明範囲、共有探索予算を確認 |

指導人数の容量・担当役割・職位推定は対象外。勤務時刻は有限候補で入力し、休憩を待機へ置換しない。
代表例は架空入力であり、実店舗や100人30日の性能保証ではない。
