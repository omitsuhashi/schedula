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
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-conditions-3000.json docs/evaluations/inputs/roster-conditions-6000.json docs/evaluations/inputs/roster-conditions-12000.json --repeat 2 --processes 1 --timeout-seconds 180 --output test-results/roster-conditions-scale.json
uv run --locked --extra cp-sat python scripts/evaluate.py examples/playground/roster-100-30.json --repeat 1 --processes 1 --timeout-seconds 90 --output test-results/roster-conditions-original.json
uv run --locked --extra cp-sat python scripts/evaluate.py examples/partial_replan_preserve_assigned.json examples/partial_replan_rebuild.json docs/evaluations/inputs/replan-*.json docs/evaluations/inputs/combined-overnight.json docs/evaluations/inputs/combined-split_roster.json --repeat 2 --processes 1 --output test-results/roster-conditions-combined.json
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

正式な反復測定と必須CIの結果は、実行後に以下へ追記する。
