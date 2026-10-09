# 現行の入出力契約0.15

利用者・組込アプリの開発者が、確定した入力を検証し、解・不足・証明を読み分けて採用と再計画を行うための仕様です。
現在の通常入口は `schema_version: "0.15"` だけを受理します。版の省略・未知版・旧版は拒否し、暗黙変換しません。
パッケージ版、JSON契約版、Adapterの外側形式版は別の識別子です。

機械で検査する完全な形状は[Request Schema](../src/shift_schedula/schemas/0.15/request.schema.json)と
[Response Schema](../src/shift_schedula/schemas/0.15/response.schema.json)にあります。
本書は全業務機能の現在の意味をまとめ、過去の契約追加文書を前提にしません。

## 確定入力と公開入口

| 入口 | 入力・結果と役割 |
| --- | --- |
| `load_json(text)` | 重複キー、非有限数、不正JSONを拒否してJSON値を読む |
| `validate(request)` | Schema・参照・日時・業務条件を確認。ソルバーを読み込まず、実行可能性を証明しない |
| `solve(request, num_workers=2)` | 条件に対応する一つのbackendを選び、独立検証に成功した解だけを返す |
| `verify(request, solution)` | 原入力と返却解から条件・集計・目的値を再計算。ソルバー・最適性認定は使わない |
| `make_baseline(request, solution, plan_id)` | 有効なroster解を再検証し、元Request・元解・固定状態を次の基準へ保存 |
| `get_schema(kind, schema_version="0.15")` | request/response/solution/verificationの現在Schemaを取得。旧版はValueError |
| `split_request/import_request/assemble` | 入力元と確認を保ったDraftを作り、組み立てたRequestを既存validateへ渡す |

dictを直接渡す場合もJSON型・有限数・非循環構造を要求します。boolを整数の代用にしません。
未知項目・参照不明・重複IDを拒否します。IDは英字で始まる80文字以内の英数字・`_ . -`、
labelは400文字以内です。欠落・確認済み空集合・明示0・対象外を勝手に同一視しません。

Requestの必須項目は `schema_version/request_id/problem_type/planning_window/skills/roles/employees/`
`demand/shift_candidates/constraints/preferences/objectives/solver`。
不要な必須配列も空配列を明示します。rosterの任意機能は次の各節の項目で指定します。

| 基本項目 | 意味 |
| --- | --- |
| `planning_window` | start/end/timezone/slot_minutesで計画期間Wと粒度を指定 |
| `skills` | id/label。登録した技能の集合 |
| `roles` | id/label/required_skills。各技能のskill_idとmin_levelを全て満たす人だけ担当可能 |
| `employees` | id/label/skills/availability。保有技能はskill_id/level。空availabilityは勤務不可 |
| `demand` | id/role_id/interval/required_peopleと任意minimum_people/priority |
| `shift_candidates` | roster用の有限候補。assignmentでは空。候補外の勤務時刻を探索しない |
| `constraints/preferences/objectives` | 必須条件、選好、辞書式最小化の尺度を別々に指定 |
| `solver` | backend/time_limit_seconds/seed。期限は全探索段階で共有 |

## 日時、担当配置、需要

全区間は正の半開区間 `[start, end)`。日時には既知のオフセットを付け、秒・小数秒を持つ時刻を拒否します。
IANA timezoneと粒度1/5/10/15/20/30/60分を使い、対象区間は計画開始からの粒度に揃えます。
DSTの曖昧時刻・存在しないテンプレート時刻は拒否し、明示オフセットの区間はUTCで実経過分数を測ります。
暦日数・勤務日はローカル日付で判定し、実経過24時間の商で代用しません。

`assignment`は勤務可能な枠で担当する人・役割だけを決め、出退勤・休憩は選びません。
同じ人は同じ枠で一役割。技能はAND条件で、必要レベル0でも未保有技能を有資格とは扱いません。
同じ役割の需要区間の重複を拒否し、未指定の枠の需要は0。過剰配置を許しません。

