# 勤務分類と勤務パターンの契約0.13

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #88](https://github.com/omitsuhashi/schedula/issues/88)の仕様に従い、
0.12の必須最低人数・不足許容・目的順を継承する。追加項目はroster専用であり、
0.1〜0.12へ渡すと拒否する。有限候補と担当配置の同時最適化、原区間保持、独立検証を維持する。

## 勤務分類

任意の`shift_categories`は1〜20件。一意の`id`、表示用`label`、1〜1000件の
`intervals`、整数1〜10,000,000の`min_overlap_minutes`を持つ。区間はW内、
continuityがある場合はC内で、秒・端数分を含めず計画の粒度に揃える。
重複する区間は和集合として一度数える。

原勤務の全segmentsから休憩を除き、分類区間と重なる実経過分数が閾値以上なら該当する。
待機を含み、分割間の非勤務を除く。候補・確認済み実績・確定勤務で同じ式を用いる。
一勤務が複数分類に該当してよく、未参照の分類も保持できる。目標値は持たない。
`label`、候補ID、テンプレートIDから夜勤や祝日を推定しない。

```json
{
  "id": "night",
  "label": "夜勤",
  "intervals": [{"start": "2026-10-05T22:00:00+09:00", "end": "2026-10-06T06:00:00+09:00"}],
  "min_overlap_minutes": 60
}
```

これは分類要素の部分例。完全なRequestは[入力例](../examples/shift_patterns.json)を使う。

## 必須ルール

constraintsの一要素として`id`、`type`、空でない重複なしの`employee_ids`、
`evaluation_period`を指定する。評価期間はW内の正の00:00同士。
`day_offset`と`min_days`は整数1〜366、`max_groups`は整数0〜366。
bool、null、浮動小数、未知項目、未知ID、重複ID、不正区間を拒否する。

| type | 追加項目 | 意味 |
| --- | --- | --- |
| `forbidden_shift_successions` | `from_category_id`、`to_category_id`、`day_offset` | from分類の開始日のday_offset日後にto分類を開始できない。間に別勤務があっても禁止する |
| `days_off_after_shift` | `category_id`、`min_days` | 該当勤務の最終終了から、最後に勤務区間が触れた暦日の翌日を起点とするmin_days個の完全休日の終端まで、新しい勤務区間を置けない |
| `min_consecutive_days_off` | `min_days` | 評価期間と交差する完全休日の最大連続区間をmin_days以上にする。完全休日がない場合は違反しない |
| `worked_date_groups_limit` | `date_groups`、`max_groups` | 明示した各日群に勤務区間が一度でも重なると一群。勤務した群数をmax_groups以下にする |

date_groupsは一意のIDと空でないdatesを持つ1〜366群。1群は1〜366日で、
日付はローカル暦日、群内・群間で重複させず、評価期間内に収める。
連続する2週末を二群としてmax_groups=1を指定すれば、片方の土日両方の勤務は許可し、
第1週土曜と第2週日曜の勤務を禁止する。週の開始曜日や休日を推定しない。
占有日の判定は休憩を含む原勤務区間を使い、分割間の非勤務と終端00:00の翌日は含めない。

## 夜勤後の許可境界と期間の余白

月曜22:00〜火曜06:00の夜勤後にmin_days=2を指定すると、火曜06:00以降の残りと
水曜・木曜を休み、最も早い次の勤務は金曜00:00になる。
月曜24:00終了なら火曜・水曜が完全休日で、木曜00:00から勤務できる。
日数の加算はローカル暦日、区間の重なりと分類分数は実経過時間を使う。

| ルール | 必要な判定範囲 |
| --- | --- |
| 禁止する並び | 評価開始のday_offset日前から評価終了のday_offset日後まで |
| 夜勤等の後の休み | 評価期間内に開始する該当候補・確定勤務の最終終了と、その後の完全休日の終端まで |
| 連続休日 | 評価期間の前後にmin_days日ずつ |
| 日群 | 全対象日をW内に含める |

左余白はW内の計画またはcontinuityの確認済み過去。右余白はW内に必要で、
C内の未入力の未来を休日の証明に使わない。該当候補の一部だけを捨てることもしない。
必要範囲が不足すると`INVALID_INPUT`の診断`INCOMPLETE_HISTORY`に
`required_start` / `required_end`を返す。利用者がWまたはCを広げる。

評価期間より前に開始した勤務も、禁止対象日または休み義務が評価期間へ重なれば適用する。
確認済み実績だけで完結する違反は遡及判定しない。履歴要約のlast_shift_endから
最長の休み義務が評価期間へ届く場合、分類を確認できる原勤務をC内の実績として入力する。
履歴要約を分類済み勤務と見なしたり、実績を新しい選択候補へ変えたりしない。

## 求解・検証・再計画

新ルールは必須条件であり、違反を不足として許容しない。有効条件が矛盾すれば
`INFEASIBLE`、探索で未確定なら`UNKNOWN`。ルールと必須最低人数を守って元需要に
不足が残る場合は`PARTIAL`。不足総量→priority群→利用者の目的順を維持する。

公開verifyは元Requestと返却原区間から分類・日別状態を再構成し、違反を`INVALID_PLAN`にする。
診断`SHIFT_PATTERN_VIOLATION`に条件pointer、条件ID・従業員・関係勤務IDと、
起点日、`forbidden_start` / `forbidden_end`、`date_group_ids`等を返す。
モデルの係数表・ソルバー値を正本にせず、最適性・不足最小性は認定しない。

診断の削除単位はルール1件。分類、実績、確定勤務は背景条件として保持する。
allowed_changesによる分類・パターンの編集は受け付けない。
make_baselineは元の分類とルールを保存し、原版で再検証する。
次のRequestの業務ルールを自動設定する機能ではないため、同じルール・分類区間と
必要な実績は利用者が次回入力にも明示する。preserve_assignedと矛盾した固定を自動解除しない。

## 実行例

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/shift_patterns.json > result.json
uv run --locked python -c 'import json; from shift_schedula import verify, make_baseline; q=json.load(open("examples/shift_patterns.json")); r=json.load(open("result.json")); print(verify(q,r["solution"])["status"]); print(make_baseline(q,r["solution"],"saved")["plan_id"])'
```

入力例は4ルールと必須最低人数・priorityを含む。夜勤・day4・遅番・weekendを選び、
遅番翌日の早番は不足30人分として返す。勤務量780分、独立検証成功のPARTIAL、CLI終了コード2。
verifyもPARTIALを返す。ブラウザーのJSONサンプルにも同じ入力を用意する。
性能・境界・拒否の確認内容は[受け入れ記録](evaluations/shift-patterns.md)を参照する。
