# 探索予算の見直し

2026-10-06、利用者の「5秒の予算制限は解除します」という指示に従い、
5秒固定を性能・品質の合格条件から外す。
[5秒での54予定試行](performance.md)は履歴として保持する。
同日、利用者が推奨仕様と以下の解獲得・既存目的値の条件を承認し、gapは評価指標として記録するよう指定した。

## 測定前の比較条件

候補集合・需要・技能・勤務ルール・目的順序・seed 0・CP-SAT worker 1を保持し、
最初に20人7日、40人14日、20人7日15分を30秒・60秒で各1回調べる。
結果が必要な範囲に届かなければ120秒・300秒へ延長する。
既存契約0.1は正の有限探索予算を入力し、上限は300秒である。
5秒を外すために契約0.1の意味やソルバー方式を変更しない。
固定した5秒以外の効果と、アルゴリズムの改善を混同しない。

有用な予算を選んだ入力は冷起動3回を再測定し、初回だけの結果から合格とは扱わない。
測定スクリプトに追加する `--time-limit-seconds` は実効の `solver_request` と条件欄に残す。
原本の入力SHA-256は維持し、実際に使用した予算を原本の5秒と区別する。
外部のworker上限は各探索予算に30秒を加え、未完了も測定結果に保存する。

## 採用した合格基準

| 対象 | 条件 |
| --- | --- |
| 通常・拡大・15分勤務計画 | 選んだ予算で全3試行が独立検証済み `OPTIMAL` / `FEASIBLE`。`UNKNOWN` は不可能性でも成功でもない |
| 総時間 | 単独の通常入力は探索予算+5秒、拡大・15分は探索予算+10秒の観測最大値以内。外部応答時間の保証ではない |
| メモリ | 通常は各workerの512 MiB以下、拡大・15分は1024 MiB以下 |
| 通常入力の目的値 | 目的順序の辞書式比較で `[630, 32670, 83]` 以下を維持する |
| 解品質の証明範囲 | 適用可能な先頭目的の相対gapを記録する。合否条件にはしない。後段の未探索・下限不明は未判定とし、0で補完しない |
| 未達 | 長い予算でも基準を満たさなければ、#20の未完了項目として入力・状態・下限・品質を引き継ぐ |

解獲得・既存目的値は利用者の承認済み。時間とメモリの数値は、測定前に設定した工学上の評価目安であり、実環境の応答期限の保証ではない。
反復数・統計・状態・source識別は既存の評価方法を使う。

## 結果

### 時間延長とworker比較の判断

基準は `3e19b0c0edf6507237dc30de92041c0af6af733c`、環境・入力は5秒評価と同じ。
30/60秒は各入力1回、120/300秒は40人14日を各1回のスクリーニングとし、合格判定には使わない。
rawは [30秒](results/2026-10-06-screening-30.json)・[60秒](results/2026-10-06-screening-60.json)・
[120秒](results/2026-10-06-screening-large-120.json)・[300秒](results/2026-10-06-screening-large-300.json)。

| worker1・入力 | 予算 | 状態 | 目的順の値 | request秒 | RSS MiB |
| --- | --- | --- | --- | --- | --- |
| 20人7日 | 30 / 60秒 | `FEASIBLE` / `FEASIBLE` | `[360,33000,58]` / 同値 | 30.463 / 60.467 | 199.359 / 199.281 |
| 20人7日15分 | 30 / 60秒 | `FEASIBLE` / `FEASIBLE` | `[375,33000,140]` / `[345,33000,91]` | 30.552 / 60.550 | 294.438 / 293.328 |
| 40人14日 | 30 / 60 / 120 / 300秒 | すべて `UNKNOWN` | 解なし | 30.671 / 60.667 / 120.785 / 300.694 | 479.703 / 475.312 / 473.031 / 481.734 |

時間延長だけでは40人14日の解獲得が改善しないため、実測で支配的な探索の標準パラメーターを比較した。
[OR-Tools 9.15の公式定義](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto)では、
複数workerは並行探索を実行する。既存の `num_search_workers` を1から2へ変更し、
同一sourceの一行変更コピーを30秒・同じ入力/seed/目的順序で測った。