`minimum_people`は省略時0、`0 <= minimum_people <= required_people`の必須下限です。
完全充足を要求する場合は各需要へ `minimum_people = required_people` を明示します。
required_peopleは元需要であり、不足を隠すために減らしません。
下限を満たした有効計画でも元需要へ不足があればPARTIAL、下限違反は有効なPARTIALにはなりません。

探索順は不足総量（実経過人分）→priority降順の各需要群の不足→objectives配列順。
priorityは省略0の非負整数。同じ不足総量でのみpriorityを比較し、優先需要のために不足総量を増やしません。

## 勤務候補・テンプレート・履歴

`roster`は有限勤務候補の選択と担当配置をCP-SATの同じモデルで決めます。
候補はid/employee_id/segments。各segmentはinterval/breaksを持ち、1勤務に1〜4区間です。
同じ従業員の同じ原勤務開始日に最大1候補を選びます。夜勤を翌日の別勤務へ分割しません。
勤務区間全体はavailability内。休憩は勤務区間の両端に接しない正の内部区間で、重複を拒否します。
分割区間の間は正の非勤務時間です。休憩・分割間は担当不可、待機は担当せずに勤務する状態です。

テンプレートはid/employee_ids/dates/start_times/segment_optionsを持ちます。
各選択肢はsegmentのoffset_minutes/duration_minutes/breaks。休憩offsetは該当segment開始から測ります。
展開した候補を日時・勤務可能時間で絞り、候補IDと展開は順序によらず決定的です。
テンプレートの時刻を丸めたり、使用不能な候補を広げたりしません。

continuityを使わないrosterの全従業員にhistoryを要求します。
last_shift_end/last_work_day/consecutive_work_days_before_windowを明示し、履歴なしはnull/null/0。
最終勤務時刻・原勤務日・直前連勤数の矛盾、未来履歴、日付不明を拒否します。
履歴から過去の個々の勤務日や勤務分類を推定しません。

## 継続計画と原勤務

任意の `continuity` はcontext_window（文脈期間C）と全従業員の確認情報を持ち、WをC内に置きます。Cの両端はローカル00:00です。
continuityとemployees.historyの併記は拒否し、W外の原勤務・休憩は整数分のまま保持します。
各人へemployee_id/before_context/actual_shifts/committed_shifts/past_complete/commitments_completeを明示します。
完全性フラグはtrueを要求し、確認済み空配列と未確認を区別します。
actualは過去実績、committedは既知の確定勤務で、原id/segmentsと休憩を保持します。

Wへ伸びる原勤務も切断して保存しません。担当変数はWへ投影し、実績・確定勤務・新規選択を一度ずつ数えます。
確定勤務は自動解除せず、未入力の未来を休日や勤務として補完しません。
文脈外・重複・アンカー矛盾・不完全な履歴は入力不備です。
勤務量、休息、連勤は確認済み過去・確定勤務と新規選択を照合します。

## 必須条件

各ルールは一意id/typeと空でない既知employee_idsを指定します。分数・日数・回数は整数です。

| type | 項目と意味 |
| --- | --- |
| `max_assigned_minutes` | limit_minutes。担当分数の上限。両モード、待機は除外 |
| `max_role_switches` | limit_count。隣接する担当枠間の役割変更。休憩・待機を挟む変更は数えない |
| `max_scheduled_minutes` | limit_minutes。休憩を除き待機を含む勤務分数の上限 |
| `min_rest_minutes` | limit_minutes。原勤務の最終終了から次の開始まで。直前履歴とも照合 |
| `max_consecutive_days` | limit_days。原勤務開始日の連勤上限。直前連勤を引き継ぐ |
| `min_split_gap_minutes` | limit_minutes。分割区間間の最小非勤務時間 |
| `scheduled_minutes_bounds` | intervalとmin_minutes/max_minutes。期間内の休憩を除く勤務分数の上下限 |
| `work_days_bounds` | intervalとmin_days/max_days。原勤務開始日が期間内にある勤務日数 |
| `days_off_bounds` | intervalとmin_days/max_days。全く原勤務区間に触れない完全休日数 |
| `forbidden_shift_successions` | evaluation_period/from_category_id/to_category_id/day_offset。原開始日間の指定日差で禁止する分類の並び |
| `days_off_after_shift` | evaluation_period/category_id/min_days。該当勤務終了と最後の占有日の後、指定数の完全休日を要求 |
| `min_consecutive_days_off` | evaluation_period/min_days。期間と交差する完全休日の最大連続区間を下限以上にする。完全休日がない場合は違反しない |
| `worked_date_groups_limit` | evaluation_period/date_groups/max_groups。明示日群のうち原勤務が触れる群数の上限 |
| `required_coworkers` | interval/coworker_ids/minimum_people。対象者の勤務枠で必要な同僚人数を要求 |
| `incompatible_employees` | interval。対象集合の同時勤務者を最大1人とする。対象2人以上 |

