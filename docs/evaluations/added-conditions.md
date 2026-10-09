# 追加勤務条件の結合・規模評価

2026-10-08、[Issue #90](https://github.com/omitsuhashi/schedula/issues/90)と
[Issue #91](https://github.com/omitsuhashi/schedula/issues/91)の受け入れを検証する。
JSON契約0.15で勤務回数を追加し、0.11〜0.14の4機能と同時に求解・独立検証・基準保存・再計画できることが目的である。
HTTP公開・認証・保存・法令判定・PyPI公開・タグ・productionデプロイは対象外とする。

## 入力と合格条件

| シナリオ | 再現入力・検証 | 期待と確認内容 |
| --- | --- | --- |
| 週の勤務日数・月の休日数・夜勤後の休み | [月の例](../../examples/combined_month.json)、`tests/test_added_conditions.py` | 実績・夜勤・分割を含み、勤務2日・占有3日・完全休日28日、夜勤1回。分数上限・休息・連勤を保持し、余白不足を拒否 |
| 必須の責任者と不足許容 | [結合例](../../examples/combined_conditions.json) | 技能を持つ新人の最低1人を必須にし、一般枠の不足120人分を返す。新人不在はINFEASIBLE |
| 新人・指導者・休憩交代 | 同じ結合例 | 指導者の相互にずれた休憩と同時勤務禁止を守り、待機込み勤務240分。必要同僚の違反を独立検証で拒否 |
| 回数と分数・費用・希望 | [履歴付き夜勤回数](../../examples/shift_count_balance.json)、`tests/test_shift_counts.py` | 過去Alice1回を保持し、今回はBobへ配分して偏差0。分数・費用との目的順、小規模全探索、未証明の上位目的で停止することを確認 |
| 欠勤と移動期間の再計画 | `tests/test_added_conditions.py` | PARTIAL基準の指導者交代をpreserve_assigned/rebuildで解き、旧分類・目標・新必須条件を基準往復で保持。期間移動後も原勤務の回数と変更量0を確認 |
| 手修正・不可能・打切り | `tests/test_added_conditions.py`、`tests/test_shift_counts.py` | 日数・最低需要・同時勤務・日群の違反と改ざん集計を拒否。不可能性の十分集合と単一要素除去を公開solveで照合し、UNKNOWNをINFEASIBLEと区別 |

回数の追加検証には8時間1回と4時間2回、分割1回、対象外と0目標、59/60分閾値、
休憩と分類区間の和集合、開始日の期間帰属、実績と未来確定勤務の重複防止、
DST、未確認履歴、旧版拒否、46目的、10,000,000回の到達不能なソフト目標を含む。
期待値の全探索は元JSONから算出し、モデル係数や独立検証器を期待値の正本にしない。

## 100人・30日・30分の規模

既存[100人・30日の入力](../../examples/playground/roster-100-30.json)の従業員・技能・
需要・休憩2案・3,000候補を維持し、禁止する並びの判定余白を前後1日ずつ足す。
Wは9月30日〜11月1日、評価対象は10月1日〜31日の30日。1,536枠・2役割で
従業員×枠×役割は307,200となり、上限1,000,000内に収まる。
候補を一案に事前固定せず、各従業員の日数上限20・完全休日下限10、連続勤務禁止、
必要同僚・同時勤務禁止・勤務回数目標12を合わせる。月の分数上限9,000と休息660分は既存どおり。

| 入力 | 条件 | 固定コミットの3試行 |
| --- | --- | --- |
| [通常](inputs/combined-100-30-normal.json) | 既存需要へminimum_people=1を追加 | FEASIBLE 3/3、全回独立検証成功、不足0・勤務540,000分 |
| [不足](inputs/combined-100-30-partial.json) | 元必要人数だけ各100へ増加、最低1を保持 | PARTIAL 3/3、全回独立検証成功。不足2,211,750人分・勤務668,250分、最適性は未証明 |
| [必須矛盾](inputs/combined-100-30-conflict.json) | 調理1需要のminimum_people=100、資格者は50人 | INFEASIBLE 3/3、解・集計なし |
| [探索打切り](inputs/combined-100-30-timeout.json) | 通常と同じ条件、探索予算0.000001秒 | UNKNOWN 3/3、解・集計なし |

測定対象はcommit `9145f71bec1af50646726acb417d19808536e05c`を`git archive`で取り出したコードで、
Python 3.14.8・OR-Tools 9.15.6755・macOS 26.7.1 arm64を用いた。パッケージ版は0.1.5のまま、
JSON契約だけ0.15を追加する。依存版・入力SHA・ソースSHA・各試行の結果は
`docs/evaluations/results/added-conditions-20261008-fixed.json`へ全15試行を保存した。
測定後の修正は`make_baseline`の公開型宣言で、求解・独立検証の実装は同じである。

通常の総処理32.88〜32.97秒・RSS959〜964 MiB、不足33.17〜33.27秒・
RSS1,409〜1,477 MiBだった。必須矛盾は1.29〜1.39秒・約228 MiB、探索打切りは
1.42〜1.50秒・約253 MiBで、どちらも解なしである。通常・不足とも探索に30秒を使い、準備は約0.8秒、
独立検証は約0.5〜0.6秒である。総処理には入力検証・依存読み込み・結果検証も含む。
回数偏差は通常444/424/414、不足は全回309だった。到達した計画の値であり、
上位の勤務分数が未証明なので回数の最適化まで到達していない。
不足最小性や全目的の最適性をこの規模で保証しない。
固定前の初回全12試行も`docs/evaluations/results/added-conditions-20261008-initial.json`に保持する。
初回も通常・不足は各3回独立検証成功だった。測定生データはGitに保持し、sdistには含めない。

固定commitの測定再実行はリポジトリ内から行う。一時worktreeへ記載の固定commitを展開し、
その入力・`uv.lock`・配布版を使う。測定runnerだけは現在の `scripts/evaluate.py` をコピーし、
出力は現在のリポジトリの `test-results/historical/` へ保存する。
測定後は一時worktreeだけを削除し、通常の0.15入力と過去の測定JSONを変更しない。

```sh
(
  set -eu
  evaluation_root="$(git rev-parse --show-toplevel)"
  evaluation_checkout="$(mktemp -d)"
  git worktree add --detach "$evaluation_checkout" 9145f71
  cp "$evaluation_root/scripts/evaluate.py" "$evaluation_checkout/scripts/evaluate.py"
  cd "$evaluation_checkout"
  uv sync --locked --extra cp-sat
  uv run --locked --extra cp-sat python scripts/evaluate.py \
    docs/evaluations/inputs/combined-100-30-normal.json \
    docs/evaluations/inputs/combined-100-30-partial.json \
    docs/evaluations/inputs/combined-100-30-conflict.json \
    docs/evaluations/inputs/combined-100-30-timeout.json \
    docs/evaluations/inputs/combined-legacy-010.json \
    --repeat 3 --source-ref 9145f71 --timeout-seconds 180 \
    --output "$evaluation_root/test-results/historical/added-conditions.json"
  cd "$evaluation_root"
  git worktree remove --force "$evaluation_checkout"
)
```

冷起動はOSのファイルキャッシュを消さない新規Pythonプロセスであり、2 workersを用いる。
30秒はモデル準備後に共有する探索予算で、総応答時間の上限ではない。
条件グループ縮小の独立照合は小規模矛盾入力で実施し、規模測定の矛盾では追加診断を要求しない。
診断の所要時間は`diagnosis_result.elapsed_seconds`、入力検証・候補展開・モデル準備・探索・
独立検証は`search_stats`、総時間・ピークRSSは測定欄で別々に確認する。

## 旧版の比較と公開入口

追加条件を持たない[0.10比較入力](inputs/combined-legacy-010.json)を基点main
`9ff6fccf56d8c7a7600057f0bebb614f89c928ca`で3回測定し、全回FEASIBLE・独立検証成功・
勤務540,000分を得た。現行の固定コミットも全3回で同じ状態・尺度・独立検証成功だった。
旧実装は総処理32.35〜32.87秒・RSS976〜1,010 MiB、現行は32.26〜32.35秒・
RSS1,023〜1,031 MiBで、単一環境・3試行から速度差を一般化しない。同率解の配置順は比較しない。
旧実装の測定は`docs/evaluations/results/added-conditions-20261008-legacy-before.json`に保存する。
固定前の現行比較は`docs/evaluations/results/added-conditions-20261008-legacy-after.json`に保持する。

```sh
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
PLAYWRIGHT_MODULE_PATH=/path/to/playwright node tests/playground-browser.cjs
```

全Schema・公開型・CLI・wheel/sdist・OR-Toolsなしの公開verifyとmake_baselineは既存テストで確認する。
Chromiumでは0.11〜0.15の実エンジン実行、回数表示、bool目標・改ざん集計の拒否、
新サンプル選択と携帯幅の表示を確認する。

ローカル全体試行は1,840 testsと6 subtestsが成功し、隔離wheelの型検証1件が失敗した。
`make_baseline`の型宣言に`Request015`を追加し、同じ隔離wheel・OR-Toolsなしの実行・
mypy利用者コードのテストが成功した。後から追加した目的順3件を含む結合16 tests、回数43 tests、
pre-commit全ファイルとChromiumも成功した。最終コミットの全体CI・配布検証結果は
[PR #103](https://github.com/omitsuhashi/schedula/pull/103)のチェックと#85の受け入れコメントに記録する。

初回のサンドボックス実行はHTTP待受・uvキャッシュへのアクセスで失敗し、必要権限下で再実行した。
追加テストの初回にはテスト入力の重複ID、縮小した文脈より長いavailability、診断codeの期待値、
fairnessヘルパーが目的列を置換することによる46件の数え誤りがあり、入力と期待値を修正した。
最初の全体再実行では縮小した文脈の入力と、作成途中の文書をsdistに含めたタイミングでも失敗した。
ブラウザー初回は長いサンプル名によって携帯幅がはみ出したため、selectの最大幅を100%にして再確認し成功した。
この修正履歴を成功した試行だけに置き換えない。

## 採用範囲と残る制限

採用対象は明示した有限候補・粒度・分類・確認済み履歴・目的順である。
分類区間と目標の業務妥当性、実績の真正性、未入力の未来勤務は利用側が管理する。
勤務回数目標は必須条件ではなく、需要外の待機勤務を選ぶこともある。
実店舗の応答期限や性能は保証しない。結合入力の局所的な全探索一致を実務全般の保証に拡張しない。

#85・#91のmain反映・全体完了と、ローカルの実装・検証・PR提出は区別する。
PRとCIが揃っても、未マージなら全体完了チェックやmilestoneを閉じない。
