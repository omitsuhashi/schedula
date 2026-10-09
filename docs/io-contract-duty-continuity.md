# 契約0.10の履歴を含む指定区間の目標偏差

> 契約導入時の履歴仕様です。以下にある旧版の受付・型・コマンドは現在のサポート範囲ではありません。現在の全機能と意味は[現行契約0.15](io-contract-current.md)、変更と終了の条件は[サポート方針](contract-support.md)を参照してください。

[Issue #79](https://github.com/omitsuhashi/schedula/issues/79)で、契約0.9の `duty_balance` を
確認済みの実績・未来の確定勤務へ接続した。0.9の計画内評価は変更せず、
拡張する入力は `schema_version: "0.10"` を指定する。新しい依存は追加しない。

## 評価の範囲

計画期間Wを包含する `continuity.context_window` をCとする。
0.10の `evaluation_period` はC内の正の半開区間を指定でき、各 `intervals` は評価期間内に収める。
日時は明示オフセット付きの整数分。W内の端点は計画開始からの粒度に揃え、
W外の端点は整数分のまま保持する。区間の重複・隣接・再掲は和集合として一度だけ数える。

C開始からW開始までの実績確認と、C内の既知の確定勤務の完全性確認は
[継続計画の契約](io-contract-continuity.md)どおり全従業員へ要求する。
履歴・確認フラグ・対象者が欠落した場合は `INCOMPLETE_HISTORY`。
空の `actual_shifts` は `past_complete: true` と組にした場合だけ確認済みの勤務なしを意味する。
アンカーの最終勤務時刻から過去勤務量を推測せず、欠落を0分へ補完しない。

`continuity` なしの場合はW内の評価に限定する。W外の評価には `INCOMPLETE_HISTORY` を返す。
C外は `INVALID_CONTINUITY_INTERVAL`、評価期間外の区間は `INVALID_DUTY_INTERVAL` として拒否する。
0.9以前では過去を含む評価を受理しない。

## 集計・目的・結果

評価区間の和集合と、各人の休憩を除く原勤務区間の交差から実経過分数を求める。
過去実績と確定勤務を定数、選択勤務を候補の値として扱い、待機は含む。
開始・終了境界をまたぐ勤務も原 `segments` を一度だけ持ち、過去・W内・未来へ投影する。
W外だけの確定勤務はRequestから、Wに重なる確定勤務は返却解の原区間から独立検証する。
休憩・分割間の非勤務を除外し、DSTの時計表示差でなくUTC上の経過時間を数える。

各対象者の偏差は `abs(actual_minutes - target_minutes)`、目的値はその合計。
未指定者は対象外、明示0目標と区別する。達成不能な目標は偏差として残す。
必須条件・固定・不足最小化・priorityを緩和せず、上位未証明なら下位目的を探索しない。
既存 `fairness_deviation_minutes`、`scheduled_minutes`、`scheduled_cost` はW内だけの意味を保つ。
待機で偏差を減らす勤務も有効であり、抑制する場合は勤務量・費用との目的順を明示する。

結果の形は0.9と共通で、新しい集計フィールドは追加しない。
`duty_balance_summary` から評価期間・併合区間・対象者・目標・実分数・偏差を追跡し、
同じ結果の `continuity_summary` から参照したC・W・期間別勤務量・確定勤務IDを確認する。
同一のRequestと両集計を保存する。`verify` は元入力・原 `segments` から再計算し、
モデルの候補表・係数を読まない。最適性・不足最小性の証明は付与しない。

## 入力例と基準計画

[架空入力](../examples/continuity_duty_balance.json)では過去夜勤がAlice240分・Bob0分、
残りの需要が240分、目標が各240分。Bobの勤務を選び実分数240/240・偏差0となる。
Aliceだけを候補にすると480/0・偏差480。計画内勤務240分、費用432000単位である。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/continuity_duty_balance.json
uv run --locked python -m shift_schedula schema request --schema-version 0.10
uv run --locked python -m shift_schedula schema verification --schema-version 0.10
```

公開型は `Request010`、`Response010Success`、`Response010Failure`。
`make_baseline` は評価条件と元continuityを保存し、旧解を元条件で再検証する。
0.10は対応済み旧版の基準を受理し、旧版から0.10の基準を参照する入力は拒否する。
重複期間の比較・固定は[契約0.7](io-contract-overlap.md)の意味を保つ。
計画出力から実績を自動生成せず、期間をずらす際の確認済み実績は利用側が入力する。

条件変更案と矛盾縮小でも実績・確定勤務は背景条件に保持する。
評価目的は必須条件の矛盾原因として削除しない。原区間と履歴の範囲を変えずに診断する。
検証と実測は[受け入れ記録](evaluations/continuity-duty-balance.md)、
採用判断は[ADR-0008](adr/0008-duty-balance-context.md)を参照する。