| worker2・単発比較 | 状態 | 目的順の値 | request秒 | RSS MiB |
| --- | --- | --- | --- | --- |
| 20人7日 | `FEASIBLE` | `[270,33000,34]` | 30.499 | 255.203 |
| 40人14日 | `FEASIBLE` | `[1080,131340,95]` | 30.956 | 665.625 |
| 20人7日15分 | `FEASIBLE` | `[270,33000,85]` | 30.561 | 396.594 |

[通常/15分](results/2026-10-06-workers-2-normal-30.json)・[40人14日](results/2026-10-06-workers-2-large-30.json)の
source tree SHAは `1c2acfd334d26dc5948c72291f0c7666b95b92a2d436d5e04e477ad09bb0502b`。
基準commitのコピーを変更したため `external_tree_copy` / `dirty: true` と明記する。
4workerへの増加や別アルゴリズムは、2workerで解獲得・通常品質が改善しメモリ目安内のため追加しなかった。
この比較は採用候補を選ぶ証拠であり、最終の反復検証で合否を判断する。

worker1の30秒冷起動は、[通常と15分を各3回](results/2026-10-06-budget-30-cold.json)測定した。
すべて検証済み `FEASIBLE`、通常は `[360,33000,58]` / 最大30.542秒・199 MiB、
15分は `[375,33000,140]` / 最大30.561秒・295.266 MiB。
この段階は機能編集と小規模テストが並行したため、完全なホスト占有測定とはしない。
最終反復はCPU負荷の大きいローカルテストを終えた後に順次実行した。

### 実装と機能の検証

実装sourceは `b6128903668095297cdb03a8be95a5d738ae8e6b`。
採用した契約0.2の夜勤・分割・公平性・固定/変更・診断を API/CLI/版別Schema に導入した。
[組合せ評価入力](inputs/roster-extended.json)は旧夜勤分割の計画を基準に、現勤務の前半固定、
後半の欠勤再計画、目標120分ずつ、許可した需要2→1の診断案を同時に扱う。
元入力は `INFEASIBLE`、変更案は `[16,0,240]` の検証済み `OPTIMAL` である。
変更案は元入力の解獲得率へ加算せず、別に検証済み案の件数を記録する。

