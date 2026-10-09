# 先行する必要人数・連勤教材の評価

2026-10-09、[#118](https://github.com/omitsuhashi/schedula/issues/118) の先行教材について、
初期・変更・履歴・復元の9段階を実エンジンで確認した。
狙った指標と編集範囲は [設計文書](../designs/demo-redesign.md)、入力と操作は
[lessons.json](../../examples/playground/lessons.json)、維持テストは `tests/test_demo_lessons.py` にある。

## 確認した性質

- 必要人数は、初期の充足、2枠を3人へ増やしても充足、4人へ増やすと不足60人分、復元で初期充足を確認した。
- 連勤は、初期の5連勤、上限だけ3日へ変えても全員3日以内で充足、交代要員の勤務可能日削減で不足60人分を確認した。
- 履歴追加では、Aの直前3連勤を含めた上限5日を維持し、計画初日からの勤務が最大2日に制限されることを確認した。
- 求解結果は独立検証成功。教材テストは元Requestに対する公開verifyも通し、探索による証明との違いを確認する。
- 必須の最低人数を両立できない入力の `INFEASIBLE`、負の必要人数の `INVALID_INPUT` を、需要不足の `PARTIAL` と区別した。

## 環境と測定条件

| 項目 | 固定した値 |
| --- | --- |
| エンジンcommit | `bbb7a93b757cc3272943bbc09f9f2dcb359bd457` の `git archive` |
| 版・契約 | `shift-schedula 0.1.6`、全入力0.15 |
| 実行環境 | macOS 26.7.1、arm64、論理CPU 8、Python 3.14.8、uv 0.12.23 |
| 依存 | `uv.lock` 固定、OR-Tools 9.15.6755、tzdata 2026.5 |
| backend | 必要人数は `auto`（実結果 `min_cost_flow`）、連勤は `cp_sat` |
| 探索設定 | 入力の5秒・seed 0、CP-SATは既存solveの既定2 workers |
| 反復 | 9段階×3回×2方式＝54件、測定プロセス並行数1 |
| 冷起動 | 毎回新しいPythonプロセス。OSのファイルキャッシュは消さない |
| 継続 | 各段階の新プロセスで3回。最初の1回と後続2回を分ける |
| 測定用の上限 | 1プロセス60秒。探索予算やUIの待機期限とは別 |

全54件は想定した `OPTIMAL` または `PARTIAL` で、解の独立検証が成功した。
生記録には入力SHA-256、ソース・runner・lockのSHA-256、環境、設定、状態、検証、目的値、時間、RSSを保存した。
素材とガイドは本PRで追加した入力であり、固定エンジンcommitへ元から存在したとは扱わない。

## 冷起動と継続の実測

下表の冷起動はimport・入力読込・solveの最大時間、継続は同じプロセスの後続2回の最大時間を示す。
Pythonプロセスの起動と終了を含む時間は生記録の `workers.elapsed_seconds` に別記する。

| 教材・段階 | 状態 | 不足人分 | 冷起動最大（秒） | 継続最大（秒） |
| --- | --- | ---: | ---: | ---: |
| `demand/initial` | `OPTIMAL` | 0 | 0.1391 | 0.0069 |
| `demand/covered` | `OPTIMAL` | 0 | 0.1378 | 0.0069 |
| `demand/shortage` | `PARTIAL` | 60 | 0.1380 | 0.0091 |
| `demand/restored` | `OPTIMAL` | 0 | 0.1405 | 0.0068 |
| `consecutive_days/initial` | `OPTIMAL` | 0 | 0.3804 | 0.0292 |
| `consecutive_days/shorter` | `OPTIMAL` | 0 | 0.4271 | 0.0344 |
| `consecutive_days/fewer_backups` | `PARTIAL` | 60 | 0.4228 | 0.0207 |
| `consecutive_days/history` | `OPTIMAL` | 0 | 0.3824 | 0.0300 |
| `consecutive_days/restored` | `OPTIMAL` | 0 | 0.4375 | 0.0317 |

冷起動のプロセス全体は全27件で最大0.5733秒。継続方式の最初の1回は各段階で0.1543〜0.4493秒で、後続2回へ混ぜない。

記録: [冷起動27件](https://github.com/omitsuhashi/schedula/blob/a30885473b050d3a91dcf63fff1254a941c4cb07/docs/evaluations/results/demo-lessons-cold-20261009.json)、[継続を含む27件](https://github.com/omitsuhashi/schedula/blob/a30885473b050d3a91dcf63fff1254a941c4cb07/docs/evaluations/results/demo-lessons-warm-20261009.json)。
少数標本のためp95から一般的な性能を推定せず、教材を選ぶための最大値として使う。
HTTP・ブラウザー描画・利用者評価は未測定。新規依存導入直後やOSキャッシュを消した起動も本測定の対象外である。

## 再現手順

リポジトリ直下で `uv sync --locked --extra cp-sat` を実行してから、操作を適用した純粋なRequestを生成する。
ガイドの適用は既存シナリオと同じ補助関数を使い、初期ファイルを変更しない。

```sh
uv run --locked --extra cp-sat python - <<'PY'
import json
from pathlib import Path
from tests.test_playground_scenarios import SAMPLES, scenario_requests

out = Path('test-results/demo-lessons-inputs')
out.mkdir(parents=True, exist_ok=True)
for lesson in json.loads((SAMPLES / 'lessons.json').read_text(encoding='utf-8')):
    baseline = json.loads((SAMPLES / lesson['request_file']).read_text(encoding='utf-8'))
    for step, request in scenario_requests(lesson, baseline):
        path = out / f"{lesson['id']}-{step['id']}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
uv run --locked --extra cp-sat python scripts/evaluate.py test-results/demo-lessons-inputs/*.json --repeat 3 --mode cold --processes 1 --timeout-seconds 60 --source-ref bbb7a93b757cc3272943bbc09f9f2dcb359bd457 --output test-results/demo-lessons-cold.json
uv run --locked --extra cp-sat python scripts/evaluate.py test-results/demo-lessons-inputs/*.json --repeat 3 --mode warm --processes 1 --timeout-seconds 60 --source-ref bbb7a93b757cc3272943bbc09f9f2dcb359bd457 --output test-results/demo-lessons-warm.json
uv run --locked --extra cp-sat pytest -q tests/test_demo_lessons.py tests/test_playground_scenarios.py tests/test_playground_server.py
```

同じ固定エンジンとlockを使える環境で再現する。契約移行後のエンジンを測るときは対応する新しいcommitを指定し、
古い固定エンジンの結果を新画面の性能証拠にしない。評価記録の結果JSONはsdistには含めない既存の配布方針を維持する。

## 後続で確認すること

同等環境では冷起動のプロセス全体1秒以内、継続の読込・solve 0.25秒以内を目安にする。
#119では初期計算・再計算それぞれのHTTP全往復と描画終了までを計測し、2秒以内を暫定の合格目安とする。
環境・backend・設定・繰返し数を記録し、超過時は原因と教材規模を確認してから判断する。
#126では人が入力と不足・必須条件・最適性を説明できるか、待ち時間をどう受け止めるかを別途確認する。
本記録は教材の技術検証であり、画面の使いやすさ、実店舗性能、期間別テンプレートの完成を示さない。
