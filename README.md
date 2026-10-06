# schedula

技能・勤務可能時間・役割別需要・業務ルールから、担当配置（`assignment`）と
出退勤・休憩を含む勤務計画（`roster`）の検証済み解を求める Python ライブラリと CLI です。
schedula 0.1.3 / JSON 契約0.1で、独立した配置は最小費用流、
担当時間・担当切替を含む配置と勤務計画は CP-SAT を使用します。

## クリーンな環境から実行する

[uv](https://docs.astral.sh/uv/getting-started/installation/) と Git を導入し、次を実行します。
Python 3.14.8 と依存版は `.python-version` / `uv.lock` で固定しています。
すでに clone 済みなら、リポジトリ直下で `uv python install` から実行してください。

```sh
git clone https://github.com/omitsuhashi/schedula.git
cd schedula
uv python install
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python -m schedula solve examples/assignment.json
uv run --locked --extra cp-sat python -m schedula solve examples/linked_assignment.json
uv run --locked --extra cp-sat python -m schedula solve examples/roster.json
```

全例が `OPTIMAL`、`verification.performed: true` / `valid: true`、終了コード0を返します。
担当配置の2例は選好ペナルティ0、勤務計画は選好ペナルティ60・勤務量2640分・担当切替0回です。
勤務量は待機を含み、休憩を除きます。目的値は `objectives` の配列順に優先され、
`proven_optimal` で目的ごとの証明範囲を確認できます。

最小費用流だけを使う場合は `--extra cp-sat` を省略できます。
CP-SAT が必要な入力を依存なしで解くと `BACKEND_UNAVAILABLE` になります。
標準出力は JSON のみで、結果は `> result.json` で保存できます。
標準入力と Schema の取得も同じ CLI で実行できます。

```sh
uv run --locked --extra cp-sat python -m schedula solve - < examples/assignment.json
uv run --locked --extra cp-sat python -m schedula schema request
uv run --locked --extra cp-sat python -m schedula schema response
```

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
uv run --locked --extra cp-sat python -m schedula solve request.json
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

## ライブラリで解と診断を読む

同じ環境で次を実行できます。自作入力に切り替える場合はファイル名を変更します。

```sh
uv run --locked --extra cp-sat python - <<'PY'
import json
from pathlib import Path
from schedula import solve

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
| `INFEASIBLE` | 必須条件を満たす解がないと証明された。診断を確認し、入力条件を見直す | 2 |
| `UNKNOWN` | 解も不可能性の証明もない。予算や問題規模を見直す | 2 |
| `INVALID_INPUT` | `code` / `json_pointer` / `related_ids` / `facts` を基に入力を修正する | 2 |
| `BACKEND_UNAVAILABLE` | `cp-sat` extra を導入して再実行する | 2 |
| `INTERNAL_ERROR` | 解を採用せず、入力・エンジン版・診断を保存して調査する | 2 |

解を返すのは独立検証に成功した `OPTIMAL` / `FEASIBLE` だけです。
それ以外は `solution: null` / `objectives: []`。終了コード2だけでは状態を区別できません。
`message` は補助説明で、プログラムでは `status` と診断の `code` で分岐します。
次の2例は意図的に終了コード2となります。

```sh
uv run --locked --extra cp-sat python -m schedula solve examples/infeasible.json
uv run --locked --extra cp-sat python -m schedula solve examples/invalid-input.json
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

上限は従業員250人・役割50・時間枠3000・勤務候補5000、
従業員 × 時間枠 × 役割1,000,000以下です。上限内の性能を保証する値ではありません。
`time_limit_seconds` はモデル準備後に全目的で共有する探索予算です。
入力検証・依存読み込み・候補展開・モデル構築・結果検証を含む総時間は
`stats.elapsed_seconds`、探索時間は `SEARCH_STATS` の `facts` で確認できます。

夜勤・分割勤務、候補外の時刻、契約時間に対する公平性、変更最小化、給与計算・法令判定、
詳細な矛盾原因・自動緩和は未対応です。Web UI・外部 API・LLM・PyPI 公開・production デプロイは対象外です。
参照 ZIP のコードはライセンス未選定のため取り込まず、採用した業務仕様から独自実装しています。
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

評価スクリプトは macOS / Linux の各入力を別プロセスで1回測定し、環境・依存版・入力 SHA-256・
条件・目的値・証明範囲・検証結果・時間・ピーク RSS を JSON に保存します。
測定した checkout の commit SHA・未コミット変更の有無・uv.lock の SHA-256 も記録します。
架空の30人・7日の担当配置、20人・7日の勤務計画は実務規模が未確定のため提案値です。
入力・測定方法・実測・未測定範囲は [利用入口・CI・実行評価の記録](docs/evaluations/runtime.md)を参照してください。

## 設計ドキュメント

開発者・仕様を決める人が、導入済み機能の対象範囲と守るべき意味を共有するための文書です。
次の順に読むと、全体から個別の実装条件まで確認できます。

| 文書 | 内容 |
| --- | --- |
| [全体像](docs/overview.md) | 目的、利用例、対象範囲、構成、公開物 |
| [設計方針](docs/design-policy.md) | アルゴリズム選択、制約・選好、検証、LLM の境界 |
| [入出力契約](docs/io-contract.md) | JSON の意味、日時、履歴、目的順序、結果状態 |
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
