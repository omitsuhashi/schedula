# 性能・解品質の反復評価

Issue [#18](https://github.com/omitsuhashi/schedula/issues/18) の評価基盤と、
[#20](https://github.com/omitsuhashi/schedula/issues/20) へ渡す比較条件を記録する。
この文書は採用前の5秒評価と提案を保存する履歴である。実データは未取得であり、架空入力の数値を実環境の性能保証にしない。
現在の採用条件・改善結果は [探索予算の見直し](search-budget.md) を正本とする。

2026-10-06、利用者が「5秒の予算制限は解除します」と指定した。
以下の5秒前提の基準と改善目標は比較時点の履歴として保持し、現在の合否には使わない。
延長予算の比較条件は [探索予算の見直し](search-budget.md) を参照する。

## 比較前に置く合格基準案

対象は macOS 26.7.1 / ARM64 / 8論理コア / Python 3.14.8 / uv 0.12.23、
OR-Tools 9.15.6755 / jsonschema 4.26.0。CP-SAT の探索 worker は1、入力 seed は0。
通常の探索予算は5秒であり、外部期限とは区別する。全測定の依存版を結果 JSON に保存する。
次の数値案は、今回の反復比較の測定前に記載した。

| 対象 | 提案する機械判定条件 |
| --- | --- |
| 現行の週単位担当配置・勤務計画 | 3回以上の全試行で独立検証済み解を得る。単独の `request_elapsed_seconds` の観測最大値10秒以下、各 worker のピーク RSS 512 MiB 以下 |
| 15分勤務計画・40人14日の勤務計画 | 3回以上の全試行で独立検証済み解を得る。単独の観測最大値15秒以下、ピーク RSS 1024 MiB 以下 |
| 2プロセスの現行勤務計画 | 全試行で独立検証済み解を得る。各試行の観測最大値20秒以下、各 worker のピーク RSS 1024 MiB 以下。合計メモリの基準ではない |
| 現行勤務計画の解品質 | 目的順序の辞書式比較で `[630, 32670, 83]` 以下。過去の単発実測を後退検出の起点にした提案であり、最適値の主張ではない |
| 取得できた未証明の目的の解品質 | 上位の全目的が証明済みの場合だけ、その目的の相対 gap 20%以下を提案する。bound 不明なら未判定とし、0や合格で補わない |
| 不可能・探索予算切れ・上限拒否 | 不可能入力は `INFEASIBLE`、0.001秒予算の入力は `UNKNOWN` または検証済み `FEASIBLE`、上限超過は `INVALID_INPUT` / `INPUT_LIMIT`。状態の区別・理由・試行数を保持する |
| 全ケース | 未検証の解、`INTERNAL_ERROR`、worker 障害、計測用の期限超過を成功扱いしない。性能基準の対象ケースに発生した場合は未達とする |

平均・中央値・p95・観測最大値を併記するが、3回の p95 は nearest-rank 法により最大値と一致する。
母集団の p95 や応答時間保証を推定した値ではない。基準承認後の運用測定では反復数を増やす。

## 評価入力と採用理由

全入力は公開可能な架空データで、3役割、技能条件は調理・接客の2種類。
現行勤務計画は調理のみ・接客のみ・補助・両技能の各5人、毎日10:00〜16:00に各役割3人を要求する。
需要がある時間枠の割合は24時間中6時間の25%。選好ペナルティ → 勤務量 → 担当切替を最小化し、
休息600分、連勤5日以下、勤務量上限1650分、空の計画前履歴を明示する。
この条件と人数・時刻・休憩位置は就業規則や法令の基準ではない。

| 入力 | 人数・期間・粒度 | 時間枠・候補 | 採用理由・生成条件 |
| --- | --- | --- | --- |
| [assignment-week.json](inputs/assignment-week.json) | 30人・7日・30分 | 336・0 | 既存の比較入口。各技能10人と補助10人、各役割8人、選好だけ。最小費用流の軽量経路を保持する |
| [roster-week.json](inputs/roster-week.json) | 20人・7日・30分 | 336・560 | 既存の未証明解と比較。1人1日につき6時間勤務・30分休憩の4位置から候補を生成する |
| [roster-fortnight-large.json](inputs/roster-fortnight-large.json) | 40人・14日・30分 | 672・2240 | 人数・期間・候補の同時拡大。現行の20人を `_extra` IDで複製し勤務可能時間と需要を7日後へ追加。各役割6人、勤務量上限3300分、他の規則・目的順序は保持する |
| [roster-week-15min.json](inputs/roster-week-15min.json) | 20人・7日・15分 | 672・560 | 人数・候補集合を変えず、担当変数と隣接枠の増加を分離する。現行入力の粒度だけを15分へ変更する |
| [roster-week-infeasible.json](inputs/roster-week-infeasible.json) | 20人・7日・30分 | 336・560 | 技能偏在と高密度需要。初日の調理需要だけ11人へ増加し、担当資格を持つ10人を超える。解なしの試行を集計する |
| [roster-week-timeout.json](inputs/roster-week-timeout.json) | 20人・7日・30分 | 336・560 | 現行入力の探索予算だけ0.001秒へ変更し、未確定を不可能と混同しない経路を確認する |
| [roster-input-limit.json](inputs/roster-input-limit.json) | 20人・88日・30分 | 4224・展開前拒否 | 終了日だけ2027-01-01へ変更し、時間枠3000の現行上限を超える。性能試験から分けて拒否を確認する |
| [linked_assignment.json](../../examples/linked_assignment.json) | 3人・2時間・30分 | 4・0 | 過去の36.748秒の遅延と同じ入力を、冷起動・継続・並行で再実行する。依存読み込みと探索を分離する |

派生入力は `roster-week.json` の深いコピーから上表の変更と `request_id` の変更だけで生成した。
乱数生成は使っていない。solver seed 0を全件に保存し、ファイル SHA-256 は各試行の `input_sha256` に残す。
全組合せは行わず、目的順序・勤務候補の違いを同時に変えるケースは追加していない。
新契約の組合せはマイルストーンの最終確認で別途追加する。

## 測定の定義

`scripts/evaluate.py` を再利用する。`--repeat N --mode cold` は入力あたりN個の新しい Python プロセスを作る。
OSのファイルキャッシュは消去しない。`--mode warm` は入力ごとに1個のプロセスでN回を継続実行し、
`iteration: 1` / `execution: cold_initial` と、その後の `execution: continued` を区別する。
`first_request_elapsed_seconds` と `continued_request_elapsed_seconds` を別集計し、初回を継続実行の値に混ぜない。
`--processes` は同時に動かす worker 数の**上限**で、実際に開始した個数は `worker_processes_started`。
単一入力の warm は1プロセスである。並行負荷の比較は同じ入力の cold 反復を `--processes 2` で実行する。

`elapsed_seconds` は `solve` 全体、`request_elapsed_seconds` は schedula import・入力読込・JSON読込・solve の合計。
`import_seconds`・`input_seconds` を別記し、SEARCH_STATS がある場合は正規化・候補展開、CP-SAT依存読込、
モデル構築、探索、独立検証の時間も保持する。Schema検証は正規化に含み、候補展開と個別には分けない。
出力Schema検証とその他の処理は総時間に含み、内訳の合計を総時間と同一とは扱わない。
`workers[].elapsed_seconds` はプロセス起動から終了までで、結果保存用の条件集計・再正規化とJSON出力も含む。
継続実行ではN回の合計であり、1回の応答時間に置き換えない。

ピークRSSは `ru_maxrss`（macOSはバイト、LinuxはKiB）をMiBへ変換する。
Python・JSON・ネイティブの依存を含むプロセス全体のピークで、各solve後・条件再正規化前に取得する。
warm は同じプロセスの過去のピークを保持する。前回の再正規化、読み込み済みSchema・依存、OSキャッシュの影響もあり、
反復ごとの増分メモリとは扱わない。並行の親プロセス・合計RSSは今回測定していない。

`--timeout-seconds` は worker 全体の外部上限で、warm は初回を含むN回の全体に適用する。
期限超過は `WORKER_TIMEOUT`、非ゼロ終了や壊れた計測出力は `WORKER_ERROR`、その後の未実行反復は `WORKER_NOT_RUN`。
完了済みNDJSON行を保持し、予定した全反復を母数に含める。状態数と解獲得率の母数は解なし・障害も含む。
時間・RSSの値を取得できなかった試行はnull相当とし、分布の `samples` を必ず示す。
workerの実時間は失敗・期限超過も `process_elapsed_seconds` に残す。中央値を架空の期限値で補完しない。

## bound と gap の扱い

目的順序の各値と `proven_optimal` を保存し、配列順の辞書式比較を使う。
CP-SATの `OBJECTIVE_BOUND` はその段階の目的の下限であり、上位の最適値を固定した範囲にだけ適用する。
保持された検証済み解の同じ目的の値から `absolute_gap = max(0, value - best_bound)`、
`relative_gap = absolute_gap / max(abs(value), 1)` を再計算する。値と下限が0ならgapは0。
最適性を証明した目的は値自身を下限として扱える。
未探索・未取得のbound、上位未証明の後段目的はnullとし、分布では取得件数を明示する。
後段の目的値を保持していても、その段階を探索した証拠にはせず、全体の最適性保証にも使わない。

## ソースの固定と再実行

基準commitは `76d3534a0cd79253691f76c82da82e4d71daef9c`、schedula 0.1.3 / 契約0.1。
`--source-ref` は `git archive` で `src/`・`uv.lock`・`pyproject.toml` を一時ディレクトリへ固定し、
workerの `PYTHONPATH` をそのソースへ向ける。指定なしでは開始時のcheckoutのコピーを使う。
同時に別作業がソースを更新しても、開始済みの測定には混ぜない。
source commit、dirty、source tree SHA-256、runner SHA-256、lock SHA-256、package版を保存する。
依存パッケージは現在の `.venv` を使う。旧refのlockへ自動同期しないため、package版またはlockが現在と異なるrefは拒否する。
その場合は対象refと同じ環境を先に同期して再実行する。今回の基準と比較ソースはpackage版とlockが同一である。
`source.dirty: false` は固定したgit archiveの状態であり、新runnerや測定入力まで基準commitに含まれる意味ではない。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/assignment-week.json docs/evaluations/inputs/roster-week.json docs/evaluations/inputs/roster-fortnight-large.json docs/evaluations/inputs/roster-week-15min.json docs/evaluations/inputs/roster-week-infeasible.json docs/evaluations/inputs/roster-week-timeout.json docs/evaluations/inputs/roster-input-limit.json examples/linked_assignment.json --repeat 3 --source-ref 76d3534a0cd79253691f76c82da82e4d71daef9c --output docs/evaluations/results/2026-10-06-baseline-cold.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json examples/linked_assignment.json --repeat 3 --mode warm --source-ref 76d3534a0cd79253691f76c82da82e4d71daef9c --output docs/evaluations/results/2026-10-06-baseline-warm.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json examples/linked_assignment.json --repeat 4 --processes 2 --source-ref 76d3534a0cd79253691f76c82da82e4d71daef9c --output docs/evaluations/results/2026-10-06-baseline-parallel.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json docs/evaluations/inputs/roster-fortnight-large.json docs/evaluations/inputs/roster-week-15min.json examples/linked_assignment.json --repeat 3 --output docs/evaluations/results/2026-10-06-profile.json
```

新runnerの回帰テストは `uv run --locked --extra cp-sat pytest -q tests/test_evaluation.py`。
本worktreeではuvキャッシュとPython導入先を `/private/tmp` に向けた。
測定時は全回帰テスト・wheel導入の終了を待ち、意図した2プロセス比較以外のテストを同時実行しない。

## 基準ソースの観測結果

2026-10-06、上記環境で測定した。元の基準ソースを変更せず、
[冷起動24試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-baseline-cold.json)、
[初回と継続6試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-baseline-warm.json)、
[2プロセス8試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-baseline-parallel.json)を保存した。
3ファイルの source tree SHA-256 は `18406fc579c9635f38117ca84080ff7ff4ae5e2fdd1a4666e0cfd60395adc591`。
平均・中央値・p95・観測最大値・個別試行はJSONに残す。以下は `request_elapsed_seconds` の中央値と観測最大値である。

| 冷起動・単独（各3回） | 状態 | 解獲得率 | 目的値（順序どおり） | 中央値 / 最大（秒） | RSS最大（MiB） |
| --- | --- | --- | --- | --- | --- |
| 30人7日・担当配置 | `OPTIMAL` 3 | 3/3 | 0・証明済み | 0.141 / 0.150 | 38.469 |
| 20人7日・勤務計画 | `FEASIBLE` 3 | 3/3 | 630・32670・83、全目的未証明 | 5.453 / 5.456 | 191.969 |
| 40人14日・勤務計画 | `UNKNOWN` 3 | 0/3 | 解なし | 5.671 / 5.692 | 458.406 |
| 20人7日15分・勤務計画 | `FEASIBLE` 3 | 3/3 | 930・33000・84、全目的未証明 | 5.547 / 5.552 | 283.266 |
| 初日調理11人・不可能 | `INFEASIBLE` 3 | 0/3 | 解なし | 0.376 / 0.378 | 111.703 |
| 探索予算0.001秒 | `UNKNOWN` 3 | 0/3 | 解なし | 0.387 / 0.390 | 120.219 |
| 時間枠上限超過 | `INVALID_INPUT` 3、`INPUT_LIMIT` | 0/3 | 展開前の拒否 | 0.064 / 0.064 | 34.969 |
| 時間横断配置例 | `OPTIMAL` 3 | 3/3 | 0・証明済み | 0.284 / 0.286 | 103.031 |

通常勤務計画の時間・メモリ・既存の目的値比較は提案値内だった。
40人14日は時間・メモリの数値案内でも、解獲得率100%の提案に未達だった。
`UNKNOWN` は不可能性の証明ではない。通常勤務計画と15分入力の先頭目的のboundは旧ソースでは取得しておらず、gapは未判定。
後段目的の値を得ても、後段の探索や最適性を証明したとは扱っていない。

| 実行条件 | 入力 | 試行数・状態 | 初回（秒） | 継続中央値 / 最大（秒） | RSS最大（MiB） |
| --- | --- | --- | --- | --- | --- |
| 同じプロセスで継続 | 20人7日 | 初回1 + 継続2、`FEASIBLE` 3 | 5.469 | 5.171 / 5.173 | 200.797 |
| 同じプロセスで継続 | 時間横断配置例 | 初回1 + 継続2、`OPTIMAL` 3 | 0.283 | 0.003 / 0.003 | 103.125 |
| 2プロセスの冷起動 | 20人7日 | 4、`FEASIBLE` 4 | 各回が初回、中央値5.491・最大5.499 | 継続なし | 192.563 |
| 2プロセスの冷起動 | 時間横断配置例 | 4、`OPTIMAL` 4 | 各回が初回、中央値0.305・最大0.306 | 継続なし | 103.016 |

単独3回、継続2回、並行4回の今回の範囲で、過去のsolve 36.748秒は再現しなかった。
元の測定はwheel導入との同時実行だったが、同じ競合を再現したものではない。
原因を特定したとは扱わず、[過去の初回結果](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-initial.json)を保持する。
今回の2プロセス比較では時間横断配置例の最大request時間は0.306秒だった。

## 時間内訳と解品質を追加した観測

[時間内訳を持つ12試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-profile.json)は、基準commitを親に持つ作業中ソースのコピーを固定して測った。
source tree SHA-256 は `d67766df51cf491e390a789345b05ab6759f0b941915bd586e6638d5cc3b3723`、
`source.dirty: true`。基準の測定へこの変更を後付けせず、別ファイルに保持する。
次表の内訳は各3回の算術平均、requestは観測最大値、メモリは観測最大値である。

| 入力 | 状態 | 正規化（秒） | 依存読込（秒） | 構築（秒） | 探索（秒） | 独立検証等（秒） | request最大（秒） | RSS最大（MiB） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20人7日 | `FEASIBLE` 3 | 0.030 | 0.219 | 0.083 | 5.008 | 0.042 | 5.468 | 192.281 |
| 40人14日 | `UNKNOWN` 3 | 0.064 | 0.217 | 0.328 | 5.009 | 0.003 | 5.668 | 457.391 |
| 20人7日15分 | `FEASIBLE` 3 | 0.030 | 0.221 | 0.160 | 5.014 | 0.050 | 5.564 | 283.438 |
| 時間横断配置例 | `OPTIMAL` 3 | 0.016 | 0.218 | 0.001 | 0.002 | 0.008 | 0.284 | 102.984 |

通常勤務計画は3回とも先頭目的値630・下限0・相対gap1.0、15分入力は値930・下限0・相対gap1.0。
後段の2目的はbound未取得。先頭目的のgap20%という数値案には未達である。
これは現状の証明できる範囲からの差であり、下限0が達成可能な最適値と証明したものではない。
時間横断配置例は値0・下限0・gap0で、最適性も証明済みだった。
旧測定と状態・目的値が同じでも、計測追加だけで性能が改善したとは扱わない。

## 障害・計測期限の保存

[外部期限の2試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-harness-timeout.json)は正常な現行勤務計画を
`--repeat 2 --timeout-seconds 0.000001` で測り、`WORKER_TIMEOUT` 2件を母数に保存した。
solve時間とRSSを取得できず分布のsamplesは0だが、worker実時間のsamplesは2。
エンジンの `UNKNOWN` と計測workerの終了は別の状態である。

[入力ファイル不足の2予定試行](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-harness-failure.json)は、意図的に存在しない
`docs/evaluations/inputs/missing-evaluation-input.json` を `--repeat 2 --mode warm` で指定した。
最初の `WORKER_ERROR` と、続行できない `WORKER_NOT_RUN` を各1件として保存し、解獲得率の母数を2とした。
ファイルが存在しないためinput hashはnullで、理由はstderrに保持する。このファイルは作成しない。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json --repeat 2 --timeout-seconds 0.000001 --source-ref 76d3534a0cd79253691f76c82da82e4d71daef9c --output docs/evaluations/results/2026-10-06-harness-timeout.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/missing-evaluation-input.json --repeat 2 --mode warm --source-ref 76d3534a0cd79253691f76c82da82e4d71daef9c --output docs/evaluations/results/2026-10-06-harness-failure.json
```

6ファイルを合わせて予定54試行を保存し、正常入力・不可能・探索予算切れ・上限拒否・worker期限・worker障害・未実行を保持した。
今回の通常測定にworker障害や計測用の期限超過はなく、上の2ファイルでは意図的にその保存経路を実行した。
Ruffのlint・formatと評価テスト4件が成功し、失敗・スキップ0件。
テストでは冷起動の反復・並行、継続の初回分離、入力不正・worker障害・外部期限、
boundの適用範囲、値0、nearest-rank、基準sourceの固定を確認した。全体回帰とGitHub CIの結果はPRに記録する。

## 5秒評価時点の引き継ぎと未決事項（履歴）

[#20](https://github.com/omitsuhashi/schedula/issues/20) の着手条件は利用者が評価基準を承認した後に確定する。
入力・seed・候補集合・目的順序・5秒の探索予算を保ち、基準ソースと同じ冷起動3回で比較する。
最適性未証明の `FEASIBLE` を障害として修正せず、承認した解獲得率・品質・時間・メモリで判断する。

1. **大きい問題の解獲得**: 40人14日2240候補が3回とも `UNKNOWN`。探索は平均5.009秒、構築は0.328秒。
   提案目標は予算5秒のまま検証済み解3/3、request観測最大15秒以下・RSS 1024 MiB以下。
   次の比較では探索による解獲得を優先し、基準入力を単純化して合格扱いしない。
2. **通常・15分入力の先頭目的の品質**: 各3回で相対gap1.0。取得できた下限に対する20%案は未達。
   先頭目的の値・下限・gapと証明範囲を合わせて比較する。後段の値だけの改善では合格にしない。
3. **起動時の固定費**: 時間横断配置例では平均0.218秒がCP-SAT依存読込で、探索は0.002秒。
   継続呼出しは約0.003秒。小規模入力の応答を重視する用途でだけ、依存の継続読み込みを改善候補にする。
   現行の数値案内であり、新たなサービス・キャッシュ基盤はこの結果だけでは追加しない。

利用者に確定してもらう事項は、代表規模を20人7日とするか40人14日まで含むか、
5秒の探索予算を維持するか、検証済み解の取得を優先するかgap20%を必須とするか、
通常10秒・大規模15秒・並行20秒、RSS 512/1024 MiBの上限案でよいかである。
勤務計画の実データ、他の目的順序、より長い期間、skill偏在の組合せ、他のCPU・OSの性能は未確認。
上の判断待ちは5秒評価時点の記録である。その後、利用者が5秒制限解除・検証済み解の獲得・既存目的値の条件を承認し、gapを評価指標のみと指定した。
現在の実装・反復比較・完了判定は [探索予算の見直し](search-budget.md) と PR #26 に記録する。
