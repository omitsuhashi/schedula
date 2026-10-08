# 分割入力・確認と実行記録

[マイルストーン8](https://github.com/omitsuhashi/schedula/milestone/8)の共通Adapterです。
実行契約0.1〜0.15、エンジン基点 `cd0787c194b1d3f592742f3a975d647aee694202`、
配布版0.1.6を対象とします。Python 3.14.8、jsonschema 4.26.0、
OR-Tools 9.15.6755、tzdata 2026.5は `uv.lock` の版です。
外側の `adapter_version: "1.0"` は実行契約とは独立しています。

## 入力と所有元

RequestDraftは `schema_version`、`sources`、`unresolved`、`assumptions`、
`overrides`、`order` を持ちます。入力元は `id`、`revision`、`section`、
`data`、`references`、`applies_to`、`confirmation` を持ちます。
`data` は次の所有元に従うRequestの部分オブジェクトです。
六区分は分類であり、空の区分や六ファイルを要求しません。

| Requestの項目 | 所有元 | 必要情報・保存/表示 |
| --- | --- | --- |
| schema_version | Draft直下 | 0.1〜0.15。自動移行しない |
| skills, roles | basic | 必須。空も明示。全項目を保存 |
| employees.id/label/skills | basic | 全員の順序と技能を保存 |
| employees.availability | period | 全員に明示。`[]` は勤務不可、欠落は未入力 |
| employees.history | history | rosterで採用する履歴。未確認を0/nullにしない |
| request_id, problem_type, planning_window | period | 必須。今回の期間を明示 |
| demand | period | 必須。required_people/minimum_people/priorityを保持 |
| shift_candidates, shift_templates | period | rosterの有限候補。日付を自動移動しない |
| constraints | common / period | 日時を持たないルールはcommon。日付/絶対区間付きはperiod |
| preferences, shift_categories | period | 日時付き条件。未指定と空を区別 |
| continuity | history | 原実績・確定勤務・文脈期間・完全性宣言を保持 |
| baseline, fixed_parts, replan_mode | replanning | 原基準期間と固定状態を保持 |
| objectives, solver, fairness, costs, duty_balance, shift_count_balance, diagnosis | execution | 目的の配列順・明示0・対象外・探索設定を保持 |

この表は0.1〜0.15の全トップレベル項目とemployeeの全項目を含みます。
ネストした全フィールドの型・必須性・上限・業務意味は選んだ実行版のSchemaと
既存validateが正本です。constraintsは利用者が明示した必須条件、preferencesと
objectivesは選好です。新しい制約判定器や候補展開器は追加しません。

同じ区分は複数入力元に分けられます。employeesはbasicのID/順序を基準に
項目単位で結合し、他区分の不明ID・同一区分内の重複・同一項目の所有競合を拒否します。
constraintsだけは入力元順に連結できます。`order.constraints` に全IDの順序を
指定すればその順を保持します。objectives等の他の配列は丸ごと一つの所有元に置きます。
確認済み空配列も一つの所有値です。必須項目の欠落は補完しません。

明示置換はcommonのconstraint一件をperiodで同じIDのルールへ置き換える操作だけです。
`overrides` に `source_id`、`target_source_id`、`constraint_id`、変更前の `before`、
`reason` を置きます。変更後はperiod.data.constraintsの同じIDです。
変更前が一致しなければ拒否し、両入力元と理由を保存します。
後勝ちmerge・暗黙の条件緩和・汎用patch DSLはありません。

## 確認と失効

`confirmation: null` は未確認、空集合を含む値のdigestを明示操作で記録すると確認済みです。
`confirm_source(draft, source_id)` は入力元一件を確認した新しいDraftを返します。
`confirmation_state(draft)` は各入力元の現在のdigest・保存digest・状態を返します。
根拠文と仮定は表示/保存するデータであり、コードや条件として実行しません。
未解決項目はsource_id、json_pointer、messageを持ち、残っていれば実行を止めます。
仮定はassumptionsに文字列として残し、解消/採用は入力者が決めます。

確認のdigestは値、入力元ID/改訂、references、applies_to、実行版、関連する置換/順序、
参照マスターの必要項目に結びつきます。periodは現在のplanning_window、historyは
continuityのcontext_window（未採用ならplanning_window）、replanningと日時付きexecutionも
現在のplanning_windowに結びつきます。確認対象期間をapplies_toで明示します。
実績・確定勤務・baselineの値は原期間のままです。

従業員/同僚・技能・役割・分類のID参照を自動追跡します。commonは従業員の存在、
periodは参照者の技能と役割の必要技能、分類参照は分類値へ依存します。
ラベル変更や無関係の入力元改訂では他の確認を失効させません。
勤務可能時間の変更はその入力元、計画期間の変更は期間依存元を失効させます。
基本情報や期間非依存ルールの再利用に今回の期間の確認を要求しません。
確認は出典の真正性や法的適合性の証明ではありません。

`import_request(request)` は既存validateが受理した完全Requestを、originがunknownの
単一入力元へ取り込みます。業務値の有効性と出典不明を区別し、元の履歴宣言を保持します。
取り込んだままなら確認済みマスターと偽らず組み立てできます。編集すれば確認が失効します。
`split_request(request)` は六区分へ分けた未確認Draftを作ります。
日時付きデータの所有元を分類するだけで、勤務形状/適用日の別DSLは作りません。

`assemble(draft)` はrequest（成功時のみ）、provenance、diagnostics、confirmations、
status（VALID / INVALID_INPUT / INTERNAL_ERROR）を返します。ファイル・DB・ネットワーク・
ソルバーにはアクセスしません。受理したRequestの実行可能性はsolveへ委ねます。
診断のcode/json_pointer/related_ids/factsを保ち、sourcesに元ID/改訂/区分/元pointerを付けます。
複数所有競合では双方を示します。provenanceは確定Requestのpointerから入力元へ対応します。

## ファイルとCLI

`manifest_version: "1.0"`、`draft`（sources以外のDraft項目）、`files`（相対パス配列）の
manifestを `read_draft(path)` へ渡します。参照先は入力元一件のJSONだけでincludeはありません。
基点はmanifestの親。絶対パス・親参照（`..`）・内外へのsymlink・重複参照を拒否します。
manifest自身のsymlinkも拒否し、通常ファイルだけを開きます。
標準入力 `-` はインラインDraftのみ。ファイル参照の基点はありません。

ローカルCLIはmanifest/Draft/入力元/実行記録それぞれ16 MiB、入力元は最大32件、
manifestを含め総64 MiBです。読み込み中にも上限を検査します。
ブラウザーはアップロード/貼付けのインラインDraft/実行記録のみ、本文2 MiB、
最大100人・30日・3000枠で、上限超過は拒否します。サーバー上の任意パスは読みません。
100人・30日の組み立て/保存はCLI上限内で検証し、詳細表示はdemo上限内で確認します。

```sh
uv run --locked --extra cp-sat python -m shift_schedula adapter split examples/roster.json --output draft.json
# draft.jsonを編集し、必要な入力元を一件ずつ確認する
uv run --locked --extra cp-sat python -m shift_schedula adapter confirm draft.json period --output confirmed.json
uv run --locked --extra cp-sat python -m shift_schedula adapter assemble examples/adapter/assignment.manifest.json
uv run --locked --extra cp-sat python -m shift_schedula adapter solve examples/adapter/assignment.manifest.json --output run.json
uv run --locked python -m shift_schedula adapter verify-record run.json
uv run --locked python -m shift_schedula adapter view run.json
uv run --locked python -m shift_schedula adapter schema draft
```

assembleは組み立て結果全体を返し、`--request-only` で確定Requestだけを出力します。
元CLIのsolve/verify/schemaは維持します。成功は0、PARTIAL・入力/記録不正・無解・未確定は2。
`--output` は新規保存のみ、既存ファイルには明示した `--overwrite` が必要です。
入力ファイルと参照元への出力は上書き指定でも禁止します。
一時ファイルのfsync後に置換/新規リンクし、途中失敗で既存記録を壊しません。

## 実行記録と表示

`run_draft(draft, num_workers=2)` は組み立て成功時だけsolveし、実行記録を返します。
`create_record(request, response, provenance, sources, num_workers=2)` は同じ実行を保存します。
record_versionは1.0、run_idは毎回新規UUID、request_idとは別です。
確定Request・Response・num_workers・入力元内容と改訂・対応表・エンジン/依存版を保存します。
入力元content_hashは元バイト列ではなく正規化した入力元JSONのSHA-256です。
正規化はUTF-8、ensure_ascii=False、sort_keys=True、separators=(",", ":")、有限数のみ。
objectキー順は無視し、配列順と数値表現（1と1.0）は保持します。
記録content_hashはcontent_hash自身を除く全フィールドを同じ方式で照合します。
ハッシュは偶発的な混在/破損の検出用で、真正性や実行認証を保証しません。

`check_record` はSchema・ハッシュ・request_id/版・目的/解とRequestとの対応を検査します。
保存時もResponseの既存検証を使います。無解・UNKNOWN等のsolutionはnullのままです。
`reverify_record` は元記録を変更せず、recordとcurrent_verificationの別欄を返します。
solutionなしではcurrent_verificationはnull（未実施）です。
現在の有効性・不足/評価はverify結果を使い、保存済みverificationは代用しません。
verifyは最適性・不足最小性を付与せず、手修正解は別引数solutionで渡せます。
基準保存は既存make_baselineを使い、解を勤務実績へ変換しません。

| 用途 | 同じ記録から渡す値 |
| --- | --- |
| 勤務確認 | run_id、原solution、planning_window、現在verification、状態/不足、元記録hash |
| 採用判断 | 現在の有効性/需要充足、元Responseの状態と過去の証明、現在は証明なし |
| 評価比較 | objectivesの順序/尺度、全summary、変更量。異なる条件の値を優劣として断定しない |
| 入力修正 | diagnosticsとprovenance、未解決項目、確認失効。条件変更案は別Requestの案 |
| 再検証 | 元Request/Response/入力元/設定の完全記録、現在verifyを別欄 |

`record_view` は上記の最小JSON投影です。未検証/無効な解は勤務表を返しません。
PARTIAL/完全、FEASIBLE/OPTIMAL、UNKNOWN/INFEASIBLEを区別し、0とnullを保持します。
全指標と診断はJSON詳細でも保持し、勤務は原区間を切らずに保存します。
表示期間は既存demoの投影だけで、再求解や別の集計器を追加しません。

## アプリへの引き継ぎ

[schedula-app #30](https://github.com/omitsuhashi/schedula-app/issues/30)でアプリ利用を別管理します。
採用候補はエンジン0.1.6/契約0.1〜0.15と本形式1.0。
Draftはアプリの入力候補保存先、run_idはアプリの計画案へ関連付ける外部実行識別子です。
月次/個人別/比較Queryには確定Request・原Solution・現在verify・元Response・provenanceを渡します。
session_id/version/plan_idは既存アプリ保存層で所有し、エンジンRequestへ混入させません。
SQLite正本と旧JSONの移行/HTTP経路はアプリ側で判断します。本変更はその保存形式を変更しません。
共通Adapter完成とアプリ追随完了、将来契約追随、PyPI公開・デプロイは別です。
