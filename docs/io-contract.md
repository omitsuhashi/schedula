# 入出力契約

## 基準と変更の扱い

初期設計の基準は SkillShift Starter の `schema_version: "0.1"`。
[Request Schema](reference/skillshift-starter-0.1/skillshift/schemas/request.schema.json)と
[Response Schema](reference/skillshift-starter-0.1/skillshift/schemas/response.schema.json)を
原文のスナップショットとして保存する。本書はその業務上の意味を説明する。
これらは公開安定版ではなく、schedula の実装・互換性保証が完成したことを示すものではない。

参照スナップショットは変更しない。schedula 用の実行契約の配置、版の付け方、移行方針は
[参照実装の評価](evaluations/engine-introduction.md)で次のとおり確定した。
`urn:skillshift:request:0.1` など元の `$id` は来歴のため保持する。
LLM 用の RequestDraft は実行契約と別に定義する。

## schedula の契約の公開単位

| 対象 | 決定 |
| --- | --- |
| Request Schema | `src/schedula/schemas/0.1/request.schema.json`、`$id: urn:schedula:request:0.1` |
| Response Schema | `src/schedula/schemas/0.1/response.schema.json`、`$id: urn:schedula:response:0.1` |
| JSON Schema dialect | 両方に `$schema: https://json-schema.org/draft/2020-12/schema` を明示する |
| 入出力の契約版 | `schema_version: "0.1"`。パッケージ版・`solver.engine_version` と区別する |
| 配布単位 | Request / Response を対にして wheel に同梱する。版別 Schema が構造の正本 |
| プログラムの入口 | `from schedula import solve`、`solve(request: dict) -> dict` |
| CLI の入口 | `python -m schedula solve <入力ファイル>`。UTF-8 JSON、`-` は標準入力 |
| Schema の取得 | `python -m schedula schema request` / `response`。初期版は0.1を返す |

これらのファイルと入口は Issue #6、担当時間・担当切替と CP-SAT は Issue #7 で実装した。
現在の目的は最大1件とし、複数目的は未対応として明示的に拒否する。利用例と対応範囲は
[担当配置の利用手順](assignment.md)を参照する。
`src/schedula/` を `setuptools.build_meta` でパッケージ化し、版別 JSON を package data に含める。
参照コードのライセンス未選定を踏まえ、保存済み原本を直接編集・コピーせず、
本書の業務仕様から schedula 用の Schema・例・コード・テストを作成する。

0.1は開発中の初期契約であり、公開安定版やすべての機能の実装を示さない。
Schema が表現できる条件でも、導入済み機能以外は意味検証で `INVALID_INPUT` として拒否する。
対応機能はパッケージ版ごとに文書化し、`auto` や明示 backend が条件を捨てることは認めない。

一度導入した契約版の受理構造・必須項目・状態・業務上の意味は同じ版で変更しない。
未知項目を拒否するため、項目・ルールの追加も新しい契約版として Request / Response を揃える。
説明文だけの訂正や既存仕様に従う実装修正は、構造・意味を変えずパッケージ版で記録する。
新しい契約版では別の配置と `$id` を使い、変更理由、旧版との差分、入力の移行例、
旧版の対応期間を同じ PR に記録する。旧版ファイルは保持し、無言の自動移行はしない。
実行エンジンが未対応の契約版を受け取った場合も `INVALID_INPUT` とし、診断で版を示す。
SDK 生成は版別の実行 Schema を基準とし、参照スナップショットを生成元にしない。

## Request の構成

| フィールド | 意味と初期条件 |
| --- | --- |
| `schema_version` | `"0.1"` |
| `request_id` | 呼び出し側の照合用 ID。認証や再実行防止の仕組みではない |
| `problem_type` | `assignment` / `roster` |
| `planning_window` | 開始、終了、IANA タイムゾーン、`slot_minutes` |
| `skills` | 登録済み技能の ID と表示名 |
| `roles` | 役割の ID、表示名、必要技能と最低レベル |
| `employees` | 従業員の ID、表示名、保有技能、勤務可能時間、必要に応じた履歴 |
| `demand` | ID、役割 ID、時間区間、`required_people` |
| `shift_candidates` | 従業員、出退勤区間、休憩を明示した勤務候補 |
| `shift_templates` | 任意項目。対象者・日付・時刻・勤務長・休憩位置から候補を作る |
| `constraints` | 指定した全件を守る必須ルール |
| `preferences` | 避けたい担当と対象者、1分当たりの整数ペナルティ |
| `objectives` | 評価指標の優先順序。先頭を最優先とする |
| `solver` | `backend`、`time_limit_seconds`、`seed` |