最初の2ルール以外はroster専用です。上下限は少なくとも片側を指定し、省略側は無制約、nullと逆転を拒否します。
達成不能な有効下限は入力不備とはせず、必須条件を満たす解がない場合にINFEASIBLEとなります。

勤務日数と占有日数は別です。夜勤は開始日の1勤務日、触れる暦日は複数の占有日になります。
休憩も原勤務区間として日を占有し、分割間は占有しません。終端00:00は翌日を占有しません。
日数評価の両端はローカル00:00。確認済みCの開始からWの終了まで評価でき、未入力未来を休日と見なしません。

`shift_categories`はid/label/intervals/min_overlap_minutesで明示する勤務分類です。
区間和集合と原勤務全体の休憩を除く交差分数が閾値以上なら該当します。複数分類へ該当可能です。
夜勤・祝日は名前から推定しません。パターンは原開始日と原区間で判定し、W投影後の形状で分類しません。
禁止並びはday_offset分、連続休日はmin_days分の前後余白を要求し、夜勤後休日には必要な未来をW内に置きます。
不足範囲はINCOMPLETE_HISTORYのrequired_start/required_endで返し、一部候補を黙って捨てません。
確認済み実績だけで完結する違反を遡及判定しません。

同僚の勤務は待機を含み、休憩と分割間は除きます。指導者の交代を許し、同じ人は複数対象者を支えられます。
対象集合とcoworker_idsの交差、最低人数0・同僚数超過を拒否します。指導容量・担当役割は推定しません。
同時勤務禁止は集合全体で最大1人であり、3人集合の2人を許す容量条件ではありません。

## 選好、目的、整数尺度

選好は `avoid_role`（role_idとpenalty_per_minute）、`prefer_work/avoid_work`（intervalとpenalty_per_minute）。
選好があればpreference_penalty目的を要求します。希望は必須の禁止・固定と別で、必要な選好違反を許します。
明示した対象者と区間だけを使い、技能者全員や勤務希望を自動生成しません。

全目的を整数で最小化し、配列順を辞書式に優先します。大きな重みの和へ置換しません。
最大46目的。通常metricの重複を拒否し、duty_deviation_minutesはduty_id、shift_count_deviationはbalance_idごとに一意です。

| metric | 評価値 |
| --- | --- |
| `preference_penalty` | 担当・勤務・非勤務の対象分数×明示ペナルティの加算 |
| `scheduled_minutes` | W内の休憩を除く勤務分数。待機を含む |
| `role_switches` | 隣接担当枠の役割変更回数 |
| `fairness_deviation_minutes` | 明示対象者の勤務分数と目標の絶対偏差合計 |
| `plan_changes` | 重複期間の枠ごとの勤務状態差と担当状態差の合計 |
| `scheduled_cost` | W内勤務分数×各従業員の整数分単価の合計 |
| `duty_deviation_minutes` | 指定区間和集合での勤務分数と目標の絶対偏差合計 |
| `shift_count_deviation` | 原勤務件数と目標回数の絶対偏差合計 |

fairnessはevaluation_periodとemployee_targets（employee_id/target_minutes）を対応目的と対で指定します。
未指定者は対象外、明示0は0目標。比率・自動均等割り・契約時間による正規化はしません。

