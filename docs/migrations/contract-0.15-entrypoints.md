# 利用入口を0.15へ移す準備の記録

[Issue #124](https://github.com/omitsuhashi/schedula/issues/124) の勤務計画・Adapterの変更。
基点は `0d17150b52567e4dff6850d38c7bd7dcd72d8f57`（PR #144）、配布版0.1.6、既存 `uv.lock`。
旧版の通常受付・Schema・公開型・求解・独立検証は引き続き維持する。
旧版除去は #124 の残りの準備と #125 の保存往復の受け入れ後に #111 で行う。

## 変更する意味と維持する条件

既存の `scripts/migrate_contract.py:migrate_request` と
`scripts/migrate_adapter.py:migrate_draft` で明示変換し、利用例のJSONを更新した。
0.1/0.2の完全充足には `minimum_people = required_people` を明示し、診断の人数編集には
同じ下限編集を結び付けた。0.3以降の不足許容には新しい下限を追加していない。
入れ子の `baseline.source_request` と元期間の解を一緒に移し、日付・原区間・休憩・固定・目的順を保つ。
`roster_conditions.solution.json` は旧新の公開verifyでVALIDを確認し、内容を変更していない。
不正入力例は0.15でも同じUNKNOWN_REFERENCEで拒否する。

0.1の勤務テンプレートは32件の元ID付き明示候補へ展開した。
翌週の正常例も、その週に明示した日付で32件へ展開する。古い週の例は古い区間を保持して
STALE_APPLICABILITYで停止する。日付の自動移動は行わない。
JSONの増分はこの候補列挙によるもので、汎用変換器や新しい生成機能は追加しない。

Adapter例の確認は作成時に移行前後の条件を照合し、以前確認済みだった箇所だけを明示確認した。
未確認例はbasicの未確認と未解決項目を保つ。翌週で失効するperiod/history、
変更しないbasic/common/execution、元履歴保持を引き続き検証する。
これは確認の自動引き継ぎを緩める変更ではない。一般の移行処理は変更せず、
変更された入力元の確認失効を既存の移行試験で検証する。

## 回帰の行先

[回帰基準の機能対応表](contract-0.15-regression.md#共通fixtureと既存テストの行先)に従う。

| 検証内容 | 今回の行先 |
| --- | --- |
| 全現行JSONと入れ子基準の0.15検証・不正例拒否 | `test_playground_scenarios.test_current_examples_use_015_including_baselines` |
| 同時最適化・候補ID/休憩・夜勤・分割・履歴・公平性・変更最小化 | 既存 `test_roster` / `test_extended_roster` / `test_extensions` / `test_objectives` が更新例を実行 |
| 不足・priority・必須最低人数・日数/休日・パターン・同僚・回数 | 既存の各業務テストが更新例を実行し、既存0.15試験も維持 |
| 実績・確定勤務・移動期間の基準・費用と目標分数 | 既存 `test_continuity` / `test_overlap_replanning` / `test_continuity_duty_balance` / `test_roster_metrics` |
| 未確認・翌週失効・確定Request一致・記録保存/現在verify・基準/再計画 | 既存 `test_adapter` と追加の全Draft例確認、実Chromium |
| 明示移行と旧0.3の受理範囲 | `tests/fixtures/contract-migration/*.legacy.json` を明示参照。通常例へ旧版形状を戻さない |
| HTTP/CLI・隔離wheel/sdist・公開型・失敗応答の表示 | 既存server/CLI/distribution試験と `playground-browser.cjs`。0.15の解なし応答は全追加summaryをnullにして元の失敗検証を維持 |

旧0.3の受理範囲と完全充足の診断移行に必要なdiagnosis/fairness/split_rosterだけは、
基点の原bytesを移行fixtureへ分離した。既存の旧版代表・原SHAと業務テストを削除していない。
これらの移行専用fixture/試験は、#125の検証後に #111 の最終切替で撤去する。
共通fixtureの全面移行、残る通常回帰の形状整理、評価再実行入力・設計例は #124 の後続変更で扱う。
#112では旧版除去後の全入口・旧版拒否・全画面回帰を最終確認する。

## 勤務計画の共通fixtureと通常回帰

基点 `4cdb5a3fbd15f3ee4153dd65c81a7aea2ec4eef7`（PR #146）から、共通の
`tests.roster_support.request` / `candidate` / `template` を0.15へ移した。
従来の `request015` と通常の `request` を統合し、不足許容は需要下限の省略で保持する。
完全充足を求める試験だけが `complete_demand` で必要人数と同じ下限を明示する。
既存のテスト関数と固定した旧/新比較fixture・SHAを削除・変更していない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 勤務量、待機・休憩、資格、役割切替、休息・連勤、候補の同日選択 | `test_roster` の通常fixtureを0.15化。全需要を必須にし、矛盾はINFEASIBLEのまま |
| 5,000候補の休息モデル | `test_rest_model_stays_linear_with_5000_distinct_candidates`。0.15の勤務重複と休息に各5,000区間・各1本のNoOverlap、全制約15,000未満 |
| 需要と目的順の独立した全探索 | 日勤60組の `test_optimum_matches_independent_enumeration` と、既存の目的順の全探索。日勤は単一区間をassertし、夜勤・分割は別の原JSON全探索24組を保持 |
| 候補・区間・休憩・勤務日・履歴・勤務条件の改ざん拒否 | `test_roster_verification` / `test_extended_roster`。ソルバー用表を消しても元入力から検証し、違反解の返却を阻止 |
| テンプレートの勤務長・休憩位置の選択肢 | 既存の分割テンプレート検査と `test_current_template_duration_and_break_alternatives_keep_complete_demand`。展開順の不変、必要人数の必須下限、元入力非変更を確認 |
| 夜勤・分割間・日跨ぎ・勤務日・DST | `test_extended_roster` の通常fixtureを0.15化。原区間・休憩・開始日の帰属・実経過分数を保持 |
| 旧版受理と移行元 | `legacy_request` / `legacy_candidate` / `legacy_template` / `legacy_extended_request` を呼出側で明示。旧Schema・型・実行受付を維持 |

目的段階の打切り・証明接頭辞と公平性・基準の移行は次節に記録する。
不足/priority、0.4の勤務条件と基準投影、勤務評価/日数の
残る通常回帰と評価再実行入力・設計例は#124の後続変更で移す。
#125のアプリ保存往復と#111の旧版除去・移行専用資産撤去は、この準備の完了には含めない。

## 目的順序・証明と公平性・基準計画の通常回帰

基点 `0a4dd0d6f4b2e40e1c15694911d7cf8e430e243f`（PR #147）から、
`test_objectives.tradeoff_request` と `test_extensions.baseline` を0.15へ移した。
通常の基準は `source_request` と原解も0.15とし、需要には必要人数と同じ必須下限を明示する。
候補ID・日付・原区間・休憩・担当状態・履歴・目的順と、元需要を満たす意味を保持する。
求解・検証・Schema・公開型はこの変更で更新しない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 3目的の全順序と5目的の証明接頭辞 | `test_objectives`。元JSONの全探索と値を照合し、不足0と不足最小性を指定目的の証明から分ける |
| FEASIBLE/UNKNOWN/INFEASIBLE/内部障害・既知解の更新 | 不足段階と指定目的段階を分け、後段の矛盾はINTERNAL_ERROR、打切りは検証済みの既知解を保持。目的値・証明接頭辞の改ざんは拒否 |
| 探索予算・下限・準備と検証の時間 | 不足段階を含む4段で10/8/6/4秒の残予算を確認。公開応答の再検査を含む総時間と、到達した指定目的だけの下限・JSON pointerを保持 |
| 明示目標・0目標・対象外と公平性の目的順 | `test_extensions`。勤務量の全探索、硬い需要、達成不能な目標、原入力の不正拒否を保持 |
| 候補ID変更・退職/欠勤・役割変更・休憩移動・固定on/off | 0.15の原基準から変更件数0/8/2/4と固定違反を確認。比較区間と30分の粒度も検査 |
| 基準の必須条件・解・区間の改ざん | 元需要の下限違反は `baseline.source_request.demand`、候補や区間の改ざんは `baseline.source_solution` の実在する値へ到達するpointerを確認 |
| 旧版基準・旧形式の全探索比較・後続の旧fixture | `legacy_baseline` / `legacy_extended` / `legacy_tradeoff_request` を呼出側で明示。0.1/0.2の区間違反と0.2基準の正常再計画を保持し、0.15のケースを追加 |

既存のテスト関数は削除せず保持した。不足段階の終端5件と、基準の0.15区間違反2件・
公平性再計画1件を追加した。候補ID変更の変更0・入力非変更も0.1/0.2/0.15の基準で確認する。
0.15で不足0かつ指定目的が全て証明済みの場合のOPTIMAL、
空目的で不足0が分かった場合のOPTIMALは、既存の0.15の意味として検証する。
旧形式の比較用入力は固定比較に使い、通常fixtureから旧版への暗黙変換は行わない。
これらの旧形式専用ヘルパー・試験の最終整理は#125の保存往復後、#111で扱う。

## 不足・priorityと応答整合性の通常回帰

基点 `888a96bace394789685667289bf75dedc27e6c45`（PR #148）から、
`test_partial_plans` / `test_demand_priority` の通常入力と、
`test_partial_contract.result_example` の通常の合成応答を0.15へ移した。
不足試験では完全充足の共通fixtureの需要下限を明示0にし、priorityのヘルパーでは
下限を省略して既定0を使う。元需要・日付・区間・休憩・候補ID・公平性・固定・目的順を保つ。
通常の基準は元Requestと解も0.15の共通fixtureを使う。
エンジン・通常の旧版受付・Schema・公開型・配布版は変更しない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 不足行の結合・数量・順序・原需要・DSTの実経過人分 | `test_partial_plans`。1,001件の不足と、人数/時刻/ID/合計/非結合の応答改ざん拒否を保持 |
| 資格・二重/過剰配置・未指定需要・休憩・固定・勤務量/休息/連勤 | 不足を許してもその他の必須条件は緩和しない。完全充足は0.15の明示下限と `require_complete=True` で確認 |
| 両backendの空目的・全不足・0需要・競合と全探索 | 元JSONの全探索で不足総量→選好→担当切替を比較。公開応答の照合・解の独立検証・入力非変更も確認 |
| 下限0/1/2と不足許容 | 担当配置/勤務計画の6ケース。下限を満たした残りの不足はPARTIAL、下限未達はINFEASIBLE、手修正した空解の下限違反も独立拒否 |
| 夜勤/分割・公平性・再計画・診断と不足の併用 | 現行0.15例を実行し、元需要・証明範囲・入力非変更と、固定によるINFEASIBLEを保持 |
| 打切り・未証明の途中解・内部集計の改ざん | flowの部分配置、CP-SATの証明接頭辞、ゼロ不足の最小性、INTERNAL_ERROR、CLI終了コード2と完全JSONを保持 |
| 不足総量→priority群→指定目的 | `test_demand_priority`。ID/役割順に依存しない選択、人数上限付き全探索、基準保存/再検証/両モードの再計画を0.15でも確認 |
| priorityの予算・証明・集計改ざん | 総予算10/8/6/4秒、到達した群だけの下限・証明と、数量/priority/順序/証明の改ざん拒否を保持 |
| 下限・priorityの省略/0と不正priority | auto/cp_sat/min_cost_flowの12組で不足合計 `total_person_minutes = 30`、目的値0、flow選択を確認。負数/bool/小数/文字列の4件は0.15で拒否 |
| 合成応答の状態・証明・不足集計 | `test_partial_contract`。0.15の必須集計と下限を含め、全8状態、矛盾、10,001行、PARTIAL時の診断非適用を保持 |
| 旧版固有の受理・比較・Schema | 0.3の導入比較/完全基準限定/旧Response/CLI、0.4/0.5のpriority既定値比較、0.5/0.7/0.8の証明/再計画は版を明示して保持。#111で旧版拒否へ整理 |

変更した3ファイルの既存テスト関数34個をすべて保持した。
0.15のpriority再計画/証明5件、不正履歴/公平性/固定/診断4件、
下限6件、省略/0の12件、不正priority4件の計31ケースを追加した。
共有ヘルパーを使う `test_minimum_demand` の0.12試験も同時に確認する。
残る期間別勤務量・勤務希望・継続/重複期間・診断・費用/勤務評価・日数等の通常回帰と、
評価再実行入力・設計例は#124の後続変更で移す。アプリ保存往復は#125の責務であり、
#111の旧版除去・移行専用資産の撤去へは進まない。

## 期間別勤務量・勤務希望と未完成基準の通常回帰

基点 `e00ff8763950bc6ae6f96e454dfa8f41c08ab72a`（PR #149）から、
`test_contract_04.current` と通常の入れ子基準を0.15の共通fixtureへ移した。
0.4の需要下限省略による不足許容を保持し、日付・候補ID・原区間・休憩・履歴・
勤務量上下限・希望の単価・目的順・基準の固定状態を変更していない。
基本入力3組と未完成基準1組は `scripts/migrate_contract.py:migrate_request` の
明示変換結果と一致し、変換前の入力も変更されないことを確認した。
通常のエンジン・旧版受付・Schema・公開型・配布版はこの変更で更新しない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 期間別勤務量上下限・待機・勤務希望 | `test_contract_04`。上下限の境界、重複期間・月末、担当のない希望勤務、代替者の選択、不足を先に最小化する順序を保持 |
| 夜勤・分割・休憩・DSTの実経過分数 | 原区間との重なりで420分/60分と希望の評価値を求め、応答の評価値改ざんを拒否 |
| 原JSONの全探索 | 勤務量下限4通り・上限2通り・必要人数3通りの48組を保持。ソルバーや独立検証器から期待値を作らない |
| 未完成基準・固定/全体再計画・反復保存 | 元Request/解を0.15で保存し、担当済み枠と空欄を区別。固定の不足30人分、全体の不足0、再保存の変更0、休憩/待機の変更、1,005担当の固定を保持 |
| 必須最低人数との併用 | 上下限6組に完全充足を追加。不足許容のPARTIALと下限を守れないINFEASIBLEを区別。未完成基準を保ったまま今回の下限だけを必須にし、両再計画モードと下限違反解の独立拒否を確認 |
| 公開verify・証明非付与・改ざん/障害 | 通常の0.15入力で技能・候補・二重配置・休憩・上下限・固定・未知項目を拒否。探索を禁止した独立検証で下限0/完全充足と、最適性・不足最小性の非付与を確認 |
| CLI・Schema・公開型/配布 | 0.15の公開Schema4種類とverifyのVALID/PARTIAL・終了コード、壊れた解JSONの契約/IDを確認。既存 `test_public_api` / wheel / sdist の型・導入検査も維持 |
| 診断の明示許可変更 | 期間別の必須下限120分を90分へ変える案のみを実行し、元の不可能性と変更後の評価90分を区別 |
| 旧版固有の受付 | 旧版の条件拒否、0.3の未完成基準拒否、各版の候補数/独立検証、0.4のSchema/CLIは版とlegacy fixtureを明示して保持。#111で旧版拒否へ整理 |

既存テスト関数25個をすべて保持し、上下限6件・今回の必須下限と基準2件・
探索なしの完全充足検証1件・0.15のSchema/CLI1件の計10ケースを追加した。
5,001明示候補・5,019選択勤務・6,000生成候補の検査は旧版と0.15を分けて継続する。
継続/重複期間・診断・費用/勤務評価・日数等の残る通常回帰、評価再実行入力・設計例と
#125のアプリ保存往復は後続作業であり、#124/#105全体の完了には至っていない。
#111の旧版除去・移行専用資産の撤去は、準備と保存往復の受け入れ後に行う。

## 継続計画・重複期間の再計画と勤務評価の通常回帰

基点 `e85f68761dbf9d906b3f9d3fe7fb653abed8b7f2`（PR #150）から、
`test_roster_metrics.cost_request` / `night_request` を0.15の共通Request・候補へ移した。
旧0.9の下限省略による不足許容を保持し、候補ID・日付・原区間・休憩・履歴・
単価・目標分数・目的順を変更しない。両ヘルパーは基点の旧入力に
`scripts/migrate_contract.py:migrate_request` を適用した結果と一致し、原入力も変更しない。
継続計画の利用例は既に0.15へ移行済みであり、通常回帰で0.9/0.10へ戻していた箇所を整理した。
空の解を持つ基準も元Requestの0.15を保持する。
通常のエンジン・旧版受付・Schema・公開型・配布版はこの変更で更新しない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 原勤務・実績・確定勤務・文脈期間 | `test_continuity`。未確認履歴・事実の矛盾・原区間改ざんを拒否。過去だけの条件違反を遡及判定せず、アンカー・未来の休息/連勤を検証 |
| 夜勤・分割・休憩・期間端・DST | 原区間と原勤務日を保持し、期間内/外の実経過分数を別集計。候補とテンプレートの開始期間、17分など枠外の分数、全期間と分割期間の同じ勤務列を保持 |
| 原JSONの全探索とpriority | 継続計画12組、固定/全体再計画、費用/目標偏差/選好の全6目的順、実績込みの全6目的順を保持。総不足→priority群→指定目的を先行し、証明した接頭辞だけを報告 |
| 移動期間・重複部分の比較/固定 | `test_overlap_replanning`。前進/後退/反復保存、担当交代の両成分、従業員の追加/削除、休憩/非勤務/待機、重複外の元固定の再検証と同じIDの事実の矛盾を保持 |
| 整数費用・指定区間の目標偏差 | `test_roster_metrics`。1分/17分/0単価、整数・欠落・overflow拒否、区間和集合、0目標と対象外、休憩/分割/待機、変えた単価と元基準、20評価定義と目的群を保持 |
| 実績・未来確定勤務の偏差と計画内費用 | `test_continuity_duty_balance`。未確認履歴の拒否、実績で変わる選択、計画内だけの公平性/費用、原勤務の一度だけの集計、未来確定勤務・DST・期間移動を0.15で確認 |
| 必須最低人数と再計画の併用 | 費用/偏差4組で下限省略/0/1/2を比較。履歴付き再計画6組と重複期間再計画2組で、現在の下限と元基準を分離。下限を満たした不足はPARTIAL、下限未達はINFEASIBLE、違反解は独立拒否 |
| 独立検証・保存・証明非付与 | モデルの候補/事実表を消し、探索を禁止しても原JSONと解から検証。費用/偏差/履歴/固定/比較区間/解の改ざんを拒否し、現在verifyで不足最小性・目的最適性を付与しない |
| 旧版固有の受付・公開入口 | 0.4〜0.6の同一期間限定、0.9基準の受理/新基準の旧版拒否、0.9/0.10と0.15の計画内費用比較を版で明示。0.6/0.7/0.9のSchemaと0.15のCLI/Schemaを併せて保持。#111で旧版拒否へ整理 |

変更した4ファイルの既存テスト関数79個をすべて保持し、対象回帰は240件から258件へ増えた。
追加は必須下限と独立検証/再計画12件、旧0.10との比較1件、0.15のSchema/CLI5件である。
勤務評価ヘルパーを使う呼出側と、継続計画の区間ヘルパーを使う日数・勤務分類・同僚・回数・
全機能併用、Adapter・移行試験も全体回帰で確認する。
残る診断・日数/勤務分類/同僚等の通常回帰、評価再実行入力・設計例は#124の後続作業、
アプリ保存往復は#125の責務である。#124/#105の完了、#111の旧版除去・移行専用資産の撤去は行わない。

## 診断・必須最低人数・日数・勤務分類・同僚の通常回帰

基点 `60dc489751b4286f35d2b3e312027beb2458f94a`（PR #151）から、
`test_diagnosis` / `test_minimum_demand` / `test_day_counts` /
`test_shift_patterns` / `test_coworkers` の共通入力を0.15へ移した。
`test_conflict_refinement` の背景条件の試験も、通常の継続計画を0.8へ戻さず使う。
担当配置・勤務計画の診断、必須最低人数、日数、勤務分類、同僚の代表6組は、
基点の旧入力へ `scripts/migrate_contract.py:migrate_request` を適用した結果と一致し、
原入力も変更しない。候補ID・原区間・休憩・日付・履歴・元需要・目的順を保持する。
0.2の完全充足の診断だけは、元需要と許可した人数編集に同じ必須下限を付ける。
日数・分類・同僚の下限省略を必須充足へ変えない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 元条件と許可変更後の計画 | `test_diagnosis`。assignment/rosterの完全充足、競合需要・候補・勤務量・連勤・休息、許可編集・不正pointer・重複拒否、入力非変更を保持 |
| 需要の上下限の明示編集 | 必要人数だけを下げて下限を越える案は拒否、最低人数だけを下げる案は元需要を保ったPARTIAL、両方を下げる案は完全充足。変更案は元条件の正式解として扱わない |
| 診断の背景条件と矛盾縮小 | `test_conflict_refinement`。資格・候補・実績・確定勤務を背景へ分け、条件グループ・十分性・包含極小性・UNKNOWN・検証した証拠・固定解除・予算/障害を保持。全列挙と別モデルの照合も継続 |
| 必須最低人数と不足の目的順 | `test_minimum_demand`。下限0/省略・資格競合・250人境界・不足総量→priority→目的、両再計画モード・基準保存・原JSONの全探索・全候補部分集合を保持 |
| 勤務日・占有日・完全休日 | `test_day_counts`。原開始日・夜勤・00:00・分割間/休憩・月末/年末・DST・実績/確定勤務の一度だけの集計、全探索・範囲/型/余白拒否を0.15で検証 |
| 勤務分類と4種類の勤務パターン | `test_shift_patterns`。区間和集合・閾値・待機/休憩/分割間、連続休日・勤務後休み・禁止並び・日付群、原履歴・余白・固定/全体再計画・原JSON全探索・独立拒否を保持 |
| 同時勤務の必要条件・禁止 | `test_coworkers`。指導者の交代・最低人数・相互条件・待機・休憩・分割間・DST、集合の全組・原区間からの全探索・改ざん/固定/未確認の拒否を保持 |
| 日数・禁止並びと必須下限 | 日数条件と下限0/1/2、禁止並びと下限0/1を併用。PARTIALとINFEASIBLEを分け、元条件を緩めず下限違反解を独立拒否 |
| 現在検証と元の証明 | 探索を禁止した公開verifyでも変更案・日数を検証し、最適性・不足最小性を付与しない。元条件に戻した変更案の解を拒否 |
| CLI・Schema・型と旧版境界 | 通常の0.15のsolve/verify/Schema4種類・公開型を確認。0.2/0.8/0.11/0.12/0.13のSchema/CLI、導入前の拒否・旧基準の受理は版やlegacy fixtureを明示して保持。#111で旧版拒否へ整理 |

変更した6ファイルの既存テスト関数109個をすべて保持した。
追加ケースは需要編集6件、日数と下限3件、禁止並びと下限2件、PARTIAL診断非適用1件、
CLI/Schema・最低人数編集の現行版追加6件の計18件。
同じヘルパーを使う勤務回数・全機能併用・移行試験も全体回帰で検証する。
通常のエンジン・旧版受付・Schema・公開型・配布版はこの変更で更新しない。
残る評価再実行入力・設計例と通常入口の最終棚卸しは#124、アプリ保存往復は#125の責務である。
#124/#105の完了、#111の旧版除去・移行専用資産の撤去はまだ行わない。

基点mainのCI [37914520923](https://github.com/omitsuhashi/schedula/actions/runs/37914520923) は、
GitHub Actionsのアカウントの支払い・利用上限を理由に全5ジョブが開始されなかった。
テストの実行失敗とは区別し、必須CI成功の証拠として扱わない。

[Draft PR #152](https://github.com/omitsuhashi/schedula/pull/152) の実装commit
`0b2b1edcefc7185c418afe715ef16a8a9465034c` で、手元の全体回帰は
`uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml` により
2,618 passed, 6 subtests passed in 685.06s、JUnitのfailure/error/skip 0。
対象8テスト群は417 passed、隔離wheel/sdist・公開型・base/cp-satの回帰も全体に含む。
pre-commitとstrict mypy（`examples/typed_api.py` / `examples/typed_adapter.py`）が成功し、
実Chromiumは10 scenarios / 21 interactions / 25 response samples / page errors 0だった。
PRの [CI 37915936701](https://github.com/omitsuhashi/schedula/actions/runs/37915936701) も
同じ支払い・利用上限の理由で全5ジョブが開始されず、main反映後の受け入れは未完了である。

## 原bytesと更新後bytesのSHA-256

原本は上記基点commitの各パスを参照する。JSONをcanonical化した内容ハッシュとは区別する。
失効例は0.15の正常勤務計画から明示的に古い適用範囲・古い勤務候補を保持して再構成した。

| パス | 原SHA-256 | 更新後SHA-256 |
| --- | --- | --- |
| `examples/conflict_refinement.json` | `2af3293996fa4152adea89a1aba3d31d9d318969a0423c0f3b0220f92dc58349` | `dcd3885ccc600c2355669a5b9a2b806360d3cddeab20b152eff2fa617b76c57c` |
| `examples/continuity_duty_balance.json` | `f99ae3a64cd2cdab2457fbdf48afe763240ab7d32ced9b8f63e73ae937e6538b` | `79996874bcfd5ae2cbd8ac5e276493c869a464dc4b28685147a46bdae4a08114` |
| `examples/continuity_month.json` | `779043eb2e3e7d8c3c8ffbda05b510dc6ee92af004894715a06234d6c3a733d7` | `712593113a7a0afe247c9401840c0828328f31a6814508f587b660cc3919eadf` |
| `examples/continuity_replan.json` | `628bbe0fdfbd9080c1a9ddba756bbb55d36fb60f15e21b57be0d7519b691c74a` | `7719ff5463578e937c3d462743a3d5656e63429e75732360c5d058e30de3b567` |
| `examples/continuity_week.json` | `8d9bd7621a775a55026ed5c3e70366fb50f591ade751b1f46626bfedaad93d3f` | `f0146522392c072a943e892a49547b6d84c69735a00d418501bee0596d15ccbc` |
| `examples/coworkers.json` | `15d7451db07177773c20a6ca4e2fd9c9218b66dc8dd6fd524dc5b3d40425b2e8` | `401991cd75eb8ccb42615e2294d9286077bf89ffbb56d9d06d5cfb3b6c4b9c8b` |
| `examples/day_counts.json` | `d45faa8ed14c48a26e3b06087b9ad887c6f4a3e07c3b5d2f32ce97b3847c274b` | `c5faac58aa922685ca88557d396cc5764f4a960e75ca3432dd09c63baf920c2b` |
| `examples/demand_priority.json` | `1ad3d6c58de46e2c47d745b3256f30f8b9e39212a849544ecb16377998507eab` | `30014f20a4e98b0d64873cc37ebd9e0d1e1b584b281e3bc30a1b528d893dbdb2` |
| `examples/diagnosis.json` | `3e0c5c4fc9733349b24de077ef66383cccecd104244252d5bae4ac8de12d679b` | `25e6f718bb88d10dada2bf730d7c8327500b6ec9713419a032a59ab39da6f796` |
| `examples/duty_balance.json` | `b6a1ed556e1b7d338d42abc1de9b3aa99dd27daadd262ba596edca95f8dc3a18` | `71b3ea2b665773acf42117dba55519877fab26dd98ede2eaed8aad1623694457` |
| `examples/fairness.json` | `6d4f850b093cbf857ae5374cee2610babf9ab9502088d357038474b0e4009ea8` | `3fc17504285a4a77c8fe072020e36da70279009b7538dd5128f3d04c65fce15a` |
| `examples/invalid-input.json` | `bffc0c3f071099a7489d7369479064ba4fe1ed1d319c6c0c275ec503e42e84eb` | `ab6be5a751eb35d28296979892be78afef57cc81e106de74d0b50036788a332e` |
| `examples/minimum_assignment.json` | `48ba77f7386f57c0f7773193bcb2c72d378cdc581d5d5a47b5de089d8f3d33ae` | `e8bd60bb30d9e78ee4ae61859102d8733223c58415ff50a37f5212b22e9d5ec5` |
| `examples/minimum_conflict.json` | `0bf9f6f886215c0eac4647b63675216fca8f6aae0acf7217f44e642d8fe1a4e8` | `fffbbc6094e5daebcd296324a1a50107ce4cb2e2f9a13e1f9b3adb2a1c20863d` |
| `examples/minimum_roster.json` | `8896c4b139cd2ba4d305110888038e78212dbfd3f7acdc48ef6a3e5c461f4f96` | `d59fba1f1890b352d8ef7cff9c0cfd5593451c6e0a05376ef4b95e84ec7bf311` |
| `examples/overnight.json` | `3a8b32d3df48daefad8dc411d585ba4b6ea214f4c0f43e30dacc66c5f12cb96c` | `dfbccd30359bcdc5da44aed20f06403e47559dd765ad3a2082623b198b74b000` |
| `examples/partial_replan_preserve_assigned.json` | `c307c2e4fc997479ab7dd1dd2db3e76e00fab26013d3065e26b9126fc225c5e9` | `675b6388bf3005d0e3a5811d82ea809dfa2680f6c018176652d80ebd9fb0dbb3` |
| `examples/partial_replan_rebuild.json` | `87000b963af447c21c950ac49785542e39c7c71b5c52e39896803ab63dd9a6a2` | `d2a2debaa90c719e0d2d13934d4ddb5e4fcf7ec67bf653691d5ee3f6dc72b7ed` |
| `examples/partial_roster.json` | `140203281e04594878b2a6f08ed3124d2060f9f810491f291886834f6550739b` | `3d92cabe97441c5b52ef0a85ee31406277a0dffab4f089fbfacb8d11ef22a367` |
| `examples/replan.json` | `e3afa224e45a43802948e7c776671e3d8b3c545085b1f90ed4d1eb166e528b97` | `f5942add4e2203aea570af57ab39134330f53b50b468e44136d043838a9ec27c` |
| `examples/roster.json` | `bd9cc8b03fa4b012807fe22ff9937516423b0b5919ae811ce7355d06eec73121` | `e9efd64a827f73e0d064c1dafa32ef3c5582d352a010998f79376542dc094461` |
| `examples/roster_conditions.json` | `1e212fc26dc594babea06440cb8a6c2c3d0be0932f97bf3f9517c816ad05d771` | `f8be171975e1544cea499130aff9139c6d23363dbe5472c0f693e24ba8805748` |
| `examples/scheduled_cost.json` | `4ed530d68b2c33a1e0114a3214d75e92f3f04e69e7add874982cd6b3bb042623` | `66b64c318fb6c28c247fc104914eefde33f40536f32d8fb9b221a25f2b130ba3` |
| `examples/shift_patterns.json` | `74805a82d72ca53b8ce88b0bda2b8d7c0af6766d81d4badae715404e91823bcb` | `90f7919b18a1e2905fad305115af098ead7e9d15ec8ac55700f5899811e0b236` |
| `examples/split_roster.json` | `ff5172bfb71d8fa54a385c8fce5a9c1855393a2d7595988d28453b15ce05ecc9` | `43cb400b58fa95317976a5456589fbbed932c75526ee4a2653ce02673469e05a` |
| `examples/adapter/continuity_week.draft.json` | `5f5c90a0b25237fcbcbce3dae541c7162efda2fa05a084d2e81e7e79935b2977` | `f607fa9a8dfefce120aa4ad14bda84f0e5802fa9b59cbcc981ce59b85a6af7e2` |
| `examples/adapter/partial_replan_preserve_assigned.draft.json` | `ebb8b3adfcbe44d05a12f96669649342f99e45021f71512ee29eb6b7f1cc856b` | `c3dba396bcd2dbd0bd7341281cfca6503958a069137e4d3a72e4162a418d27ab` |
| `examples/adapter/partial_roster.draft.json` | `4184743853452a2a1d0986cd1a3cacfff060f48cf24c6ef6fa806f6b804719e1` | `edbadb217a0e4d522db77a30bdefa57604f851d36e4901a06dd5369059c46a58` |
| `examples/adapter/roster.draft.json` | `67d130c9b6ce2a36745ee80929f4bf053afe786cabc91f8b1b9439a4b29f0e5a` | `689ca3e37abf072aa0e96ad93e74df4386ee91116b6bc27f932a118e3174df18` |
| `examples/adapter/unconfirmed.draft.json` | `f2fca8850834efc9e7e3f433c1f20eeed754b5a23da7f918ac2b5ec5065b8e4b` | `8a88feb1a2e7e8bbe7ba3a823283514af29477caa695788fad1f3ba61da2e6e8` |
| `examples/adapter/week-next.draft.json` | `788563fd69d5ab3245703568be822dab7e0367be169a4e77c74fac481ea01987` | `c0de5ea0d2fa61889a380e1284abefaaeb213e7cf8c3370796c44578f663a6e6` |
| `examples/adapter/week-next-stale.draft.json` | `a70ffe8e157f88adc6227cf3e78e804fbf7c27ebe981dd666dd98fb32dc54503` | `6b3bc7d491f34ffe94966baadf2284e392df7d8e859c5702bbb06c35a1bacadf` |
| `examples/adapter/week-next.request.json` | `fe454f3584b176cea6c34dcded4539ea3f8f56ad22abbc221e8508a207a86bd6` | `fe45ad0290243c4d80c32cd65e2dda88a1df374b9e584a8d2ac0ec55a39af916` |

## 評価再実行入力・設計例と通常入口の棚卸し

基点 `d634741aff115a6a4212eedf3427f6b1f5552bdf`（PR #152）の旧版評価入力22件を、
既存の `scripts/migrate_contract.py:migrate_request` で0.15へ移した。
既存0.15の規模比較入力4件と、過去の測定結果JSONは変更していない。
旧0.1/0.2の完全充足には必要人数と同じ最低人数を明示し、診断の人数編集にも同じ下限編集を付けた。
0.4/0.10の下限省略による不足許容を保ち、入れ子基準の元Request・元解も移した。
候補ID・勤務日・原区間・休憩・勤務枠を正規化前後で照合し、日付・固定・履歴・目的順・予算を保持した。

旧0.1の6件の勤務テンプレートは、旧IDを持つ有限候補へ展開した。
週の5件は各560候補、2週間は2,240候補。候補は1行1件で記録し、行数を抑えた。
エンジンのテンプレート機能は残し、現行形式の候補生成は通常の業務回帰で引き続き検証する。
不正例は有効な構造で明示変換した後、期間上限超過と未確認履歴を元の値へ戻した。
`roster-input-limit.json` は `INPUT_LIMIT /planning_window`、
`continuity-duty-invalid.json` は `INCOMPLETE_HISTORY /continuity/employees/1` のまま拒否する。
不正例を有効入力として移行できたとは扱わない。

`combined-legacy-010.json` は0.10由来を示すファイル名を保持し、現在の内容を0.15へ移した。
過去の測定に使った原bytesはこの基点commitの同じパスで参照する。
過去の測定結果の入力SHAと現在の入力SHAは異なる。新入力の測定を過去の再現・性能同等の証拠にしない。

| 検証内容 | 今回の行先・維持した判定 |
| --- | --- |
| 全評価入力と入れ子基準の0.15・必須下限・不正例拒否 | `test_evaluation.test_current_evaluation_inputs_keep_contract_and_required_conditions`。26入力、原ファイル非変更、公開verifyと現在の証明非付与 |
| 夜勤/分割・固定・公平性・許可変更後の解 | 既存 `test_combined` の原JSON全探索。必要人数と下限を共に編集し、元入力のINFEASIBLEと変更後の検証済み解を区別 |
| 評価器のJSON・SHA・単独/継続/並行・外部期限・障害 | 既存 `test_evaluation` の全検査。通常の診断例は0.15を明示し、旧パッケージ名の測定は版互換専用の検査として保持 |
| 現在の設計JSON部分例 | `scheduled-cost` / `duty-balance` を完全な0.15例へ追加して公開validate。既存の他目的を保持 |
| 設計の数値・矛盾・仮定の検算 | 既存 `docs/designs/check_examples.py` の数値・全列挙・CP-SAT検算を通常pytestから実行。方式比較・導入版は履歴として保持 |

通常例・フォーム/JSON/HTTP・Adapter・共通fixture・各業務回帰の移行はPR #144〜#152と本変更に対応する。
残る旧版依存は、公開Schema/型/エンジンの受付、版固有の受付・拒否比較、
移行専用fixture/スクリプト/検証、過去の設計判断・測定記録である。
#111では版固有の受付を拒否へ置き換え、混在する通常の業務回帰を保持した上で移行専用資産を撤去する。
全公開仕様・配布参照の統合は#113/#114の責務とする。

mainと本PRの必須CI成功、#125のアプリ保存往復は別の受け入れ条件であり、
#124/#105の完了や#111の旧版除去の許可には代えない。
最新基点mainの [CI 37918082896](https://github.com/omitsuhashi/schedula/actions/runs/37918082896) は、
GitHub Actionsの支払い・利用上限により全5ジョブが検査開始前に失敗した。

### 評価入力の原bytesと更新後bytesのSHA-256

| パス | 導入契約 | 原SHA-256 | 更新後SHA-256 |
| --- | --- | --- | --- |
| `docs/evaluations/inputs/assignment-week.json` | 0.1 | `57bb786b8f98b3d708105246d7058179f4a0945e1c08dc8f75144a7f58ecd854` | `d47c98335aa495e254f6bbec81a65d30b5e1f09a13ff360ed785866f7498aa35` |
| `docs/evaluations/inputs/combined-legacy-010.json` | 0.10 | `feb5ab26f23200561e37e7b19d064e534b09197daca138b8367c17c31543619f` | `6cf1de0fc7cc7176eb45f22917e0e6e10ea470927383e6841e131a991caba1af` |
| `docs/evaluations/inputs/combined-overnight.json` | 0.4 | `a8769f82901e379f698ae6426beda23d9d5cc6389a02f5a794165e595106525b` | `d66d234329d1baf838a5f7cb44692f9a13ccd242007e653db9bd85a5831f896b` |
| `docs/evaluations/inputs/combined-split_roster.json` | 0.4 | `caa2d146ca3cc958e3a605d1e1750db4528b24eee3961ed777efa6631e9a911c` | `001066c60bcb2674885496fe402fa20fa8ee500220815d6176d44e8adedd9b09` |
| `docs/evaluations/inputs/continuity-duty-conflict.json` | 0.10 | `db9c2c682a6542e780ecb586aaa14a4b5734650d6925a8c92cff9e9dc2ee5c93` | `89d4a390c4b3ce040a65a2c88d3e50fefdb441a21f418bbee15b73b430174d83` |
| `docs/evaluations/inputs/continuity-duty-invalid.json` | 0.10 | `f85f6f1a614fd3077237e08fbdbbea30aeffefb4e55f41b8918ff6b1d38cc14b` | `80dca1320c9240de481bffb05bd9048fe897f43001cc7c2b3b404c32c9b5c11b` |
| `docs/evaluations/inputs/continuity-duty-partial.json` | 0.10 | `6390f6fd9bd98a18285f4e5742f63f1809cb0361b28a581b6458c294e16450bc` | `bc151d51bd507829515b228ff22d95ef33e5be1090ec28b068d24d169744f8bd` |
| `docs/evaluations/inputs/continuity-duty-timeout.json` | 0.10 | `e218b8025a85f1cf8a1231f329fbf7596649f424ce8ac7172095e25d41266e67` | `4fd07f8f0022ecad317a75d4cf3f0d52db4f68e3d5113e4d8002eeb042f49ffb` |
| `docs/evaluations/inputs/replan-equal-rebuild.json` | 0.4 | `b7207614100962f4d5d453a9094e8016b0ff09eccdd2626bbaafb7719661c2b0` | `38ae99a61fe80792f698e1baf31e91de7709f8a3b6d2410e48dcacc968ea6446` |
| `docs/evaluations/inputs/replan-equal.json` | 0.4 | `2460ddba36021d74c4ec58ea92e02aab44bf737bdad427f25cc5bbe5a3324358` | `17b7a370250c42dd9f644685a9ea75daa2547962ec6e51f0414ca2edd142368f` |
| `docs/evaluations/inputs/replan-fixed-impossible-rebuild.json` | 0.4 | `3118bcc318f65b6c26e219792ffbdc2477887592ccbbf37edd10d60138683e3d` | `18d9085b0c249759be5dcc4dde502a3c92b9474316774e67884d781e3ffedfe3` |
| `docs/evaluations/inputs/replan-fixed-impossible.json` | 0.4 | `b01139da19fd39da18aabad354087986521a55cf91ada116a0b910ef03c3a38d` | `e8fa795484c967f5900b9e16ccecc5880feb6313f420e652cac7c2751d02823a` |
| `docs/evaluations/inputs/roster-conditions-12000.json` | 0.4 | `ab795677ccf3d68e334555aa305a322b880dbf5e619872599fe578aeb443010c` | `33be6ca5501a7e7a60b9d43085d10ec879b42e26cb5878d8eaf24ba19044776a` |
| `docs/evaluations/inputs/roster-conditions-3000.json` | 0.4 | `4e30feb0504c4fc337780fb12eb4277eb9b796dd9b80e58d9a755502e607f0fc` | `ecbd104e5b231ca8761fb0cab85624a12289991012253a7fcedc4d666d43fd6a` |
| `docs/evaluations/inputs/roster-conditions-6000.json` | 0.4 | `0a81160efe7d8a301678733752698c26146bcf021027794e8858fa60fbad248d` | `38e8e124f85c5e6c913bcbb5e064ebf860cc59ce48c64478504e895b53a81b06` |
| `docs/evaluations/inputs/roster-extended.json` | 0.2 | `a8d05d7f57b57a59c732f99782225af37d201f7ddb0e63bd985e1df89295a06f` | `4409754225e2c4dd1a0b1cc6b21f0b31840781c26f6a062d6f250b7ab6db4722` |
| `docs/evaluations/inputs/roster-fortnight-large.json` | 0.1 | `ae4f89e8be42368213533ea8da508c514e33a49a034a74c301f921cd29b0fec1` | `9561cc71bfe87a622b714e52fee12ffebcf6a678ea54a2a9a7e2563024e3ec78` |
| `docs/evaluations/inputs/roster-input-limit.json` | 0.1 | `57b477b0867067a06a7cd9c190163a1b71b6854b869593588a809b1b887c0e3f` | `c3cf4434294c421c79ab370b0ff8f9b88dc4f4630bf833f13524097db38c3712` |
| `docs/evaluations/inputs/roster-week-15min.json` | 0.1 | `68e1a1d94e0af9c4b4d2d14b2fe9adf6c6e8eb5df021807be6eafc6a9eb42f6e` | `5d95b4cf1cdda07f1094963dfc9fa948c3d64c2e49bdf23fcf33bd3ecc164d8c` |
| `docs/evaluations/inputs/roster-week-infeasible.json` | 0.1 | `e31ebe900d24cc5807c3feb5aa5c7ecada944e4633a433ea18959b2facd22bc1` | `c60869bb4f07d311d8b7f55c0b24fe0a7e85a5dff28b5b4807b4b3500d7ae004` |
| `docs/evaluations/inputs/roster-week-timeout.json` | 0.1 | `729cbc9307d8567b0cf9729563befa9f15df86afee0e3a797cb1a5121dbb771c` | `eca3e11d12290feb0f073164054220bb1a082754869eedc60e490b236469ec73` |
| `docs/evaluations/inputs/roster-week.json` | 0.1 | `b9c3f1f9713027b9534b304fd4f9e0366aecbb97d9d90a01aab105ac1ef9941c` | `f63768b0004748b1886302899955aec2039e5174da54af2e0827ca9d65cb97bb` |

### この変更の検証結果

[Draft PR #153](https://github.com/omitsuhashi/schedula/pull/153) の実装commit
`525d58a0ce8633ea9b5bcc11e3615f4a6486108c` で、手元の全体回帰は
`uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml` により
2,647 passed, 6 subtests passed in 704.80s、JUnitのfailure/error/skip 0。
対象回帰40件、隔離wheel/sdistとその同梱業務回帰・公開型・base/cp-satも成功した。
既存テスト関数11個をすべて保持し、通常の入力・設計例に29ケースを追加した。
pre-commit・strict mypyは成功。実Chromiumは10 scenarios / 21 interactions /
25 response samples / page errors 0で、フォーム・JSON・100人30日・Adapter確認/失効・
記録保存/再読込/再検証・基準保存/再計画・キーボード・狭い画面の回帰を保持した。

22件すべてが既存の明示移行結果と一致し、旧新の有限候補の業務属性を照合した。
原SHA・更新後SHAは上表と一致し、既存0.15の4件と過去の測定結果・旧比較fixtureは非変更。
今回の内容は通常回帰の準備であり、#116の同条件の性能・解品質の再測定を代替しない。

実装commitの [PR CI 37918987719](https://github.com/omitsuhashi/schedula/actions/runs/37918987719) は、
GitHub Actionsの支払い・利用上限により全5ジョブが検査開始前に失敗した。
必須CI成功・main反映後の受け入れと、#125のアプリ保存往復は未完了。
#124/#105はOPENに保ち、#111の旧版除去・移行専用資産の撤去へは進まない。