`shift_templates` 以外の上記トップレベル項目は必須。
利用しない配列も `[]` を明示する。0件と未入力を混同しない。
ID は種類ごとの集合内で一意とし、参照先が存在することを確認する。
未知フィールド・未知の `type` を拒否し、未対応条件を無視して解かない。

## 複数技能と担当資格

従業員の `skills` は配列で、1人が複数の技能をそれぞれのレベル付きで保有できる。
次は調理と接客の両方を持つ従業員のデータの一部分であり、完全な Request ではない。
参照する技能 ID はトップレベルの技能マスターに登録する。

```json
{
  "id": "alice",
  "skills": [
    {"skill_id": "cooking", "level": 2},
    {"skill_id": "service", "level": 1}
  ]
}
```

役割の `required_skills` も配列で、指定された技能と最低レベルをすべて満たすことを
担当資格の条件とする（AND 条件）。上記の従業員は、必要レベルを満たす調理・ホールの
どちらの配置候補にもなり、時間帯ごとに担当を選べる。
保有技能が複数でも、同じ時間に担当する役割は最大一つとする。
「複数技能のうちどれか一つでよい」という OR 条件や、資格の有効期限は初期契約に含めない。

## モードごとの意味

`assignment` は既に配置可能な区間の担当だけを決める。
出退勤・休憩の選択、計画前履歴、`scheduled_minutes` は扱わず、勤務候補は空とする。
確定した休憩がある場合は、それを除いた区間を `availability` に指定する。
配置されなかった従業員について、欠勤や退勤が確定したとは解釈しない。

`roster` は勤務候補の選択と担当配置を同時に決める。
計画期間の両端は指定タイムゾーンのローカル日付00:00。
1人・ローカル日付ごとに最大1候補を選び、区間の終端を除いた勤務時間が
日付をまたぐ候補は初期契約では拒否する。分割勤務へ暗黙に変換しない。
選ばれた勤務の休憩を除く時間だけ担当可能で、未担当の勤務時間は待機となる。

## 時間・空値・需要

日時は `2026-10-05T11:00:00+09:00` のようにオフセットを明示し、
`planning_window.timezone` には `Asia/Tokyo` など128文字以内の IANA 名を指定する。
区間は半開区間 `[start, end)`。開始より終了が後で、計画期間内に収まり、
計画開始を基準とする時間粒度に揃っている必要がある。秒・端数分や粒度のずれを丸めない。

| 入力 | 意味 |
| --- | --- |
| `availability: []` | 配置・勤務不可。不明や終日可能にはしない |
| `required_skills: []` | この役割には技能条件がない |
| 未登録の従業員技能 | その技能の要件を満たさない。レベル0として補完しない |
| 未指定の役割・時間帯の需要 | 必要枠数0 |
| `required_people: 0` | その時間帯の担当枠数0 |
| `objectives: []` | 必須条件を満たす任意の解を求める |

需要は厳密な必要担当枠数である。最低人数以上の過剰配置や訓練目的の追加配置は別の意味として
将来設計する。勤務中の余剰人員は待機できるが、役割担当として余分に計上しない。
同じ役割の需要区間の重なりは、合算・置換を推測せず拒否する。
同じ人の勤務可能区間の重なりも拒否する。終端と開始が接する区間は許可する。

元チャット初期案の「必要人数以上」から、ZIP の「必要枠数と等しい」へ具体化された点を
採用している。両方の意味を同じフィールドに混在させない。[採用判断](sources.md)

## 勤務候補と休憩

`shift_candidates` とテンプレートで生成した候補は合成する。
休憩を含む候補の全区間が、その従業員の勤務可能時間に収まる必要がある。
明示候補の逸脱は入力エラー、テンプレート由来の期間外・勤務可能時間外候補は除外とする。

