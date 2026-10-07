# 利用入口・CI・実行評価の記録

2026-10-06、Issue #10 を schedula 0.1.3 / JSON 契約0.1で検証した。
エンジンの条件・Schema・目的順序は変更せず、利用手順・継続検証・評価用の入口を整備した。
参照 ZIP の原本と過去の結果は今回の実測に混ぜていない。

## 導入と利用入口

[README](../../README.md)に、clone から uv による導入、コピーできる完全な Request、
ライブラリ・CLI・標準入力・Schema、解・診断・目的値・証明範囲、全状態の扱いを記載した。
[不可能例](../../examples/infeasible.json)は勤務可能な従業員がいない入力、
[不正入力例](../../examples/invalid-input.json)は未登録の役割を参照する入力である。
それぞれ `INFEASIBLE` / `INSUFFICIENT_QUALIFIED_EMPLOYEES`、
`INVALID_INPUT` / `UNKNOWN_REFERENCE` と終了コード2を返す。

この worktree に `.venv` がない状態から `uv sync --locked --extra cp-sat` で同期した。
wheel のテストではソース checkout を import せず、lock file から取り出した実行依存と wheel を
新しい uv の隔離環境へインストールする。担当配置の2例・勤務計画・不可能・不正入力を
ライブラリと CLI の両方で実行し、Response Schema・検証結果・目的値・終了コードを確認する。
もう一つの空環境では wheel の `cp-sat` extra だけをインストール対象とし、lock file の実行依存を
constraints として渡す。制約の記載だけでは依存をインストールせず、wheel の `Requires-Dist` に
導入を委ねる。両環境で同じ利用例を確認し、wheel の依存宣言の欠落も検出する。
OR-Tools がない別の隔離環境でも、最小費用流の `OPTIMAL` と
CP-SAT の `BACKEND_UNAVAILABLE`、非対応方式の `INVALID_INPUT` を確認する。
README の完全な JSON もテストで読み取り、記載した配置と目的値を確認する。

## 継続する中核検証

既存の `deploy-entrypoint` に CP-SAT 導入下の全テストを維持する。
pytest の `-ra` で失敗・スキップ理由を表示し、JUnit XML に成功・失敗・収集エラー・スキップを保存する。
後続の確認で `<skipped>` が一つでもあれば CI を失敗させる。
`pytest-results` artifact は成功・失敗時とも保存し、実行 URL と結果は PR に記録する。
依存読み込み失敗はテスト収集エラーとして失敗する。

| 対象 | 継続実行する検証 |
| --- | --- |
| 独立した担当配置 | 150入力を各バックエンドで全探索と比較し、最適値と不可能性を照合する |
| 時間横断配置 | 80入力を独立した全探索と照合し、担当時間・担当切替・目的順序を確認する |
| 勤務計画 | 60入力の候補選択・配置を全探索と照合し、目的順序の全6通りも確認する |
| 独立検証器 | 技能・二重配置・不足・過剰・休憩・勤務ルール・目的値を壊した解の公開を遮断する |
| 状態と予算 | `FEASIBLE` の証明範囲、`UNKNOWN`、既知解の保持、内部障害、共有探索予算を確認する |
| パッケージ | wheel の同梱 Schema、隔離導入後のライブラリ・CLI、依存不足を確認する |
| 利用・評価手順 | README の入力、別プロセスの測定、環境・入力ハッシュ・時間・RSS・候補数を確認する |

意図的に1件スキップする一時テストでも、pytest 自体の終了コード0に対し、
JUnit 確認が終了コード1で拒否し、スキップ理由をログと XML に残すことを実測した。

## 評価条件と環境

想定する実務規模は未確定である。次の週単位入力は性能を調べるための**提案値**であり、
実在の従業員データ、実務での推奨条件、法令・就業規則の基準ではない。
保存した JSON をそのまま再実行でき、各測定の SHA-256 で入力の一致を確認できる。

- [担当配置・30人・7日](inputs/assignment-week.json): 調理技能10人・接客技能10人・技能条件なし10人。
  毎日10:00〜16:00に調理・ホール・皿洗い各8枠を要求し、技能者の皿洗いを1分1で評価する。
  明示制約なし、選好ペナルティを最小化する。最小費用流と CP-SAT に同じ入力・5秒予算を渡す。
- [勤務計画・20人・7日](inputs/roster-week.json): 調理・接客・補助・両技能の各5人。
  毎日10:00〜16:00に各役割3枠を要求する。6時間勤務・30分休憩の位置4通りから560候補を生成する。
  全員の計画前履歴は明示的な空履歴。勤務量上限1650分・休息600分以上・連勤5日以下を指定し、
  選好ペナルティ → 勤務量 → 担当切替の順に最小化する。共有探索予算は5秒。

全入力は3役割・30分粒度・`seed: 0`。CP-SAT の worker 数は既存実装の1である。
小規模例の探索予算は10秒。入力期間と候補数は下表に示す。

実行環境は macOS 26.7.1 ARM64 / Apple M1 / 8論理コア / 16 GiB メモリ、
CPython 3.14.8 / uv 0.12.23。jsonschema 4.26.0 / OR-Tools 9.15.6755 / pytest 9.1.1 /
Ruff 0.16.10 / pre-commit 4.6.2 を使用した。全依存版は結果 JSON の `environment.packages` に保存する。

