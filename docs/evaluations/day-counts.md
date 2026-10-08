# 勤務日数・完全休日数の受け入れ記録

対象は[Issue #86](https://github.com/omitsuhashi/schedula/issues/86)、契約0.11。
2026-10-08にApple Silicon macOS、CPython 3.14.8、OR-Tools 9.15.6755、
`uv.lock` の依存を用いて検証した。全体計画#85の残りの機能はこの検証には含めない。

## 再実行

```sh
uv run --locked --extra cp-sat pytest -q tests/test_day_counts.py
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
node tests/playground-browser.cjs
```

ブラウザー検証は既存のPlaywright導入手順と `PLAYWRIGHT_MODULE_PATH` を使う。
全テストにはwheel・sdistの隔離導入、公開型、CLI、版別Schema、JSON試用入口を含む。
実行件数・結果はPRとGitHub Actionsの記録へ残す。

## 確認する受け入れ条件

| ケース | 期待・確認内容 |
| --- | --- |
| 同じ240分の1勤務日と2勤務日 | 2日必須で2日案だけを選び、旧0.10の分数条件では両案を受理 |
| 7日の勤務日数3〜4日 | 3/4日を受理し、2/5日へ編集した解を拒否 |
| 22:00〜翌06:00、3暦日 | 勤務1日、占有2日、完全休日1日 |
| 22:00〜翌00:00 | 勤務1日、占有1日、翌日は完全休日 |
| 年末の分割勤務と丸1日の休憩 | 分割間の空白日だけを完全休日にし、休憩日は占有 |
| 過去2勤務日と選択1勤務日 | 合計3日。4日へ編集した解を拒否 |
| 評価開始をまたぐ確定夜勤 | 勤務日の帰属と暦日占有を別々に計算し、原区間を一度だけ数える |
| 確定勤務と日数条件の矛盾 | INFEASIBLE。診断はルール1件を削除単位とし、確定勤務を背景に保持 |
| 達成不能な有効下限 | 入力検証はVALID、求解はINFEASIBLE |
| 春・秋のDST週 | 23/25時間の勤務日も1暦日。7日間から完全休日6日を計算 |
| 4候補の全部分集合 | 同日勤務・外側重複・上下限の手計算とverifyを照合し、最小不足→勤務量を求解と比較 |
| 基準往復・固定・再構築 | 元の日数条件を保持して旧解を検証。固定との矛盾はINFEASIBLE |
| 未知項目・数値・ID・日時・履歴 | null/bool/浮動小数・上限超過・不正区間・未確認の過去・計画外未来を拒否 |
| 改ざん・独立性 | 日数集計の改ざんを検出。モデルの候補・事実表を空にしても元入力・返却解から再計算 |
| 共有予算・証明 | UNKNOWNと未証明の目的順を維持し、独立検証は最適性を認定しない |
| 互換性 | 旧0.1〜0.10で新条件を拒否。0.11へ従来の目的・continuity・基準を継承 |

日数条件に休日カレンダー・反復設定・法令判定は含めない。
本記録は合成入力の機能検証であり、実業務規模の性能保証ではない。

## 実行結果

入力例はOPTIMALで勤務3日・占有3日・完全休日4日、勤務270分、不足0を返した。
同じ解の独立検証はVALIDで、基準保存も成功した。
Chromium 151.0.7922.34で日数のJSON実計算・表示・全5失敗状態の集計保持拒否と、
既存3シナリオ・100人30日・キーボード・狭い画面・応答失効を確認した。page errorは0。
Ruff hooks、Node構文確認、`bash -n scripts/deploy`、`git diff --check` は成功。
旧0.1〜0.10のSchema20ファイルは開始commitの原bytesと一致した。
開始commitは `fd8c140ff0dae8c8cefa82b5d3857ec0e0e90eaf`。
`uv.lock` のSHA-256は `b848a99532d8d329e6b18c35257ec158ff829b111fe0b98a3381904cb7703cd7`。

新機能70件を含む全体1597件と6 subtestsが543.97秒で成功した。
JUnitのfailure・error・skipはすべて0。wheel・sdistの隔離導入と中核テスト再実行、
mypy consumer、版別Schema、公開APIとCLIを含む。実行ログはPRのCIと
ローカル `test-results/pytest.xml` / `test-results/playground-browser.json` に記録する。
