# 契約0.15の結合受け入れ

この記録は[#105](https://github.com/omitsuhashi/schedula/issues/105)の全機能維持と旧契約終了を判定するためのものです。
通常契約は0.15、配布版は0.2.0、Adapter/manifest/record形式は1.0です。
現在の仕様は[現行契約](../io-contract-current.md)、対応方針は[サポート方針](../contract-support.md)を参照します。
棚卸し・一回限りの移行・入口準備・候補アプリ受け入れの原証拠は上書きしません。

## 範囲と引き継ぐ証拠

責任者は所有者`@omitsuhashi`、確認した利用側はschedulaとschedula-appです。
所有者がリポジトリ内の例・テスト以外に保存済みJSON/SQLiteはないと回答したため、今回の変換対象はその範囲です。
旧0.1〜0.14の代表16組の原/移行先SHAは[比較台帳](contract-0.15-cases.json)、
Request/解/基準・Draft/recordの意味と原本保護は[切替記録](contract-0.15-integration.md)、
DB Schema 1/2の候補往復は[アプリ先行受け入れ](contract-0.15-app.md)に保持しています。
一時変換コード・専用試験・旧fixtureは、これらの確認後に承認に従って撤去しました。
過去の変換資材は固定commit `d17a036a9790999c8182cdd319473d32368ddaec` のGit履歴を参照します。

## 全機能と現在の検証先

下表は[棚卸し対応表](contract-0.15.md)の全業務行と、契約外の公開機能を照合したものです。
実装は`src/shift_schedula/`、回帰は`tests/`、入力は`examples/`・`tests/fixtures/contract-015/`にあります。
すべて0.15で求解・独立検証する経路を持ち、旧形式の受理で代用しません。
利用側はAPI/CLI/デモ・型付き例を維持し、アプリは公開エンジンのRequest/Responseと全summaryを保存・表示します。

| 導入時の機能 | 現在の主な回帰・利用例 |
| --- | --- |
| 0.1 担当配置・資格・需要・加算選好・flow | `test_assignment/test_cp_sat/test_verification/test_objectives`、`assignment.json`。完全充足は明示下限でbaseを維持 |
| 0.1 候補・テンプレート・休憩・勤務ルール | `test_roster/test_roster_contract/test_roster_verification/test_input_contract`、`roster.json`。segmentsと明示履歴で同じ条件を保持 |
| 0.2 夜勤・分割・履歴 | `test_extended_roster`、`overnight.json/split_roster.json`。全探索・DST・原区間・勤務日を保持 |
| 0.2 目標・公平性 | `test_extensions/test_combined`、`fairness.json`。明示0と対象外・目的順を保持 |
| 0.2 基準・固定・変更最小化 | `test_extensions/test_overlap_replanning`、`replan.json`。元Request/解・原W・固定を保持 |
| 0.2 診断・変更案 | `test_diagnosis`、`diagnosis.json`。許可範囲・独立検証・原需要を保持 |
| 0.3 不足・PARTIAL・不足最小性 | `test_partial_plans/test_partial_contract`、`partial_roster.json`。元required_peopleと証明範囲を保持 |
| 0.4 期間別勤務量・希望日時 | `test_contract_04`、`roster_conditions.json`。上下限と希望/必須条件を区別 |
| 0.4 未完成基準・公開verify/make_baseline | `test_contract_04/test_public_api`、`partial_replan_preserve_assigned.json`。担当済み固定・空欄・反復保存を保持 |
| 0.5 需要priority | `test_demand_priority`、`demand_priority.json`。不足総量→各群→利用者目的の順 |
| 0.6 実績・確定勤務・文脈期間 | `test_continuity`、`continuity_month.json`。原区間・投影・確認済み履歴を保持 |
| 0.7 移動W・重複部分の再計画 | `test_overlap_replanning`、`continuity_replan.json`。元基準を切り詰めず検証 |
| 0.8 矛盾縮小 | `test_conflict_refinement`、`conflict_refinement.json`。背景・包含極小性・UNKNOWNの意味を保持 |
| 0.9 費用・指定区間偏差 | `test_roster_metrics`、`scheduled_cost.json/duty_balance.json`。明示整数・待機・休憩を保持 |
| 0.10 履歴付き偏差 | `test_continuity_duty_balance`、`continuity_duty_balance.json`。実績/確定/選択を一度ずつ集計 |
| 0.11 日数・完全休日 | `test_day_counts`、`day_counts.json`。勤務日・占有日・完全休日を区別 |
| 0.12 必須最低人数 | `test_minimum_demand`、`minimum_roster.json`。省略0・正下限・PARTIAL診断案を保持 |
| 0.13 勤務分類・4種類のパターン | `test_shift_patterns`、`shift_patterns.json`。余白不足の拒否・原勤務分類を保持 |
| 0.14 同時勤務 | `test_coworkers`、`coworkers.json`。待機込み・休憩/分割間なし・確定勤務を保持 |
| 0.15 履歴付き勤務回数・全機能併用 | `test_shift_counts/test_added_conditions/test_contract_015_regression`、`shift_count_balance.json`、100人30日の固定4入力 |
| 厳密JSON・型・API/CLI・失敗応答 | `test_input_contract/test_public_api/test_cli/test_response_initialization/test_single_contract/test_demo`。原入力非変更・全旧版/未知版/欠落拒否 |
| 期限・取消・CPU・logging・並行実行 | `test_execution/test_timezone`。既存のspawn・tzdataとOS行列を維持 |
| wheel/sdist・base/cp-sat | `test_cli/test_sdist/test_public_api`。5 Schema・py.typed・LICENSE/依存表示を保持 |
| 分割入力・確認・記録・再検証・表示 | `test_adapter/test_execution`、実Chromium。日付自動移動なし、revision確認失効、run_idと現在verifyの分離 |

## 整理前の0.15の保持と旧版拒否

整理前後の0.15のRequest/Response/Solution/Verification Schemaは内容が一致します。
省略minimum_people=0、priority=0、空配列/null、目的順、原区間・元基準、証明済み接頭辞を維持します。
元Responseの最適性・不足最小性を現在verifyへ転記しません。
通常API/CLI/Adapter/Schema/型/デモ/wheelは0.15のみで、失敗応答も現在の構造とnull集計を保ちます。
求解後の独立検証失敗はINTERNAL_ERROR・performed=true/valid=falseと非空の違反詳細を保持し、解を表示しません。
実行コード検索で残る`roster.py`の`"0.2"`は既存候補IDのハッシュ名前空間です。旧版の実行経路ではありません。

## 固定成果物

[成果物台帳](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-artifacts.json)に構築条件・wheel/sdist/lockのSHAを記録します。
固定ソースはPR #156の`6f96300dc6830f1132c1c6330b1ed5e2f27288b0`です。
`SOURCE_DATE_EPOCH=1791556851 uv build --wheel --sdist`で2回のクリーン構築を行い、wheel bytesの一致を確認しました。
wheel SHA-256は`f011b1af77535739dfd36899af4011d31d5f906a8a20efa65653f618f2ad48c6`です。
sdist・wheelの通常Schemaは0.15とAdapterの5ファイルだけで、公開型・py.typed・LICENSE/依存表示を保持します。
PyPI、GitHub Release、リポジトリ公開化、実顧客への配備は今回の作業範囲に含めません。

## 同条件の性能・解品質判定

固定基準は[回帰基準](contract-0.15-regression.md)、基点は`bbb7a93b757cc3272943bbc09f9f2dcb359bd457`です。
同じmacOS ARM64・8 CPU・Python 3.14.8・OR-Tools 9.15.6755、seed=0、worker=2、探索30秒、総期限120秒で、
変更していない100人30日の通常/PARTIAL/必須矛盾/微小期限をcold/warm各3回比較しました。
依存版・runner・入力・目的順・制約・不足・独立検証・証明範囲を照合しています。

[初回cold](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-regression-after-cold.json)は全基準内でした。
[初回warm](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-regression-after-warm.json)の通常勤務数偏差中央値434は上限382を超えました。
この失敗を保持し、4入力の[CPモデルと目的式](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-model-comparison.json)が基点とbyte単位で同じことを確認しました。
探索パラメータと実行コードを変更せず、同じ環境で基点/変更後を組にして再測定しています。
[最初の組の基点](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-recheck-before-warm.json)は初回OR-Tools読込に35秒を要し、3回全体の120秒期限で中断しました。
[同じ組の変更後](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-recheck-after-warm.json)も中央値404で不合格でした。
この組を捨てず、3回完了する組を再測定した結果、[基点](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-recheck2-before-warm.json)は438、
[変更後](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-recheck2-after-warm.json)は372で、変更後が元の上限382を満たしました。
有限予算・2 workerの解品質の揺れが基点でも生じており、最適性未証明の配置差を目的式変更の証拠とは扱いません。

[判定台帳](https://github.com/omitsuhashi/schedula/blob/main/docs/evaluations/results/contract-015-regression-acceptance.json)は、warm通常の再測定を明示して採用し、他7組は初回結果で判定します。
基準・入力・探索予算は緩めていません。変更後の通常/PARTIALは各3/3有効、通常の不足0・勤務540,000分、
PARTIALの不足2,211,750人分以下・勤務668,250分以下・同値時の回数偏差309以下を満たしました。
実行時間中央値/最大、RSS中央値/最大、外側期限、INFEASIBLE/UNKNOWNの状態も事前基準内です。
最終成果物の実行ソースhashは測定時と同じ`4d44c7cfd56bf4cf188a28b41b21d43d120baa0eca67694ae6ec11d15d82e78f`です。
合成入力の測定であり、実店舗性能や全目的の最適性を保証する結果ではありません。

## 最終検証の記録

切替時の手元全体は2,149 passed + 6 subtests、failure/error/skip 0です。
公開境界193件、Ruff/pre-commit・mypy strict・bash構文・相対リンクも成功しています。
最終レビュー修正後のエンジン実Chromiumは10 scenarios / 21 interactions / 26 response samples、page errors 0でした。
最終ソースの隔離配布は`test_sdist/test_public_api/test_cli`の26件、361.63秒、failure/error/skip 0で成功しました。sdistから元checkoutなしでwheelを再構築し、同梱業務回帰・相対リンクも検査しました。

## アプリの最終受け入れ

アプリ変更は[schedula-app PR #34](https://github.com/omitsuhashi/schedula-app/pull/34)です。
固定wheel・OpenAPI・全生成/保存/復元/Query/比較/採用・画面・現在手順を0.15へ揃えています。
DB Schema 2 / schedula-app/2、session/version/planとrequest/runの責務、楽観競合・不変の案を維持します。
候補3代表の原evidenceとRequest/解・日付・Draft/未検証editを保持し、最終pinで現在verifyしました。
[受け入れ台帳](../evaluations/contract-015-final/acceptance.json)はbackend 189件・front 4件、failure/error/skip 0、
Ruff/Biome/型/build・SQLiteバックアップ/実HTTP再起動・顧客分離の成功を記録します。
[built](../evaluations/contract-015-final/browser.json)と[Vite](../evaluations/contract-015-final/browser-dev.json)の実Chromium各35項目、page errors 0、
[Linux SSH運用](../evaluations/contract-015-final/customer-operations.json)8項目も成功しました。
旧版/未知版/欠落/型不正・旧pin・解改ざん・元record付替え・保存/入力の競合は、原本・既存セッションを変更せず拒否します。
入力/編集→実計算→月次/個人別/比較→採用→保存/再起動/復元→再検証/固定・全体再計画と、
Draft確認→記録→保存/再読込/現在verifyを実エンジンで通しました。
app #30の未完了機能全体を追加・完了したとは扱いません。

## mainと必須CIの確認

エンジンPR #156はmain `7801c83f44ff621c0bffdb39dc0a299f3889b791`へ反映済みです。
固定成果物のソースcommitはsquash前のレビュー済みheadで、mainとの実装・Schema・型・例・テスト・lockの差はありません。
[PRの必須CI全5ジョブ](https://github.com/omitsuhashi/schedula/actions/runs/37946021448)は成功し、全体2,149件＋6 subtests・skip 0、
Linux/Windowsのbase/cp-sat各89件、隔離wheel/sdist・型・実Chromiumが通りました。
所有者はローカルの同等CI成功を今回の必須CI成功として承認しています。GitHub Actionsの結果とは区別して記録します。
アプリの[GitHub CI 37947939047](https://github.com/omitsuhashi/schedula-app/actions/runs/37947939047)は検査開始前に失敗し、worker stepは0件です。
アプリmain `d95b10fadeff37d4a47d0ebde4efd32b18d093e9`へPR #34を反映済みです。mainの[CI 37948155349](https://github.com/omitsuhashi/schedula-app/actions/runs/37948155349)も支払い・利用上限で検査開始前に停止しました。アプリは上記すべてのローカルCI相当検査を成功させた結果で受け入れます。エンジンの最終main CIは確認後にIssueへ記録します。

