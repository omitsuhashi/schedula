# 勤務条件・再計画・公開検証の結合と規模評価

2026-10-07（Asia/Tokyo）。対象は[マイルストーン5](https://github.com/omitsuhashi/schedula/milestone/5)。
実店舗の入力・応答時間の目標は未確定であり、以下は架空条件の実測である。

## 測定前に固定した条件

パッケージ0.1.4、CPython 3.14.8、uv 0.12.23、OR-Tools 9.15.6755、
macOS ARM64で実行する。CP-SATの探索workerは既存どおり2、seedは0。
規模測定は各入力2回の冷起動、1プロセスずつ、探索予算60秒、プロセスの打切り180秒とする。
既存3000候補デモは変更せず、その入力の30秒予算で1回測る。
小規模の再計画・結合例はそれぞれの明示予算10秒で2回測る。
成功条件は独立検証済みの `OPTIMAL` / `FEASIBLE` で、規模例には不足0を要求する。
`UNKNOWN`・入力拒否・`PARTIAL`・worker障害をこの規模の成功へ数えない。

## 保存入力と再現方法

[元の3000候補サンプル](../../examples/playground/roster-100-30.json)を起点に、
[3000](inputs/roster-conditions-3000.json)・[6000](inputs/roster-conditions-6000.json)・
[12000](inputs/roster-conditions-12000.json)の候補入力を保存した。
全例は100人、30日、30分粒度、調理・ホール各50人、毎日各役割20人、昼は10人の元需要。
勤務可能時間は月全体、勤務長480分・休憩30分。
月全体上限9000分、休息660分、連勤5日を維持する。

3000は1開始時刻・1休憩形状、6000は09:00と09:30の2開始時刻、
12000はさらに開始から180分と210分の2休憩位置を選べる。
テンプレートの直積で全件を生成し、候補を切り捨てない。
各7日の明示区間に全従業員900〜2250分、月末2日には下限0・上限2250分を追加した。
月末の値は入力者の明示値であり、自動按分ではない。
従業員002の10月2日09:00〜12:00の希望勤務と、001の10月1日09:00〜17:00の勤務回避を追加し、
不足 → 選好ペナルティ → 勤務量の共通目的で比較する。

既知実行可能性は、各役割の50人を日ごと20人ずつ巡回させ、09:00開始の候補を選ぶ構成で確認できる。
人数上限、週別最低2勤務、休息、連勤の条件を満たす。
希望の実現と勤務量最小性は、その構成だけから証明しない。

再計画は[固定で不足が残る例](../../examples/partial_replan_preserve_assigned.json)と
[全体で埋まる例](../../examples/partial_replan_rebuild.json)、
[固定が不可能な例](inputs/replan-fixed-impossible.json)、[両案同等の例](inputs/replan-equal.json)を保存した。
[夜勤の結合](inputs/combined-overnight.json)・[分割の結合](inputs/combined-split_roster.json)では、
勤務量上下限、希望、目標未達、不足、基準、自動固定を組み合わせる。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-conditions-3000.json docs/evaluations/inputs/roster-conditions-6000.json docs/evaluations/inputs/roster-conditions-12000.json --repeat 2 --processes 1 --timeout-seconds 180 --source-ref 3d6dbe0c7ec00b3500a630438349bcf37ec50415 --output test-results/roster-conditions-scale.json
uv run --locked --extra cp-sat python scripts/evaluate.py examples/playground/roster-100-30.json --repeat 1 --processes 1 --timeout-seconds 90 --source-ref 53115de16c115786ca7291d77cb75005aee0a2de --output test-results/roster-conditions-original.json
uv run --locked --extra cp-sat python scripts/evaluate.py examples/partial_replan_preserve_assigned.json examples/partial_replan_rebuild.json docs/evaluations/inputs/replan-*.json docs/evaluations/inputs/combined-overnight.json docs/evaluations/inputs/combined-split_roster.json --repeat 2 --processes 1 --timeout-seconds 60 --source-ref 53115de16c115786ca7291d77cb75005aee0a2de --output test-results/roster-conditions-combined.json
```

規模評価は単体テストから分離する。結果には入力SHA-256、ソースSHA-256、commit、dirty状態、
lock file、環境・依存版、候補数、状態、不足、目的値・下限・証明範囲、変更量、各時間、ピークRSSを残す。
`SEARCH_STATS` の入力検証・候補展開、モデル準備、探索、独立検証と、呼び出し全体の所要時間は別に読む。
入力検証には意味検証と基準の再検証が含まれる。探索予算はモデル構築後に始まる。
最終ResponseのSchema・意味検証などの処理も総時間に含まれるため、表示された段階の和と総時間は同一ではない。

## 初回の取り扱い

[初回生データ](results/2026-10-07-roster-conditions-initial.json)では全3入力が不足0・選好0の `FEASIBLE` だった。
ただし測定途中でパッケージ0.1.3から0.1.4へ同期したため、snapshotの版と実行環境の版が一致しない。
この初回を正式な比較の根拠に採用せず、固定した0.1.4で全試行を取り直す。
初回の成功・時間・RSS・証明範囲も削除せず、この制限を付けて保持する。

## 検証範囲

新条件の入力検証、境界、重複期間、休憩・待機、月境界、夜勤・分割、時計変更、
小規模全探索との一致、旧版拒否、評価値改ざん、自動固定1000枠超、
再計画の繰り返しとsnapshotの固定保持をテストする。
固定枠以外の休憩・待機・非勤務は自動固定しないことも確認する。

wheelの隔離環境から `solve` / `verify` / `make_baseline` / `get_schema` の公開入口だけで利用する。
OR-Toolsなしの別環境でも完全・不足・不正Request・編集違反、夜勤・分割、保存・再読込・
基準変換の繰り返しを確認する。API・CLIの検証結果は最適性・不足最小性を付与しない。
画面・商用運用をエンジンCIの依存にせず、既存デモのブラウザー回帰も維持する。

## 規模の反復測定

[正式な生データ](results/2026-10-07-roster-conditions-scale.json)はソース `3d6dbe0` の
Git archiveから実行した。snapshot・実行環境ともパッケージ0.1.4で、lockも一致する。
その後の `53115de` は基準スナップショットの未登録従業員を拒否する参照検証とテストの追加で、
規模入力は基準を持たず、その差分を実行しない。元サンプルと結合例は後者のソースを使う。
各生データに完全なcommit・ソース/runner/lockのSHA-256と環境を保存した。
冷起動は新しいPythonプロセスであり、OSのファイルキャッシュは消去しない。

| 候補数 | 試行・状態 | 不足/選好 | 冷起動総時間 平均/最大 秒 | ピークRSS 平均/最大 MiB | 勤務量の観測値 分 |
| ---: | --- | --- | ---: | ---: | ---: |
| 3000 | 2/2 `FEASIBLE`・検証成功 | 0/0 | 62.278 / 62.298 | 1049.3 / 1049.3 | 540000 |
| 6000 | 2/2 `FEASIBLE`・検証成功 | 0/0 | 62.727 / 62.737 | 1408.7 / 1436.7 | 559800〜561150 |
| 12000 | 2/2 `FEASIBLE`・検証成功 | 0/0 | 63.930 / 64.364 | 1722.6 / 1731.9 | 587700〜594000 |

全6試行で不足最小性と選好0を証明し、勤務量の最適性は未証明だった。
勤務量のsolver下限は全試行359550分で、固定された不足・選好の最適な接頭辞の下での下限。
3000の観測値より6000・12000の勤務量が大きくても、後者の最適値が悪いとは証明しない。
60秒は探索の予算で、初期化・モデル構築・独立検証を含む応答時間の上限ではない。
12,000候補で約1.7 GiBのピークRSSを観測しており、候補選択肢の追加にはメモリも必要になる。
架空入力・2試行の結果から、一律の応答時間や実店舗の運用可能性を保証しない。

| 候補数 | 入力検証 秒 | 候補展開 秒 | backend読み込み 秒 | モデル準備 秒 | 探索 秒 | 独立検証 秒 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3000 | 0.065 | 0.051 | 0.210 | 0.693 | 60.063 | 0.400 |
| 6000 | 0.066 | 0.092 | 0.208 | 0.898 | 60.082 | 0.435 |
| 12000 | 0.072 | 0.175 | 0.234 | 1.259 | 60.095 | 0.595 |

各段階は2試行の平均。総時間との差には最終Responseの再検証などが含まれる。
規模試行に `UNKNOWN`・入力拒否・不足付き解・worker障害はなく、別の固定件数や切捨てによる回避も行っていない。

## 元サンプルとの比較と結合例

[元サンプルの生データ](results/2026-10-07-roster-conditions-original.json)は3000候補・探索30秒で
不足0の独立検証済み `FEASIBLE`、勤務量540000分・最適性未証明だった。
冷起動総時間32.201秒、ピークRSS1002.5 MiB、入力検証0.051秒、候補展開0.050秒、
モデル準備0.581秒、探索30.060秒、独立検証0.400秒。
新条件の3000例とは条件・目的・予算が違うため、純粋な速度改善率として比較しない。

[結合例の生データ](results/2026-10-07-roster-conditions-combined.json)は8入力×2冷起動の16試行。
全試行が期待した状態になり、有効な14解は独立検証に成功した。
残り2試行は固定と新しい勤務不可が衝突する `INFEASIBLE` で、有効解へ数えない。
worker障害は0。各試行の冷起動総時間は0.328秒以下、ピークRSSは105.9 MiB以下だった。

| 入力 | 2回とも同じ状態 | 不足 人分 | 目的値（入力順） | 変更量 |
| --- | --- | ---: | --- | ---: |
| `partial_replan_preserve_assigned` | `PARTIAL` | 30 | 勤務量90 | 0 |
| `partial_replan_rebuild` | `OPTIMAL` | 0 | 勤務量180 | 5 |
| `replan-equal` | `OPTIMAL` | 0 | 勤務量180 | 4 |
| `replan-equal-rebuild` | `OPTIMAL` | 0 | 勤務量180 | 5 |
| `replan-fixed-impossible` | `INFEASIBLE` | 解なし | 解なし | 解なし |
| `replan-fixed-impossible-rebuild` | `PARTIAL` | 30 | 勤務量90 | 8 |
| `combined-overnight` | `PARTIAL` | 420 | 選好2460・目標偏差30・勤務量420 | 0 |
| `combined-split_roster` | `PARTIAL` | 420 | 選好1020・目標偏差30・勤務量420 | 0 |

有効解は不足最小性と全入力目的の最適性を証明した。
固定/全体の比較は不足を先に比較し、固定では残る不足を全体案で埋める。
同等例は共通目的が同じでも変更量は同じにならず、全体案へ変更最小化を混入させない。
夜勤・分割は新条件・目標勤務量・不足・基準・自動固定を同時適用する。
保存・再読込と2回以上の再計画、複数期間・月境界・下限のための待機はpytestで確認した。

## 必須チェック

ローカルの `uv run --locked --extra cp-sat pytest -q --junitxml=test-results/pytest.xml` は
1176件と6 subtests成功（164.44秒）、JUnitのskipは0。
参照検証の追加2件は別途0.12秒で成功した。
[修正後コードのCI](https://github.com/omitsuhashi/schedula/actions/runs/37572807294)では
同じ全pytestを1178件と6 subtests成功（105.63秒）、skip禁止も成功した。
pre-commit全ファイル、wheel build・隔離導入・OR-Toolsなしの公開検証は成功した。
wheelの `License-Expression: MIT` とLICENSE・依存表示の同梱、参照資料の除外も確認した。

ブラウザー回帰はローカルChrome 154.0.8037.99とCIのPlaywright 1.62.1 / Chromiumで成功した。
既存のシナリオ・JSON・100人30日・キーボード・狭い画面・応答失効に加え、
期間別上下限・選好と固定/全体再計画の0.4入力を実行した。
結果・画像はローカルの `test-results/` とCIの `pytest-results` artifactに保存する。
