# 契約0.15への機能対応表と旧データの移行方針

[Issue #105](https://github.com/omitsuhashi/schedula/issues/105) の承認済み方針に従い、
実行契約を0.15へ集約する。実装担当者は以下の対応表を回帰・移行の基準とし、
条件と証拠が揃うまで旧版を除去しない。旧wire形式の常設サポートを終了しても、
業務機能、必須条件、独立検証、保存・再計画、baseで使えていた担当配置を維持する。

本変更は [#106](https://github.com/omitsuhashi/schedula/issues/106) の棚卸しであり、
通常入口はまだ0.1〜0.15を受理する。0.15の現在の意味・既定値も維持対象とする。
0.1/0.2の完全充足を移行するための正の下限について、baseの最小費用流に不足がある。
補完は #108、明示移行は #109/#110、最終旧版除去は #111 が担当する。

## 調査対象と基点

基準日は2026-10-09、対象・移行判断の責任者はリポジトリ所有者 `@omitsuhashi`。
利用者回答により、利用側は `omitsuhashi/schedula` と `omitsuhashi/schedula-app` に限定する。
この範囲外の利用を仮定した移行基盤は作らない。

| 対象 | 固定した基点と確認方法 |
| --- | --- |
| エンジン | main `bbb7a93b757cc3272943bbc09f9f2dcb359bd457`、配布版0.1.6、契約0.1〜0.15、Adapter/manifest/record 1.0。契約文書、ADR-0001〜0009、公開型、求解・検証、CLI、例・テストを照合 |
| アプリ | main `ccd32402119762cca4c2981b705730b1e7dc3230`。vendor manifest、backendのworkflow/store/commands/queries/storage_admin、保存テストを照合。ローカルの古いcheckoutを現行仕様の根拠にしない |
| アプリ固定エンジン | 0.1.5 / Schema 0.10 / `fd8c140ff0dae8c8cefa82b5d3857ec0e0e90eaf`。wheel SHA-256 `3b8256c0d277da253cd79252683727c65c9ab7265c02aec93ff26a24006e9195` を現物と照合 |
| リポジトリ内データ | エンジンexamples 50 JSON、評価再実行入力26 JSON、過去測定42 JSON、アプリ例13 JSON。原bytesのSHA・版・入れ子pointerは[棚卸し記録](contract-0.15-inventory.json)に固定 |
| テスト・フォーム | testsの生成fixture、demoのフォーム/JSON/サンプル、型付き例は保存済み実データとは区別し、#107/#124で移す。参照原本 `docs/reference/` は歴史資料として保持 |
| 顧客保存先 | アプリは起動引数 `--data-dir` の `sessions.sqlite3` を正本とし、JSONは取込・持出し。現行mainのGit管理ファイルには顧客DBがなく、実保存先・件数の有無は利用者へ確認中。不存在と断定しない |

## 全機能の対応表

以下の入力はすべて明示的に `schema_version: "0.15"` を指定する。
0.2以降の形状をそのまま使える場合も、埋め込み基準・解・応答と旧意味を別に検査する。
表の維持テストは現行の業務検証の行先であり、0.15化の完了を意味しない。
求解と独立検証の両方を移し、版重複の統合で検証内容を消さない。

| 導入 | 入力形状・既定値・拒否条件 | 0.15の表現・出力・backend | 実装と維持テスト |
| --- | --- | --- | --- |
| 0.1 担当配置 | `skills/roles/employees/availability/demand`、未指定需要0、技能はAND、同じ枠に一人一役割。配列の省略・参照不明・需要区間重複・過剰配置を拒否 | 完全充足は各需要の `minimum_people = required_people`。`assignments/roster` を保持。制約なし・加算選好だけのflowを #108 で補完。他の制約/目的はCP-SAT | `model.py/flow.py/cp_sat.py/verify.py`、`test_assignment.py/test_cp_sat.py/test_verification.py` の全探索、残余経路、競合・改ざん |
| 0.1 勤務候補・テンプレート | 候補直下 `interval/breaks`、テンプレートの `start_times/durations_minutes/break_options`。rosterは空履歴も必要。旧版は日跨ぎを拒否 | 候補を一要素の `segments`、テンプレートを `segment_options` へ。候補ID・原区間・休憩・旧版での展開結果を保持。履歴の追加事実は下記。rosterはCP-SAT | `roster.py/cp_sat.py/verify.py`、`test_roster.py/test_roster_contract.py/test_roster_verification.py` |
| 0.1 勤務ルール・選好 | 勤務量上下限、連勤、休息、休憩、担当上限・切替、`avoid_role`。選好には対応目的が必要、目的は配列順 | 同じconstraints/preferences/objectives。待機は勤務量、休憩は除外。資格・availability・固定を緩和しない。`objectives/roster` と独立検証を保持 | `model.py/roster.py/cp_sat.py/verify.py`、`test_roster_metrics.py/test_objectives.py/test_input_contract.py` |
| 0.2 夜勤・分割・履歴 | 1〜4 `segments`、正の分割間隔、`history.last_work_day` を明示。勤務開始日で一日一候補・連勤判定。欠落・矛盾・期間外を拒否 | segments/segment_optionsを保持。分割間は非勤務、休息は最終退勤から。`shifts.segments`、待機/担当を保持。CP-SAT | `roster.py/verify.py`、`test_extended_roster.py/test_extended_roster.py::test_extended_roster_matches_independent_small_enumeration` |
| 0.2 目標・公平性 | `fairness.evaluation_period/employee_targets` と目的の対。明示0は0目標、未指定者は対象外。目標推定・正規化なし | `fairness_deviation_minutes`、`fairness_summary`。必須上下限とは別。CP-SAT | `extensions.py/cp_sat.py/verify.py`、`test_extensions.py/test_combined.py` |
| 0.2 基準・固定・変更 | `baseline.source_request/source_solution`、`fixed_parts`、`plan_changes`。元版で完全な基準のみ。同一W・zone・粒度を要求 | 元版の完全充足下限を埋込Requestにも付け、元解を検証。勤務/担当の時間枠状態差、固定を維持。0.15で可能な部分基準や重複Wへ勝手に変更しない | `extensions.py/verify.py`、`test_extensions.py/test_overlap_replanning.py` |
| 0.2 診断・変更案 | `diagnosis.time_limit_seconds/max_suggestions/allowed_changes`。未許可編集・重複・flow指定を拒否 | CP-SATの不可能性証拠と変更後Request/解を別に保持。完全充足の人数編集は下限も旧許可範囲内で連動させる。元Responseの証明を転記しない | `diagnosis.py/engine.py`、`test_diagnosis.py` |
| 0.3 不足 | 元required_peopleを保持し不足を最優先。0.1/0.2は不足許容でなかった | 下限を追加せず省略/0を維持。`PARTIAL/shortage_summary.proven_minimal` と全目的最適性を区別。flow/CP-SATとも維持 | `flow.py/cp_sat.py/verify.py/engine.py`、`test_partial_plans.py/test_partial_contract.py` |
| 0.4 勤務量・希望日時 | `scheduled_minutes_bounds` は省略側無制約、null不可、上下限逆転を拒否。`prefer_work/avoid_work` は勤務禁止とは別 | 同じintervalと整数分数/penalty。`preference_penalty` を保持、待機を含み休憩/分割間を除く。CP-SAT | `model.py/cp_sat.py/verify.py`、`test_contract_04.py` |
| 0.4 未完成基準・公開検証 | `preserve_assigned/rebuild`、元の固定状態/snapshot_origin。rebuildと固定・変更目的の併用を拒否 | `make_baseline/verify` と `change_summary`。担当済み枠のみ自動固定、空欄は固定しない。投影で比較用項目だけ除く。verifyはソルバー不要 | `extensions.py/verify.py/__init__.py`、`test_public_api.py/test_contract_04.py` |
| 0.5 需要priority | 任意整数priority、省略0、負数不可 | 不足総量→priority降順の各群→利用者目的順。`priority_summary`。非0のpriorityはCP-SAT、全0は既存flow | `model.py/cp_sat.py/verify.py`、`test_demand_priority.py` |
| 0.6 継続計画 | 任意 `continuity.context_window` と確認済みactual_shifts/committed_shifts/before_context。W⊆C、未確認・C外・重複/アンカー矛盾を拒否 | 原区間と休憩、計画内開始の新規選択、Wへの投影を保持。continuity省略時は従来の期間内候補。`continuity_summary`、CP-SAT | `continuity.py/roster.py/verify.py`、`test_continuity.py` |
| 0.7 重複W再計画 | 同じzone/粒度、移動したWの重複だけ比較・固定。期間外の基準改ざんも拒否 | baselineを元Wのまま保管・検証。新Wに切り詰めない。`change_summary.comparison_window`。0.6以前の同一W用途も保持 | `extensions.py/continuity.py`、`test_overlap_replanning.py` |
| 0.8 矛盾縮小 | 任意 `diagnosis.conflict_refinement`、省略は縮小なし。縮小予算は診断予算内 | 元候補・資格・実績等の背景を保持。需要/ルール/固定を単位に `conditions/checks/minimality`。包含極小と要素数最少は別、UNKNOWNでは除去しない。CP-SAT | `diagnosis.py/cp_sat.py`、`test_conflict_refinement.py` |
| 0.9 費用・指定区間偏差 | `costs` と目的、`duty_balance` と `duty_id` の対。全従業員の明示整数単価、明示0と欠落を区別。上界・粒度・参照を検査 | W内勤務の費用、区間和集合と明示目標の分数偏差。`cost_summary/duty_balance_summary`、1分粒度。給与/為替へ拡大せず、CP-SAT | `roster_metrics.py/cp_sat.py/verify.py`、`test_roster_metrics.py` |
| 0.10 履歴付き偏差 | duty_balance評価期間をC内へ拡張。未確認過去・C外/評価期間外を拒否 | actual/committed/selectedを原区間から一度ずつ数える。費用は引き続きW内。`duty_balance_summary`、CP-SAT | `roster_metrics.py/continuity.py`、`test_continuity_duty_balance.py` |
| 0.11 日数・完全休日 | 期間別 `work_days_bounds/days_off_bounds`、省略側無制約、null/上下限逆転を拒否 | 開始日に帰属する勤務日、休憩込み原区間が触れる占有日、完全休日を別に数える。`day_count_summary`。日数編集allowed_changesは未対応のまま。CP-SAT | `day_counts.py/verify.py`、`test_day_counts.py` |
| 0.12 必須最低人数 | `demand.minimum_people`、省略/0は下限なし、required_people以下の非負整数 | 元必要人数・上限と下限を保持。下限違反はINFEASIBLE/UNKNOWN、PARTIALでは通さない。不足行にminimum_people。正の下限は現状CP-SAT、#108で完全充足flowのみ補完 | `model.py/cp_sat.py/flow.py/verify.py/diagnosis.py`、`test_minimum_demand.py` |
| 0.13 勤務分類・パターン | 明示 `shift_categories`、連続休日/勤務後休み/禁止並び/勤務した日群の4ルール。未入力未来や履歴要約だけで必要な余白を補わない | 原勤務を分類し開始日・占有日・完全休日を各ルールで使い分ける。余白不足はINCOMPLETE_HISTORY。allowed_changesに未対応の編集を追加しない。CP-SAT | `shift_patterns.py/continuity.py/verify.py`、`test_shift_patterns.py` |
| 0.14 同時勤務 | `required_coworkers` は対象者と同僚の交差不可・正の人数、`incompatible_employees` は2人以上。省略なら追加ルールなし | 待機込み、休憩/分割間なしの勤務枠を使用。同僚は各枠で交代可、禁止集合は最大1人。W内の確定勤務も適用。allowed_changes編集は未対応。CP-SAT | `coworkers.py/verify.py`、`test_coworkers.py` |
| 0.15 勤務回数 | `shift_count_balance` と `balance_id` 目的が対。対象/分類/期間を明示、評価期間はローカル00:00、目標は非負整数、未知/重複/nullを拒否 | 原勤務の最初の開始日時で1件、分割も1件、分類任意、明示0と対象外を区別。`shift_count_balance_summary`。省略は追加評価なし、空配列の形も保持。CP-SAT | `shift_counts.py/shift_patterns.py/verify.py`、`test_shift_counts.py/test_added_conditions.py` |

全行で各版のSchemaと公開型を維持先に対応付ける。型名の `Request01`〜`Request014` 等を除く前に、
`Request015` と必要な入れ子型へcallerを移す。`SchemaVersion/Request/Response/Solution/Verification`、
exports/stub/py.typedの最終整理は #111、配布は #114。

## 意味が変わりやすい具体例

### 完全充足と不足許容

同じ役割を二人必要とし、配置可能な従業員が一人の場合、旧0.1/0.2はINFEASIBLE。
0.15へ単に版だけを書き換えるとPARTIALを許すため、完全充足の移行では次の需要にする。

```json
{"id": "d", "role_id": "r", "interval": {"start": "2026-10-09T09:00:00+09:00", "end": "2026-10-09T10:00:00+09:00"}, "required_people": 2, "minimum_people": 2}
```

これは需要要素の部分例。0.3以降の不足許容に下限2を付けると逆に業務条件が強くなる。
省略/0の下限を維持すれば、同じ条件は不足60人分のPARTIALとなる。
priorityは必須充足の代替にならない。正の需要が全て完全充足、または全下限0だけをflow対象とし、
混在・中間下限・診断・非0 priority・明示制約・切替目的は #108 の範囲外とする。

### 候補とテンプレートと履歴

0.1の `{"id":"c","employee_id":"alice","interval":I,"breaks":B}` は
`{"id":"c","employee_id":"alice","segments":[{"interval":I,"breaks":B}]}` へ移す。
テンプレートは元の開始時刻×勤務長×休憩位置の直積をsegment_optionsへ移し、
旧版と同じ生成ID・候補集合・フィルタリングを固定旧環境で比較する。
日時やavailabilityを動かさず、旧版で不正だったテンプレートを新形状で救済しない。

旧0.1の履歴が `last_shift_end: null`、連勤数0なら確認済み空履歴なので、
`last_work_day: null` を明示できる。非nullの終了だけから勤務開始日を推測しない。
不足するlast_work_dayは利用者確認で止める。旧計算の終了日の帰属と移行後の明示勤務日を照合し、
確認値が旧連勤判定を変えるなら無条件の移行成功としない。

### 計画期間と文脈期間

月曜22:00〜火曜06:00の原勤務に00:00〜00:30の休憩がある場合、
火曜00:00からのWで勤務を再保存して開始日を火曜にしない。
元の月曜を勤務日とし、C内の実績/確定勤務は原区間のまま、Wへ重なる勤務は330分と数える。
月曜の実績と同じ勤務を新規候補として再選択しない。W外の確認済み事実を落とさず、未来の未入力を休日としない。

### 基準と固定と変更案

基準の勤務状態と担当状態は別で、待機はworkかつ担当なし。
preserve_assignedは担当済み枠だけを固定し、待機や不足枠を自動固定しない。
rebuildには明示固定/変更最小化を持ち込まない。Wを移す場合もsource_request/source_solutionと
source_fixed_statesを元Wで検証し、重複部分だけを今回比較する。

旧完全充足で `allowed_changes` がrequired_peopleを2から1へ下げることを許した場合、
移行でminimum_peopleだけ2に残すと変更案が消える。一方、元許可を超えて下限だけ緩めることも禁止する。
#109でrequired_peopleと等しい下限を同じ編集に対応させる方法を確定し、許可後の入力を0.15で再検証する。
diagnosis・suggestionsは元Responseの過去証拠を保持し、移行した正式解や新たな不可能性証明として転記しない。

## 保存データごとの扱い

担当は `@omitsuhashi`、エンジンの変換実装は #109/#110、アプリ変更はapp #30、
旧版除去前の保存往復は #125。本文には実在従業員データを転載しない。

| 保存単位 | 確認できた所在・版 | 原本保全と移行判断 |
| --- | --- | --- |
| Request | examples、評価入力、アプリ例。実版・全入れ子は棚卸しJSONに記録 | 元bytes/SHAを保持して別出力へ。0.1候補/履歴、0.1/0.2下限、baseline/diagnosisを先に処理。0.15は意味・既定値を変更しない |
| Solution | `examples/roster_conditions.solution.json`、baseline内、生成fixtureとアプリ保存案 | 解単体にschema_versionがないため必ず元Requestと組にする。原勤務・候補ID・休憩・担当を保持し、旧/新の独立検証を実施 |
| Response | 評価結果、fixture/実行記録、アプリplans.result | 原応答を過去証拠として不変保存。新検証のsummaryは新結果にし、OPTIMAL/proven_optimal/proven_minimalをコピーしない。解なし試行も保持 |
| baseline | 再計画例のsource_request/source_solution、source_fixed_states/snapshot_origin | 元期間で再帰的に移行・検証。入れ子参照を全部たどり、最後に公開make_baselineで投影。固定・来歴の落ちた単なるsnapshotへの置換を禁止 |
| RequestDraft | examples/adapterのdraft、testsで生成。outer 1.0、inner 0.1/0.3/0.4/0.6等 | 確認済み空と未確認、assumptions/unresolvedを保全。内版・意味・値・依存が変わる入力元のdigest/確認を失効。無変更部分の確認を一律失効させない |
| manifest/入力元 | assignment.manifest.jsonと明示された4参照ファイル、outer 1.0、inner 0.1 | 一つの参照単位として別出力へ。改訂・applies_to・順序・override・referencesを追跡し、追加下限や履歴を所有する元だけ更新。パス境界を緩めない |
| record | tests/test_adapter.pyとデモ操作で生成、常設保存recordは未確認 | 原Request/Response/実行設定/source/provenance、元run_idを保持。内容変更後は別run_id、元証拠とcurrent_verificationを別保存。外側形状が変わる場合だけ版を変更 |
| アプリJSON | schedula-app/1、engine pin、input文字列、plans、selected/baseline、edit。後述の合成代表1件を保存 | 旧restoreで全解を再検証→明示移行→新pinの新JSON/新セッションへ。未完成input/editを勝手に正規化しない。元証拠をevidenceへ、現在結果をresultへ |
| アプリSQLite | DB Schema 1、metadata.engine、sessionsとplans。合成代表は1セッション/2計画、実保存先は確認中 | 標準backupで整合した旧DBを保存。旧pinの読取・再検証後、新しい専用ディレクトリへ新pinのDBを作る。稼働原本/既存セッションを上書きしない |
| 過去測定・参照原本 | docs/evaluations/results、docs/reference | 歴史資料として版・当時の結果を保持。通常回帰と再実行入力だけ #107/#124へ対応付ける。過去の成功を新契約の証明に読み替えない |

実保存データがない形式にも意味の対応と各旧版の代表移行試験を残す。
発見時に元版に対応する固定環境で確認し、不正は拒否、不足事実は要確認、
変換できない元証拠は旧環境で保管する。汎用移行サービス・自動探索・通常入口の暗黙変換は作らない。

## 公開入口と実行環境

| 境界 | 維持する契約と検証 |
| --- | --- |
| 公開API | load_json/validate/solve/verify/get_schema/make_baseline、InvalidInput、JSONValue。入力非破壊、validateは探索なし、verifyは最適性を付与しない。`test_public_api.py/test_logging.py/test_schema_encoding.py` |
| Adapter | split_request/import_request/confirm_source/confirmation_state/assemble/read_draft/run_draft/create_record/check_record/reverify_record/record_view/save_json/get_adapter_schema。全所有項目はadapter.SECTIONS/EMPLOYEE_FIELDSと照合。`test_adapter.py`、型付きconsumer |
| CLI | solve/verify/schemaとadapter各action、stdin/UTF-8/厳密JSON/JSON stdout。終了0はOPTIMAL/FEASIBLE/VALID、PARTIAL/不正/無解/UNKNOWNは2。`test_cli.py/test_adapter.py/test_diagnosis.py` |
| 型/Schema | schema_versionを残し、欠落・不正型・旧版・未知版を明示拒否。既定Schema取得は #111 で0.15へ。Request/Response/Solution/Verificationとexports/stubを同時に移す。mypy strict consumerと誤記拒否を維持 |
| base依存 | jsonschema/tzdataのみ、OR-Toolsなしで入力検証・保存解検証・基準保存と従来対応のflow。依存不足はSOLVER_UNAVAILABLEとして明示、0.15の正の完全充足を #108 で補完。`test_timezone.py/test_minimum_demand.py/test_public_api.py` |
| 実行制御 | num_workers既定2、正のint32整数でbool不可。探索予算と外部総期限を区別。spawnの期限/取消/異常終了・一件の取消から独立した並行実行・cleanupを維持。`test_execution.py`、controlled_solve.py |
| logging | NullHandler、root logger非変更、JSON stdout維持、捕捉例外のDEBUG exc_info。従業員データをログ展開しない。`test_logging.py` |
| 時刻 | 既知offset・半開区間・UTC実経過分、DST/曖昧・不存在ローカル時刻拒否、OS TZDB優先/tzdata fallback。`test_timezone.py/test_input_contract.py/test_extended_roster.py` |
| OS/配布 | Python>=3.14、Linux/Windowsのbase/cp-sat CI matrix、macOS ARM64実測。Windowsの全中核/ブラウザーとfree-threaded/他実装は既存の未検証範囲。wheel/sdist隔離導入、LICENSE/依存表示/py.typedを保持 |

詳細は[Python公開API](../python-api.md)、[配布方針](../distribution.md)、
[入力Adapter](../input-adapter.md)、[CI](../../.github/workflows/ci.yml)に対応付ける。
旧固定環境は通常配布のwheel/sdistから除外し、
[Git保存した復旧用成果物](https://github.com/omitsuhashi/schedula/tree/main/docs/migrations/legacy)から取得する。
旧Schemaの常設再同梱で移行を解決しない。

## schedula-appの接続と保存の決定

現行機能の更新は既存 [app #30](https://github.com/omitsuhashi/schedula-app/issues/30) 内の先行PRとする。
共通エンジンは公開APIを提供し、アプリが session_id/version/plan_id、取込・採用・保存を所有する。

| 現行操作 | 移行に必要な変更と不変条件 |
| --- | --- |
| 編集・計算 | vendor wheel/manifest/依存パス/lock、公開Schemaを0.15の候補へまとめて更新。form/サンプル/JSON/HTTPの契約を揃え、文字列inputは未完成のまま保存できる |
| 比較・採用 | 同じ新条件でpreserve_assigned/rebuildを別実行。原Request/解は不変、採用前に公開verify。PARTIALの採用を完全充足や実績としない |
| 月次・個人別・比較 | 元Request/原勤務/現在verifyの不足・全summaryを渡す。分数・日数・回数・費用・状態差と証明範囲を区別。表示のための再求解や別業務集計器を作らない |
| JSON取込・保存 | engineのversion/schema_version/commit/sha256は引き続き完全一致。旧JSONを通常restoreで黙って受け入れない。明示移行入口が旧pinを旧環境で照合して別ファイルを作り、その後通常restoreへ渡す |
| SQLite | DBのテーブル形状が同じならDB Schema 1を保つ。metadata.engineだけの書換えは禁止。新pinの新DBへ検証済みセッションを明示取込。保存競合のexpected_version・トランザクションと無変更失敗を維持 |
| 元証拠 | evidenceを旧Responseとして保持、resultを現在verifyにする。selected/baseline参照とplan IDの対応を保持、取込先session IDは新規。不正・未確認editは採用可能に変えない |
| 復旧 | 旧wheel/lock/pinと整合バックアップを別配置へ復元して全計画を再検証。旧/新DBを混在させず、更新後入力・未保存編集の消失を伴う切戻しは所有者の判断対象 |

外側のschedula-app/1とDB Schema 1は、保存項目・意味を増減しない上記の契約移行では維持できる。
厳密なpin照合が旧新の混同を防ぐ。#125で項目追加が必要と判明した場合は、
外側の版変更と明示変換を同じPRで定義し、無断のshape拡張をしない。
新しい構造化RequestDraft・入力元確認・改訂/来歴の日常操作・run_idの保存は未接続であり、
今回の既存操作維持のために一律追加しない。app #30の別機能開発として残す。

#125では最終wheelの完成を待たず候補commit/SHAで、代表旧JSON/DBの
復元→再検証→再計画→保存→再読込、完全/PARTIAL、pin不一致・不正・保存競合・失敗からの復旧を通す。
原本SHA・候補pin・期待値・結果を #105/#111/#115へ渡す。
実データ未入手なら保存した合成代表を暫定証拠とし、実在すると確認した未移行データを残してゲートを閉じない。
#115は #114 の最終固定wheelで実Chromium・採用・再起動・保存を再確認し、app #30全体とは別に判定する。

## 旧固定環境の保管と再現

復旧用Gitディレクトリには0.1.6の新規固定wheel、0.1.5の既存wheel原bytes、
それぞれのuv.lock、ハッシュ付きruntime requirements、アプリbackend固定source archive、
合成代表JSON/SQLite、SHA/版/構築条件manifestを保存した。アプリのruntimeとエンジンbase/extraを分け、
開発機のeditable導入や別checkoutを検証環境に使わない。

0.1.6は基点commitの `SOURCE_DATE_EPOCH=1791463601 uv build --wheel` で構築した。
過去PRの候補wheelと同一bytesであるとは主張しない。アプリ0.1.5は既存SHAと一致する。
CPython3.14.8、uv0.12.23、macOS ARM64の隔離導入で以下を確認した。

| 固定環境 | 今回の期待値と確認結果 |
| --- | --- |
| 0.1.6 | assignment: OPTIMAL/不足0、partial_assignment: PARTIAL/不足60人分、combined_conditions: PARTIAL/不足120人分。各解の公開verify成功。Adapter recordの再検証成功 |
| app 0.1.5 | 合成代表の完全/PARTIAL二案を求解して旧restoreへ通し、VALID/PARTIALへ再検証。証明フラグfalse、元JSON不変。SQLiteはDB Schema 1、1セッション/2計画、quick_check成功・外部キー違反なし。固定archiveから展開したbackendのcheck_savedと別保存先へのrestore_backupも成功 |

これは旧環境の再作成と期待値の保存であり、0.15へのデータ変換・アプリ更新・新旧保存往復の完了証拠ではない。
取得・SHA照合・再作成コマンドは保存ディレクトリのREADMEを使う。
依存wheel全bytesのオフラインミラーは作らず、再導入にはlockした配布元への接続が必要。

## 後続Issueへの引き渡しと除去条件

| 担当Issue | この棚卸しから渡す条件 |
| --- | --- |
| #107 | 表の全維持テスト、各0.1〜0.14代表移行fixture、共通0.15 fixture、現行0.15の独立した意味/既定値回帰。基点commit/成果物を使い、測定前に性能/解品質の許容範囲と責任者を固定 |
| #108 | 独立assignmentの全正需要が完全充足か全下限0のflow。一般下限やCP-SATの制約/priority/診断へ拡張しない。依存なしwheelと競合需要も検証 |
| #109 | 全旧版の代表、0.1形状・履歴要確認、0.1/0.2完全充足、基準/固定/許可編集。確認済み対象の一回限りの明示変換、原本非上書きと失敗/再実行を検証 |
| #110 | Draft/manifest/入力元/recordの全所有項目、確認失効、新run_id、旧証拠と現在検証、原子保存とパス境界を保持 |
| #124 | 棚卸しの現行examples/評価再実行入力、フォーム/JSON/型付き例と通常回帰を0.15へ移す。旧代表は移行fixtureへ、過去測定は履歴として保持 |
| #125 | app #30の上記接続/保存仕様、合成代表と実保存先調査結果、固定旧環境。候補wheelで旧版除去前に保存往復。最終wheelを待たない |
| #111 | 上記準備完了後、内部整理と最終拒否を複数PRで実施。schema_versionの0.1 fallback、旧型/Schema/デモ失敗応答まで追跡。全summary/null/0と不正応答契約を0.15へ揃える |
| #112/#113 | 最終画面/拒否と文書整合。ADR-0003/0004/0005/0009、io-contract-next、distributionの旧常設保証を履歴と区別して改訂。次回契約追加時の互換・移行・終了条件も記録 |
| #114/#115 | 破壊的変更を識別する新配布版、固定成果物SHA/lock、隔離base/extra/wheel/sdistと既存OS。最終アプリ受け入れを候補成功と区別 |
| #116 | 対応表全行、旧→新と現行0.15維持の別比較、性能/解品質・全CI/main・実Chromium・保存/復旧。未解決の退行を残して全体完了としない |

旧版除去を妨げる事項は、完全充足flowの補完、明示移行/確認失効の実装、通常callerの0.15化、
候補アプリ保存往復、実保存先確認である。実保存先・件数は確認中として #105/#106へ記録し、
未知を0件としない。対象を拡大する情報が出た場合は一覧に追加し、後続責任と除去条件を更新する。
各PRの全必須CI・skip拒否・独立検証・実Chromiumを維持する。
PyPI公開・GitHub Release・実環境デプロイは #105 の完了条件に含めない。