## 測定方法と再実行

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python scripts/evaluate.py examples/assignment.json examples/linked_assignment.json examples/roster.json docs/evaluations/inputs/assignment-week.json docs/evaluations/inputs/roster-week.json --output test-results/auto.json
uv run --locked --extra cp-sat python scripts/evaluate.py docs/evaluations/inputs/assignment-week.json --backend cp_sat --output test-results/cp-sat.json
```

`scripts/evaluate.py` は入力ごとに新しいプロセスを起動し、`time.perf_counter()` で `solve` の呼び出しを測る。
構造・意味検証、正規化、候補展開、CP-SAT の依存読み込み、モデル構築、探索、解・Response の検証を含む。
プロセス起動、ファイル読み取り・JSON の読み取り、schedula 自体の import はこの時間に含まない。
エンジン内部の `stats.elapsed_seconds` と、`SEARCH_STATS` の探索時間も保存する。

メモリは測定終了時の `resource.getrusage(RUSAGE_SELF).ru_maxrss` を MiB に換算する。
macOS はバイト、Linux は KiB として扱う。プロセス開始からのピーク RSS であり、
Python・JSON・依存・ネイティブの OR-Tools を含む。エンジンだけの増分メモリではない。
条件集計のための再正規化は測定値を取得した後に行う。
親プロセスや別入力の過去のピークを混ぜず、`tracemalloc` だけでネイティブメモリを測ったとは扱わない。
評価対象は正規化できる入力で、ファイル・JSON・正規化のエラーは非ゼロ終了となる。

各コマンドの測定は入力あたり1回で、最適値・解の有効性・性能を分けて記録する。
新しい評価結果では、測定開始前にスクリプトが置かれた checkout の `source.commit`、
`source.dirty`、`source.uv_lock_sha256` を記録する。呼び出し元の作業ディレクトリには依存しない。
`dirty` は Git の追跡済み変更と非無視の未追跡ファイルの有無であり、未コミット内容そのものの識別ではない。
以下の既存の測定 JSON は追加前の記録として保持し、当時記録していない source 情報は後付けしない。
`--backend` は入力の backend だけを変更し、有効な指定を `solver_request` に保存する。
結果は [auto の再測定](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-auto.json) と
[共通問題の CP-SAT](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-cp-sat.json)に保存した。

## 観測結果

| 入力・方式 | 人数・期間 | 時間枠・候補 | 状態 | 目的値（配列順） | 総時間（秒） | ピーク RSS（MiB） |
| --- | --- | --- | --- | --- | --- | --- |
| 担当配置例・最小費用流 | 3人・2時間 | 4・0 | `OPTIMAL` | 0 | 0.037 | 32.2 |
| 時間横断配置例・CP-SAT | 3人・2時間 | 4・0 | `OPTIMAL` | 0 | 0.255 | 101.6 |
| 勤務計画例・CP-SAT | 4人・2日 | 96・32 | `OPTIMAL` | 60・2640・0 | 0.323 | 109.3 |
| 週単位担当配置・最小費用流 | 30人・7日 | 336・0 | `OPTIMAL` | 0 | 0.116 | 35.2 |
| 同じ週単位担当配置・CP-SAT | 30人・7日 | 336・0 | `OPTIMAL` | 0 | 0.335 | 110.6 |
| 週単位勤務計画・CP-SAT | 20人・7日 | 336・560 | `FEASIBLE` | 630・32670・83 | 5.418 | 191.0 |

すべて `verification.performed: true` / `valid: true` / 違反0件だった。
最初の5行は指定した目的をすべて証明済み。最後の行は必須条件を満たす解を得たが、
先頭目的の最適性を証明できず、3目的すべて `proven_optimal: false` である。
勤務計画の探索は約5.009秒、入力検証・構築・結果検証を含む総時間は約5.418秒となり、
探索予算が外部応答期限ではないことも確認できた。
両方式の共通問題では検証成功・最適値0が一致した。同率解の担当そのものの一致は要求していない。

[初回測定](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-initial.json)も保存した。
wheel の隔離導入テストと並行していた初回の時間横断配置例は総時間36.748秒・探索約0.002秒だった。
他の検証を終えて順に再測定した同じ入力は0.255秒で、探索以外に大きな遅延があった。
依存読み込み・構築などの個別時間や遅延の原因は切り分けていない。
初回値を削除したり、再測定の速い値だけをすべての環境の性能として扱ったりしない。

## 検証範囲とマイルストーン

検証コマンドは `uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml`、
Ruff の lint・format、`bash -n scripts/deploy`、`git diff --check`。
導入時の全テストは802件と subtest 6件成功、失敗・スキップ0件、47.55秒だった。
wheel の依存宣言と評価の source 記録の検証を追加した後は、803件と subtest 6件成功、
失敗・スキップ0件、66.17秒だった。対象テストは23件成功、55.31秒だった。
Ruff の lint・format も成功した。GitHub CI の実行 URL・結果は PR に記録する。

マイルストーン「検証済みの担当配置・勤務計画をライブラリと CLI で生成する」の
先行 Issue #5〜#9 は終了済みである。今回、確定 JSON から担当配置・勤務計画の検証済み解、
目的値・状態・診断をライブラリと CLI で返すこと、クリーンな導入、CI と再実行できる評価を確認する。
Issue #10 の PR merge 後に Issue が閉じることと、これらの実装・検証の完了は別に確認する。

測定した入力・環境・単発実行の範囲であり、実務の性能保証、平均・分位点・最大所要時間、
複数プロセスの競合、技能偏在・大規模候補・15分粒度・長期間・その他の目的順序の性能は未測定である。
HTTP の隔離・期限・キャンセル、Windows 本体、PyPI・Web UI・外部 API・LLM・production デプロイは対象外。
夜勤・公平性などの拡張と公開条件は [開発・検証方針](../development-policy.md)に残す。
