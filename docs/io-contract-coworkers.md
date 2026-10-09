# 同時勤務条件の契約0.14

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #89](https://github.com/omitsuhashi/schedula/issues/89)に従い、0.13の勤務分類・
勤務パターン・必須最低人数・不足許容・目的順を継承する。追加する2条件はroster専用。
0.1〜0.13へ新条件を渡すと拒否する。パッケージ版0.1.5とは別のJSON契約版である。

## 入力と意味

constraintsの各要素に一意の`id`、`type`、`employee_ids`、`interval`を指定する。
intervalはW内の正の半開区間で、計画開始からの時間粒度に揃える。
対象者は1〜250人の重複なしの既知従業員集合であり、同時勤務禁止では2人以上を要求する。

| type | 追加項目 | 必須条件 |
| --- | --- | --- |
| `required_coworkers` | `coworker_ids`、`minimum_people` | 対象者が勤務する各枠で、同僚集合のうち最低人数以上が勤務する |
| `incompatible_employees` | なし | 対象集合の同時勤務者は各枠で最大1人 |

`coworker_ids`は1〜250人の重複なしの既知従業員集合。対象者集合との交差を拒否する。
minimum_peopleは1〜coworker_ids件数の整数。bool、null、浮動小数、0、人数超過を拒否する。
未知項目・未知ID・重複ID・空集合・不正区間も入力不備とする。
技能・職位・候補IDから指導者を推定しない。

```json
{
  "id": "training_cover",
  "type": "required_coworkers",
  "employee_ids": ["trainee"],
  "coworker_ids": ["mentor_a", "mentor_b"],
  "minimum_people": 1,
  "interval": {"start": "2026-10-05T09:00:00+09:00", "end": "2026-10-05T11:00:00+09:00"}
}
```

これはconstraints要素の部分例。完全なRequestは[入力例](../examples/coworkers.json)を使う。

勤務状態は休憩と分割間の非勤務を除き、待機を含む。担当変数の有無で代用しない。
各枠で同僚を交代でき、同じ1人の終日勤務を要求しない。対象者が勤務しない枠には
同僚を強制せず、同僚だけの勤務も許可する。同じ指導者は複数対象者を同時に支えられる。
指導人数の容量や担当役割は今回の条件に含まない。

同時勤務禁止は集合内の全組合せへ適用する。3人集合も最大1人であり、2人を許す容量制約ではない。
休憩中は同時勤務に数えない。境界ちょうどの退勤・出勤は重複しない。

## 求解・独立検証

有限候補と担当配置の同時最適化を維持し、既存の選択候補・確定勤務から勤務状態を作る。
対象者eの勤務有無をw[e]とすると、required_coworkersは
`sum(w[c] for c in coworkers) >= minimum_people * w[e]`、同時勤務禁止は`sum(w[e]) <= 1`。
Wへ重なる確定勤務も同じ式で判定する。W外の実績や未入力の未来へ条件を推測して延ばさない。

有効条件が必須需要・休日・固定状態と矛盾すれば`INFEASIBLE`、探索未確定は`UNKNOWN`。
必須最低人数を守り、元需要に不足が残れば`PARTIAL`。不足総量→priority群→指定目的順を保つ。
対象者の勤務を選ばないために不足が残る場合も、不足を明示する。

公開verifyは元Requestと返却原区間から勤務状態を再構成し、違反を`INVALID_PLAN`にする。
診断`REQUIRED_COWORKERS_VIOLATION` / `INCOMPATIBLE_EMPLOYEES_VIOLATION`に
条件pointer、条件ID・対象者と同僚、`interval_start` / `interval_end`、`actual_people`と
`minimum_people`または`maximum_people`を返す。ソルバー係数・目的値は参照せず、最適性を認定しない。
Response・solution・verificationは0.13の出力構造を継承し、対応版のSchemaで検査する。

## 診断と再計画

新ルール1件を削除可能な条件グループ1件とする。相手の技能・勤務可能時間・候補・実績・
確定勤務は背景条件として維持し、緩和試行の解を正式解として返さない。
allowed_changesによるminimum_people・相手集合・ルールの編集は受け付けない。

make_baselineは元ルールを保存し、元契約版で基準を再検証する。
次Requestの同時勤務条件は利用者が明示し、preserve_assigned/rebuildの両方で適用する。
固定や確定勤務を自動解除しない。既存どおりrebuildと明示fixed_partsの併用は入力不備である。

## 実行例

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/coworkers.json > result.json
uv run --locked python -c 'import json; from shift_schedula import verify, make_baseline; q=json.load(open("examples/coworkers.json")); r=json.load(open("result.json")); print(verify(q,r["solution"])["status"]); print(make_baseline(q,r["solution"],"saved")["plan_id"])'
```

例は新人09:00〜11:00を指導者A09:00〜10:00とB10:00〜11:00が交代で支える。
指導者は担当資格のない役割へ配置せず待機勤務する。A/Bの同時勤務は禁止する。
元需要2人・必須最低人数1人のため、勤務240分、不足120人分の検証済みPARTIALを返す。
solveとverifyのCLI終了コードは2。JSON試用画面にも同じサンプルを用意する。
[受け入れ記録](evaluations/coworkers.md)に検証結果と制限を記す。