costsはcurrency（大文字3文字）/units_per_currency/employee_ratesをscheduled_cost目的と対で指定します。
候補がない人も含む全従業員のunits_per_minuteを要求し、明示0を欠落と区別します。
費用はW内だけで、休憩・分割間・W外の実績/未来は加算しません。途中の丸めをせず整数単位で返します。
給与・税・為替・日額・時間帯単価を自動計算しません。

duty_balanceはid/label/evaluation_period/intervals/employee_targetsを1〜20定義し、目的のduty_idと1対1です。
同一定義の重複区間は和集合、異なる定義の重複は許可。確認済みC内ではactual/committed/selectedを一度ずつ数えます。
shift_count_balanceはid/label/evaluation_period/employee_targetsと任意category_idを1〜20定義し、目的のbalance_idと1対1です。
両端ローカル00:00の評価期間に原勤務の最初の開始が入り、指定分類へ該当すれば1回。分割数・分数・夜勤明けの日は回数にしません。
未指定category_idは全勤務、nullは不正。未確認の計画外を自動補完しません。
どちらも明示0と対象外を区別し、必須条件を緩めないソフト目標です。待機勤務を抑える場合は勤務量/費用の優先順を指定します。

## 基準・固定・再計画

baselineはplan_id/source_request/source_solutionと、保存されたsource_fixed_states/snapshot_originを持ちます。
元Requestと元解を元期間のまま保持し、入力条件・参照・全原区間を再検証します。
埋込Requestも0.15のみ。baseline/diagnosisの再帰ネストを拒否します。

新旧Wは同じtimezone/粒度で枠境界が揃い、正の重複を持ち、比較と自動固定は重複枠だけに適用します。
基準を新Wへ切り詰めず、期間外の原条件や確認済み実績の改ざんも検出します。
固定対象はfixed_partsのemployee_id/interval/components（work/role）で指定します。
workは勤務/休憩/非勤務、roleは担当または担当なしの基準状態を保持します。

`replan_mode: preserve_assigned`は既に担当済みの枠だけを自動固定し、未担当・不足枠は埋められます。
`rebuild`は元比較基準を保持して全体を再計画し、fixed_partsとplan_changes目的の併用を拒否します。
省略時は明示固定と指定目的だけを使う従来の再計画です。目標・単価の変更だけを勤務状態変更へ加算しません。
新期間のavailability・日付条件・履歴・分類・目標は利用者が明示し、自動で翌週へ移しません。
make_baselineは有効なPARTIALも保存でき、保存時の証明を新しい求解・独立検証へ転記しません。

## 診断と許可変更案

diagnosticsはcode/message/json_pointer/related_ids/factsで入力・条件・結果へ追跡します。
messageは補助で、機械側はstatus/codeを使います。診断なし入力で変更案探索は行いません。

diagnosisはtime_limit_seconds/max_suggestions/allowed_changesを指定します。
許可選択肢はidと1〜20 edits、各編集はjson_pointerと整数value。最大100選択肢・10提案です。
需要のrequired_people/minimum_people、対応ルールのlimit_minutes/limit_days/limit_count/min_minutes/max_minutesだけを編集できます。
日数上下限・勤務分類・同僚集合・技能・availability・候補・固定の編集は未対応として拒否します。
同一項目の重複編集を拒否し、別選択肢を勝手に組み合わせません。元Requestを変更しません。

元条件のINFEASIBLEとsolution:nullを維持し、変更後のmodified_request/responseはsuggestionsに分けます。
条件グループの削除試行でも技能・候補・実績・確定勤務等の背景を保持し、ソフト目標を矛盾原因にしません。
conflict_refinementを指定すると診断全体以下の予算で包含極小性を調べます。
UNKNOWNで条件を除去せず、background_only/checks/minimalityの証明範囲を明示します。
包含極小は要素数最少・唯一原因と別です。縮小途中の緩和解を正式解として返しません。

