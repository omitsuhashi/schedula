# 不足付き担当配置・勤務計画の検証記録

2026-10-07、Milestone [不足を明示した担当配置・勤務計画の出力](https://github.com/omitsuhashi/schedula/milestone/4) の実装を検証した。
契約0.3は元需要を保った `PARTIAL` を追加し、0.1・0.2の完全充足・解なしの意味は維持する。
本記録の性能値は架空入力の単発測定であり、性能保証・最速・現場での有効性を主張しない。

## 環境と再実行

macOS 26.7.1 arm64、Python 3.14.8、uv 0.12.23、jsonschema 4.26.0、OR-Tools 9.15.6755。
ブラウザーはインストール済みChrome 154.0.8037.99、Playwright 1.62.1。ブラウザーのタイムゾーンを
UTCにして検証し、入力の `Asia/Tokyo` に基づく時間帯を維持した。CIは固定したPlaywrightでChromiumを導入する。
実行依存の新規追加・版変更は行っていない。

```sh
uv python install
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
uv run --locked --extra cp-sat python -c 'import xml.etree.ElementTree as ET; assert not ET.parse("test-results/pytest.xml").findall(".//skipped")'
bash -n scripts/deploy
uv build --wheel
git diff --check
# CIはPlaywright 1.62.1とChromiumを一時ディレクトリに導入して次を実行する。
node tests/playground-browser.cjs
```

ローカルでは既存の8765が使用中だったため、`python demo/server.py --port 18765` と
`PLAYGROUND_URL=http://127.0.0.1:18765` を使用した。Playwright既定のChromium実行ファイルがなかったため、
`PLAYWRIGHT_CHANNEL=chrome` と既存ランタイム内の `PLAYWRIGHT_MODULE_PATH` を指定した。
これらの初回起動失敗は実装の結果状態やブラウザー検証成功と混同しない。

## 元入力・結果・探索の実測

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py examples/assignment.json examples/roster.json examples/playground/lunch.json examples/partial_assignment.json examples/partial_roster.json examples/playground/roster-100-30.json --repeat 1 --timeout-seconds 90 --output test-results/partial-plans.json
```

[測定の生データ](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-07-partial-plans.json)には入力SHA-256、共有予算、環境・依存版、
基準commit `ff16c6a094642f4419cc37dbe04a3371aad799ae` からの未コミットソースのハッシュ、
uv.lockのハッシュ、状態・不足・目的・下限・検証・時間・ピークRSS・ワーカーの失敗有無を保存した。
新規Pythonプロセス各1回、同時実行数1。OSキャッシュは消去していない。
測定時のソースハッシュはエンジンと評価スクリプトのスナップショットを指し、後続の利用文書や表示調整とは区別する。

| 入力 | 状態 | 不足人分 | 不足最小性 | 指定目的と証明 | 探索秒 | solve全体秒 |
| --- | --- | ---: | --- | --- | ---: | ---: |
| `examples/assignment.json` | OPTIMAL | 対象外（旧版） | 対象外 | preference_penalty=0（証明済み） | 0.000089 | 0.036 |
| `examples/roster.json` | OPTIMAL | 対象外（旧版） | 対象外 | preference_penalty=60（証明済み）、scheduled_minutes=2640（証明済み）、role_switches=0（証明済み） | 0.071439 | 0.332 |
| `examples/playground/lunch.json` | OPTIMAL | 0 | 証明済み | 指定なし | 0.000181 | 0.063 |
| `examples/partial_assignment.json` | PARTIAL | 60 | 証明済み | 指定なし | 0.000150 | 0.059 |
| `examples/partial_roster.json` | PARTIAL | 30 | 証明済み | scheduled_minutes=90（証明済み） | 0.005397 | 0.271 |
| `examples/playground/roster-100-30.json` | FEASIBLE | 0 | 証明済み | scheduled_minutes=540000（未証明） | 30.052789 | 32.093 |

全6測定で独立検証成功、ワーカー失敗なし。不足60人分は12:00〜13:00の調理1人不足、
不足30人分は10:00〜10:30の調理1人不足で、各入力の必要人数を変更していない。
100人・30日は不足0を証明した `FEASIBLE`、勤務量540000分の最適性は未証明。
30秒はモデル構築後に不足最小化と指定目的で共有する探索予算で、総時間とは異なる。
不足人分は追加従業員数ではなく、正の最小不足を証明しても空ける区間の一意性は保証しない。

## 自動テストと隔離環境

ローカルの全pytestは1115テスト・6サブテスト成功、136.57秒、JUnitのスキップ0だった。
Ruffのpre-commit、deploy構文、wheelビルド、差分の空白検査も成功した。
不足付き入力を同じAPI・CLI・HTTPで実行し、CLIの `PARTIAL` は完全なJSONを出力して終了コード2となる。
完全な計画・未完成の計画・入力不正をwheelの新しい隔離環境から再実行する。
OR-Toolsなしの隔離環境では0.3の最小費用流で不足60人分を返し、勤務計画の依存不足を保持する。

独立検証の直接テストは一部・全不足、ゼロ需要・未指定需要、隣接区間の集約、異なる需要IDの分離、
時計変更の実経過分数、診断上限を超える不足一覧、不足の隠蔽・人数・区間・ID・合計・順序改ざんを確認する。
担当資格、二重配置、過剰配置、休憩中配置、固定部分違反を不足許容で通さない。
ソルバーが報告した不足量と独立再計算が異なる場合は `INTERNAL_ERROR` / `solution: null`。

小規模全探索は不足→選好→担当切替の評価を比較し、共通範囲で両バックエンドの評価値が一致する。
勤務量・公平性を改善するために不足を増やさない。夜勤・分割勤務・休息・連勤・勤務量上限・再計画・固定・診断を
0.3で結合確認し、不足のある0.3基準計画は拒否する。固定に違反する空計画を代用しない。

時間切れのテストは実行速度に依存しないよう、実CP-SATの計画を取得してから返却状態を制御し、
後段UNKNOWN・上位未証明・不足0の最小性・証明済み接頭部分を確認する。
最小費用流も1回の増加路の後で終了状態を制御し、途中配置と残りの不足を検証する。
これらは実機のタイムアウト発生率や、その配置が不可避の不足であることの証明ではない。

## 実ブラウザーと合成応答

[ブラウザーの生記録](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-07-partial-browser.json)の `scenarios` は実HTTP・実ソルバーの結果である。
通常22人枠→需要変更23人枠→復元、欠勤20人枠・不足60人分→必要人数の明示編集→復元、
ピーク需要24人枠→復元、自由編集、キーボード操作、勤務不可時刻の保持、重複名のID比較を確認した。
全員勤務不可では配置0・不足660人分を実計算し、未完成の計画として表示する。
390pxと1440pxで画面全体の横溢れがなく、不足人数・状態・役割名を文字で読み取れる。
表の横スクロール領域にはキーボードで到達でき、強制配色でも「不足1人」が残る。
独立検証は「不足集計・需要以外の必須条件を確認済み」と説明し、需要充足とは分けた。

JSONから100人・30日の勤務計画、旧版の夜勤・分割勤務、新しい不足付き担当配置・勤務計画を実計算した。
日付切替、休憩・待機・勤務なし、ファイル入力、編集後の結果失効、重複キー・不正UTF-8も確認した。
ブラウザーの大規模入力は `FEASIBLE` / 独立検証成功、solve総時間31.824秒だった。

`response_samples` は合成応答による表示・境界検証である。UNKNOWN、入力不正、依存不足、内部障害、
初回失敗、通信失敗、識別子・検証・不足改ざん、遅延応答と待機期限を実ソルバーの実測とは区別する。
JSONの `FEASIBLE` と不足最小性未証明の `PARTIAL` は実結果の証明フィールドを変更した表示サンプルであり、
「埋められないことが確定したわけではありません」と表示する。

### 大量の不足一覧のレビュー修正

不足表は1ページ100件に限定し、共有のDOM追加処理もスプレッドから1件ずつの追加に変更した。
追加回帰テストは実Chromeに15万件の合成不足一覧を注入し、先頭・末尾ページ、キーボードによるページ選択、
不足合計、日付切替後の配置表、詳細JSONと元データの15万件保持を確認した。ページごとの表は100行だった。
これは描画処理の検証であり、実ソルバーによる15万件の生成や不足集計の独立検証ではない。
CIのブラウザー成果物では `response_samples` の `shortage_rendering` に記録する。

## 未確認・対象外

実店舗・給与・法令・就業規則の適合性、全上限入力での性能、他OSでの同一人選、実際の時間切れ頻度は未確認。
本番デプロイ、PyPI公開、需要以外の自動緩和、役割ごとの不足優先度、未完成の基準計画の受理は対象外。
ローカル検証とGitHub CIの結果を区別し、CIの結果はこの変更のPR上で確認する。