macOS ARM64 / Python3.14.8の全回帰は953件・subtest6件成功、失敗/スキップ0、67.39秒。
[GitHub CI](https://github.com/omitsuhashi/schedula/actions/runs/37421597438)も Ubuntu / Python3.14.8で
953件・subtest6件成功、失敗/スキップ0、37.70秒。Ruff hook・スキップ拒否が成功した。
両バックエンドの全探索、0.1回帰、0.2候補と担当の完全列挙、全6目的順序、
新5目的の途中終了と証明prefix、壊した解/集計の拒否、診断失敗/予算切れ、
wheelの隔離導入（0.1/0.2 Schemaと全例）を含む。
独立レビューの具体的指摘は修正し、再レビューで未解消の指摘なしを確認した。
別の監査では既存14個の測定JSONのraw/summary、母数・状態・nearest-rank・gap適用範囲・入力SHAを再計算し、
基準/実装のgit archive・lock・package版とworker2の一行変更SHAも一致した。
最終冷起動12試行と並行4試行も同じ観点で照合し、rawと集計・全workerの正常終了が一致した。
診断の変更案3件はソルバーを呼ばず再検証し、許可編集だけの変更、baseline・fixed_partsの保持、
違反0、目的値・集計の一致を確認した。

### 最終反復

固定sourceの [改善前40人14日・冷起動3回](results/2026-10-06-before-large-30-cold.json) と
[改善後4入力・各冷起動3回](results/2026-10-06-final-cold.json) を比較した。
改善前40人14日は `UNKNOWN` 3/3、検証済み解0/3、最大30.682秒・479.953 MiB。
改善後は通常・40人14日・15分の全9試行で検証済み `FEASIBLE` を取得した。

| 改善後・各3試行 | 元状態 | 検証済み解 | request平均 / 中央 / p95=最大 秒 | RSS最大 MiB |
| --- | --- | --- | --- | --- |
| 20人7日 | `FEASIBLE` 3 | 3/3 | 30.470 / 30.454 / 30.513 | 260.828 |
| 40人14日 | `FEASIBLE` 3 | 3/3 | 30.960 / 30.955 / 30.979 | 672.375 |
| 20人7日15分 | `FEASIBLE` 3 | 3/3 | 30.573 / 30.557 / 30.611 | 387.125 |
| 夜勤・分割・固定・公平性・再計画・診断 | `INFEASIBLE` 3 | 元0/3、検証済み変更案3/3 | 0.322 / 0.322 / 0.326 | 105.047 |

通常の目的値は `[270,33000,33]`、`[270,33000,66]`、`[270,32670,15]`。
すべて旧比較値 `[630,32670,83]` 以下の辞書式値である。
40人14日は `[1080,128370,91]`、`[1080,129030,86]`、`[1080,130350,71]`、
15分は `[270,33000,92]`、`[270,33000,86]`、`[270,32670,61]`。
先頭下限は0、相対gapは1.0で、全目的の証明は未完了。後段のgapは `null` のまま保存した。
並行探索では同じseedでも時間切れの同率解は同一とは限らず、各値を保持する。
新機能の元不可能性は全3回で維持し、許可案 `restore_one_person` の変更後解は全3回
`OPTIMAL` / `[16,0,240]`。診断はすべて `COMPLETE`、追加検証まで約0.037〜0.041秒だった。

coreのsource tree SHAは `1b4362f993b5acb6e180e8759ebb2a5511377f562d4174b91d9139d86308ccb7`、
runnerは `04dfcc93c92b96d738f272f23c50ececd4576997bb921fcb44ff879c9a7412f5`、
lockは `ca6e4dfa241cdb48cc75a22fe4371877a59a8ed4237e2939f5ea545d253de488`。
package版0.1.3と契約版0.1/0.2は区別する。通常・拡大・15分の原本は5秒、新機能の原本は10秒のままで、
実効の30秒だけを `solver_request` と条件欄へ記録し、原本の入力SHAは保持した。

最終冷起動の開始時に通常入力のパスを誤指定した実行は保存前に中断した。
[中断台帳](results/2026-10-06-final-cold-input-path-error.json)に実行コマンド・誤/正パス・exit130を残し、
取得できなかった件数・時間・RSSを `null` とした。正しい入力の反復とは別の実行記録であり、未取得値を補完しない。
全測定後の2026-10-06T06:13:32Zには評価runnerの残存プロセスがないことを確認した。
中断時の子プロセス一覧は取得しておらず、この事後確認から測定中のホスト専有は主張しない。

実測はロックに合わせて同期済みの環境で `uv run --no-sync` を使用した。
以下は同じロックと追加依存を準備する再現用コマンドである。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-fortnight-large.json --repeat 3 --time-limit-seconds 30 --timeout-seconds 60 --source-ref 3e19b0c0edf6507237dc30de92041c0af6af733c --output docs/evaluations/results/2026-10-06-before-large-30-cold.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json docs/evaluations/inputs/roster-fortnight-large.json docs/evaluations/inputs/roster-week-15min.json docs/evaluations/inputs/roster-extended.json --repeat 3 --time-limit-seconds 30 --timeout-seconds 60 --source-ref b6128903668095297cdb03a8be95a5d738ae8e6b --output docs/evaluations/results/2026-10-06-final-cold.json
```

[最終並行測定](results/2026-10-06-final-parallel.json) は通常/40人14日の各2試行、Pythonプロセス上限2、各CP-SAT worker2とした。

| 入力 | 検証済み解 | request平均 / 中央 / p95=最大 秒 | RSS最大 MiB |
| --- | --- | --- | --- |
| 20人7日 | 2/2 | 30.498 / 30.498 / 30.504 | 246.172 |
| 40人14日 | 2/2 | 30.970 / 30.970 / 30.977 | 688.406 |

全4試行は `FEASIBLE`、通常の値は `[270,33000,87]` / `[270,32670,12]`、
40人14日は `[1080,131340,71]` / `[1080,130020,77]`。先頭gap1.0、後段gapはnullを維持した。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/roster-week.json docs/evaluations/inputs/roster-fortnight-large.json --repeat 2 --processes 2 --time-limit-seconds 30 --timeout-seconds 60 --source-ref b6128903668095297cdb03a8be95a5d738ae8e6b --output docs/evaluations/results/2026-10-06-final-parallel.json
```

採用した全試行の解獲得・通常の目的値条件を満たし、時間・RSSも評価目安内だった。
追加のworker4、独自の探索方式、キャッシュサービスは追加しない。
合格はこの架空入力・候補集合・OS/CPU・粒度・目的順序と予算に限定する。
実データ、異なる技能偏在/期間/目的順序、ホスト全体の専有、他OS/CPUの性能保証は含まない。