休憩は候補内で互いに重ならず、始業・終業に接しない明示区間とする。
`shift_templates.break_options` の各要素は、一つの休憩位置の代替候補であり、
複数休憩を同時に入れる指示ではない。空配列は休憩なしの候補となる。
複数休憩が必要なら明示的な `shift_candidates` で表す。
休憩の法的な適切性、有給・無給、賃金計算はこの契約で判定しない。

テンプレートの曖昧なローカル時刻や時計変更で存在しない時刻は拒否する。
曖昧な時刻はオフセット付きの明示候補で表す。
テンプレートの候補数と時間粒度が探索範囲を定めるため、結果の評価にはその条件を添える。

## 計画前履歴

`roster` は全従業員の `history` を必須とする。空履歴も次のように明示する。
以下は従業員データの一部分であり、完全な Request ではない。

```json
{
  "history": {
    "last_shift_end": null,
    "consecutive_work_days_before_window": 0
  }
}
```

これは「影響する以前の勤務がない」という入力者の明示である。
不明な履歴をこの値に置換しない。履歴がある場合は最終勤務の終了時刻と、
計画開始日の直前日まで続いた連勤数を渡す。直前日が休日なら連勤数は0。
履歴が計画期間に重ならず、最終勤務の日付と連勤数が整合することを検証する。
週・月・給与締め期間の累計や翌期間の固定勤務は0.1では扱わない。

## 指定できる必須ルール

需要・技能・勤務可能時間・二重配置の禁止は基本条件として常に適用する。
`constraints` の各要素は ID、対象の `employee_ids`、次の `type` と対応する値を持つ。

| `type` | モード | 意味 |
| --- | --- | --- |
| `max_assigned_minutes` | 両方 | 役割を担当する分数の上限。待機は数えない |
| `max_scheduled_minutes` | `roster` | 選択した勤務の休憩を除く分数の上限。待機は数える |
| `min_rest_minutes` | `roster` | 勤務終了から次の開始までの最小間隔。計画前の最終勤務とも照合 |
| `max_consecutive_days` | `roster` | ローカル日付での連勤上限。計画前履歴を引き継ぐ |
| `max_role_switches` | 両方 | 隣接時間枠で両方とも担当しているときの役割変更回数の上限 |

担当切替は、休憩・待機を挟んだ担当変更を数えない。
勤務中の総変更回数、休憩後の同一担当を求めるルールとは区別する。

## 選好と目的順序

例えば技能者の皿洗いを避ける入力は次のように表す。
以下は完全な Request のうち選好・目的の部分である。

```json
{
  "preferences": [{
    "id": "preserve_specialists",
    "type": "avoid_role",
    "employee_ids": ["alice", "bob"],
    "role_id": "washing",
    "penalty_per_minute": 1
  }],
  "objectives": [{
    "id": "use_skills",
    "metric": "preference_penalty"
  }]
}
```

担当した分数 × ペナルティを合計する。必要ならこの配置を許し、選好違反の数値を返す。
対象者は ID の明示リストであり、技能者全員を自動選択する機能は0.1に含まれない。
`preferences` があるのに `preference_penalty` 目的がなければ入力エラーとする。

初期の目的は `preference_penalty`、`scheduled_minutes`、`role_switches`。
同じ指標は重複指定しない。すべて最小化し、`scheduled_minutes` は `roster` だけで使う。
最小費用流で使う目的は空または `preference_penalty`。

`preference_penalty` → `scheduled_minutes` → `role_switches` の順なら、
選好を守るために勤務量が増える場合がある。勤務量を優先したければ順序を変える。
`scheduled_minutes` は休憩を除き待機を含む時間で、給与額の代用ではない。
目的に指定しなかった指標が最小になるとは保証しない。

## Response と呼び出し側の扱い

