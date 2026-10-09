# Request・解・基準計画の明示移行

[Issue #109](https://github.com/omitsuhashi/schedula/issues/109) の移行入口は
[scripts/migrate_contract.py](../../scripts/migrate_contract.py)。通常のsolve/validateへ暗黙変換を追加しない。
所有者の2026-10-09回答により、例・テスト以外の保存済み実データはない。
現行例の一括切替は #124、Draft・manifest・実行記録は #110、アプリの保存往復は #125 が担当する。
このスクリプトはRequestと、そのRequestに属する解またはResponseを対象とする。
不正入力を補完したり、保存先を探索したり、DBや既存セッションを変更したりしない。

## 実行と保存

旧契約を受理する、このスクリプト導入時のcheckoutと既存lockで実行する。
新配布物から旧契約を除去した後の旧版照合は、必要なときだけこの固定commitとlockから
一時環境を作る。導入PRのマージcommitを移行基点とする。旧Schemaを新wheelへ再同梱しない。
旧環境の複製保管・復旧試験は行わない。

```sh
uv sync --locked --extra cp-sat
uv run --no-sync python scripts/migrate_contract.py examples/roster.json --output migration.json
# 保存解がある場合。Responseを使う場合は --solution の代わりに --response を指定する。
uv run --no-sync python scripts/migrate_contract.py examples/roster_conditions.json --solution examples/roster_conditions.solution.json --output migration-with-plan.json
```

成功時の終了コードは0、入力不正・要確認・保存失敗は2。stdoutは状態を表すJSONのみ。
入力は通常ファイルまたは一つだけの標準入力 `-` とし、UTF-8・厳密JSON・16 MiB上限を使う。
シンボリックリンク、未知版・欠落版・不正型、重複JSONキー・非有限数を拒否する。
出力は原本とは別の新規ファイルに原子保存する。上書き指定は設けず、失敗・再実行・中断でも
原本と成功済み出力を変更しない。再実行は原本と新しい出力先を指定する。

出力は `migration_version: "1.0"` の移行記録であり、通常のRequest/Responseではない。
`request` が確定した0.15入力、`solution` が変換・再検証した保存解、
`current_verification` が現在の独立検証である。解なしの記録は後二者をnullとする。
入力/出力の意味内容のSHA-256を `source_request_hash`・`target_request_hash`、
元解を `source_solution_hash`、各入力の明示パスと内容を `inputs` に記録する。
ハッシュはcanonical JSONの内容照合であり、原ファイルbytesのハッシュとは区別する。
`original_response` は元応答を変更せず過去証拠として保持する。新Responseを捏造しない。

通常入口へ渡すときも新規ファイルへ取り出す。

```python
from shift_schedula.records import read_json_file, save_json
record, _ = read_json_file("migration.json")
save_json("request-015.json", record["request"], protected=["migration.json"])
if record["solution"] is not None:
    save_json("solution-015.json", record["solution"], protected=["migration.json"])
```

## 版ごとの意味と確認

| 元版 | 0.15へ移す処理 |
| --- | --- |
| 0.1 | 各需要に必要人数と同じ最低人数を追加。明示候補のinterval/breaksを一要素のsegmentsへ移す。保存勤務に元開始日のwork_dayとsegmentsを付ける。履歴は下記の確認を要求 |
| 0.2 | 完全充足を同じ最低人数で維持。許可された人数変更には同じ値の下限変更を同じ選択肢へ追加。候補・夜勤・分割・履歴・公平性はそのまま |
| 0.3 | 元需要とPARTIAL許容を維持し、必須下限を追加しない |
| 0.4 | 未完成の基準、期間別勤務量、希望、preserve_assigned/rebuild、明示・自動固定を保持 |
| 0.5 | 不足総量が先、その後priority群という目的順を保持 |
| 0.6 | 原勤務・休憩・実績・確定勤務・文脈期間を切り詰めず保持 |
| 0.7 | 基準の元期間を保持し、新旧の重複部分だけを比較 |
| 0.8 | 条件グループ、背景条件、診断設定を保持。過去の包含極小性を新しい証明へ転記しない |
| 0.9 | 明示単価と指定区間の目標分数を保持 |
| 0.10 | 実績・未来確定勤務を含む目標分数を保持。アプリ固定0.1.5の実行契約もこの版 |
| 0.11 | 勤務日・占有日・完全休日の区別と必須上下限を保持 |
| 0.12 | 明示minimum_people、未指定/0の下限、既存の下限編集を保持 |
| 0.13 | 明示分類と勤務パターン・日群を保持 |
| 0.14 | 同時勤務の必要条件・禁止を保持。待機/休憩/分割間の扱いを変えない |
| 0.15 | 値・省略・明示0・空・目的順を変更しないコピー。日付を移動しない |

0.1のテンプレートは元の開始時刻×勤務長×休憩位置を旧展開器で列挙する。
各組はoffset 0・duration・breaksを持つ一要素のsegment_optionsと同じ勤務形状になるが、
0.15のテンプレートで再生成するとIDの式が変わる。このため移行出力では有効な展開結果を
旧ID付きの明示候補にし、旧テンプレートを除く。原文は原本に保持する。
元の候補集合・生成ID・原区間・休憩・availabilityによる除外は維持し、
旧版で不正だったテンプレートを新形状で救済しない。将来の期間への再生成は別の入力更新である。

0.1の確認済み空履歴（last_shift_endがnull、連勤数0）だけはlast_work_dayをnullにできる。
終了時刻が非nullなら、勤務開始日を推測せず `HISTORY_CONFIRMATION_REQUIRED` で止める。
確認JSONを `--history-confirmations` に指定する。入れ子基準の確認はその位置までのpointerを使う。

```json
{"/employees/0/history/last_work_day": "2026-10-04"}
```

確認した日が旧版の終了直前の暦日と異なれば、旧連勤判定を変えるため
`HISTORY_SEMANTICS_CHANGED` で止める。不要・対象外の確認も拒否する。
要確認の結果に移行済み入力は含めず、原本を維持して確認・条件見直し後に再実行する。

## 基準・診断・証明

baselineのsource_requestを再帰的に移し、source_solutionを元期間で旧/新とも検証する。
source_fixed_states・snapshot_origin・fixed_parts・replan_modeを保持し、
待機や不足枠を新しく自動固定しない。再計画後の基準保存には引き続き公開make_baselineを使う。

旧完全充足のrequired_people編集には同じ値のminimum_people編集だけを結び付ける。
下限だけを緩める権限は追加しない。旧最大10編集を保持するため0.15の選択肢だけ最大20編集へ広げる。
編集先・値域・重複拒否と、旧版の最大10編集は維持する。保存Responseの変更案は別の
`suggestions` にRequest/解/現在検証として移し、元の応答・証明はoriginal_responseに保持する。

旧解を新Requestで検証して不足・目的値・全summaryを取得する。最適性、最小不足、
不可能性、包含極小性を再認定しない。current_verificationの証明フラグはfalseのまま。
完全充足とPARTIALの意味は版の対応に従い、単なる版番号書換えで成功にはしない。

## 検証の対応

[tests/test_contract_migration.py](../../tests/test_contract_migration.py) で、
固定済み全旧版16組との一致、保存解と元証拠、確認が必要な履歴、完全/PARTIAL、
基準・固定・重複期間・継続勤務、許可変更案、最大編集数、DSTと期間端、
不正入力/解・厳密JSON・保存失敗・中断・再実行・原本/成功済み出力の不変を試験する。
既存CIのLinux/Windows × base/cp-satでCLIと求解なしの移行を実行し、skipを拒否する。
2026-10-09の手元検査では、examples直下・playgroundと評価再実行入力の62 Request中59件が移行可能だった。
残るinvalid-input.json（UNKNOWN_REFERENCE）、continuity-duty-invalid.json（INCOMPLETE_HISTORY）、
roster-input-limit.json（INPUT_LIMIT）は意図した不正入力として拒否した。例の原本は変更していない。
旧業務テストは削除しない。新しい汎用移行サービスや復旧基盤は追加しない。
