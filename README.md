# schedula

Python の配布名は `shift-schedula`、import 名は `shift_schedula` です。
旧ローカルwheelからの移行は[配布方針](docs/distribution.md#旧ローカルwheelからの移行)を参照してください。

技能・勤務可能時間・役割別需要・業務ルールから、担当配置（`assignment`）と
出退勤・休憩を含む勤務計画（`roster`）の検証済み解を求める Python ライブラリと CLI です。
JSON 契約0.1〜0.8に対応し、独立した配置は最小費用流、
担当時間・担当切替を含む配置と勤務計画は CP-SAT を使用します。

独自コード・文書・デモは[MIT](LICENSE)で、自力導入・組み込み・商用利用ができます。
現在のリポジトリは非公開で、PyPI公開は未実施です。参照資料はこの許諾の対象外です。
無料範囲、固定wheelの導入、依存表示、セキュリティ窓口と公開条件は[配布方針](docs/distribution.md)を参照してください。

## クリーンな環境から実行する

[uv](https://docs.astral.sh/uv/getting-started/installation/) と Git を導入し、次を実行します。
利用者向けの Python 要件は `>=3.14` です。開発環境は CPython 3.14.8 を
`.python-version` に固定し、依存版は `uv.lock` に記録しています。
測定した対応環境と将来版の制限は[Pythonセットアップ](docs/python-setup.md)を参照してください。
すでに clone 済みなら、リポジトリ直下で `uv python install` から実行してください。

```sh
git clone https://github.com/omitsuhashi/schedula.git
cd schedula
uv python install
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python -m shift_schedula solve examples/assignment.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/linked_assignment.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/roster.json
```

全例が `OPTIMAL`、`verification.performed: true` / `valid: true`、終了コード0を返します。
担当配置の2例は選好ペナルティ0、勤務計画は選好ペナルティ60・勤務量2640分・担当切替0回です。
勤務量は待機を含み、休憩を除きます。目的値は `objectives` の配列順に優先され、
`proven_optimal` で目的ごとの証明範囲を確認できます。

最小費用流だけを使う場合は `--extra cp-sat` を省略できます。
探索なしの入力検証、厳密JSON読み取り、型情報は[Python公開API](docs/python-api.md)を参照してください。
CP-SAT が必要な入力を依存なしで解くと `BACKEND_UNAVAILABLE` になります。
標準出力は JSON のみで、結果は `> result.json` で保存できます。
標準入力と Schema の取得も同じ CLI で実行できます。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve - < examples/assignment.json
uv run --locked --extra cp-sat python -m shift_schedula schema request
uv run --locked --extra cp-sat python -m shift_schedula schema response
```

## ブラウザーで担当配置を試す

clone 済みのリポジトリ直下で起動します。担当配置のフォームだけなら OR-Tools や Node.js は不要です。
JSON から勤務計画も計算するときは、同期・起動に `--extra cp-sat` を追加します。

```sh
uv python install
uv sync --locked
uv run --locked python demo/server.py
```

[http://127.0.0.1:8765](http://127.0.0.1:8765) をブラウザーで開くと、架空の飲食店の配置を実計算します。
「通常のランチ営業」「急な欠勤」「ピーク時の必要人数増加」を選び、
「この変更を入力」→「再計算」で元の条件と比較できます。
欠勤では元の必要人数を保持した `PARTIAL` と、不足一覧・配置できた箇所を比較できます。
必要人数を見直す場合は、次のガイドから調理人数を明示的に編集して再計算します。
「サンプルへ復元」で初期計算に戻り、「自由に編集する」で条件と比較元を保持して編集を続けられます。

名前、技能、勤務可能時間、必要人数を編集できます。編集後の結果は再計算まで無効です。
`INFEASIBLE` は解なし、`UNKNOWN` は未確定です。入力不備・依存不足・内部障害・通信失敗も文字と診断で読み分けます。
登録・JSON の手作成は不要です。終了はターミナルで Ctrl+C。
8765が使用中なら `--port 8766` を追加し、表示されるURLを開いてください。
編集上限・全状態は[配置プレイグラウンドの仕様](docs/playground.md)、
再実行コマンドと検証結果は[デモの検証記録](docs/evaluations/playground.md)を参照してください。

画面上部の「JSON で担当配置・勤務計画を計算する」を開くと、JSON の貼り付け・
UTF-8 ファイルの読み込み（2 MiBまで）から、契約0.1〜0.8の入力を実行できます。
「100人・30日・30分刻みの勤務計画」を選び、「サンプルを読み込む」→「JSON で計算」を押します。
結果の日付を選ぶと、100人分の担当・休憩・待機・勤務なしと役割別の需要充足を確認できます。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python demo/server.py
```

サンプルは[roster-100-30.json](examples/playground/roster-100-30.json)です。
2026-10-01〜10-30の架空条件で、調理・ホール各50人から毎日各20人の勤務を選びます。
勤務候補は9:00〜17:00・30分休憩の3000件、勤務量上限9000分・勤務間の休息660分・連勤上限5日です。
昼の休憩中は役割ごとの需要を10人、それ以外は20人と明示しています。
探索予算30秒と総処理時間は別で、`FEASIBLE` は独立検証済み・最適性未証明として表示します。

## 不足を伴う計画を出力する

```sh
uv run --locked python -m shift_schedula solve examples/partial_assignment.json > partial-assignment-result.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/partial_roster.json > partial-roster-result.json
```

どちらも `PARTIAL`、独立検証成功、終了コード2でJSONを保存します。
担当配置の不足合計は60人分、勤務計画は30人分で、いずれも `proven_minimal: true` です。
独立検証成功は、不足以外の必須条件と不足集計が正しいことを意味し、完全な需要充足を意味しません。
不足最小性が未証明なら、その不足が不可避だとは判断できません。追加従業員数とも区別してください。
入力・候補・目的を変更せずに版だけで不足を許容できるのは0.2→0.3です。
0.1の勤務計画は `history.last_work_day` と `segments` / `segment_options` へ明示的に移行します。
詳細は[契約0.3](docs/io-contract-partial.md)、実測と再実行は[検証記録](docs/evaluations/partial-plans.md)を参照してください。

不可能性の十分集合を条件グループ単位で絞るには[契約0.8の診断](docs/diagnosis.md#契約08の条件グループ縮小)を使います。
[架空入力](examples/conflict_refinement.json)は元の `INFEASIBLE` を保持し、背景条件に対する包含極小性と確認範囲を返します。

## 再計画・期間別勤務量・希望日時と編集後の検証

契約0.4のrosterは、担当済み枠を保持する `preserve_assigned` と固定・変更最小化を外す `rebuild`、
期間ごとの必須上下限 `scheduled_minutes_bounds`、`prefer_work` / `avoid_work` を扱います。
同じ需要・業務条件・共通目的で方式ごとに `solve` を呼び、各案の不足・目的値・変更量と証明を比較します。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/roster_conditions.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/partial_replan_preserve_assigned.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/partial_replan_rebuild.json
uv run --locked python -m shift_schedula verify examples/roster_conditions.json examples/roster_conditions.solution.json
```

上下限・希望例の目的は `[0, 180]`。再計画例の固定案は不足30人分・`PARTIAL`・終了コード2、
全体案は不足0・`OPTIMAL`です。公開 `verify(request, solution)` はOR-Toolsなしで保存済み・編集済み解を検証し、
`VALID` / `PARTIAL` / `INVALID_INPUT` / `INVALID_PLAN` を分けます。検証だけでは最適性を付与しません。
公開 `make_baseline(request, solution, plan_id)` で固定条件を保持した次の基準へ変換し、
`get_schema("request" | "response" | "solution" | "verification", "0.4")` でSchemaを取得できます。
実績・確定勤務を引き継ぐ週・月境界の集計は[契約0.6](docs/io-contract-continuity.md)で利用できます。
月末夜勤420分を過去120分・計画内300分へ分け、原区間と休憩を保持します。

詳細と保存・再計画の使い方は[契約0.4](docs/io-contract-replanning.md)、
合成入力の実測は[結合・規模評価](docs/evaluations/roster-conditions.md)を参照してください。

## 入力を作る

次を `request.json` として UTF-8 で保存すれば、1人・1役割の担当配置を実行できます。
ID は種類ごとに一意にし、参照先を登録します。不要な配列も `[]` を明示してください。

```json
{
  "schema_version": "0.1",
  "request_id": "my_assignment",
  "problem_type": "assignment",
  "planning_window": {
    "start": "2026-10-05T11:00:00+09:00",
    "end": "2026-10-05T12:00:00+09:00",
    "timezone": "Asia/Tokyo",
    "slot_minutes": 30
  },
  "skills": [{"id": "cooking", "label": "調理技能"}],
  "roles": [{"id": "kitchen", "label": "調理", "required_skills": [{"skill_id": "cooking", "min_level": 1}]}],
  "employees": [{
    "id": "alice", "label": "Aさん",
    "skills": [{"skill_id": "cooking", "level": 1}],
    "availability": [{"start": "2026-10-05T11:00:00+09:00", "end": "2026-10-05T12:00:00+09:00"}]
  }],
  "demand": [{
    "id": "lunch", "role_id": "kitchen", "required_people": 1,
    "interval": {"start": "2026-10-05T11:00:00+09:00", "end": "2026-10-05T12:00:00+09:00"}
  }],
  "shift_candidates": [],
  "constraints": [],
  "preferences": [],
  "objectives": [{"id": "preferences", "metric": "preference_penalty"}],
  "solver": {"backend": "auto", "time_limit_seconds": 5, "seed": 0}
}
```

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve request.json
```

結果の `solution.assignments` で Aさんの11:00〜12:00の調理担当、
`objectives[0].value` で0を確認できます。
区間は終端を含まない半開区間で、日時にオフセットが必要です。
計画開始からの30分粒度に揃え、勤務可能時間や同じ役割の需要を重複させません。
需要は厳密な人数で、未指定の時間・役割は0枠です。技能要件はすべて満たす必要があります。

勤務計画を作るときは [examples/roster.json](examples/roster.json) をコピーし、
全従業員の `history` と、勤務候補または `shift_templates` を指定します。
計画期間の両端はローカル00:00、1人1日最大1勤務です。
テンプレートは対象者・日付・始業・勤務長・休憩位置の選択肢から有限候補を生成します。
詳細な入力条件は [担当配置](docs/assignment.md)・[勤務計画](docs/roster.md)を参照してください。

夜勤・分割勤務は [契約0.2](docs/io-contract-next.md) の `segments` を指定します。
[夜勤・分割勤務](docs/roster-next.md)、[公平性・再計画](docs/replanning.md)、
[不可能性診断](docs/diagnosis.md) の例を API と CLI で実行できます。
勤務日・目標勤務量・変更単位は明示し、固定は必須条件として保持します。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/overnight.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/split_roster.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/fairness.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/replan.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/diagnosis.json
uv run --locked --extra cp-sat python -m shift_schedula schema request --schema-version 0.2
```

診断例は元条件の `INFEASIBLE` と終了コード2を維持し、許可した人数変更後の検証済み解を別に返します。
性能の条件・反復測定は [性能評価](docs/evaluations/performance.md) と
[5秒制限解除後の比較](docs/evaluations/search-budget.md)を参照してください。

## ライブラリで解と診断を読む

同じ環境で次を実行できます。自作入力に切り替える場合はファイル名を変更します。

```sh
uv run --locked --extra cp-sat python - <<'PY'
import json
from pathlib import Path
from shift_schedula import solve

for filename in ["assignment.json", "roster.json", "infeasible.json", "invalid-input.json"]:
    request = json.loads(Path("examples", filename).read_text(encoding="utf-8"))
    result = solve(request)
    print(filename, result["status"], result["solver"])
    if result["status"] in {"OPTIMAL", "FEASIBLE"}:
        assert result["verification"]["performed"] and result["verification"]["valid"]
        print(result["solution"], result["objectives"])
    else:
        print(result["diagnostics"])
PY
```

`solve(request: dict) -> dict` に渡す値は JSON 型・有限数で構成します。
`json.loads` 後の dict では重複キーを検出できません。外部 JSON の厳密な読み取りには
重複キー・非有限数も拒否する CLI を使ってください。

## 状態と呼び出し側の扱い

| `status` | 呼び出し側の扱い | CLI 終了コード |
| --- | --- | --- |
| `OPTIMAL` | 検証成功を確認して解を採用する。指定した条件・候補・粒度・目的の範囲で最適 | 0 |
| `FEASIBLE` | 検証成功と未証明の目的を確認し、採用または探索予算を増やして再計算する | 0 |
| `PARTIAL` | 契約0.3〜0.8の未完成の計画。不足一覧・合計人分・`proven_minimal` を読み、需要充足と検証成功を区別する | 2 |
| `INFEASIBLE` | 必須条件を満たす解がないと証明された。0.3では需要不足を許容しても計画を作れない。診断を確認する | 2 |
| `UNKNOWN` | 解も不可能性の証明もない。予算や問題規模を見直す | 2 |
| `INVALID_INPUT` | `code` / `json_pointer` / `related_ids` / `facts` を基に入力を修正する | 2 |
| `BACKEND_UNAVAILABLE` | `cp-sat` extra を導入して再実行する | 2 |
| `INTERNAL_ERROR` | 解を採用せず、入力・エンジン版・診断を保存して調査する | 2 |

解を返すのは独立検証に成功した `OPTIMAL` / `FEASIBLE` / `PARTIAL` だけです。
0.1・0.2は完全充足を求め、0.3〜0.8だけが元需要を保持した不足付き計画を許容します。
それ以外は `solution: null` / `objectives: []`。終了コード2だけでは状態を区別できません。
`message` は補助説明で、プログラムでは `status` と診断の `code` で分岐します。
次の2例は意図的に終了コード2となります。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/infeasible.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/invalid-input.json
```

前者は勤務可能な従業員がいないため `INFEASIBLE` / `INSUFFICIENT_QUALIFIED_EMPLOYEES`、
後者は未登録の役割参照のため `INVALID_INPUT` / `UNKNOWN_REFERENCE` を返します。
勤務計画の不可能例は全体の `NO_FEASIBLE_PLAN` を返し、唯一の原因や追加人数は推測しません。

## 対応範囲と実行上限

`assignment` は `max_assigned_minutes` / `max_role_switches`、
`roster` はさらに `max_scheduled_minutes` / `min_rest_minutes` / `max_consecutive_days` を扱います。
選好は `avoid_role`、目的は選好ペナルティ・担当切替と、勤務計画の勤務量です。
`auto` は入力条件から一つの方式を選び、未対応条件は `INVALID_INPUT` として拒否します。
必須条件を無断で減らしたり緩和したりしません。

勤務候補と選択済み勤務の件数上限はありません。その他の上限は従業員250人・役割50・時間枠3000、
従業員 × 時間枠 × 役割1,000,000以下です。上限内の性能を保証する値ではありません。
`time_limit_seconds` はモデル準備後に全目的で共有する探索予算です。
入力検証・依存読み込み・候補展開・モデル構築・結果検証を含む総時間は
`stats.elapsed_seconds`、探索時間は `SEARCH_STATS` の `facts` で確認できます。

夜勤・分割勤務、明示目標に対する公平性・変更最小化は契約0.2・0.3で利用できます。
候補外の時刻、契約時間に対する公平性、給与計算・法令判定、詳細な矛盾原因・自動緩和は未対応です。外部 API・LLM・PyPI 公開・production デプロイは対象外です。
ブラウザーの利用入口は、上記のローカル担当配置・JSON デモに限定します。
参照 ZIP のコードは参照元のライセンス未選定のため取り込まず、採用した業務仕様から独自実装しています。
公開条件は [開発・検証方針](docs/development-policy.md)に記載しています。

## 検証・ビルド・評価の再実行

```sh
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
bash -n scripts/deploy
uv build --wheel
uv run --locked --extra cp-sat python scripts/evaluate.py examples/assignment.json examples/roster.json docs/evaluations/inputs/assignment-week.json docs/evaluations/inputs/roster-week.json --output test-results/evaluation.json
```

既存 CI の `deploy-entrypoint` は CP-SAT 導入下で全テストを実行し、スキップがあれば失敗します。
成功・失敗・スキップ理由は pytest ログと保存される `pytest-results` の JUnit XML で追跡できます。
全探索との比較、両バックエンドの共通問題、独立検証器の違反検出に加え、
wheel を lock file の実行依存とともに新しい隔離環境へ導入し、ライブラリ・CLI・Schema を確認します。
別の空環境では wheel の依存宣言から導入し、lock file はバージョン制約だけに使います。
OR-Tools なしの別の隔離環境でも、最小費用流と依存不足の経路を確認します。

評価スクリプトは macOS / Linux で冷起動・継続・並行実行を反復測定し、環境・依存版・入力 SHA-256・
条件・目的値・証明範囲・検証結果・時間・ピーク RSS を JSON に保存します。
測定した checkout の commit SHA・未コミット変更の有無・uv.lock の SHA-256 も記録します。
架空の30人・7日の担当配置、20人・7日の勤務計画は実務規模が未確定のため提案値です。
入力・測定方法・実測・未測定範囲は [利用入口・CI・実行評価の記録](docs/evaluations/runtime.md)を参照してください。

通常の再測定出力は Git 対象外の `test-results/` に置き、CI のテストログと JUnit XML は Actions 側に残します。
Git には採用判断で使う入力・条件・集計・失敗を含む生データを保存します。
保存先と追加基準は [評価結果と実行ログの保存](docs/development-policy.md#評価結果と実行ログの保存)を参照してください。

## 設計ドキュメント

飲食店デモの推奨構成・編集範囲・3シナリオは
[配置プレイグラウンドの仕様](docs/playground.md)と[静的な画面案](docs/playground-wireframe.html)を参照してください。
ブラウザーから計算するデモは、上記の起動手順で試せます。

開発者・仕様を決める人が、導入済み機能の対象範囲と守るべき意味を共有するための文書です。
次の順に読むと、全体から個別の実装条件まで確認できます。

| 文書 | 内容 |
| --- | --- |
| [全体像](docs/overview.md) | 目的、利用例、対象範囲、構成、公開物 |
| [設計方針](docs/design-policy.md) | アルゴリズム選択、制約・選好、検証、LLM の境界 |
| [入出力契約0.1](docs/io-contract.md)・[契約0.2](docs/io-contract-next.md) | JSON の意味、日時、履歴、目的順序、結果状態と移行 |
| [再計画・勤務量・希望日時の契約0.4](docs/io-contract-replanning.md) | 新条件、基準スナップショット、公開検証API/CLIと移行 |
| [重複期間の基準比較・固定再計画の契約0.7](docs/io-contract-overlap.md) | 元の基準を保持した移動期間の比較・固定・変更集計 |
| [継続計画・診断・費用・夜勤休日評価の設計案](docs/planning-extensions.md) | Issue #67〜#70の仕様案、数値例、検証計画、実装の依存関係。継続計画・重複期間の再計画・矛盾縮小は実装済み |
| [不足を伴う計画の契約0.3](docs/io-contract-partial.md) | 元需要を保持した不足集計・独立検証・両ソルバー・CLI・デモと証明範囲 |
| [開発・検証方針](docs/development-policy.md) | 開発順序、完了条件、公開条件、未決定事項 |
| [参照実装の評価](docs/evaluations/engine-introduction.md) | CP-SAT を含む実測、導入時の修正、コードの採用可否と公開入口 |
| [用語集](GLOSSARY.md) | single-context の共通用語 |
| [設計判断](docs/adr/0001-json-first-engine.md) | JSON を中心にしたエンジンと、[勤務計画の同時最適化](docs/adr/0002-joint-roster-optimization.md) |
| [出典と採用判断](docs/sources.md) | 元チャット、ZIP、採用箇所、参照資料の来歴 |

## デプロイ

デプロイの入口は、環境名とビルド済みの成果物ファイルを引数で受け取ります。

```bash
scripts/deploy staging ./release.tar.gz
scripts/deploy production ./release.tar.gz
```

デプロイ先は未定です。スクリプトは引数を検証し、デプロイが実装されるまでは
終了コード1で失敗します。引数が不正な場合は終了コード2で失敗します。
現時点ではビルド・アップロード・デプロイは行いません。

今後導入するリリース workflow では、staging と production に同じ成果物を渡して
このスクリプトを呼び出します。production は GitHub Environment の承認を待ってから
実行します。workflow の導入前に、Environment の保護を設定・検証します。

## Repository の変更管理

main の変更には PR と、CI チェック `deploy-entrypoint` の成功が必要です。
一人運用のため、PR の必須承認は0名です。merge は squash のみに限定し、
main の force push と削除は禁止します。ruleset の bypass は許可しません。

`v*` の正式タグを作成できるのは Repository Admin のみです。現在は
@omitsuhashi が該当します。将来 Admin を追加すると、その人もタグを作成できます。
既存の `v*` タグの移動・削除は禁止し、Admin による bypass も許可しません。

デプロイに関して未確定なのは、production の承認者、実際のビルドコマンド、
デプロイ先です。デプロイの入口と CI はセットアップ PR で導入し、
merge 後に main で利用できるようになります。

契約0.5では需要の任意 `priority`（省略時0）を指定できる。不足総量を先に最小化し、
同量の計画では高いpriority群の不足、利用者の目的の順に比較する。
[契約と証明範囲](docs/io-contract-priority.md)、[1人・2役割の例](examples/demand_priority.json)を参照する。