元計画がOPTIMAL/FEASIBLE/PARTIAL/UNKNOWNならNOT_APPLICABLEで提案探索を行いません。
診断結果はCOMPLETE/TIME_LIMIT/ERROR/UNSUPPORTED/NOT_APPLICABLEを区別します。
提案は許可変更後の独立検証に成功した完全なOPTIMAL/FEASIBLEだけで、元条件の解と混ぜません。
診断予算は通常探索と別で、追加の検証・探索・縮小・変更後検証を含みます。

## 応答と独立検証の採用境界

Responseはschema_version/request_id/status/solver/solution/objectives/diagnostics/verification/statsと全summary/diagnosis_resultを持ちます。
有効なsolutionはassignments（employee_id/role_id/interval）とshifts（candidate_id/employee_id/work_day/segments）。
原勤務区間・休憩を保ち、同一担当の隣接枠は併合します。solver.backend/selection_reason/library_versionで実方式を追跡します。

| status | 解と意味 | solveのCLI終了コード |
| --- | --- | --- |
| `OPTIMAL` | 需要を満たし全探索段階の最適性を証明、独立検証成功 | 0 |
| `FEASIBLE` | 需要を満たす独立検証済み解、未証明の探索段階あり | 0 |
| `PARTIAL` | 必須条件・下限を満たす独立検証済み解、元需要に不足あり | 2 |
| `INFEASIBLE` | 必須条件を満たす解がないと証明 | 2 |
| `UNKNOWN` | 解も不可能性の証明もない | 2 |
| `INVALID_INPUT` | 入力不備。指摘箇所を修正 | 2 |
| `BACKEND_UNAVAILABLE` | 必要なcp-sat extraがない | 2 |
| `INTERNAL_ERROR` | 処理・独立検証の障害。解を採用しない | 2 |

解なしはsolution:null/objectives:[]、未実施検証はperformed:false/valid:null、全summaryはnullです。
適用しない任意機能のsummaryもnull。有効な明示0・空群・0回対象者は省略しません。

shortage_summaryはtotal_person_minutes/proven_minimal/shortages、各不足行は需要・役割・区間・
required_people/minimum_people/assigned_people/missing_peopleを持ちます。
priority_summaryは降順groupsでpriority/total_person_minutes/proven_minimalを返します。
objectivesは入力順のid/metric/value/proven_optimalと該当duty_id/balance_idを保持します。
証明は不足総量→priority群→利用者目的の連続した接頭辞だけ。未証明上位の後に最適性を付与しません。
PARTIALの不足最小性と需要充足、独立検証成功と最適性を別に読みます。

fairness_summary/change_summary/continuity_summary/cost_summary/duty_balance_summary/day_count_summary/
shift_count_balance_summaryは原条件と原解から各節の尺度を再計算した集計です。
変更量はwork_changes/role_changesと比較期間、日数はwork_days/occupied_days/days_off、
費用はtotal_unitsと各人cost_units、分数・回数偏差は目標/実績/偏差と非正規化の尺度を返します。

公開verifyはVALID（完全）/PARTIAL（有効不足）/INVALID_INPUT/INVALID_PLAN/INTERNAL_ERRORを返します。
VALIDだけCLI終了0、他は2。有効な場合のみdemand_satisfiedがtrue/false、集計・目的を返します。
無効な解はperformed:true/valid:false、入力不備と障害は未実施。全証明フラグはfalseです。
ソルバーの候補係数・保存された目的値を信用せず、元Requestと返却解から独立して確認します。

## backend、予算、実行上限

autoは対応能力から一つのbackendを選びます。独立assignmentで制約なし・加算選好だけなら最小費用流を使います。
完全充足の下限同値と下限0の不足許容に対応し、一般の正の下限・非0 priority・勤務計画・複合条件はCP-SATです。
min_cost_flowを明示して未対応条件を渡すとINVALID_INPUT。依存不足で条件を減らした別解へ置換しません。
base導入だけでvalidate/verify/完全需要flowは実行可能です。