| `status` | 意味 | 呼び出し側の扱い |
| --- | --- | --- |
| `OPTIMAL` | 対象モデルで目的順序を含む最適性を確認 | 検証済み解と、その探索範囲を表示する |
| `FEASIBLE` | 必須条件を満たす解がある。最適性は未確定 | 解と未証明の目的を表示する |
| `INFEASIBLE` | 対象モデル・候補集合で実行不可能と判定 | 条件の見直しを促す。勝手に緩和しない |
| `UNKNOWN` | 解も不可能性の証明も得られない | 未確定と説明し、再実行などを選べるようにする |
| `INVALID_INPUT` | 構造・参照・意味・対応機能などが不正 | 入力の該当箇所を修正する |
| `BACKEND_UNAVAILABLE` | 必要なバックエンド依存がない | 実行環境を整える |
| `INTERNAL_ERROR` | 実行・モデル・結果検証などの内部障害 | 正式な解として扱わず、障害を調べる |

有効な解を返すのは `OPTIMAL` / `FEASIBLE` かつ結果検証成功の場合だけ。
それ以外は `solution: null`。
最適性は入力・時間粒度・候補・ルール・目的順序の範囲に限られ、
入力の真偽や未入力条件への適合を保証しない。

| フィールド | 内容 |
| --- | --- |
| `schema_version` / `request_id` | 契約版と照合 ID。不正入力で ID を取り出せなければ `null` |
| `solver` | 実際の `backend`、選択理由、エンジン版、依存ライブラリ版 |
| `solution.assignments` | 従業員 ID、役割 ID、担当区間。隣接した同じ担当をまとめる |
| `solution.shifts` | 選択した候補 ID、従業員 ID、勤務区間、休憩。`assignment` では空 |
| `objectives` | 目的ごとの `id`、`metric`、数値 `value`、`proven_optimal` |
| `diagnostics` | `code`、`message`、`json_pointer`、`related_ids`、`facts` |
| `verification` | `performed`、`valid`、`violations`。未検証なら `valid: null` |
| `stats.elapsed_seconds` | エンジン呼び出しにかかった時間 |

`facts` は `name` / `value` を持つ配列。診断の根拠を機械で読める形で保持する。
最小費用流では単独役割の有資格者不足と、複数役割で同じ人を取り合う不足を区別する。
CP-SAT の詳細矛盾抽出、自動緩和、必要最小追加人数は未実装。
Response の状態と最適性の整合も、公開前の検証対象にする。

## 実行・資源上限

0.1 参照 API は `solve(request: dict) -> dict`、uv 環境での CLI は
`uv run --extra dev --extra cp-sat python -m skillshift solve <入力ファイル>`。
CLI は JSON だけを標準出力へ出し、解があれば終了コード0、それ以外は2。
`INFEASIBLE` と入力エラーは終了コードではなく `status` で区別する。
これらは ZIP の入口であり、現在の schedula で実行できるコマンドではない。
実行環境は [参照 ZIP の評価手順](python-setup.md#参照-zip-を評価する場合)に従う。
現在の schedula の利用例は
`uv run --locked python -m schedula solve <入力ファイル>`。
CP-SAT を使う場合は `--extra cp-sat` を指定する。標準出力は JSON のみとし、
結果検証に成功した `OPTIMAL` / `FEASIBLE` は0、それ以外の結果状態は2とする。
引数の誤りなど CLI の使用法エラーは標準エラーへ表示し、終了コード2とする。
Schema 取得は JSON を標準出力へ出し、成功時は0とする。

参照実装には従業員250人、役割50、時間枠3000、候補5000、
従業員 × 時間枠 × 役割が1,000,000以下などの入力・意味上の制限がある。
上限内で性能が保証されるという意味ではない。将来の公開上限は測定して決める。
探索予算は目的の各段階で共有し、後段が時間切れなら直前の実行可能解を保持する方針。
schedula では入力検証・依存読み込み・候補展開・モデル構築を探索予算から分け、
探索を始めてから共有予算を消費する。総応答時間は結果検証を含めて別に測る。
参照 CP-SAT 経路は ZIP 作成時には未検証だったが、今回の評価で実行した。
初回読み込みで予算を使い切る構造と修正条件は
[評価記録](evaluations/engine-introduction.md#後続実装で修正する差分)に残す。
HTTP の状態コード、非同期ジョブ、キャンセル、再試行・冪等性の仕様は未決定。
