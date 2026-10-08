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

## 実行結果

新機能55テストが成功した。3条件設定の候補部分集合24通りを独立した時間比較と
公開verify・選択を日数で固定したsolveで照合した。指導者交代・同時休憩・最低2人・
共有指導者・相互条件・分割空白・確定勤務・基準固定・不足・診断縮小を含む。
DSTの秋の25時間の日ではオフセットを保持し、勤務360分の完全な計画を独立検証した。
診断では必要人数と同時勤務禁止をそれぞれ1グループとして除去・再確認した。

関連351テスト、公開型を含む56テスト、版継承の回帰185テストが成功した。
全回帰を開始した後、0.14で継承する0.8〜0.10の機能を拒否対象に含める期待値の更新漏れを
3ファイルで修正した。修正箇所は185テストで再確認した。実装の受理範囲や旧版の意味は変えていない。

Chromiumでは同時勤務サンプルの実計算、待機勤務・必須最低人数・PARTIALの不足表示と
集合交差の入力不備表示が成功した。既存3シナリオ、100人30日、キーボード、狭い画面、
応答失効も成功した。結果は手元の`test-results/playground-browser.json`に保存した。
Ruff hooks、Node構文、bash構文、git diff --checkが成功した。
旧0.1〜0.13の26 Schemaファイルは基点commitの原bytesと一致し、uv.lockは変更していない。

## 代表例の反復

commit `1094de3c29c807bad9042ee5925cdd42ef0bf786`のgit archiveで、同じ入力を3つの
新規Pythonプロセスから実行した。全回でPARTIAL、不足120人分、勤務240分、
不足最小性・勤務量最適性の証明と独立検証が成功した。
Request全体の中央値0.374秒、最大0.397秒、最大RSS108.34 MiBだった。
全回帰と並行実行した参考値であり、他条件との性能比較には用いない。
生データは`docs/evaluations/results/coworkers-20261008-cold.json`。
source SHA、lock SHA、依存版、入力SHA、準備・探索・検証の時間と全試行を保持する。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py examples/coworkers.json --repeat 3 --mode cold --source-ref 1094de3 --output test-results/coworkers-cold.json
```
