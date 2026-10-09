# Draft・manifest・実行記録の明示移行

> 履歴記録: 旧版からの明示移行を検証した際の手順と結果です。一時スクリプト・専用試験・旧fixtureは検証後に撤去しました。原資材は[固定commit](https://github.com/omitsuhashi/schedula/tree/d17a036a9790999c8182cdd319473d32368ddaec)に保存されています。現在の通常入口は契約0.15だけを受理します。

[Issue #110](https://github.com/omitsuhashi/schedula/issues/110) の入口は
[scripts/migrate_adapter.py](https://github.com/omitsuhashi/schedula/blob/d17a036a9790999c8182cdd319473d32368ddaec/scripts/migrate_adapter.py)。
[Request・解・基準計画の移行](contract-0.15-data.md)を再利用し、求解せず別出力を作る。
旧契約を受理する導入commitと既存lockで実行する。通常のAdapter APIへ暗黙変換を追加しない。
所有者の2026-10-09回答により、例・テスト以外の保存済みJSON・SQLiteはない。
対象はリポジトリ内のDraft/manifestと、既存APIで生成する代表記録である。

```sh
uv sync --locked --extra cp-sat
uv run --no-sync python scripts/migrate_adapter.py draft examples/adapter/assignment.manifest.json --output adapter-migration.json
uv run --no-sync python scripts/migrate_adapter.py draft examples/adapter/roster.draft.json --output roster-migration.json
uv run --no-sync python scripts/migrate_adapter.py record old-run.json --output record-migration.json
```

`draft` はインラインDraftまたは明示manifest、`record` は実行記録1.0を受け取る。
入力元一件だけでは実行契約・依存・所有元を判断できないため、Draft/manifestとして指定する。
`--history-confirmations` の形式とpointerはRequest移行と共通である。
勤務開始日を推測せず、必要な履歴確認・適用期間の不一致は `NEEDS_CONFIRMATION`、
不正入力・保存失敗は `INVALID_INPUT` と終了2で止める。成功は `MIGRATED` と終了0。
成功は確認済みの確定入力や実行可能性を意味しない。変更箇所は次の操作で確認する。

## 所有元と確認

[Adapterの所有表](../input-adapter.md#入力と所有元)にある全トップレベル項目・employee項目を保持する。
組み立ての対応表から、追加minimum_people、履歴last_work_day、候補のsegments、
埋め込みbaseline、診断の許可編集を元の所有元へ戻す。
従業員は元のID対応と入力元内の順序を使い、異なる配列順でも履歴を別人へ付けない。
目的順序、solver設定、num_workers、根拠references、origin、applies_to、order、overrides、
assumptions、unresolvedを保持し、日付・原勤務区間・休憩を自動移動しない。
未入力、未確認、確認済み空配列、明示0を補完しない。

0.1のテンプレートは旧ID付き明示候補へ展開する。元テンプレートと明示候補の所有元が
別なら、候補配列を所有していた入力元へ展開結果をまとめる。
両方の原所有元を `migration_provenance` に保持し、両方の値変更を確認失効の対象にする。
現在の所有元 `provenance` と、移行元の根拠を混同しない。

値が変わった入力元のrevisionは、元revisionと移行後dataのcanonical JSON SHA-256に更新する。
旧版のdigestに含まれた版番号だけを、意味が保たれた移行後の版へ照合し直す。
元の確認が有効で、値・改訂・参照・適用期間・依存・置換・順序がすべて一致する入力元だけ
digestを移行後の値へ付け替える。`transferred_confirmations` に対象を記録する。
無変更のbasic/common/execution等を一律失効させず、変更された入力元・依存する入力元は
旧digestを残してstaleにする。元のstale/未確認を確定へ昇格させない。
外側Adapter/manifest/recordは1.0のままで、内側の実行契約0.15とは別である。

値と所有元の検査には、確認・未解決項目を一時コピーから外した組み立てを使う。
出力Draftの確認・未解決項目は保持し、実行に使うのは通常のassembleが成功した後だけである。
不足項目・所有競合・不正条件を補完した成功出力は作らない。

```python
from shift_schedula import assemble, confirm_source, confirmation_state, read_draft, run_draft, save_json
from shift_schedula.records import read_json_file

migration, _ = read_json_file("adapter-migration.json")
save_json("draft-015.json", migration["draft"], protected=["adapter-migration.json"])
draft = read_draft("draft-015.json")
# stale/unconfirmedの各入力元を担当者が確認した後、そのsource_idだけをconfirm_sourceへ渡す。
print(confirmation_state(draft))
draft = confirm_source(draft, "period")
assert assemble(draft)["status"] == "VALID"
record = run_draft(draft)
save_json("run-015.json", record)
```

## 実行記録と過去証拠

出力は `migration_version: "1.0"` の移行記録であり、RunRecordではない。
`migration_id` は変換の識別子、`source_run_id` は元実行の識別子。
request_idは保持する。新しい求解を捏造せず、移行後の再実行では既存run_draft/create_recordが
新しいrun_idと実行環境を記録する。元run_idを新内容で上書きしない。

`original_record` は旧Request/Response/verification・証明・入力元・metadata・provenance・
実行設定・engine/依存版・ハッシュ・run_idをそのまま保持する。
`original_response` も過去証拠のまま、`solution` と `current_verification` は
0.15で再検証した値として別欄に持つ。保存解なしなら両者はnull。
現在の検証へOPTIMAL・proven_optimal・proven_minimal・不可能性の証明を転記しない。
条件変更案は別Request/解/現在検証のsuggestionsとして移す。
基準計画は元期間・固定を保持し、再保存には通常のmake_baselineを使う。

`execution` は再実行へ渡す元設定、`migration_engine` は変換に使った配布版/依存版。
原実行のengineと区別する。`draft_metadata: null` で入力元もない記録は、Request/解だけ移す。
metadataなしで入力元がある記録は、所有関係を推測せず `UNTRACKED_SOURCES` と要確認で止める。

## 保存・検証と後続作業

`original_draft`、`source_draft_hash`/`target_draft_hash`、`source_record_hash`、
`source_request_hash`/`target_request_hash` と `inputs` の明示ファイル/内容ハッシュで来歴を追跡する。
ハッシュはcanonical JSONの照合であり、元ファイルのbytesのハッシュではない。
manifestは明示された参照単位を検査し、移行後はfile欄を元位置の来歴として持つインラインDraftにする。
新しいファイル群やmanifestを自動生成せず、通常read_draftで単一Draftを再読込できる。
16 MiB/総64 MiB/32入力元、UTF-8・厳密JSON・通常ファイルの境界を既存I/Oへ委ねる。
絶対/親参照・symlink・循環/重複参照・URL・暗黙探索を許可しない。
出力は新規ファイルの原子保存だけ。参照元と履歴確認を含む原本、成功済み出力を変更しない。

[tests/test_adapter_migration.py](https://github.com/omitsuhashi/schedula/blob/d17a036a9790999c8182cdd319473d32368ddaec/tests/test_adapter_migration.py) で全旧版の分割/取り込み、
全所有項目、複数所有元、確認保持/失効/未確認、未解決項目、原期間、履歴要確認、
基準、保存記録・現在検証・再実行の新run_id、保存/再読込、パス・JSON・上限・保存失敗を確認する。
既存CIのLinux/Windows × base/cp-satへ移行CLIを追加し、sdistからの再実行とskip拒否を維持する。
実Chromiumでは移行Draftの個別確認→実計算→記録保存/再読込/再検証を確認する。

通常の例・デモの一括0.15化は #124、アプリの保存往復は #125、旧版の最終拒否は #111。
本作業では既存業務テスト・旧版Schema/APIを除去せず、アプリの未接続UI機能を追加しない。
