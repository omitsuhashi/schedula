# 契約0.15への移行を判定する回帰基準

[Issue #107](https://github.com/omitsuhashi/schedula/issues/107) の成果として、
[機能対応表](contract-0.15.md)の業務挙動を保持する比較入力と判定方法を固定する。
通常入口の旧版受付、求解・独立検証、公開型、デモはこの変更では整理しない。
全テストの移行は各実装変更と #124、旧版拒否への切替は #111 で行う。
#106 の実保存データ確認は別の未解決事項であり、この基準の追加を実データ移行完了とは扱わない。

## 二つの比較

旧版からの意味の移行と、現行0.15の維持を別々に判定する。
前者は0.1/0.2の完全充足を明示下限へ移し、候補・履歴の形状を変更する。
後者では0.15の省略下限0、priority省略0、空配列/null、目的順、各尺度、証明の意味を変更しない。
#108 で完全充足の独立assignmentをflowへ補完する変更だけは、backend能力の意図した追加として判定する。

比較の基点は `bbb7a93b757cc3272943bbc09f9f2dcb359bd457`、配布版0.1.6、既存の `uv.lock`。
当時のソース・lockはGit履歴を参照し、旧環境の保存・復旧を常設検証しない。
同率解では担当者・配列順・候補選択の全一致を求めず、必須条件、目的配列の順番と値、
不足量、証明済みの目的の接頭辞、不足最小性、公開verifyによる有効性を比較する。
verifyが最適性を付与しないことも確認する。

## 固定した代表入力

[比較fixture](../../tests/fixtures/contract-migration/cases.json) は0.1〜0.14の全版を含む16組。
各 `.legacy.json` は基点examplesの原bytes、`.015.json` はレビュー可能な明示した比較入力である。
原SHA・移行先SHA・由来・旧版を対応付け、原本のexamplesを更新しても旧代表を失わない。
テストで両fixtureの原bytesのSHA-256を記録値と照合し、比較基準の意図しない変更を検出する。
これは移行処理の実装ではなく、#109 が実装する変換の期待入力としても使う。

| 導入版 | 代表 | 維持する条件・観察 |
| --- | --- | --- |
| 0.1 | assignment、roster | 資格・加算選好、完全充足、候補・テンプレート・休憩・勤務量・休息・連勤 |
| 0.2 | overnight、replan | 夜勤、原勤務日、明示履歴、公平性、埋込基準と固定、変更最小化 |
| 0.3 | partial_roster | 元必要人数を減らさない不足、選好より先の不足最小化 |
| 0.4 | partial_replan_preserve_assigned | 未完成の基準、担当済み枠の固定、空欄を埋める再計画 |
| 0.5 | demand_priority | 不足総量を先に固定し、priority群順に比較 |
| 0.6 | continuity_week | 確認済み実績・確定勤務、文脈期間、原区間と休憩 |
| 0.7 | continuity_replan | 重複期間だけの比較と固定、期間外の原情報 |
| 0.8 | conflict_refinement | 背景条件を保持した不可能性診断と矛盾縮小 |
| 0.9 | scheduled_cost | 明示整数単価、費用と選好の目的順 |
| 0.10 | continuity_duty_balance | 実績・確定勤務を含む指定区間の目標分数偏差 |
| 0.11 | day_counts | 勤務日・占有日・完全休日の区別 |
| 0.12 | minimum_roster | 必須最低人数と、下限を超える不足許容 |
| 0.13 | shift_patterns | 明示分類、原勤務、余白、4種類の勤務パターン |
| 0.14 | coworkers | 同時勤務の必要条件・禁止、待機・休憩・分割間の区別 |

0.1/0.2の全需要には `minimum_people = required_people` を明示する。
0.3以降の省略下限には新しい必須人数を追加しない。
0.1 rosterの空履歴にだけ `last_work_day: null` を追加し、不明な勤務日を推測しない。
この代表に非nullの0.1履歴はない。未確認履歴を止める移行処理と失敗試験は #109 の責務である。

0.1テンプレートを0.15のsegment_optionsへ機械的に変えると生成IDのハッシュ入力が変わる。
rosterの比較入力は旧テンプレートで生成した有限候補を旧IDの明示候補へ展開し、
生成後の候補集合・原区間・休憩・勤務可能時間による絞り込みを保持する。
この代表では旧新の候補ID・勤務日・区間・休憩・勤務枠が一致することを確認する。
0.1の不正テンプレートを新しい形状で救済しない検査は #109 に引き渡す。

## 共通fixtureと既存テストの行先

#124の勤務計画・Adapterの利用例は、入れ子基準を含めて0.15へ移した。
変更条件、業務回帰の行先、原SHA/更新後SHAと後続作業は
[利用入口の準備記録](contract-0.15-entrypoints.md)を参照する。
旧0.3の受理範囲と診断移行を意図的に確認する試験は原bytesのlegacy fixtureを明示参照する。
共通fixture・残る通常回帰と評価再実行入力の全面切替は後続の変更で行う。

`assignment_request015` は固定した完全充足の担当配置。
`tests.roster_support.request015` はsegmentsと明示空履歴を持つ0.15勤務計画で、需要下限は既定0。
完全充足を検証する呼び出し側だけが `tests.support.require_complete_demand` を使う。
`assignment_request` の通常利用は同じ0.15の完全充足fixtureへ移した。
技能・需要競合・残余経路・加算選好・勤務量/役割切替・独立検証・入力境界・
CLI/API・実行制御・logging・タイムゾーンの回帰は、この共通fixtureを使う。
完全充足の需要を組み直す `tests.test_cp_sat.small_request` は0.15に明示下限を付ける。
需要0への編集は下限も0にし、故意の不足違反は `MINIMUM_DEMAND_VIOLATION` で検出する。
不正な解のSchemaを独立検証した際に不足集計が作れない場合はpriority集計を行わず、
検出した違反と検証済み/無効の結果を保って解を拒否する。

旧版と0.15を比較する明示パラメータは残す。
旧版固有の受理範囲・移行元・各版のSchema/型検査と、後続で移す不足/priorityの回帰は
`legacy_assignment_request` を明示する。`test_partial_plans`、`test_partial_contract`、
`test_demand_priority`、`test_contract_04`、`test_minimum_demand` の旧版部分、
`test_contract_migration` と旧版の条件拒否が該当する。
これらの業務回帰の0.15化と旧版受理の拒否への置換は、対応表の後続責務を維持する。
下限省略/明示0の既定値は `test_current_015_defaults_and_empty_output_structure` が別に検証する。

| テスト群 | 残す業務挙動 | 移す形状・統合できる重複 | 旧版除去後の行先 |
| --- | --- | --- | --- |
| assignment / cp_sat / verification | 全探索、技能AND、二重配置、競合需要、残余経路、加算選好、改ざん拒否 | 完全充足に明示下限。版だけ異なる同じ全探索は0.15へ統合可 | #108/#124。base完全充足・不足許容の両方を維持 |
| roster / roster_contract / roster_verification / extended_roster | 同時最適化、候補展開、待機・休憩、勤務量・連勤・休息、夜勤・分割・履歴 | interval/breaksをsegmentsへ。テンプレートIDの保持と履歴要確認は移行試験 | #109/#124。旧版だけの日跨ぎ拒否は移行元検査へ |
| objectives / extensions / combined | 辞書式目的順、全探索、ソフト目標0と未指定、基準・固定・変更量、証明接頭辞 | 0.1基準の原Request/解を入れ子で明示移行 | #109/#124。各順序・矛盾・改ざんを削除しない |
| partial_plans / partial_contract | 元需要、不足の実経過人分、需要以外の必須条件、未証明解、空解、応答矛盾 | 各不足行へminimum_people=0。初期版の完全充足と統合しない | #124/#111。旧Responseは過去証拠として別保存 |
| contract_04 / public_api | 期間別上下限、勤務希望、未完成基準、preserve_assigned/rebuild、公開verify/make_baseline | 版ごとの同じ候補数・Schema型検査は現行型へ統合可 | #124/#111。型・CLI・入れ子基準を同時変更 |
| demand_priority / minimum_demand | 不足総量→priority群→目的、正の下限、下限違反、予算切れ、許可変更案 | 省略/明示0と正の下限を区別。flowの一般下限対応を追加しない | #108/#124。新backend能力に合わせた試験も同じPR |
| continuity / overlap_replanning | 原区間と勤務日、文脈、実績・確定勤務、重複Wだけの比較 | 版番号だけを変え、原履歴・基準を自動移動しない | #109/#124。DST・期間端・未確認履歴を維持 |
| diagnosis / conflict_refinement | 元条件の不可能性、背景条件、包含極小性、UNKNOWN、明示許可編集 | 完全充足の人数編集と下限の連動、元Responseは証明非転記 | #109/#124。編集・診断の意味を削除しない |
| roster_metrics / continuity_duty_balance | 整数費用、区間和集合、0目標と対象外、原実績の偏差 | 旧版の同尺度を0.15へ。勤務回数へ置換しない | #124。値・目的順・境界・不正の全探索を維持 |
| day_counts / shift_patterns / coworkers / shift_counts / added_conditions | 日数・休日・分類・同僚・回数、余白、履歴、全機能同時利用、原JSONの全探索 | 既存0.15試験はそのまま維持、0.11〜0.14の代表を0.15化 | #124。通常/PARTIAL/必須矛盾/UNKNOWNを別判定 |
| input_contract / schema_encoding / timezone | 厳密JSON、0/null、省略/空、未知項目、重複、非有限数、TZDB・DST・日付境界 | 未対応版・欠落・不正型の拒否を現行0.15でも追加。旧版拒否は後で切替 | #111。旧Schema常設試験だけを終了 |
| execution / logging / cli | CPU指定・spawn・取消・総期限・並行実行、無変更入力、stderr/終了コード | 実行制御と入力境界を旧版と0.15で同じ試験へ渡す | #124/#111。依存不足・内部障害・古い応答を区別 |
| adapter / playground / distribution / sdist | 確認失効・来歴・保存/再検証、HTTP保護、公開型、各OS、実Chromium | Draft/recordは#110、通常例・画面は#124。旧Schema同梱の常設保証だけを終了 | #110/#112/#114。新JSON fixtureをsdistへ同梱 |

新しい [比較テスト](../../tests/test_contract_migration_regression.py) は代表比較と別に、
現行0.15の完全/PARTIAL、原JSONによる全探索と目的順、公開verify・改ざん拒否、
空/nullの出力形、下限・priorityの既定値、UNKNOWN/FEASIBLE/内部障害/依存不足、入力拒否を確認する。
既存の実行制御・入力境界テストにも0.15を加え、spawn・総期限・取消・CPU数・並行実行を実行する。
全探索の期待値は元JSONの候補と配置を列挙する既存コードから求め、モデル係数や求解結果を正本にしない。
版重複の削除時はこの表へ移行先を記録し、未対応ケースの削除・skipで成功にしない。

## 規模比較の条件と事前判定

判定基準日と責任者は2026-10-09、リポジトリ所有者 `@omitsuhashi`。
基点測定後、後続の求解・正規化・検証変更を測定する前に以下を固定する。
速度改善は受け入れ条件にしない。

| 条件 | 固定内容 |
| --- | --- |
| 入力 | `docs/evaluations/inputs/combined-100-30-{normal,partial,conflict,timeout}.json` の原SHA。現行0.15の100人・30日・30分、各入力の条件と目的順を変更しない |
| ソース/依存 | 上記基点commit、既存lock。測定JSONのsource/runner/lock SHA、Python・全依存版を保存 |
| 実行環境 | macOS 26.7.1 arm64、8論理CPU、Python 3.14.8、OR-Tools 9.15.6755。solver seed=0、2 workers、同時測定プロセス1 |
| 予算/期限 | 通常/PARTIALは入力の探索予算30秒、必須矛盾30秒、UNKNOWNは0.000001秒。総期限試験は実行制御回帰で別検証。測定プロセスの外側上限120秒 |
| cold | 毎回新しいPythonプロセス、OSのファイルキャッシュは消さない。各入力3回 |
| warm | 同じPythonプロセス内で各入力3回。1回目と継続2回を分離して保存。上限120秒は3回全体に適用 |
| 時間/RSS | 各試行のrequest_elapsed_secondsとpeak_rss_mib、中央値・最大・nearest-rank p95。warmのRSSは同一プロセスの累積ピークであり、一試行の増分ではない |

基点coldでは通常FEASIBLE 3/3、不足PARTIAL 3/3、必須矛盾INFEASIBLE 3/3、打切りUNKNOWN 3/3。
有効解は全て独立検証成功。通常は不足0・勤務540,000分、回数偏差352〜400、目的の最適性未証明。
不足は2,211,750人分・勤務668,250分・回数偏差309、目的の最適性未証明。
基点の生データは `docs/evaluations/results/contract-015-regression-before-{cold,warm}.json` に保存する。

通常coldの総時間は32.80〜53.10秒（中央値32.81秒）、RSS990〜1,003 MiB。
不足は33.13〜33.15秒、RSS1,362〜1,407 MiB。
初回通常の遅延も除外せず保存する。必須矛盾・打切りは約1.3〜1.4秒、RSS約229/254 MiB。
後続比較はcold/warm・各シナリオを混ぜず、同じ条件で判定する。

warmも全12試行の状態はcoldと同じで、有効解は全回独立検証成功。
通常は32.51〜32.87秒・RSS989〜1,032 MiB・回数偏差354〜382、
不足は32.85〜33.14秒・RSS1,399〜1,506 MiB・偏差309。
継続時の解なしは約1.0秒。各モードの3試行を全て保持して中央値と最大値を比較する。

| 判定項目 | 後続変更を測定する前に固定する許容範囲 |
| --- | --- |
| 有効解 | 通常/不足で各3/3が公開独立検証成功。通常は完全、必須矛盾/打切りは解なし。UNKNOWNを不可能性の証明にしない |
| 不足と目的値 | 通常不足0・勤務540,000分を維持。不足は不足合計≤2,211,750人分、同じ不足なら勤務≤668,250分。上位が同値の場合だけ下位尺度を比較 |
| 回数偏差 | 通常は基点範囲cold 352〜400 / warm 354〜382を固定し、変更後3回の中央値は同モードの基点最大値以下を要求。不足で上位同値なら偏差≤309。未最適化の目的も観察し、退行は調査する |
| 証明範囲 | 基点が証明した不足最小性・目的接頭辞を失わない。未証明のまま最適性を付与しない。小規模OPTIMALの全探索値は完全一致 |
| 総時間 | 各モード/入力で中央値≤基点中央値×1.25、最大≤max(基点最大×1.25, 基点中央値+20秒)。加えて通常/不足は全試行70秒以内、解なしは10秒以内 |
| RSS | 各モード/入力でピーク中央値≤基点中央値×1.20、最大≤基点最大×1.20。加えて通常1,700 MiB、不足2,400 MiB、解なし400 MiB以内 |
| 超過 | 自動合格にしない。同環境で基点と変更後を連続3回ずつ再測定し、負荷・モデル準備・探索・検証・importを分離して調査。許容値変更・退行受け入れは所有者が根拠と残る影響を記録して決定 |

同率解の配置順は比較しない。2 workersの未証明の解品質は揺れるため、基点の範囲を使う。
これは架空入力の同条件比較であり、実店舗の性能・不足最小性・全目的最適性の保証ではない。
基点と変更後の環境・依存版・worker数が違う場合は同じ比較として合格にしない。
#116 はこの条件、原SHA、基点記録、全機能対応表、全CI/main・実Chromiumの証拠を引き継ぐ。

```sh
uv run --locked --extra cp-sat python scripts/evaluate.py \
  docs/evaluations/inputs/combined-100-30-normal.json \
  docs/evaluations/inputs/combined-100-30-partial.json \
  docs/evaluations/inputs/combined-100-30-conflict.json \
  docs/evaluations/inputs/combined-100-30-timeout.json \
  --repeat 3 --source-ref bbb7a93b757cc3272943bbc09f9f2dcb359bd457 \
  --timeout-seconds 120 --output test-results/contract-015-before-cold.json
# warmは同じ入力・sourceで --mode warm を追加する。
# 後続変更は対応する固定commitとlockで別出力へ測定する。
```

## この変更の検証と残る作業

追加・変更テスト、既存全体回帰、Ruff/pre-commit、隔離wheel/sdist、公開型、実Chromium、
Linux/Windowsのbase/cp-sat CIを維持する。今回の実行結果と最終commitはPRへ記録する。
通常入口の旧版拒否、明示移行処理、保存記録の確認失効、アプリ保存往復、最終配布版は後続Issueの責務。
旧版除去のゲートは [機能対応表](contract-0.15.md)のまま維持する。