solver.time_limit_secondsは0超〜300秒、seedは0〜2,147,483,647、num_workersはCPU探索の明示設定です。
モデル準備後の全探索段階で同じ予算を使い、入力検証・import・候補展開・モデル構築・結果検証とは区別します。
stats.elapsed_secondsとSEARCH_STATSで総時間・探索時間を追跡します。
外側の応答期限・プロセス隔離・並列受付は[実行制御の例](../examples/controlled_solve.py)の公開用途を参照します。

| 上限 | 値 |
| --- | --- |
| 従業員・役割・技能 | 250人・50役割・100技能 |
| 時間枠・従業員×時間枠×役割 | 3000・1,000,000 |
| 需要・制約・選好 | 10,000・1000・1000 |
| 明示/展開候補・選択勤務 | 件数上限なし。他の入力上限と計算資源を適用 |
| テンプレート | 100定義、各365日/96開始時刻/20選択肢まで |
| 固定・比較の従業員和集合 | 500人 |
| 一般の分数・日数・回数係数 | 0〜10,000,000。個別条件の正値・人数上限も適用 |
| 費用単価・倍率 | 1分単価0〜1,000,000,000、倍率1〜1,000,000 |
| 費用の保守的総和・内部整数式 | 2**53−1・2**60−1以下 |

上限内の応答時間・実店舗の性能を保証しません。最適性は指定した有限候補・条件・尺度の範囲です。
給与・法令適合・自動緩和・候補外の連続時刻探索・LLM生成コードの実行は対象外です。

## Adapterと実行記録

外側形式はadapter_version/manifest_version/record_versionが1.0、内側契約は0.15だけです。
入力元はbasic/common/period/history/replanning/executionの所有範囲、id/revision/origin/data/applies_to/references/confirmationを持ちます。
確認は値・改訂・適用期間・依存参照へ結びつき、影響する確認だけ失効します。
assembleは純粋な組立境界で、確認・所有範囲・参照・重複・衝突を検査し、ソルバーを起動しません。
基本情報と期間非依存ルールを再利用し、日付条件・availability・実績・基準を自動で移動しません。

run_idはrequest_idとは別。記録は確定Request/Response、入力元・由来、実行設定・配布版・依存版を一組で保持します。
保存済みverificationは過去証拠で、reverify_recordのcurrent_verificationとは別です。
再検証で元の最適性・不足最小性を復活させず、記録内容の付替え・未知版・不正入力を拒否します。

manifestは明示した相対ファイルだけを親ディレクトリ内で読み、絶対パス・親参照・symlink・URL・暗黙探索を拒否します。
ローカルI/Oは通常ファイルだけ、1ファイル16 MiB・合計64 MiB・32ファイルまで。
save_jsonは原入力保護・原子的保存・明示上書きで既存記録を保護します。
ブラウザーは貼付/アップロード/インライン入力だけで、任意サーバーファイルを読みません。
詳細なファイル構成とCLI例は[分割入力・実行記録](input-adapter.md)にあります。

## 実行例とサポート

```sh
uv sync --locked --extra cp-sat
uv run --no-sync python -m shift_schedula schema request
uv run --no-sync python -m shift_schedula solve examples/assignment.json
uv run --no-sync python -m shift_schedula solve examples/combined_conditions.json
```

最初の求解は完全なOPTIMAL、結合例は有効な不足が残るPARTIALで終了2です。
返却solutionを別ファイルへ保存して `python -m shift_schedula verify REQUEST SOLUTION` で独立検証できます。
公開型はRequest/Response/Validation/Verification/Solution、現在の構築型はRequest015等です。
旧版専用のRequest01〜Request014等は提供しません。

旧保存物を今回検証した範囲は[移行の受入記録](migrations/contract-0.15-integration.md)にあります。
一回限りの変換スクリプトと旧fixtureは検証後に撤去し、固定commit・原SHA・移行先SHAを履歴に保持しました。
新しい破壊的変更には別のパッケージ版を使い、今後の互換性・旧契約の終了条件は
[サポート方針](contract-support.md)に従います。PyPI公開・GitHub Release・実顧客デプロイは別作業です。
